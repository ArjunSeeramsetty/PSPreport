"""Unit tests for ERLDC corpus inventory and PDF validation."""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PageObject, PdfWriter
import pytest

from psp_pipeline.quality.erldc_corpus_inventory import (
    build_erldc_corpus_inventory,
    validate_erldc_pdf,
)


def _make_dummy_pdf(text_content: str) -> bytes:
    writer = PdfWriter()
    writer.add_page(PageObject.create_blank_page(width=612, height=792))
    stream = io.BytesIO()
    writer.write(stream)
    pdf_bytes = stream.getvalue()
    # Inject text into stream for simple matching
    return pdf_bytes + b"\n% " + text_content.encode("utf-8")


def test_validate_erldc_pdf_missing_file(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist.pdf"
    pages, sha256, status = validate_erldc_pdf(non_existent)
    assert pages == 0
    assert sha256 == ""
    assert status == "empty_or_missing"


def test_validate_erldc_pdf_invalid_signature(tmp_path: Path) -> None:
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"NOT_A_PDF_DOCUMENT_AT_ALL_JUST_SOME_TEXT_LONGER_THAN_50_BYTES")
    pages, sha256, status = validate_erldc_pdf(bad_pdf)
    assert pages == 0
    assert len(sha256) == 64
    assert status == "invalid_pdf_signature"


def test_validate_erldc_pdf_missing_header(tmp_path: Path) -> None:
    unrelated_pdf = tmp_path / "unrelated.pdf"
    writer = PdfWriter()
    writer.add_page(PageObject.create_blank_page(width=612, height=792))
    writer.write(unrelated_pdf)

    pages, sha256, status = validate_erldc_pdf(unrelated_pdf)
    assert pages == 1
    assert status == "missing_erldc_header"


def test_validate_erldc_pdf_valid_header(tmp_path: Path) -> None:
    valid_pdf = tmp_path / "Power Supply Position Report_15042025.pdf"
    content = _make_dummy_pdf("POWER SUPPLY POSITION REPORT EASTERN REGIONAL LOAD DESPATCH CENTRE ERLDC")
    valid_pdf.write_bytes(content)

    pages, sha256, status = validate_erldc_pdf(valid_pdf)
    assert pages == 1
    assert status == "valid_psp"


def test_build_erldc_corpus_inventory_from_mock_dir(tmp_path: Path) -> None:
    # Create 3 month anchors for 2025-04
    dates = ["01042025", "15042025", "30042025"]
    for d in dates:
        f = tmp_path / f"Power Supply Position Report_{d}.pdf"
        f.write_bytes(_make_dummy_pdf("POWER SUPPLY POSITION ERLDC EASTERN REGION"))

    summary = build_erldc_corpus_inventory(tmp_path)
    assert summary.total_pdf_count == 3
    assert summary.anchor_sample_count == 3
    assert summary.valid_psp_count == 3
    assert summary.invalid_count == 0
    assert summary.page_count_distribution == {1: 3}
    assert len(summary.items) == 3
    assert summary.items[0].report_date == "2025-04-01"
    assert summary.items[1].report_date == "2025-04-15"
    assert summary.items[2].report_date == "2025-04-30"
