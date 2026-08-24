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
NRLDC_STANDARD_FAMILY_ID = "nrldc_daily_psp_standard_pages"
WRLDC_STANDARD_FAMILY_ID = "wrldc_daily_psp_standard_pages"
ERLDC_STANDARD_FAMILY_ID = "erldc_daily_psp_standard_pages"
NERLDC_STANDARD_FAMILY_ID = "nerldc_daily_psp_standard_pages"
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

NRLDC_2024_TEMPLATE = ReportTemplate(
    template_id="nrldc_daily_psp_v2024_standard_09_column_generation",
    version="2024.standard09",
    rldc="nrldc",
    min_pages=12,
    max_pages=12,
    min_tables=13,
    max_tables=13,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 50, 58, 35, 42, "regional_and_state_position"),
        TableShape(2, 1, 55, 70, 9, 9, "state_generation"),
        TableShape(5, 1, 50, 70, 13, 13, "regional_generation"),
        TableShape(9, 1, 50, 75, 20, 28, "interregional_exchange"),
        TableShape(11, 1, 60, 75, 30, 36, "market_operations"),
        TableShape(12, 1, 20, 30, 14, 18, "reliability_indices"),
    ),
)

NRLDC_2025_TEMPLATE = ReportTemplate(
    template_id="nrldc_daily_psp_v2025_standard_11_column_generation",
    version="2025.standard11",
    rldc="nrldc",
    min_pages=12,
    max_pages=12,
    min_tables=16,
    max_tables=16,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 50, 58, 38, 42, "regional_and_state_position"),
        TableShape(2, 1, 55, 72, 11, 11, "state_generation"),
        TableShape(5, 1, 50, 70, 15, 15, "regional_generation"),
        TableShape(9, 1, 55, 75, 20, 26, "renewable_generation"),
        TableShape(10, 1, 50, 70, 22, 28, "interregional_exchange"),
        TableShape(11, 1, 60, 75, 30, 36, "market_operations"),
        TableShape(12, 5, 15, 25, 14, 18, "reliability_indices"),
    ),
)

NRLDC_2026_TEMPLATE = ReportTemplate(
    template_id="nrldc_daily_psp_v2026_standard_11_column_storage",
    version="2026.standard11.storage",
    rldc="nrldc",
    min_pages=13,
    max_pages=13,
    min_tables=17,
    max_tables=17,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 50, 58, 38, 42, "regional_and_state_position"),
        TableShape(2, 1, 55, 72, 11, 11, "state_generation"),
        TableShape(5, 1, 50, 70, 15, 15, "regional_generation"),
        TableShape(9, 1, 60, 78, 20, 26, "renewable_and_storage_generation"),
        TableShape(10, 1, 50, 70, 22, 28, "interregional_exchange"),
        TableShape(12, 1, 55, 72, 30, 38, "market_operations"),
        TableShape(13, 4, 18, 28, 14, 18, "reliability_indices"),
    ),
)


WRLDC_2023_TEMPLATE = ReportTemplate(
    template_id="wrldc_daily_psp_v2023_standard_09_column_generation",
    version="2023.standard09",
    rldc="wrldc",
    min_pages=7,
    max_pages=7,
    min_tables=8,
    max_tables=8,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 48, 70, 34, 38, "regional_and_state_position"),
        TableShape(2, 1, 50, 78, 9, 9, "state_generation"),
        TableShape(3, 1, 55, 85, 18, 18, "regional_generation"),
        TableShape(5, 1, 42, 68, 23, 27, "interregional_exchange"),
        TableShape(5, 2, 3, 28, 10, 14, "schedule_exchange"),
        TableShape(6, 1, 50, 82, 28, 34, "operations_and_market"),
        TableShape(7, 1, 4, 25, 7, 12, "report_annotations"),
    ),
)

WRLDC_2024_TEMPLATE = ReportTemplate(
    template_id="wrldc_daily_psp_v2024_standard_09_column_generation",
    version="2024.standard09",
    rldc="wrldc",
    min_pages=8,
    max_pages=8,
    min_tables=9,
    max_tables=9,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 50, 72, 38, 42, "regional_and_state_position"),
        TableShape(2, 1, 50, 78, 9, 9, "state_generation"),
        TableShape(3, 1, 55, 85, 18, 18, "regional_generation"),
        TableShape(5, 1, 50, 82, 29, 35, "interregional_exchange"),
        TableShape(5, 2, 2, 12, 7, 12, "schedule_exchange"),
        TableShape(6, 1, 45, 75, 18, 24, "operations"),
        TableShape(7, 1, 38, 65, 36, 44, "market_operations"),
        TableShape(8, 1, 5, 25, 7, 12, "report_annotations"),
    ),
)

WRLDC_2023_REVISED_TEMPLATE = ReportTemplate(
    template_id="wrldc_daily_psp_v2023_revised_09_column_generation",
    version="2023.revised09",
    rldc="wrldc",
    min_pages=7,
    max_pages=7,
    min_tables=8,
    max_tables=8,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 52, 72, 38, 42, "regional_and_state_position"),
        TableShape(2, 1, 50, 78, 9, 9, "state_generation"),
        TableShape(3, 1, 55, 85, 18, 18, "regional_generation"),
        TableShape(4, 1, 55, 85, 16, 18, "generation_continuation"),
        TableShape(5, 1, 45, 75, 24, 29, "interregional_exchange"),
        TableShape(5, 2, 5, 22, 10, 14, "schedule_exchange"),
        TableShape(6, 1, 48, 78, 18, 24, "operations"),
        TableShape(7, 1, 38, 70, 32, 40, "market_operations"),
    ),
)

WRLDC_2025_TEMPLATE = ReportTemplate(
    template_id="wrldc_daily_psp_v2025_standard_11_column_generation",
    version="2025.standard11",
    rldc="wrldc",
    min_pages=9,
    max_pages=9,
    min_tables=10,
    max_tables=10,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 52, 75, 41, 45, "regional_and_state_position"),
        TableShape(2, 1, 50, 78, 11, 11, "state_generation"),
        TableShape(3, 1, 55, 85, 20, 20, "regional_generation"),
        TableShape(4, 1, 18, 40, 10, 14, "generation_continuation"),
        TableShape(5, 1, 55, 85, 20, 26, "interregional_exchange"),
        TableShape(6, 1, 40, 75, 23, 30, "operations"),
        TableShape(6, 2, 5, 25, 10, 14, "schedule_exchange"),
        TableShape(8, 1, 35, 65, 27, 34, "market_operations"),
        TableShape(9, 1, 5, 25, 7, 12, "report_annotations"),
    ),
)

WRLDC_2024_REVISED_TEMPLATE = ReportTemplate(
    template_id="wrldc_daily_psp_v2024_revised_11_column_generation",
    version="2024.revised11",
    rldc="wrldc",
    min_pages=8,
    max_pages=8,
    min_tables=9,
    max_tables=9,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 52, 75, 41, 45, "regional_and_state_position"),
        TableShape(2, 1, 50, 78, 11, 11, "state_generation"),
        TableShape(3, 1, 55, 85, 20, 20, "regional_generation"),
        TableShape(4, 1, 18, 40, 10, 14, "generation_continuation"),
        TableShape(5, 1, 55, 85, 20, 27, "interregional_exchange"),
        TableShape(6, 1, 35, 65, 23, 30, "operations"),
        TableShape(6, 2, 5, 28, 10, 14, "schedule_exchange"),
        TableShape(7, 1, 45, 80, 23, 30, "market_operations"),
        TableShape(8, 1, 30, 70, 26, 34, "report_annotations"),
    ),
)

WRLDC_2025_REVISED_TEMPLATE = ReportTemplate(
    template_id="wrldc_daily_psp_v2025_revised_11_column_generation",
    version="2025.revised11",
    rldc="wrldc",
    min_pages=9,
    max_pages=9,
    min_tables=10,
    max_tables=10,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 52, 75, 41, 45, "regional_and_state_position"),
        TableShape(2, 1, 50, 78, 11, 11, "state_generation"),
        TableShape(3, 1, 55, 85, 20, 20, "regional_generation"),
        TableShape(4, 1, 18, 40, 10, 14, "generation_continuation"),
        TableShape(5, 1, 55, 90, 18, 24, "physical_exchange_first_page"),
        TableShape(6, 1, 48, 78, 28, 35, "operations"),
        TableShape(6, 2, 4, 20, 10, 14, "schedule_exchange"),
        TableShape(7, 1, 40, 75, 18, 24, "market_operations_first_page"),
        TableShape(8, 1, 45, 75, 34, 45, "market_operations"),
        TableShape(9, 1, 5, 25, 7, 12, "report_annotations"),
    ),
)

WRLDC_2024_TRANSITION_TEMPLATE = ReportTemplate(
    template_id="wrldc_daily_psp_v2024_transition_11_column_generation",
    version="2024.transition11",
    rldc="wrldc",
    min_pages=8,
    max_pages=8,
    min_tables=9,
    max_tables=9,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 55, 75, 41, 45, "regional_and_state_position"),
        TableShape(2, 1, 50, 78, 11, 11, "state_generation"),
        TableShape(3, 1, 55, 85, 20, 20, "regional_generation"),
        TableShape(4, 1, 18, 40, 10, 14, "generation_continuation"),
        TableShape(5, 1, 55, 85, 20, 26, "interregional_exchange"),
        TableShape(6, 1, 35, 65, 23, 30, "operations"),
        TableShape(6, 2, 5, 28, 10, 14, "schedule_exchange"),
        TableShape(7, 1, 40, 70, 18, 24, "market_operations_first_page"),
        TableShape(8, 1, 40, 70, 32, 40, "market_operations"),
    ),
)

WRLDC_2026_TEMPLATE = ReportTemplate(
    template_id="wrldc_daily_psp_v2026_standard_11_column_generation",
    version="2026.standard11",
    rldc="wrldc",
    min_pages=9,
    max_pages=9,
    min_tables=10,
    max_tables=10,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 52, 75, 41, 45, "regional_and_state_position"),
        TableShape(2, 1, 50, 78, 11, 11, "state_generation"),
        TableShape(3, 1, 55, 85, 20, 20, "regional_generation"),
        TableShape(4, 1, 18, 40, 10, 14, "generation_continuation"),
        TableShape(5, 1, 55, 90, 10, 15, "physical_exchange_first_page"),
        TableShape(6, 1, 55, 90, 20, 26, "interregional_exchange"),
        TableShape(7, 1, 25, 55, 23, 30, "operations"),
        TableShape(7, 2, 20, 45, 10, 14, "schedule_exchange"),
        TableShape(8, 1, 40, 75, 23, 30, "market_operations"),
        TableShape(9, 1, 30, 70, 26, 34, "report_annotations"),
    ),
)

WRLDC_2026_EARLY_TEMPLATE = ReportTemplate(
    template_id="wrldc_daily_psp_v2026_early_11_column_generation",
    version="2026.early11",
    rldc="wrldc",
    min_pages=9,
    max_pages=9,
    min_tables=10,
    max_tables=10,
    required_headings=("3(a) state entitiesgeneration", "3(b) regionalentitiesgeneration"),
    table_shapes=(
        TableShape(1, 1, 52, 75, 41, 45, "regional_and_state_position"),
        TableShape(2, 1, 50, 78, 11, 11, "state_generation"),
        TableShape(3, 1, 55, 85, 20, 20, "regional_generation"),
        TableShape(4, 1, 18, 40, 10, 14, "generation_continuation"),
        TableShape(5, 1, 55, 90, 10, 15, "physical_exchange_first_page"),
        TableShape(6, 1, 55, 90, 20, 26, "interregional_exchange"),
        TableShape(7, 1, 5, 20, 23, 28, "operations_first_page"),
        TableShape(7, 2, 35, 65, 10, 14, "operations"),
        TableShape(8, 1, 50, 75, 27, 34, "market_operations"),
        TableShape(9, 1, 20, 45, 15, 20, "report_annotations"),
    ),
)


# ERLDC has published the same operational report through both flattened and
# split-table PDF producers. These contracts classify the extracted geometry;
# the date is intentionally not used as a proxy for a particular layout.
ERLDC_2023_TEMPLATE = ReportTemplate(
    template_id="erldc_daily_psp_v2023_flat_09_column_generation",
    version="2023.flat09",
    rldc="erldc",
    min_pages=6,
    max_pages=6,
    min_tables=10,
    max_tables=10,
    required_headings=(),
    table_shapes=(
        TableShape(1, 1, 48, 52, 15, 15, "regional_and_state_position"),
        TableShape(1, 2, 9, 11, 5, 5, "state_peak_position"),
        TableShape(2, 1, 63, 70, 9, 9, "state_generation"),
        TableShape(3, 1, 65, 75, 13, 13, "regional_generation"),
        TableShape(4, 1, 60, 70, 12, 12, "generation_continuation"),
        TableShape(5, 1, 54, 62, 17, 17, "interregional_exchange"),
        TableShape(6, 1, 20, 30, 11, 11, "market_operations"),
    ),
)

ERLDC_2024_FLAT_TEMPLATE = ReportTemplate(
    template_id="erldc_daily_psp_v2024_flat_09_column_generation",
    version="2024.flat09",
    rldc="erldc",
    min_pages=7,
    max_pages=7,
    min_tables=10,
    max_tables=10,
    required_headings=(),
    table_shapes=(
        TableShape(1, 1, 58, 63, 18, 18, "regional_and_state_position"),
        TableShape(2, 1, 68, 77, 9, 9, "state_generation"),
        TableShape(3, 1, 68, 75, 13, 13, "regional_generation"),
        TableShape(4, 1, 60, 67, 16, 16, "generation_continuation"),
        TableShape(5, 1, 43, 55, 27, 27, "interregional_exchange"),
        TableShape(6, 1, 53, 60, 40, 40, "market_operations"),
        TableShape(7, 1, 8, 25, 11, 11, "reservoirs_and_annotations"),
    ),
)

ERLDC_2024_SPLIT_TEMPLATE = ReportTemplate(
    template_id="erldc_daily_psp_v2024_split_11_column_generation",
    version="2024.split11",
    rldc="erldc",
    min_pages=11,
    max_pages=11,
    min_tables=40,
    max_tables=40,
    required_headings=(
        "1. regional availability/demand:",
        "3(a) state entities generation:",
        "4(a) inter-regional exchanges (import=(+ve) /export =(-ve))",
    ),
    table_shapes=(
        TableShape(1, 1, 3, 3, 10, 10, "regional_availability"),
        TableShape(1, 2, 10, 10, 15, 15, "state_energy_position"),
        TableShape(2, 2, 11, 11, 11, 11, "state_generation"),
        TableShape(3, 2, 24, 24, 11, 11, "generation_continuation"),
        TableShape(5, 1, 39, 39, 12, 12, "regional_generation"),
        TableShape(6, 3, 20, 20, 9, 9, "interregional_exchange"),
        TableShape(8, 5, 17, 17, 8, 8, "frequency_and_voltage"),
        TableShape(9, 2, 10, 10, 14, 14, "market_operations"),
        TableShape(11, 2, 9, 9, 11, 11, "reservoirs"),
    ),
)

ERLDC_2025_SPLIT_TEMPLATE = ReportTemplate(
    template_id="erldc_daily_psp_v2025_split_11_column_generation",
    version="2025.split11",
    rldc="erldc",
    min_pages=7,
    max_pages=7,
    min_tables=33,
    max_tables=34,
    required_headings=(
        "1. regional availability/demand:",
        "3(a) state entities generation:",
        "4(a) inter-regional exchanges (import=(+ve) /export =(-ve))",
    ),
    table_shapes=(
        TableShape(1, 1, 3, 3, 10, 10, "regional_availability"),
        TableShape(1, 2, 10, 10, 15, 15, "state_energy_position"),
        TableShape(1, 4, 10, 10, 7, 7, "state_peak_position"),
    ),
)

ERLDC_2025_FLAT_TEMPLATE = ReportTemplate(
    template_id="erldc_daily_psp_v2025_flat_11_column_generation",
    version="2025.flat11",
    rldc="erldc",
    min_pages=7,
    max_pages=7,
    min_tables=10,
    max_tables=10,
    required_headings=(),
    table_shapes=(
        TableShape(1, 1, 60, 63, 23, 24, "regional_and_state_position"),
        TableShape(2, 1, 70, 74, 11, 11, "state_generation"),
        TableShape(3, 1, 68, 74, 21, 21, "regional_generation"),
        TableShape(4, 1, 60, 72, 19, 25, "generation_continuation"),
        TableShape(5, 1, 45, 55, 27, 32, "interregional_exchange"),
        TableShape(6, 1, 55, 60, 40, 40, "market_operations"),
        TableShape(7, 1, 10, 12, 11, 11, "reservoirs_and_annotations"),
    ),
)

NERLDC_2023_TEMPLATE = ReportTemplate(
    template_id="nerldc_daily_psp_v2023_standard_09_column_generation",
    version="2023.standard09",
    rldc="nerldc",
    min_pages=5,
    max_pages=5,
    min_tables=23,
    max_tables=24,
    required_headings=(
        "1. regional availability/demand:",
        "3(a) state entities generation:",
        "3(b) regional entities generation",
        "4(a) inter-regional exchanges (import=(+ve) /export =(-ve))",
    ),
    table_shapes=(
        TableShape(1, 1, 3, 3, 10, 10, "regional_availability"),
        TableShape(1, 2, 10, 10, 14, 14, "state_energy_position"),
        TableShape(2, 2, 12, 18, 9, 9, "state_generation"),
        TableShape(3, 1, 20, 35, 12, 12, "regional_generation"),
        TableShape(4, 3, 10, 12, 9, 9, "interregional_exchange"),
        TableShape(5, 1, 18, 24, 15, 15, "market_operations"),
    ),
)

NERLDC_2024_TEMPLATE = ReportTemplate(
    template_id="nerldc_daily_psp_v2024_standard_09_column_generation",
    version="2024.standard09",
    rldc="nerldc",
    min_pages=5,
    max_pages=5,
    min_tables=23,
    max_tables=23,
    required_headings=NERLDC_2023_TEMPLATE.required_headings,
    table_shapes=(
        TableShape(1, 1, 3, 3, 9, 9, "regional_availability"),
        TableShape(1, 2, 10, 10, 14, 14, "state_energy_position"),
        TableShape(2, 2, 12, 16, 9, 9, "state_generation"),
        TableShape(3, 1, 28, 34, 20, 20, "regional_generation"),
        TableShape(4, 3, 10, 12, 9, 9, "interregional_exchange"),
        TableShape(5, 1, 38, 45, 30, 30, "market_operations"),
    ),
)

NERLDC_2025_TEMPLATE = ReportTemplate(
    template_id="nerldc_daily_psp_v2025_standard_10_column_generation",
    version="2025.standard10",
    rldc="nerldc",
    min_pages=5,
    max_pages=5,
    min_tables=25,
    max_tables=25,
    required_headings=NERLDC_2023_TEMPLATE.required_headings,
    table_shapes=(
        TableShape(1, 1, 3, 3, 10, 10, "regional_availability"),
        TableShape(1, 2, 10, 10, 14, 14, "state_energy_position"),
        TableShape(2, 2, 12, 16, 10, 10, "state_generation"),
        TableShape(3, 1, 28, 34, 19, 19, "regional_generation"),
        TableShape(4, 3, 9, 11, 9, 9, "interregional_exchange"),
        TableShape(5, 1, 18, 22, 19, 19, "market_operations"),
    ),
)

NERLDC_2026_TEMPLATE = ReportTemplate(
    template_id="nerldc_daily_psp_v2026_standard_09_column_generation",
    version="2026.standard09",
    rldc="nerldc",
    min_pages=5,
    max_pages=5,
    min_tables=27,
    max_tables=27,
    required_headings=NERLDC_2023_TEMPLATE.required_headings,
    table_shapes=(
        TableShape(1, 1, 3, 3, 10, 10, "regional_availability"),
        TableShape(1, 2, 10, 10, 14, 14, "state_energy_position"),
        TableShape(2, 2, 12, 16, 9, 9, "state_generation"),
        TableShape(3, 1, 22, 26, 12, 12, "regional_generation"),
        TableShape(4, 3, 10, 12, 9, 9, "interregional_exchange"),
        TableShape(5, 1, 8, 12, 7, 7, "market_operations"),
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
    NRLDC_2024_TEMPLATE,
    NRLDC_2025_TEMPLATE,
    NRLDC_2026_TEMPLATE,
    WRLDC_2023_TEMPLATE,
    WRLDC_2023_REVISED_TEMPLATE,
    WRLDC_2024_TEMPLATE,
    WRLDC_2024_REVISED_TEMPLATE,
    WRLDC_2024_TRANSITION_TEMPLATE,
    WRLDC_2025_TEMPLATE,
    WRLDC_2025_REVISED_TEMPLATE,
    WRLDC_2026_TEMPLATE,
    WRLDC_2026_EARLY_TEMPLATE,
    ERLDC_2023_TEMPLATE,
    ERLDC_2024_FLAT_TEMPLATE,
    ERLDC_2024_SPLIT_TEMPLATE,
    ERLDC_2025_SPLIT_TEMPLATE,
    ERLDC_2025_FLAT_TEMPLATE,
    NERLDC_2023_TEMPLATE,
    NERLDC_2024_TEMPLATE,
    NERLDC_2025_TEMPLATE,
    NERLDC_2026_TEMPLATE,
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

    if rldc.lower() == "nrldc":
        if structure.page_count in {12, 13} and structure.table_count >= 13:
            return NRLDC_STANDARD_FAMILY_ID
        return UNCLASSIFIED_FAMILY_ID

    if rldc.lower() == "wrldc":
        if structure.page_count in {7, 8, 9} and structure.table_count >= 8:
            return WRLDC_STANDARD_FAMILY_ID
        return UNCLASSIFIED_FAMILY_ID

    if rldc.lower() == "erldc":
        if structure.page_count in {6, 7, 11} and structure.table_count >= 10:
            return ERLDC_STANDARD_FAMILY_ID
        return UNCLASSIFIED_FAMILY_ID

    if rldc.lower() == "nerldc":
        if structure.page_count == 5 and structure.table_count >= 23:
            return NERLDC_STANDARD_FAMILY_ID
        return UNCLASSIFIED_FAMILY_ID

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

    if best_template is None or best_confidence == 0:
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
