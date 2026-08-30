"""Replayable corpus inventory and validation for Grid-India NLDC PSP reports."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader

from psp_pipeline.schema_design.service import select_monthly_anchor_paths

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NLDCInventoryItem:
    """Validation record for one monthly anchor report."""

    report_date: str
    anchor: str
    filename: str
    source_url: str | None
    sha256: str
    page_count: int
    validation_result: str
    pdf_path: str


@dataclass(frozen=True)
class NLDCCorpusSummary:
    """Summary of NLDC corpus validation, page distributions, and transitions."""

    total_pdf_count: int
    anchor_sample_count: int
    valid_psp_count: int
    invalid_count: int
    page_count_distribution: dict[int, int]
    page_count_transitions: list[dict[str, Any]]
    items: list[NLDCInventoryItem]

    def to_dict(self) -> dict[str, Any]:
        """Convert the summary to a JSON-serializable dictionary."""
        return asdict(self)


def validate_nldc_pdf(path: Path) -> tuple[int, str, str]:
    """Validate a single NLDC PDF file and return (page_count, sha256, validation_result).

    Phase-A NLDC layout requires at least 3 pages containing national PSP headers,
    Page 2 summary/frequency, and Page 3 inter-regional physical exchange.

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
        if page_count < 3:
            return page_count, sha256, "insufficient_pages"

        # Check pages and raw header for national NLDC / Grid-India identifiers
        pages_text = [
            (reader.pages[i].extract_text() or "").upper()
            for i in range(min(page_count, 5))
        ]
        combined_text = " ".join(pages_text)
        raw_header = content[:32768].upper()

        has_psp = (
            "POWER SUPPLY POSITION" in combined_text
            or "DAILY PSP" in combined_text
            or "PSP" in combined_text
            or b"POWER SUPPLY POSITION" in raw_header
            or b"DAILY PSP" in raw_header
            or b"PSP" in raw_header
        )
        has_nldc = (
            "NLDC" in combined_text
            or "NATIONAL LOAD DESPATCH CENTRE" in combined_text
            or "NATIONAL LOAD DESPATCH CENTER" in combined_text
            or "GRID-INDIA" in combined_text
            or "GRID INDIA" in combined_text
            or "ALL INDIA" in combined_text
            or b"NLDC" in raw_header
            or b"NATIONAL LOAD DESPATCH CENTRE" in raw_header
            or b"NATIONAL LOAD DESPATCH CENTER" in raw_header
            or b"GRID-INDIA" in raw_header
            or b"GRID INDIA" in raw_header
        )

        if not (has_psp and has_nldc):
            return page_count, sha256, "missing_nldc_header"

        # Enforce summary and inter-regional exchange section signatures across front pages
        p1_text = pages_text[0] if len(pages_text) > 0 else ""
        p2_text = pages_text[1] if len(pages_text) > 1 else ""
        p3_text = pages_text[2] if len(pages_text) > 2 else ""

        has_summary = (
            "DEMAND MET" in p1_text
            or "DEMAND" in p1_text
            or "FREQUENCY PROFILE" in p1_text
            or "DEMAND MET" in p2_text
            or "DEMAND" in p2_text
            or "FREQUENCY PROFILE" in p2_text
            or "FVI" in p2_text
            or "ALL INDIA" in p2_text
            or b"DEMAND MET" in raw_header
            or b"DEMAND" in raw_header
            or b"FREQUENCY PROFILE" in raw_header
            or b"FVI" in raw_header
        )
        if not has_summary:
            return page_count, sha256, "missing_summary_signature"

        has_exchange = (
            "IMPORT/EXPORT" in p2_text
            or "LINE DETAILS" in p2_text
            or "MAX IMPORT" in p2_text
            or "INTER REGIONAL" in p2_text
            or "INTER-REGIONAL" in p2_text
            or "EXCHANGE" in p2_text
            or "IMPORT/EXPORT" in p3_text
            or "LINE DETAILS" in p3_text
            or "MAX IMPORT" in p3_text
            or "INTER REGIONAL" in p3_text
            or "INTER-REGIONAL" in p3_text
            or "EXCHANGE" in p3_text
            or b"IMPORT/EXPORT" in raw_header
            or b"LINE DETAILS" in raw_header
            or b"MAX IMPORT" in raw_header
            or b"INTER REGIONAL" in raw_header
            or b"INTER-REGIONAL" in raw_header
        )
        if not has_exchange:
            return page_count, sha256, "missing_exchange_signature"

        return page_count, sha256, "valid_psp"
    except Exception as exc:
        logger.warning("nldc_pdf_validation_error path=%s error=%s", path, exc)
        return -1, sha256, f"corrupted: {exc}"


def build_nldc_corpus_inventory(
    directory: Path,
    anchor_sample_only: bool = True,
    known_urls: dict[str, str] | None = None,
) -> NLDCCorpusSummary:
    """Build a validation inventory of local NLDC PSP PDF reports.

    Args:
        directory: Directory containing local NLDC PSP PDF reports.
        anchor_sample_only: If True, only evaluate sampled monthly anchors.
        known_urls: Optional mapping of filename/path to discovered source URL.

    Returns:
        NLDCCorpusSummary summarizing validation results and page transitions.
    """
    if not directory.exists() or not directory.is_dir():
        return NLDCCorpusSummary(
            total_pdf_count=0,
            anchor_sample_count=0,
            valid_psp_count=0,
            invalid_count=0,
            page_count_distribution={},
            page_count_transitions=[],
            items=[],
        )

    all_pdfs = sorted(directory.glob("*.pdf"))
    total_count = len(all_pdfs)

    if anchor_sample_only and all_pdfs:
        anchor_samples = select_monthly_anchor_paths(all_pdfs, source_id="grid_india_national")
        seen_paths: set[Path] = set()
        eval_items: list[tuple[str, str, Path]] = []
        for s in anchor_samples:
            if s.pdf_path in seen_paths:
                continue
            seen_paths.add(s.pdf_path)
            eval_items.append((s.report_date, s.anchor, s.pdf_path))
    else:
        eval_items = [
            ("unknown", "all", p) for p in all_pdfs
        ]

    items: list[NLDCInventoryItem] = []
    page_counts: list[int] = []
    valid_count = 0
    invalid_count = 0

    for report_date, anchor, path in eval_items:
        page_count, sha256, status = validate_nldc_pdf(path)
        if status == "valid_psp":
            valid_count += 1
            page_counts.append(page_count)
        else:
            invalid_count += 1

        source_url = known_urls.get(path.name) if known_urls else None
        items.append(
            NLDCInventoryItem(
                report_date=report_date,
                anchor=anchor,
                filename=path.name,
                source_url=source_url,
                sha256=sha256,
                page_count=page_count,
                validation_result=status,
                pdf_path=str(path),
            )
        )

    page_distribution = dict(sorted(Counter(page_counts).items()))
    transitions = _compute_page_transitions(items)

    return NLDCCorpusSummary(
        total_pdf_count=total_count,
        anchor_sample_count=len(items),
        valid_psp_count=valid_count,
        invalid_count=invalid_count,
        page_count_distribution=page_distribution,
        page_count_transitions=transitions,
        items=items,
    )


def _compute_page_transitions(items: list[NLDCInventoryItem]) -> list[dict[str, Any]]:
    """Compute chronological page count transitions across evaluated items."""
    sorted_items = [it for it in items if it.validation_result == "valid_psp" and it.report_date != "unknown"]
    sorted_items.sort(key=lambda x: x.report_date)

    transitions: list[dict[str, Any]] = []
    prev_pages: int | None = None
    for item in sorted_items:
        if prev_pages is not None and item.page_count != prev_pages:
            transitions.append({
                "report_date": item.report_date,
                "from_pages": prev_pages,
                "to_pages": item.page_count,
                "filename": item.filename,
            })
        prev_pages = item.page_count
    return transitions
