"""Replayable corpus inventory and validation for WRLDC PSP reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import logging
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader

from psp_pipeline.acquisition.downloaders.wrldc import report_url
from psp_pipeline.parsing.rldc.templates import (
    inspect_report_structure,
    match_report_template,
)
from psp_pipeline.schema_design.service import select_monthly_anchor_paths

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WRLDCInventoryItem:
    """Validation record for one monthly anchor report."""

    report_date: str
    anchor: str
    filename: str
    source_url: str
    sha256: str
    page_count: int
    validation_result: str
    pdf_path: str


@dataclass(frozen=True)
class WRLDCCorpusSummary:
    """Summary of WRLDC corpus validation, page distributions, and transitions."""

    total_pdf_count: int
    anchor_sample_count: int
    valid_psp_count: int
    invalid_count: int
    page_count_distribution: dict[int, int]
    page_count_transitions: list[dict[str, Any]]
    items: list[WRLDCInventoryItem]

    def to_dict(self) -> dict[str, Any]:
        """Convert the summary to a JSON-serializable dictionary."""
        return asdict(self)


def validate_wrldc_pdf(path: Path) -> tuple[int, str, str]:
    """Validate a single WRLDC PDF file and return (page_count, sha256, validation_result).

    A valid WRLDC PSP must contain 'POWER SUPPLY POSITION' and either 'WRLDC'
    or 'WESTERN REGIONAL LOAD DESPATCH CENTRE'.

    Args:
        path: Path to the local PDF file.

    Returns:
        A tuple of (page_count, sha256_hex, validation_status).
    """
    if not path.exists() or path.stat().st_size <= 50:
        return 0, "", "empty_or_missing"

    content = path.read_bytes()
    if not content.startswith(b"%PDF"):
        return 0, hashlib.sha256(content).hexdigest(), "invalid_pdf_signature"

    sha256 = hashlib.sha256(content).hexdigest()
    try:
        reader = PdfReader(path)
        page_count = len(reader.pages)
        if page_count < 1:
            return 0, sha256, "zero_pages"
        first_page_text = reader.pages[0].extract_text() or ""
        upper_text = first_page_text.upper()
        raw_header = content[:8192].upper()

        has_psp = "POWER SUPPLY POSITION" in upper_text or b"POWER SUPPLY POSITION" in raw_header
        has_wrldc = (
            "WRLDC" in upper_text
            or "WESTERN REGIONAL LOAD DESPATCH CENTRE" in upper_text
            or "WESTERN REGIONAL LOAD DESPATCH CENTER" in upper_text
            or b"WRLDC" in raw_header
            or b"WESTERN REGIONAL LOAD DESPATCH CENTRE" in raw_header
            or b"WESTERN REGIONAL LOAD DESPATCH CENTER" in raw_header
        )

        if not (has_psp and has_wrldc):
            return page_count, sha256, "missing_wrldc_header"
        return page_count, sha256, "valid_psp"
    except Exception as exc:
        logger.warning("wrldc_pdf_validation_error path=%s error=%s", path, exc)
        return -1, sha256, f"corrupted: {exc}"


def build_wrldc_corpus_inventory(input_dir: Path) -> WRLDCCorpusSummary:
    """Scan a local directory of WRLDC PDFs, select monthly anchors, and validate corpus consistency.

    Args:
        input_dir: Directory containing downloaded WRLDC PSP PDFs.

    Returns:
        A WRLDCCorpusSummary containing typed inventory items, page count distributions,
        and chronological page-count transition boundaries.

    Raises:
        FileNotFoundError: If input_dir does not exist.
    """
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found at {input_dir}")

    all_pdfs = sorted(input_dir.glob("*.pdf"))
    samples = select_monthly_anchor_paths(all_pdfs, source_id="wrldc")

    items: list[WRLDCInventoryItem] = []
    page_dist: dict[int, int] = {}
    valid_count = 0
    invalid_count = 0

    for sample in samples:
        path = sample.pdf_path
        page_count, sha256, val_result = validate_wrldc_pdf(path)

        if val_result == "valid_psp":
            valid_count += 1
            page_dist[page_count] = page_dist.get(page_count, 0) + 1
        else:
            invalid_count += 1

        r_date = date.fromisoformat(sample.report_date)
        url = report_url(r_date)

        items.append(
            WRLDCInventoryItem(
                report_date=sample.report_date,
                anchor=sample.anchor,
                filename=path.name,
                source_url=url,
                sha256=sha256,
                page_count=page_count,
                validation_result=val_result,
                pdf_path=str(path.resolve()),
            )
        )

    # Compute page-count transition points chronologically
    transitions: list[dict[str, Any]] = []
    prev_pages: int | None = None
    for item in items:
        if item.validation_result != "valid_psp":
            continue
        if prev_pages is not None and item.page_count != prev_pages:
            transitions.append(
                {
                    "transition_date": item.report_date,
                    "from_page_count": prev_pages,
                    "to_page_count": item.page_count,
                    "anchor": item.anchor,
                    "filename": item.filename,
                }
            )
        prev_pages = item.page_count

    return WRLDCCorpusSummary(
        total_pdf_count=len(all_pdfs),
        anchor_sample_count=len(samples),
        valid_psp_count=valid_count,
        invalid_count=invalid_count,
        page_count_distribution=dict(sorted(page_dist.items())),
        page_count_transitions=transitions,
        items=items,
    )


def classify_review_anchors(mismatches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group review-gated anchors by identical mismatch-reason signature.

    Args:
        mismatches: List of individual mismatch dictionaries containing report_date,
            filename, template_id, and mismatch_reasons.

    Returns:
        A list of grouped signature dictionaries with date ranges, counts, template candidate,
        mismatch reasons, and affects_primary_scope classification.
    """
    groups: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {}
    for item in mismatches:
        key = (item.get("template_id") or "unmatched", tuple(sorted(item.get("mismatch_reasons", []))))
        groups.setdefault(key, []).append(item)

    classified: list[dict[str, Any]] = []
    for (template_id, reasons), reports in groups.items():
        dates = [r["report_date"] for r in reports]
        affects_primary = any(
            bool(re.search(r"\bp[1-4][_:]|\bpage[_\s=]*[1-4]\b", reason, re.IGNORECASE))
            for reason in reasons
        )
        classified.append(
            {
                "template_candidate": template_id,
                "count": len(reports),
                "date_range": {
                    "start": min(dates),
                    "end": max(dates),
                },
                "mismatch_reasons": list(reasons),
                "affects_primary_scope": affects_primary,
                "sample_filenames": [r["filename"] for r in reports],
            }
        )

    return sorted(classified, key=lambda c: (c["date_range"]["start"], c["template_candidate"]))


def audit_wrldc_anchor_templates(input_dir: Path) -> dict[str, Any]:
    """Inspect structure and match templates over WRLDC anchor reports without mutating state.

    Args:
        input_dir: Directory containing downloaded WRLDC PSP PDFs.

    Returns:
        A dictionary containing template match distribution, semantic review counts,
        classified mismatch groups, and individual report details.
    """
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found at {input_dir}")

    all_pdfs = sorted(input_dir.glob("*.pdf"))
    samples = select_monthly_anchor_paths(all_pdfs, source_id="wrldc")

    template_counts: dict[str, int] = {}
    matched_count = 0
    semantic_review_count = 0
    mismatches: list[dict[str, Any]] = []

    for sample in samples:
        path = sample.pdf_path
        structure = inspect_report_structure(path)
        match = match_report_template("wrldc", structure)

        tid = match.template_id or "unmatched"
        template_counts[tid] = template_counts.get(tid, 0) + 1

        if match.semantic_pass_required:
            semantic_review_count += 1
            mismatches.append(
                {
                    "report_date": sample.report_date,
                    "anchor": sample.anchor,
                    "filename": path.name,
                    "template_id": match.template_id,
                    "confidence": match.confidence,
                    "mismatch_reasons": list(match.reasons),
                }
            )
        else:
            matched_count += 1

    review_groups = classify_review_anchors(mismatches)

    return {
        "total_anchors": len(samples),
        "matched_count": matched_count,
        "semantic_review_count": semantic_review_count,
        "template_distribution": dict(sorted(template_counts.items())),
        "review_classifications": review_groups,
        "mismatches": mismatches,
    }
