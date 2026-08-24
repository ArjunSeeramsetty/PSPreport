"""Replayable corpus inventory and validation for ERLDC PSP reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader

from psp_pipeline.acquisition.downloaders.erldc import download_url
from psp_pipeline.parsing.rldc.templates import (
    inspect_report_structure,
    match_report_template,
)
from psp_pipeline.schema_design.service import select_monthly_anchor_paths

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ERLDCInventoryItem:
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
class ERLDCCorpusSummary:
    """Summary of ERLDC corpus validation, page distributions, and transitions."""

    total_pdf_count: int
    anchor_sample_count: int
    valid_psp_count: int
    invalid_count: int
    page_count_distribution: dict[int, int]
    page_count_transitions: list[dict[str, Any]]
    items: list[ERLDCInventoryItem]

    def to_dict(self) -> dict[str, Any]:
        """Convert the summary to a JSON-serializable dictionary."""
        return asdict(self)


def validate_erldc_pdf(path: Path) -> tuple[int, str, str]:
    """Validate a single ERLDC PDF file and return (page_count, sha256, validation_result).

    A valid ERLDC PSP must contain 'POWER SUPPLY POSITION' (or 'POWER SUPPLY')
    and either 'ERLDC', 'EASTERN REGIONAL LOAD DESPATCH CENTRE', or 'EASTERN REGION'.

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

        # Check the first two pages and raw bytes header for robust recognition
        text_sample = " ".join(
            reader.pages[i].extract_text() or "" for i in range(min(2, page_count))
        ).upper()
        raw_header = content[:16384].upper()

        has_psp = (
            "POWER SUPPLY POSITION" in text_sample
            or "POWER SUPPLY" in text_sample
            or b"POWER SUPPLY POSITION" in raw_header
            or b"POWER SUPPLY" in raw_header
        )
        has_erldc = (
            "ERLDC" in text_sample
            or "EASTERN REGIONAL LOAD DESPATCH CENTRE" in text_sample
            or "EASTERN REGIONAL LOAD DESPATCH CENTER" in text_sample
            or "EASTERN REGION" in text_sample
            or b"ERLDC" in raw_header
            or b"EASTERN REGIONAL LOAD DESPATCH CENTRE" in raw_header
            or b"EASTERN REGIONAL LOAD DESPATCH CENTER" in raw_header
            or b"EASTERN REGION" in raw_header
        )

        if not (has_psp and has_erldc):
            return page_count, sha256, "missing_erldc_header"
        return page_count, sha256, "valid_psp"
    except Exception as exc:
        logger.warning("erldc_pdf_validation_error path=%s error=%s", path, exc)
        return -1, sha256, f"corrupted: {exc}"


def build_erldc_corpus_inventory(input_dir: Path) -> ERLDCCorpusSummary:
    """Scan all local ERLDC PDFs and validate the monthly anchor sample.

    Args:
        input_dir: Directory containing ERLDC PDF files.

    Returns:
        An ERLDCCorpusSummary with full anchor details and transitions.
    """
    all_pdfs = sorted(input_dir.glob("*.pdf"))
    total_pdf_count = len(all_pdfs)

    anchors = select_monthly_anchor_paths(all_pdfs, source_id="erldc")
    anchor_sample_count = len(anchors)

    items: list[ERLDCInventoryItem] = []
    page_counts: dict[int, int] = {}
    valid_count = 0
    invalid_count = 0

    for anchor in anchors:
        page_count, sha256, val_result = validate_erldc_pdf(anchor.pdf_path)
        if val_result == "valid_psp":
            valid_count += 1
            page_counts[page_count] = page_counts.get(page_count, 0) + 1
        else:
            invalid_count += 1

        # Use canonical public portal product URL representation
        url = f"https://erldc.in/api/download/DailyPSPReport/{anchor.pdf_path.name}"

        items.append(
            ERLDCInventoryItem(
                report_date=anchor.report_date,
                anchor=anchor.anchor,
                filename=anchor.pdf_path.name,
                source_url=url,
                sha256=sha256,
                page_count=page_count,
                validation_result=val_result,
                pdf_path=str(anchor.pdf_path.resolve()),
            )
        )

    # Calculate page count transitions chronologically
    transitions: list[dict[str, Any]] = []
    prev_pages: int | None = None
    for item in items:
        if item.page_count > 0:
            if prev_pages is None or item.page_count != prev_pages:
                transitions.append(
                    {
                        "start_date": item.report_date,
                        "anchor": item.anchor,
                        "page_count": item.page_count,
                    }
                )
                prev_pages = item.page_count

    return ERLDCCorpusSummary(
        total_pdf_count=total_pdf_count,
        anchor_sample_count=anchor_sample_count,
        valid_psp_count=valid_count,
        invalid_count=invalid_count,
        page_count_distribution=dict(sorted(page_counts.items())),
        page_count_transitions=transitions,
        items=items,
    )


def audit_erldc_anchor_templates(
    summary: ERLDCCorpusSummary,
) -> dict[str, Any]:
    """Audit ERLDC anchor files against registered templates and document layout drift."""
    audit_results: list[dict[str, Any]] = []
    matched_count = 0
    review_required_count = 0

    for item in summary.items:
        if item.validation_result != "valid_psp":
            continue
        pdf_path = Path(item.pdf_path)
        try:
            matched = match_report_template(pdf_path, source="erldc")
            is_matched = matched.template is not None and matched.confidence >= 0.85
            if is_matched:
                matched_count += 1
            else:
                review_required_count += 1

            audit_results.append(
                {
                    "report_date": item.report_date,
                    "anchor": item.anchor,
                    "filename": item.filename,
                    "page_count": item.page_count,
                    "matched_template_id": matched.template.template_id if matched.template else None,
                    "confidence": matched.confidence,
                    "decision": matched.decision,
                    "is_matched": is_matched,
                    "missing_sections": list(matched.missing_sections),
                    "unexpected_sections": list(matched.unexpected_sections),
                }
            )
        except Exception as exc:
            review_required_count += 1
            audit_results.append(
                {
                    "report_date": item.report_date,
                    "anchor": item.anchor,
                    "filename": item.filename,
                    "page_count": item.page_count,
                    "matched_template_id": None,
                    "confidence": 0.0,
                    "decision": f"error: {exc}",
                    "is_matched": False,
                    "missing_sections": [],
                    "unexpected_sections": [],
                }
            )

    return {
        "audited_at": datetime.now().isoformat(),
        "total_anchors_audited": len(audit_results),
        "matched_count": matched_count,
        "review_required_count": review_required_count,
        "anchors": audit_results,
    }
