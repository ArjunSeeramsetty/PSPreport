"""Unit tests for NERLDC corpus inventory and PDF validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from psp_pipeline.quality.nerldc_corpus_inventory import (
    _parse_nerldc_date_from_filename,
    run_nerldc_corpus_inventory,
    validate_nerldc_pdf,
)


def test_parse_nerldc_date_from_filename() -> None:
    d1 = _parse_nerldc_date_from_filename("NER-PSP-REPORT-DATED-15-04-2024.pdf")
    assert d1 is not None
    assert str(d1) == "2024-04-15"

    d2 = _parse_nerldc_date_from_filename("NER_PSP_01-01-2025.pdf")
    assert d2 is not None
    assert str(d2) == "2025-01-01"

    d3 = _parse_nerldc_date_from_filename("random_file.pdf")
    assert d3 is None


def test_validate_nonexistent_pdf(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.pdf"
    pages, sha, result = validate_nerldc_pdf(missing)
    assert pages == 0
    assert sha == ""
    assert result == "empty_or_missing"


def test_validate_non_pdf_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_text("Hello not a PDF file but text " * 5, encoding="utf-8")
    pages, sha, result = validate_nerldc_pdf(bad)
    assert pages == 0
    assert result == "invalid_pdf_signature"


def test_run_inventory_on_real_nerldc_corpus() -> None:
    corpus_dir = Path("downloads/NERLDC_PSP")
    if not corpus_dir.exists() or not list(corpus_dir.glob("*.pdf")):
        pytest.skip("NERLDC corpus directory not present in downloads/NERLDC_PSP")

    summary = run_nerldc_corpus_inventory(corpus_dir)
    assert summary["total_pdf_count"] >= 1000
    assert summary["anchor_sample_count"] == 114
    assert summary["valid_psp_count"] == 114
    assert summary["invalid_count"] == 0
