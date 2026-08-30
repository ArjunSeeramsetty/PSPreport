"""Unit tests for NLDC corpus inventory and PDF validation."""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PageObject, PdfWriter
import pytest

from psp_pipeline.quality.nldc_corpus_inventory import (
    build_nldc_corpus_inventory,
    validate_nldc_pdf,
)


def _make_dummy_pdf(pages_text: list[str]) -> bytes:
    """Create dummy multi-page PDF bytes with injected text streams."""
    writer = PdfWriter()
    for _ in pages_text:
        writer.add_page(PageObject.create_blank_page(width=612, height=792))
    stream = io.BytesIO()
    writer.write(stream)
    pdf_bytes = stream.getvalue()
    # Inject text chunks into comment streams for text extraction
    for text in pages_text:
        pdf_bytes += b"\n% " + text.encode("utf-8")
    return pdf_bytes


def test_validate_nldc_pdf_missing_file(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist.pdf"
    pages, sha256, status = validate_nldc_pdf(non_existent)
    assert pages == 0
    assert sha256 == ""
    assert status == "empty_or_missing"


def test_validate_nldc_pdf_invalid_signature(tmp_path: Path) -> None:
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"NOT_A_PDF_DOCUMENT_AT_ALL_JUST_SOME_TEXT_LONGER_THAN_50_BYTES")
    pages, sha256, status = validate_nldc_pdf(bad_pdf)
    assert pages == 0
    assert len(sha256) == 64
    assert status == "invalid_pdf_signature"


def test_validate_nldc_pdf_missing_header(tmp_path: Path) -> None:
    unrelated_pdf = tmp_path / "unrelated.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_page(PageObject.create_blank_page(width=612, height=792))
    writer.write(unrelated_pdf)

    pages, sha256, status = validate_nldc_pdf(unrelated_pdf)
    assert pages == 3
    assert status == "missing_nldc_header"


def test_validate_nldc_pdf_rejects_insufficient_pages_1_page(tmp_path: Path) -> None:
    """A 1-page document with generic NLDC/PSP header is rejected as insufficient pages."""
    one_page_pdf = tmp_path / "one_page.pdf"
    content = _make_dummy_pdf([
        "GRID-INDIA NATIONAL LOAD DESPATCH CENTRE DAILY POWER SUPPLY POSITION REPORT"
    ])
    one_page_pdf.write_bytes(content)

    pages, sha256, status = validate_nldc_pdf(one_page_pdf)
    assert pages == 1
    assert status == "insufficient_pages"


def test_validate_nldc_pdf_rejects_insufficient_pages_2_pages(tmp_path: Path) -> None:
    """A 2-page document missing the page 3 exchange table is rejected as insufficient pages."""
    two_page_pdf = tmp_path / "two_page.pdf"
    content = _make_dummy_pdf([
        "GRID-INDIA NATIONAL LOAD DESPATCH CENTRE DAILY POWER SUPPLY POSITION REPORT",
        "ALL INDIA DEMAND MET FREQUENCY PROFILE FVI",
    ])
    two_page_pdf.write_bytes(content)

    pages, sha256, status = validate_nldc_pdf(two_page_pdf)
    assert pages == 2
    assert status == "insufficient_pages"


def test_validate_nldc_pdf_valid_header_and_sections(tmp_path: Path) -> None:
    valid_pdf = tmp_path / "25-08-2026-nldc-psp.pdf"
    content = _make_dummy_pdf([
        "GRID-INDIA NATIONAL LOAD DESPATCH CENTRE DAILY POWER SUPPLY POSITION REPORT",
        "ALL INDIA DEMAND MET FREQUENCY PROFILE FVI",
        "INTER REGIONAL IMPORT/EXPORT LINE DETAILS MAX IMPORT MAX EXPORT NET (MU)",
    ])
    valid_pdf.write_bytes(content)

    pages, sha256, status = validate_nldc_pdf(valid_pdf)
    assert pages == 3
    assert status == "valid_psp"


def test_build_nldc_corpus_inventory_from_mock_dir(tmp_path: Path) -> None:
    # Create 3 monthly anchors for August 2026
    dates = ["01-08-2026", "15-08-2026", "31-08-2026"]
    for d in dates:
        f = tmp_path / f"{d}-nldc-psp.pdf"
        f.write_bytes(
            _make_dummy_pdf([
                "GRID-INDIA NLDC POWER SUPPLY POSITION REPORT",
                "DEMAND MET REGIONAL SUMMARY FREQUENCY PROFILE",
                "INTER-REGIONAL LINE DETAILS IMPORT/EXPORT",
            ])
        )

    # Test with default (unfabricated source_url -> None)
    summary = build_nldc_corpus_inventory(tmp_path)
    assert summary.total_pdf_count == 3
    assert summary.anchor_sample_count == 3
    assert summary.valid_psp_count == 3
    assert summary.invalid_count == 0
    assert summary.page_count_distribution == {3: 3}
    assert len(summary.items) == 3
    assert summary.items[0].report_date == "2026-08-01"
    assert summary.items[0].source_url is None
    assert summary.items[0].pdf_path == str(tmp_path / "01-08-2026-nldc-psp.pdf")
    assert summary.items[1].report_date == "2026-08-15"
    assert summary.items[2].report_date == "2026-08-31"

    # Test with known_urls provided
    known = {"01-08-2026-nldc-psp.pdf": "https://webcdn.grid-india.in/files/grdw/01.08.26_NLDC_PSP.pdf"}
    summary_known = build_nldc_corpus_inventory(tmp_path, known_urls=known)
    assert summary_known.items[0].source_url == "https://webcdn.grid-india.in/files/grdw/01.08.26_NLDC_PSP.pdf"
    assert summary_known.items[1].source_url is None


def test_build_nldc_corpus_inventory_single_file_no_duplicates(tmp_path: Path) -> None:
    """A directory with a single PDF must evaluate anchor_sample_count == 1 without duplicates."""
    f = tmp_path / "25-08-2026-nldc-psp.pdf"
    f.write_bytes(
        _make_dummy_pdf([
            "GRID-INDIA NLDC POWER SUPPLY POSITION REPORT",
            "DEMAND MET REGIONAL SUMMARY FREQUENCY PROFILE",
            "INTER-REGIONAL LINE DETAILS IMPORT/EXPORT",
        ])
    )

    summary = build_nldc_corpus_inventory(tmp_path, anchor_sample_only=True)
    assert summary.total_pdf_count == 1
    assert summary.anchor_sample_count == 1
    assert summary.valid_psp_count == 1
    assert len(summary.items) == 1
    assert summary.items[0].report_date == "2026-08-25"
    assert summary.page_count_distribution == {3: 1}


def test_validate_real_nldc_fixture() -> None:
    fixture_path = Path("downloads/NLDC_PSP/25-08-2026-nldc-psp.pdf")
    if not fixture_path.exists():
        pytest.skip(f"Fixture {fixture_path} not present in local workspace")

    pages, sha256, status = validate_nldc_pdf(fixture_path)
    assert pages >= 3
    assert len(sha256) == 64
    assert status == "valid_psp"
