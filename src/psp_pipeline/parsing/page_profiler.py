"""Fast PDF pre-flight profiling used to route pages into pdfplumber.

The profiler never extracts numeric table cells. It only classifies pages so
the geometric extractor spends CPU on dense matrices. PyMuPDF is used when
installed; otherwise ``pypdf`` (already a runtime dependency) is the
AGPL-safe default. Uncertain pages always dispatch to pdfplumber.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# Cover/art pages are skipped for table extraction only when both bounds hit.
_SPARSE_CHAR_CEILING = 200
_SPARSE_DIGIT_CEILING = 10
_DENSE_DIGIT_FLOOR = 20
_DENSE_CHAR_FLOOR = 400
_DENSE_DIGIT_RATIO = 0.03


@dataclass(frozen=True)
class PageFingerprint:
    """One page's cheap text-density fingerprint."""

    page_no: int
    char_count: int
    digit_count: int
    layout_hash: str
    is_dense_tabular: bool
    dispatch_to_pdfplumber: bool
    reason: str


@dataclass(frozen=True)
class PdfProfile:
    """Document-level routing metadata produced before geometric extraction."""

    path: str
    page_count: int
    backend: str
    pages: tuple[PageFingerprint, ...]
    layout_fingerprint: str

    def pages_for_pdfplumber(self) -> frozenset[int]:
        """Return page numbers that must receive geometric table extraction.

        An empty or failed profile returns every page so extraction never
        silently drops tabular content.
        """

        if not self.pages:
            return frozenset(range(1, self.page_count + 1)) if self.page_count else frozenset()
        selected = {page.page_no for page in self.pages if page.dispatch_to_pdfplumber}
        return frozenset(selected or {page.page_no for page in self.pages})

    def sample_text(self, max_pages: int = 2) -> str:
        """Return concatenated page hashes as a stand-in used by tests.

        Callers that need actual text should use ``extract_profile_text``.
        """

        return "\n".join(page.layout_hash for page in self.pages[:max_pages])


def classify_page_density(char_count: int, digit_count: int) -> tuple[bool, bool, str]:
    """Classify a page as dense-tabular, sparse, or uncertain.

    Returns:
        ``(is_dense_tabular, dispatch_to_pdfplumber, reason)``. Dispatch is
        fail-closed: only clearly sparse pages skip pdfplumber table extraction.
    """

    ratio = digit_count / max(char_count, 1)
    if char_count < _SPARSE_CHAR_CEILING and digit_count < _SPARSE_DIGIT_CEILING:
        return False, False, "sparse_cover_or_blank"
    is_dense = digit_count >= _DENSE_DIGIT_FLOOR or (
        char_count >= _DENSE_CHAR_FLOOR and ratio >= _DENSE_DIGIT_RATIO
    )
    if is_dense:
        return True, True, "dense_tabular"
    return False, True, "uncertain_dispatch_pdfplumber"


def profile_pdf(pdf_path: Path | str) -> PdfProfile:
    """Fingerprint page density without running pdfplumber table extraction."""

    path = Path(pdf_path)
    backend, page_texts = _extract_page_texts(path)
    pages = tuple(
        _fingerprint_page(page_no, text)
        for page_no, text in enumerate(page_texts, start=1)
    )
    digest = hashlib.sha256()
    digest.update(str(len(pages)).encode("utf-8"))
    for page in pages:
        digest.update(page.layout_hash.encode("utf-8"))
    profile = PdfProfile(
        path=str(path),
        page_count=len(pages),
        backend=backend,
        pages=pages,
        layout_fingerprint=digest.hexdigest()[:16],
    )
    skipped = sorted(
        page.page_no for page in pages if not page.dispatch_to_pdfplumber
    )
    if skipped:
        logger.info(
            "page_profiler_skip_tables path=%s backend=%s pages=%s",
            path,
            backend,
            ",".join(str(page) for page in skipped),
        )
    return profile


def extract_profile_text(pdf_path: Path | str, max_pages: int | None = None) -> str:
    """Return native page text used for family validation and OCR scoring."""

    _backend, page_texts = _extract_page_texts(Path(pdf_path))
    selected: Iterable[str] = page_texts[:max_pages] if max_pages else page_texts
    return "\n".join(text for text in selected if text)


def _fingerprint_page(page_no: int, text: str) -> PageFingerprint:
    compact = text.strip()
    char_count = len(compact)
    digit_count = sum(character.isdigit() for character in compact)
    is_dense, dispatch, reason = classify_page_density(char_count, digit_count)
    layout_hash = hashlib.sha256(
        f"{page_no}:{char_count}:{digit_count}:{compact[:240]}".encode("utf-8")
    ).hexdigest()[:12]
    return PageFingerprint(
        page_no=page_no,
        char_count=char_count,
        digit_count=digit_count,
        layout_hash=layout_hash,
        is_dense_tabular=is_dense,
        dispatch_to_pdfplumber=dispatch,
        reason=reason,
    )


def _extract_page_texts(path: Path) -> tuple[str, list[str]]:
    """Return ``(backend_name, per_page_text)`` from the fastest available reader."""

    try:
        return _extract_with_pymupdf(path)
    except Exception as exc:  # pragma: no cover - optional AGPL backend
        logger.debug("page_profiler_pymupdf_unavailable error=%s", exc)
    return _extract_with_pypdf(path)


def _extract_with_pymupdf(path: Path) -> tuple[str, list[str]]:
    """Extract page text through PyMuPDF when the optional package is present."""

    import fitz  # type: ignore[import-untyped]

    document = fitz.open(str(path))
    try:
        texts = [page.get_text("text") or "" for page in document]
    finally:
        document.close()
    return "pymupdf", texts


def _extract_with_pypdf(path: Path) -> tuple[str, list[str]]:
    """Extract page text with pypdf, the default AGPL-safe routing backend."""

    from pypdf import PdfReader

    reader = PdfReader(str(path))
    texts: list[str] = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception as exc:
            logger.warning("page_profiler_pypdf_page_failed path=%s error=%s", path, exc)
            texts.append("")
    return "pypdf", texts
