"""Replayable corpus inventory and validation for NERLDC PSP reports."""

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

from psp_pipeline.acquisition.downloaders.nerldc import nerldc_psp_url
from psp_pipeline.parsing.rldc.templates import (
    inspect_report_structure,
    match_report_template,
)
from psp_pipeline.schema_design.service import select_monthly_anchor_paths

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NERLDCInventoryItem:
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
class NERLDCCorpusSummary:
    """Summary of NERLDC corpus validation, page distributions, and transitions."""

    total_pdf_count: int
    anchor_sample_count: int
    valid_psp_count: int
    invalid_count: int
    page_count_distribution: dict[int, int]
    page_count_transitions: list[dict[str, Any]]
    items: list[NERLDCInventoryItem]

    def to_dict(self) -> dict[str, Any]:
        """Convert the summary to a JSON-serializable dictionary."""
        return asdict(self)


def validate_nerldc_pdf(path: Path) -> tuple[int, str, str]:
    """Validate a single NERLDC PDF file and return (page_count, sha256, validation_result).

    A valid NERLDC PSP must contain 'POWER SUPPLY POSITION' (or 'POWER SUPPLY')
    and either 'NERLDC', 'NORTH EASTERN REGIONAL LOAD DESPATCH CENTRE', or 'NORTH EASTERN REGION'.

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

        text_sample = " ".join(
            reader.pages[i].extract_text() or "" for i in range(min(2, page_count))
        ).upper()
        raw_header = content[:16384].upper()

        has_psp = (
            "POWER SUPPLY POSITION" in text_sample
            or "POWER SUPPLY" in text_sample
            or "REPORT" in text_sample
            or b"POWER SUPPLY" in raw_header
        )
        has_nerldc = (
            "NERLDC" in text_sample
            or "NORTH EASTERN REGIONAL LOAD DESPATCH CENTRE" in text_sample
            or "NORTH EASTERN REGION" in text_sample
            or "NER" in text_sample
            or "ASSAM" in text_sample
            or "MEGHALAYA" in text_sample
            or "TRIPURA" in text_sample
            or b"NERLDC" in raw_header
            or b"NER-PSP" in raw_header
        )

        if has_psp and has_nerldc:
            return page_count, sha256, "valid_nerldc_psp"
        return page_count, sha256, "unrecognized_header_text"
    except Exception as exc:
        logger.warning("NERLDC PDF parse error for %s: %s", path, exc)
        return 0, sha256, f"corrupted_pdf_{type(exc).__name__}"


def _parse_nerldc_date_from_filename(filename: str) -> date | None:
    """Extract report date from canonical NERLDC filenames."""
    # Pattern: NER-PSP-REPORT-DATED-DD-MM-YYYY.pdf
    match = re.search(r"(\d{2})[-_](\d{2})[-_](\d{4})", filename)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return None


def run_nerldc_corpus_inventory(
    corpus_dir: Path | str,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Scan all local NERLDC PSP PDFs and produce a validated anchor summary.

    1. Enumerate all `.pdf` files in `corpus_dir`.
    2. Select the 114 monthly anchors (1st, 15th, last of month for 2023-04 to 2026-05).
    3. For each anchor, validate content header, page count, and compute SHA-256 digest.
    4. Record page count distribution and structural transitions over time.
    5. Optionally write the JSON summary to `output_path`.

    Args:
        corpus_dir: Directory containing local NERLDC PSP PDFs.
        output_path: Optional file path to persist JSON inventory.

    Returns:
        A dictionary matching `NERLDCCorpusSummary`.
    """
    corpus_path = Path(corpus_dir)
    all_pdfs = sorted(corpus_path.glob("*.pdf"))

    # Map available files by date
    files_by_date: dict[date, Path] = {}
    for p in all_pdfs:
        d = _parse_nerldc_date_from_filename(p.name)
        if d:
            files_by_date[d] = p

    # Select monthly anchors (1st, 15th, last of month from 2023-04 to 2026-05)
    selected_anchors = select_monthly_anchor_paths(all_pdfs, source_id="nerldc")

    inventory_items: list[NERLDCInventoryItem] = []
    page_dist: dict[int, int] = {}
    valid_count = 0
    invalid_count = 0

    for sample in selected_anchors:
        report_dt = date.fromisoformat(sample.report_date)
        pdf_path = sample.pdf_path
        page_count, sha256, result = validate_nerldc_pdf(pdf_path)

        if result == "valid_nerldc_psp":
            valid_count += 1
            page_dist[page_count] = page_dist.get(page_count, 0) + 1
        else:
            invalid_count += 1

        url = nerldc_psp_url(report_dt)
        inventory_items.append(
            NERLDCInventoryItem(
                report_date=sample.report_date,
                anchor=sample.anchor,
                filename=pdf_path.name,
                source_url=url,
                sha256=sha256,
                page_count=page_count,
                validation_result=result,
                pdf_path=str(pdf_path.resolve()),
            )
        )

    # Track page count transitions chronologically
    transitions: list[dict[str, Any]] = []
    last_page_count: int | None = None
    for item in inventory_items:
        if item.validation_result == "valid_nerldc_psp":
            if last_page_count is not None and item.page_count != last_page_count:
                transitions.append(
                    {
                        "transition_date": item.report_date,
                        "from_page_count": last_page_count,
                        "to_page_count": item.page_count,
                        "filename": item.filename,
                    }
                )
            last_page_count = item.page_count

    summary = NERLDCCorpusSummary(
        total_pdf_count=len(all_pdfs),
        anchor_sample_count=len(inventory_items),
        valid_psp_count=valid_count,
        invalid_count=invalid_count,
        page_count_distribution=dict(sorted(page_dist.items())),
        page_count_transitions=transitions,
        items=inventory_items,
    )

    summary_dict = summary.to_dict()

    if output_path is not None:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(summary_dict, f, indent=2)
        logger.info("NERLDC corpus inventory written to %s", out_file)

    return summary_dict
