"""Unit tests for WRLDC corpus inventory and validation."""

from __future__ import annotations

from pathlib import Path
import pytest
from pypdf import PdfWriter

from psp_pipeline.quality.wrldc_corpus_inventory import (
    audit_wrldc_anchor_templates,
    build_wrldc_corpus_inventory,
    classify_review_anchors,
    validate_wrldc_pdf,
)


def _create_synthetic_pdf(path: Path, num_pages: int = 1, header_marker: str = "WRLDC POWER SUPPLY POSITION") -> None:
    """Create a minimal valid multi-page PDF with WRLDC header marker comment."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        # Write marker comment right after header
        handle.write(f"%PDF-1.4\n% {header_marker}\n".encode("ascii"))
        writer.write(handle)


def test_validate_wrldc_pdf_empty_and_corrupt(tmp_path: Path):
    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")
    page_count, sha, result = validate_wrldc_pdf(empty_file)
    assert result == "empty_or_missing"
    assert page_count == 0

    non_pdf = tmp_path / "non_pdf.pdf"
    non_pdf.write_bytes(b"Not a PDF header" + b"x" * 2000)
    page_count, sha, result = validate_wrldc_pdf(non_pdf)
    assert result == "invalid_pdf_signature"


def test_validate_wrldc_pdf_missing_header_marker(tmp_path: Path):
    pdf_path = tmp_path / "plain.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    page_count, sha, result = validate_wrldc_pdf(pdf_path)
    assert page_count == 1
    assert result == "missing_wrldc_header"


def test_validate_wrldc_pdf_psp_only_missing_wrldc(tmp_path: Path):
    pdf_path = tmp_path / "psp_only.pdf"
    _create_synthetic_pdf(pdf_path, num_pages=1, header_marker="POWER SUPPLY POSITION REPORT")
    page_count, sha, result = validate_wrldc_pdf(pdf_path)
    assert page_count == 1
    assert result == "missing_wrldc_header"


def test_validate_wrldc_pdf_wrldc_only_missing_psp(tmp_path: Path):
    pdf_path = tmp_path / "wrldc_only.pdf"
    _create_synthetic_pdf(pdf_path, num_pages=1, header_marker="WRLDC REGIONAL GRID REPORT")
    page_count, sha, result = validate_wrldc_pdf(pdf_path)
    assert page_count == 1
    assert result == "missing_wrldc_header"


def test_validate_wrldc_pdf_full_regional_name_valid(tmp_path: Path):
    pdf_path = tmp_path / "full_name.pdf"
    _create_synthetic_pdf(
        pdf_path,
        num_pages=7,
        header_marker="WESTERN REGIONAL LOAD DESPATCH CENTRE POWER SUPPLY POSITION",
    )
    page_count, sha, result = validate_wrldc_pdf(pdf_path)
    assert page_count == 7
    assert result == "valid_psp"


def test_validate_wrldc_pdf_valid(tmp_path: Path):
    pdf_path = tmp_path / "valid.pdf"
    _create_synthetic_pdf(pdf_path, num_pages=7)
    page_count, sha, result = validate_wrldc_pdf(pdf_path)
    assert page_count == 7
    assert result == "valid_psp"
    assert len(sha) == 64


def test_build_wrldc_corpus_inventory_transitions_and_distribution(tmp_path: Path):
    corpus_dir = tmp_path / "WRLDC_PSP"
    corpus_dir.mkdir()

    # Create dummy reports across months with differing page counts to trigger transitions
    # Month 1 (2024-01): 7 pages
    for day in ("01", "15", "31"):
        p = corpus_dir / f"WRLDC_PSP_Report_{day}-01-2024.pdf"
        _create_synthetic_pdf(p, num_pages=7)

    # Month 2 (2024-02): 8 pages
    for day in ("01", "15", "29"):
        p = corpus_dir / f"WRLDC_PSP_Report_{day}-02-2024.pdf"
        _create_synthetic_pdf(p, num_pages=8)

    summary = build_wrldc_corpus_inventory(corpus_dir)
    assert summary.total_pdf_count == 6
    assert summary.anchor_sample_count == 6
    assert summary.valid_psp_count == 6
    assert summary.invalid_count == 0
    assert summary.page_count_distribution == {7: 3, 8: 3}
    assert len(summary.page_count_transitions) == 1
    trans = summary.page_count_transitions[0]
    assert trans["from_page_count"] == 7
    assert trans["to_page_count"] == 8
    assert trans["transition_date"] == "2024-02-01"


def test_classify_review_anchors_scoping():
    mismatches = [
        {
            "report_date": "2023-06-15",
            "filename": "WRLDC_PSP_Report_15-06-2023.pdf",
            "template_id": "wrldc_daily_psp_v2023_standard_09_column_generation",
            "mismatch_reasons": ["shape_mismatch=p6_t1:56x20", "shape_mismatch=p7_t1:35x21"],
        },
        {
            "report_date": "2023-06-30",
            "filename": "WRLDC_PSP_Report_30-06-2023.pdf",
            "template_id": "wrldc_daily_psp_v2023_standard_09_column_generation",
            "mismatch_reasons": ["shape_mismatch=p6_t1:56x20", "shape_mismatch=p7_t1:35x21"],
        },
        {
            "report_date": "2024-03-01",
            "filename": "WRLDC_PSP_Report_01-03-2024.pdf",
            "template_id": "wrldc_daily_psp_v2024_standard_09_column_generation",
            "mismatch_reasons": ["shape_mismatch=p2_t1:10x10"],
        },
    ]

    classified = classify_review_anchors(mismatches)
    assert len(classified) == 2

    group_2023 = classified[0]
    assert group_2023["count"] == 2
    assert group_2023["date_range"] == {"start": "2023-06-15", "end": "2023-06-30"}
    assert group_2023["affects_primary_scope"] is False
    assert len(group_2023["sample_filenames"]) == 2

    group_2024 = classified[1]
    assert group_2024["count"] == 1
    assert group_2024["affects_primary_scope"] is True


def test_build_wrldc_corpus_inventory_missing_directory(tmp_path: Path):
    missing_dir = tmp_path / "non_existent_wrldc_dir"
    with pytest.raises(FileNotFoundError, match="not found"):
        build_wrldc_corpus_inventory(missing_dir)


def test_audit_wrldc_anchor_templates_structure(tmp_path: Path):
    corpus_dir = tmp_path / "WRLDC_PSP"
    corpus_dir.mkdir()

    p1 = corpus_dir / "WRLDC_PSP_Report_01-01-2024.pdf"
    _create_synthetic_pdf(p1, num_pages=7)

    audit = audit_wrldc_anchor_templates(corpus_dir)
    assert audit["total_anchors"] >= 1
    assert "template_distribution" in audit
    assert "semantic_review_count" in audit
    assert "matched_count" in audit
    assert "review_classifications" in audit
    assert isinstance(audit["mismatches"], list)
