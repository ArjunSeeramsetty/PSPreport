"""Tests for the AGPL-safe PDF page profiler used to route pdfplumber work."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter

from psp_pipeline.parsing.page_profiler import (
    PdfProfile,
    PageFingerprint,
    classify_page_density,
    extract_profile_text,
    profile_pdf,
)


def test_sparse_cover_pages_do_not_dispatch_to_pdfplumber() -> None:
    """Blank or artwork pages skip geometric table extraction."""

    is_dense, dispatch, reason = classify_page_density(40, 2)
    assert is_dense is False
    assert dispatch is False
    assert reason == "sparse_cover_or_blank"


def test_uncertain_pages_fail_closed_into_pdfplumber() -> None:
    """A prose page without a dense digit field still goes to pdfplumber."""

    is_dense, dispatch, reason = classify_page_density(800, 8)
    assert is_dense is False
    assert dispatch is True
    assert reason == "uncertain_dispatch_pdfplumber"


def test_dense_digit_pages_are_marked_tabular() -> None:
    """Scheduling matrices dispatch to the geometric extractor."""

    is_dense, dispatch, reason = classify_page_density(1200, 80)
    assert is_dense is True
    assert dispatch is True
    assert reason == "dense_tabular"


def test_mixed_profile_skips_only_sparse_pages() -> None:
    """Cover pages are skipped without dropping the dense matrix pages."""

    profile = PdfProfile(
        path="bulletin.pdf",
        page_count=2,
        backend="pypdf",
        pages=(
            PageFingerprint(1, 10, 0, "a", False, False, "sparse_cover_or_blank"),
            PageFingerprint(2, 2000, 90, "b", True, True, "dense_tabular"),
        ),
        layout_fingerprint="abc",
    )
    assert profile.pages_for_pdfplumber() == frozenset({2})


def test_all_sparse_profile_fails_closed_to_every_page() -> None:
    """If every page looks empty, still extract rather than drop the document."""

    profile = PdfProfile(
        path="blank.pdf",
        page_count=1,
        backend="pypdf",
        pages=(PageFingerprint(1, 0, 0, "a", False, False, "sparse_cover_or_blank"),),
        layout_fingerprint="abc",
    )
    assert profile.pages_for_pdfplumber() == frozenset({1})


def test_profile_pdf_uses_pypdf_for_blank_documents(tmp_path: Path) -> None:
    """The default backend fingerprints page count without pdfplumber."""

    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(str(path))

    profile = profile_pdf(path)
    assert profile.page_count == 1
    assert profile.backend in {"pypdf", "pymupdf"}
    assert extract_profile_text(path) == "" or isinstance(extract_profile_text(path), str)
