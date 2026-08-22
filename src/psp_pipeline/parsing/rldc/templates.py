"""Template contracts for RLDC PSP report structure validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pdfplumber

from psp_pipeline.parsing.rldc.pdf_tables import extract_page_tables


@dataclass(frozen=True)
class TableShape:
    """Expected shape for one table in a known PSP template."""

    page_no: int
    table_no: int
    min_rows: int
    max_rows: int
    min_cols: int
    max_cols: int
    section_name: str


@dataclass(frozen=True)
class ReportTemplate:
    """Known report structure contract used before semantic fallback."""

    template_id: str
    version: str
    rldc: str
    min_pages: int
    max_pages: int
    min_tables: int
    max_tables: int
    required_headings: tuple[str, ...]
    table_shapes: tuple[TableShape, ...]
    min_confidence: float = 0.85


@dataclass(frozen=True)
class ReportStructure:
    """Observed report structure extracted cheaply from a local PDF."""

    page_count: int
    table_count: int
    headings: tuple[str, ...]
    table_shapes: tuple[TableShape, ...]


@dataclass(frozen=True)
class TemplateMatch:
    """Result of comparing an observed report to a known template."""

    template_id: str | None
    template_version: str | None
    confidence: float
    semantic_pass_required: bool
    reasons: tuple[str, ...]


SRLDC_SPLIT_FAMILY_ID = "srldc_daily_psp_split_sections"
SRLDC_FLAT_FAMILY_ID = "srldc_daily_psp_flattened_pages"
SRLDC_FLAT_COMPACT_FAMILY_ID = "srldc_daily_psp_flattened_compact"
UNCLASSIFIED_FAMILY_ID = "unclassified"


DEFAULT_SRLDCP_TEMPLATE = ReportTemplate(
    template_id="srldc_daily_psp_v2026_05",
    version="2026.05",
    rldc="srldc",
    min_pages=10,
    max_pages=12,
    min_tables=40,
    max_tables=48,
    required_headings=(
        "regional availability/demand",
        "state's load",
        "state entities generation",
        "inter-regional exchanges",
        "frequency profile",
        "voltage profile",
        "major reservoir particulars",
        "short-term open access",
        "constraints",
        "weather condition",
        "re/load curtailment",
    ),
    table_shapes=(
        TableShape(1, 1, 3, 4, 9, 12, "regional_availability_demand"),
        TableShape(1, 2, 7, 12, 12, 14, "state_load_details"),
        TableShape(1, 3, 7, 12, 9, 11, "state_demand_forecast"),
        TableShape(1, 4, 7, 12, 12, 14, "state_peak_performance"),
        TableShape(8, 2, 4, 8, 8, 10, "interregional_schedule"),
        TableShape(9, 2, 10, 12, 11, 13, "reservoir_daily"),
        TableShape(10, 3, 7, 9, 8, 10, "curtailment_state"),
        TableShape(10, 4, 7, 9, 12, 14, "compliance_state"),
    ),
)

COMPACT_SRLDCP_TEMPLATE = ReportTemplate(
    template_id="srldc_daily_psp_v2026_01",
    version="2026.01",
    rldc="srldc",
    min_pages=9,
    max_pages=9,
    min_tables=37,
    max_tables=39,
    required_headings=DEFAULT_SRLDCP_TEMPLATE.required_headings,
    table_shapes=(
        TableShape(1, 1, 3, 4, 9, 12, "regional_availability_demand"),
        TableShape(1, 2, 7, 12, 12, 14, "state_load_details"),
        TableShape(1, 3, 7, 12, 9, 11, "state_demand_forecast"),
        TableShape(1, 4, 7, 12, 12, 14, "state_peak_performance"),
        TableShape(7, 1, 4, 4, 10, 10, "interregional_schedule"),
        TableShape(7, 4, 5, 7, 9, 9, "voltage_765"),
        TableShape(7, 7, 4, 5, 12, 12, "reservoir_daily_start"),
        TableShape(8, 2, 8, 10, 14, 14, "market_point_offpeak"),
        TableShape(8, 4, 8, 10, 8, 8, "market_energy"),
        TableShape(9, 2, 7, 9, 8, 10, "curtailment_state"),
        TableShape(9, 3, 7, 9, 12, 14, "compliance_state"),
    ),
)

FLAT_8_SRLDCP_TEMPLATE = ReportTemplate(
    template_id="srldc_daily_psp_v2024_flat_08",
    version="2024.flat08",
    rldc="srldc",
    min_pages=8,
    max_pages=8,
    min_tables=8,
    max_tables=8,
    required_headings=(),
    table_shapes=(
        TableShape(1, 1, 55, 70, 35, 45, "regional_and_state_combo"),
        TableShape(6, 1, 65, 75, 38, 42, "operations_combo"),
        TableShape(7, 1, 60, 70, 48, 52, "market_and_events_combo"),
        TableShape(8, 1, 1, 6, 1, 3, "remarks"),
    ),
)

FLAT_8_2025_SRLDCP_TEMPLATE = ReportTemplate(
    template_id="srldc_daily_psp_v2025_flat_08",
    version="2025.flat08",
    rldc="srldc",
    min_pages=8,
    max_pages=8,
    min_tables=8,
    max_tables=8,
    required_headings=(),
    table_shapes=(
        TableShape(1, 1, 60, 60, 40, 40, "regional_and_state_combo"),
        TableShape(6, 1, 63, 63, 37, 37, "operations_combo"),
        TableShape(7, 1, 57, 57, 35, 35, "market_and_events_combo"),
        TableShape(8, 1, 23, 23, 21, 21, "remarks"),
    ),
)

FLAT_6_2023_SRLDCP_TEMPLATE = ReportTemplate(
    template_id="srldc_daily_psp_v2023_flat_06",
    version="2023.flat06",
    rldc="srldc",
    min_pages=6,
    max_pages=6,
    min_tables=6,
    max_tables=6,
    required_headings=(),
    table_shapes=(
        TableShape(1, 1, 55, 65, 35, 40, "regional_and_state_combo"),
        TableShape(5, 1, 60, 75, 30, 40, "operations_combo"),
        TableShape(6, 1, 35, 55, 30, 45, "market_and_events_combo"),
    ),
)

FLAT_7_2023_SRLDCP_TEMPLATE = ReportTemplate(
    template_id="srldc_daily_psp_v2023_flat_07",
    version="2023.flat07",
    rldc="srldc",
    min_pages=7,
    max_pages=7,
    min_tables=7,
    max_tables=7,
    required_headings=(),
    table_shapes=(
        TableShape(1, 1, 55, 65, 35, 45, "regional_and_state_combo"),
        TableShape(5, 1, 65, 80, 30, 45, "operations_combo"),
        TableShape(6, 1, 53, 75, 35, 55, "market_and_events_combo"),
        TableShape(7, 1, 1, 25, 1, 15, "remarks"),
    ),
)

FLAT_6_2024_SRLDCP_TEMPLATE = ReportTemplate(
    template_id="srldc_daily_psp_v2024_flat_06_wide_operations",
    version="2024.flat06.wide_operations",
    rldc="srldc",
    min_pages=6,
    max_pages=6,
    min_tables=6,
    max_tables=6,
    required_headings=(),
    table_shapes=(
        TableShape(1, 1, 60, 62, 39, 41, "regional_and_state_combo"),
        TableShape(5, 1, 67, 71, 45, 49, "operations_combo_wide"),
        TableShape(6, 1, 51, 55, 39, 43, "market_and_events_combo"),
    ),
)

TEMPLATES: tuple[ReportTemplate, ...] = (
    DEFAULT_SRLDCP_TEMPLATE,
    COMPACT_SRLDCP_TEMPLATE,
    FLAT_8_SRLDCP_TEMPLATE,
    FLAT_8_2025_SRLDCP_TEMPLATE,
    FLAT_6_2023_SRLDCP_TEMPLATE,
    FLAT_7_2023_SRLDCP_TEMPLATE,
    FLAT_6_2024_SRLDCP_TEMPLATE,
)


def inspect_report_structure(pdf_path: Path) -> ReportStructure:
    """Inspect headings and table shapes without running semantic parsing."""

    headings: list[str] = []
    table_shapes: list[TableShape] = []
    table_count = 0
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for line in text.splitlines():
                cleaned = re.sub(r"\s+", " ", line.strip()).lower()
                if re.match(r"^\d+(?:\([a-z]\))?\.?\s+", cleaned):
                    headings.append(cleaned)
            for table_no, table in enumerate(extract_page_tables(page), start=1):
                table_count += 1
                rows = len(table or [])
                cols = max((len(row or []) for row in table or []), default=0)
                table_shapes.append(
                    TableShape(
                        page_no=page_no,
                        table_no=table_no,
                        min_rows=rows,
                        max_rows=rows,
                        min_cols=cols,
                        max_cols=cols,
                        section_name="observed",
                    )
                )
            page.flush_cache()
    return ReportStructure(
        page_count=len(pdf.pages),
        table_count=table_count,
        headings=tuple(headings),
        table_shapes=tuple(table_shapes),
    )


def infer_structural_family(rldc: str, structure: ReportStructure) -> str:
    """Classify a report into a semantic layout family before exact template matching."""

    if rldc.lower() != "srldc":
        return UNCLASSIFIED_FAMILY_ID

    page_table_counts = _page_table_counts(structure)
    heading_text = "\n".join(line.lower() for line in structure.headings)
    if (
        structure.page_count in {9, 10}
        and structure.table_count >= 35
        and "regional availability/demand" in heading_text
    ):
        return SRLDC_SPLIT_FAMILY_ID
    if structure.page_count >= 7 and _is_single_table_per_page(page_table_counts):
        return SRLDC_FLAT_FAMILY_ID
    if structure.page_count <= 6 and _is_single_table_per_page(page_table_counts):
        return SRLDC_FLAT_COMPACT_FAMILY_ID
    return UNCLASSIFIED_FAMILY_ID


def match_report_template(rldc: str, structure: ReportStructure) -> TemplateMatch:
    """Match observed report structure against known templates for an RLDC."""

    candidates = [template for template in TEMPLATES if template.rldc == rldc.lower()]
    if not candidates:
        return TemplateMatch(None, None, 0.0, True, ("no_template_for_rldc",))

    best_template: ReportTemplate | None = None
    best_confidence = -1.0
    best_reasons: tuple[str, ...] = ()
    for template in candidates:
        confidence, reasons = _score_template(template, structure)
        if confidence > best_confidence:
            best_template = template
            best_confidence = confidence
            best_reasons = reasons

    if best_template is None:
        return TemplateMatch(None, None, 0.0, True, ("no_template_match",))
    return TemplateMatch(
        template_id=best_template.template_id,
        template_version=best_template.version,
        confidence=round(best_confidence, 3),
        semantic_pass_required=best_confidence < best_template.min_confidence,
        reasons=best_reasons,
    )


def _score_template(template: ReportTemplate, structure: ReportStructure) -> tuple[float, tuple[str, ...]]:
    """Score one observed report structure against a template."""

    checks = 0
    passed = 0
    reasons: list[str] = []

    checks += 1
    if template.min_pages <= structure.page_count <= template.max_pages:
        passed += 1
    else:
        reasons.append(f"page_count={structure.page_count}")

    checks += 1
    if template.min_tables <= structure.table_count <= template.max_tables:
        passed += 1
    else:
        reasons.append(f"table_count={structure.table_count}")

    heading_text = "\n".join(structure.headings)
    for heading in template.required_headings:
        checks += 1
        if heading in heading_text:
            passed += 1
        else:
            reasons.append(f"missing_heading={heading}")

    observed = {(shape.page_no, shape.table_no): shape for shape in structure.table_shapes}
    for expected in template.table_shapes:
        checks += 1
        actual = observed.get((expected.page_no, expected.table_no))
        if not actual:
            reasons.append(f"missing_table=p{expected.page_no}_t{expected.table_no}")
            continue
        rows_ok = expected.min_rows <= actual.min_rows <= expected.max_rows
        cols_ok = expected.min_cols <= actual.min_cols <= expected.max_cols
        if rows_ok and cols_ok:
            passed += 1
        else:
            reasons.append(
                f"shape_mismatch=p{expected.page_no}_t{expected.table_no}:"
                f"{actual.min_rows}x{actual.min_cols}"
            )
    return passed / max(checks, 1), tuple(reasons)


def _page_table_counts(structure: ReportStructure) -> dict[int, int]:
    """Return extracted table counts grouped by page number."""

    counts: dict[int, int] = {}
    for shape in structure.table_shapes:
        counts[shape.page_no] = counts.get(shape.page_no, 0) + 1
    return counts


def _is_single_table_per_page(page_table_counts: dict[int, int]) -> bool:
    """Return whether each observed page collapsed into one extracted table."""

    return bool(page_table_counts) and all(count == 1 for count in page_table_counts.values())
