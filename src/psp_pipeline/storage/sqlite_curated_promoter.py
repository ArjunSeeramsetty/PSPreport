"""Promote approved SRLDC mappings into curated SQLite fact tables."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
import json
import re
import sqlite3

from psp_pipeline.schema_design.registry import (
    REGIONAL_MAPPINGS,
    SRLDC_COMPACT_TEMPLATE_ID,
    SRLDC_FLAT_8_TEMPLATE_ID,
    SRLDC_FLAT_8_2025_TEMPLATE_ID,
    SRLDC_FLAT_6_2023_TEMPLATE_ID,
    SRLDC_FLAT_6_2024_WIDE_TEMPLATE_ID,
    SRLDC_FLAT_7_2023_TEMPLATE_ID,
    SRLDC_TEMPLATE_ID,
    SRLDC_TEMPLATE_IDS,
    STATE_ENERGY_MAPPINGS,
    STATE_FORECAST_MAPPINGS,
    STATE_PEAK_MAPPINGS,
)
from psp_pipeline.schema_design.service import persist_report_schema_proposals
from psp_pipeline.storage.sqlite_dimensions import (
    DimensionResolutionError,
    GenerationIdentity,
    record_resolution_issue,
    resolve_generation_identity,
    resolve_state_id,
)
from psp_pipeline.storage.sqlite_srldc_enrichment import (
    reservoir_state_name,
    transmission_location,
    voltage_node_state_name,
)


SR_REGION_NAME = "Southern Region"
SR_STATE_ROWS = range(3, 9)
GENERATION_SOURCE_SEQUENCE = (
    "Thermal",
    "Hydro",
    "Gas, Naptha & Diesel",
    "Nuclear",
    "Wind",
    "Solar",
    "Others",
    "Total",
)
MARKET_POINT_COLUMNS = {
    2: "TGNA",
    3: "IEX GDAM",
    4: "IEX DAM",
    5: "IEX HPDAM",
    6: "IEX RTM",
    7: "PXIL GDAM",
    8: "PXIL DAM",
    9: "PXIL HPDAM",
    10: "PXIL RTM",
    11: "HPX GDAM",
    12: "HPX DAM",
    13: "HPX HPDAM",
    14: "HPX RTM",
}
MARKET_ENERGY_COLUMNS = {
    2: "ISGS+GNA",
    3: "TGNA",
    4: "GDAM",
    5: "DAM",
    6: "HPDAM",
    7: "RTM",
    8: "TOTAL",
}
MARKET_RANGE_TABLES = (
    ("daily_range", ("ISGS+GNA", "TGNA", "IEX GDAM", "PXIL GDAM", "HPX GDAM", "IEX DAM", "PXIL DAM")),
    ("daily_range", ("HPX DAM", "IEX HPDAM", "PXIL HPDAM", "HPX HPDAM", "IEX RTM", "PXIL RTM", "HPX RTM")),
)


@dataclass(frozen=True)
class RowWindow:
    """A page/table slice, optionally restricted to a row range."""

    page_no: int
    table_no: int
    start_row: int = 1
    end_row: int | None = None


@dataclass(frozen=True)
class GenerationScope:
    """A row window carrying generation section metadata."""

    window: RowWindow
    section_name: str
    state_name: str | None


@dataclass(frozen=True)
class VoltageWindow:
    """A row window for one nominal-kV voltage section."""

    window: RowWindow
    nominal_kv: float


GENERATION_TABLE_SCOPES = (
    GenerationScope(RowWindow(1, 5), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 1), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 2), "state_telangana", "Telangana"),
    GenerationScope(RowWindow(3, 1), "state_karnataka", "Karnataka"),
    GenerationScope(RowWindow(3, 2), "state_kerala", "Kerala"),
    GenerationScope(RowWindow(4, 1), "state_kerala", "Kerala"),
    GenerationScope(RowWindow(4, 2), "state_tamil_nadu", "Tamil Nadu"),
    GenerationScope(RowWindow(5, 1), "state_tamil_nadu", "Tamil Nadu"),
    GenerationScope(RowWindow(5, 2), "state_puducherry", "Puducherry"),
    GenerationScope(RowWindow(5, 3), "regional_generation", None),
    GenerationScope(RowWindow(5, 4), "regional_generation", None),
    GenerationScope(RowWindow(5, 5), "regional_generation", None),
    GenerationScope(RowWindow(6, 1), "regional_generation", None),
    GenerationScope(RowWindow(6, 2), "regional_renewable_wind", None),
    GenerationScope(RowWindow(6, 3), "regional_renewable_solar", None),
    GenerationScope(RowWindow(7, 1), "regional_renewable_solar", None),
    GenerationScope(RowWindow(7, 2), "regional_bess", None),
    GenerationScope(RowWindow(7, 3), "regional_generation_totals", None),
)

COMPACT_GENERATION_TABLE_SCOPES = (
    GenerationScope(RowWindow(1, 5), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 1), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 2), "state_telangana", "Telangana"),
    GenerationScope(RowWindow(2, 3), "state_karnataka", "Karnataka"),
    GenerationScope(RowWindow(3, 1), "state_karnataka", "Karnataka"),
    GenerationScope(RowWindow(3, 2), "state_kerala", "Kerala"),
    GenerationScope(RowWindow(3, 3), "state_tamil_nadu", "Tamil Nadu"),
    GenerationScope(RowWindow(4, 1), "state_tamil_nadu", "Tamil Nadu"),
    GenerationScope(RowWindow(4, 2), "regional_generation", None),
    GenerationScope(RowWindow(4, 3), "regional_generation", None),
    GenerationScope(RowWindow(4, 4), "regional_generation", None),
    GenerationScope(RowWindow(4, 5), "regional_renewable_wind", None),
    GenerationScope(RowWindow(5, 1), "regional_renewable_wind", None),
    GenerationScope(RowWindow(5, 2), "regional_renewable_solar", None),
    GenerationScope(RowWindow(6, 1), "regional_renewable_solar", None),
    GenerationScope(RowWindow(6, 2), "regional_bess", None),
    GenerationScope(RowWindow(6, 3), "regional_generation_totals", None),
)

FLAT_8_GENERATION_TABLE_SCOPES = (
    GenerationScope(RowWindow(1, 1, 39, 60), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 1, 1, 7), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 1, 12, 29), "state_telangana", "Telangana"),
    GenerationScope(RowWindow(2, 1, 31, 49), "state_karnataka", "Karnataka"),
    GenerationScope(RowWindow(2, 1, 52, 69), "state_kerala", "Kerala"),
    GenerationScope(RowWindow(3, 1, 5, 30), "state_tamil_nadu", "Tamil Nadu"),
    GenerationScope(RowWindow(3, 1, 35, 60), "regional_generation", None),
    GenerationScope(RowWindow(4, 1, 5, 17), "regional_generation", None),
    GenerationScope(RowWindow(4, 1, 21, 34), "regional_renewable_wind", None),
    GenerationScope(RowWindow(5, 1, 6, 40), "regional_renewable_solar", None),
    GenerationScope(RowWindow(5, 1, 46, 50), "regional_generation_totals", None),
)

FLAT_6_2023_GENERATION_TABLE_SCOPES = (
    GenerationScope(RowWindow(1, 1, 39, 61), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 1, 1, 5), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 1, 10, 25), "state_telangana", "Telangana"),
    GenerationScope(RowWindow(2, 1, 30, 47), "state_karnataka", "Karnataka"),
    GenerationScope(RowWindow(2, 1, 52, 68), "state_kerala", "Kerala"),
    GenerationScope(RowWindow(3, 1, 5, 29), "state_tamil_nadu", "Tamil Nadu"),
    GenerationScope(RowWindow(3, 1, 34, 74), "regional_generation", None),
    GenerationScope(RowWindow(4, 1, 5, 12), "regional_renewable_wind", None),
    GenerationScope(RowWindow(4, 1, 17, 49), "regional_renewable_solar", None),
    GenerationScope(RowWindow(4, 1, 51, 60), "regional_generation_totals", None),
)

FLAT_6_2023_STATE_ENERGY_MAPPINGS = {
    2: STATE_ENERGY_MAPPINGS[2],
    4: STATE_ENERGY_MAPPINGS[3],
    7: STATE_ENERGY_MAPPINGS[4],
    9: STATE_ENERGY_MAPPINGS[5],
    11: STATE_ENERGY_MAPPINGS[6],
    13: STATE_ENERGY_MAPPINGS[7],
    16: STATE_ENERGY_MAPPINGS[8],
    21: STATE_ENERGY_MAPPINGS[9],
    25: STATE_ENERGY_MAPPINGS[10],
    28: STATE_ENERGY_MAPPINGS[11],
    31: STATE_ENERGY_MAPPINGS[12],
    35: STATE_ENERGY_MAPPINGS[13],
}

FLAT_6_2023_STATE_FORECAST_MAPPINGS = {
    3: STATE_FORECAST_MAPPINGS[2],
    5: STATE_FORECAST_MAPPINGS[3],
    10: STATE_FORECAST_MAPPINGS[4],
    13: STATE_FORECAST_MAPPINGS[5],
    17: STATE_FORECAST_MAPPINGS[6],
    22: STATE_FORECAST_MAPPINGS[7],
}

FLAT_6_2023_STATE_PEAK_MAPPINGS = {
    3: STATE_PEAK_MAPPINGS[2],
    7: STATE_PEAK_MAPPINGS[3],
    10: STATE_PEAK_MAPPINGS[4],
    15: STATE_PEAK_MAPPINGS[5],
    20: STATE_PEAK_MAPPINGS[6],
    24: STATE_PEAK_MAPPINGS[7],
    30: STATE_PEAK_MAPPINGS[8],
    34: STATE_PEAK_MAPPINGS[9],
}

FLAT_7_2023_STATE_ENERGY_MAPPINGS = {
    2: STATE_ENERGY_MAPPINGS[2],
    4: STATE_ENERGY_MAPPINGS[3],
    8: STATE_ENERGY_MAPPINGS[4],
    11: STATE_ENERGY_MAPPINGS[5],
    14: STATE_ENERGY_MAPPINGS[6],
    17: STATE_ENERGY_MAPPINGS[7],
    20: STATE_ENERGY_MAPPINGS[8],
    25: STATE_ENERGY_MAPPINGS[9],
    29: STATE_ENERGY_MAPPINGS[10],
    32: STATE_ENERGY_MAPPINGS[11],
    35: STATE_ENERGY_MAPPINGS[12],
    39: STATE_ENERGY_MAPPINGS[13],
}

FLAT_7_2023_STATE_FORECAST_MAPPINGS = {
    3: STATE_FORECAST_MAPPINGS[2],
    5: STATE_FORECAST_MAPPINGS[3],
    11: STATE_FORECAST_MAPPINGS[4],
    16: STATE_FORECAST_MAPPINGS[5],
    18: STATE_FORECAST_MAPPINGS[6],
    24: STATE_FORECAST_MAPPINGS[7],
    27: STATE_FORECAST_MAPPINGS[8],
}

FLAT_7_2023_STATE_PEAK_MAPPINGS = {
    3: STATE_PEAK_MAPPINGS[2],
    6: STATE_PEAK_MAPPINGS[3],
    9: STATE_PEAK_MAPPINGS[4],
    13: STATE_PEAK_MAPPINGS[5],
    17: STATE_PEAK_MAPPINGS[6],
    21: STATE_PEAK_MAPPINGS[7],
    23: STATE_PEAK_MAPPINGS[8],
    28: STATE_PEAK_MAPPINGS[9],
    31: STATE_PEAK_MAPPINGS[10],
    34: STATE_PEAK_MAPPINGS[11],
    37: STATE_PEAK_MAPPINGS[12],
    40: STATE_PEAK_MAPPINGS[13],
}

FLAT_7_2023_GENERATION_TABLE_SCOPES = (
    GenerationScope(RowWindow(1, 1, 39, 61), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 1, 1, 5), "state_andhra_pradesh", "Andhra Pradesh"),
    GenerationScope(RowWindow(2, 1, 10, 25), "state_telangana", "Telangana"),
    GenerationScope(RowWindow(2, 1, 30, 47), "state_karnataka", "Karnataka"),
    GenerationScope(RowWindow(2, 1, 52, 68), "state_kerala", "Kerala"),
    GenerationScope(RowWindow(3, 1, 5, 29), "state_tamil_nadu", "Tamil Nadu"),
    GenerationScope(RowWindow(3, 1, 34, 58), "regional_generation", None),
    # Page 4 changes section breaks between the 2023 and 2024 reports.
    # Source headings in the rows determine the active fuel bucket.
    GenerationScope(RowWindow(4, 1, 1, 68), "regional_generation", None),
    GenerationScope(RowWindow(5, 1, 1, 10), "regional_generation_totals", None),
)

FLAT_6_2024_WIDE_GENERATION_TABLE_SCOPES = (
    *FLAT_6_2023_GENERATION_TABLE_SCOPES[:-1],
    GenerationScope(RowWindow(4, 1, 5, 15), "regional_renewable_wind", None),
    GenerationScope(RowWindow(4, 1, 20, 52), "regional_renewable_solar", None),
    GenerationScope(RowWindow(4, 1, 54, 63), "regional_generation_totals", None),
)


@dataclass(frozen=True)
class SRLDCPromoterLayout:
    """Template-specific page and table coordinates for SRLDC promotion."""

    generation_table_scopes: tuple[GenerationScope, ...]
    regional_summary_window: RowWindow
    state_energy_window: RowWindow
    state_forecast_window: RowWindow
    state_peak_window: RowWindow
    frequency_band_window: RowWindow
    frequency_summary_window: RowWindow
    voltage_tables: tuple[VoltageWindow, ...]
    physical_exchange_tables: tuple[RowWindow, ...]
    schedule_exchange_table: RowWindow
    reservoir_tables: tuple[RowWindow, ...]
    market_point_tables: tuple[tuple[RowWindow, str], ...]
    market_energy_table: RowWindow
    market_range_tables: tuple[tuple[RowWindow, str, tuple[str, ...]], ...]
    curtailment_table: RowWindow
    compliance_table: RowWindow
    annotation_pages: tuple[int, ...]
    physical_exchange_columns: tuple[tuple[str, int], ...] | None = None
    schedule_exchange_columns: tuple[tuple[str, int], ...] | None = None
    schedule_actual_columns: tuple[tuple[str, str, int], ...] | None = None
    market_point_columns: tuple[tuple[int, str], ...] | None = None
    market_point_column_maps: tuple[tuple[RowWindow, str, tuple[tuple[int, str], ...]], ...] = ()
    market_energy_columns: tuple[tuple[int, str], ...] | None = None
    market_range_column_maps: tuple[tuple[RowWindow, tuple[tuple[str, int, int], ...]], ...] = ()
    curtailment_columns: tuple[tuple[str, int, int], ...] | None = None
    curtailment_reason_column: int = 9


def _is_flat_8_layout(layout: SRLDCPromoterLayout) -> bool:
    """Return whether the active SRLDC layout is the flattened 8-page family."""

    return layout == SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_8_TEMPLATE_ID]


def _is_flat_8_2025_layout(layout: SRLDCPromoterLayout) -> bool:
    """Return whether the active SRLDC layout is the later flattened 8-page family."""

    return layout == SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_8_2025_TEMPLATE_ID]


def _is_flat_2023_layout(layout: SRLDCPromoterLayout) -> bool:
    """Return whether the active layout is either sparse 2023 flattened form."""

    return layout in {
        SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_6_2023_TEMPLATE_ID],
        SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_7_2023_TEMPLATE_ID],
        SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_6_2024_WIDE_TEMPLATE_ID],
    }


def _is_flat_2024_wide_layout(layout: SRLDCPromoterLayout) -> bool:
    """Return whether the active layout is the April 2024 wide-operations form."""

    return layout == SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_6_2024_WIDE_TEMPLATE_ID]


def _uses_compact_generation_columns(layout: SRLDCPromoterLayout) -> bool:
    """Return whether a flattened layout omits minimum-generation columns."""

    return layout in {
        SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_6_2023_TEMPLATE_ID],
        SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_6_2024_WIDE_TEMPLATE_ID],
    }


SRLDC_PROMOTER_LAYOUTS = {
    SRLDC_TEMPLATE_ID: SRLDCPromoterLayout(
        generation_table_scopes=GENERATION_TABLE_SCOPES,
        regional_summary_window=RowWindow(1, 1, 3, 3),
        state_energy_window=RowWindow(1, 2, 3, 8),
        state_forecast_window=RowWindow(1, 3, 3, 8),
        state_peak_window=RowWindow(1, 4, 3, 8),
        frequency_band_window=RowWindow(8, 3, 2, 2),
        frequency_summary_window=RowWindow(8, 4, 3, 3),
        voltage_tables=(
            VoltageWindow(RowWindow(8, 5), 765.0),
            VoltageWindow(RowWindow(8, 6), 400.0),
            VoltageWindow(RowWindow(8, 7), 220.0),
            VoltageWindow(RowWindow(9, 1), 220.0),
        ),
        physical_exchange_tables=(RowWindow(7, 4), RowWindow(8, 1)),
        schedule_exchange_table=RowWindow(8, 2),
        reservoir_tables=(RowWindow(9, 2),),
        market_point_tables=((RowWindow(9, 3), "off_peak"), (RowWindow(9, 4), "evening_peak")),
        market_energy_table=RowWindow(9, 5),
        market_range_tables=(
            (RowWindow(9, 6), "daily_range", ("ISGS+GNA", "TGNA", "IEX GDAM", "PXIL GDAM", "HPX GDAM", "IEX DAM", "PXIL DAM")),
            (RowWindow(10, 1), "daily_range", ("HPX DAM", "IEX HPDAM", "PXIL HPDAM", "HPX HPDAM", "IEX RTM", "PXIL RTM", "HPX RTM")),
        ),
        curtailment_table=RowWindow(10, 3),
        compliance_table=RowWindow(10, 4),
        annotation_pages=(10,),
    ),
    SRLDC_COMPACT_TEMPLATE_ID: SRLDCPromoterLayout(
        generation_table_scopes=COMPACT_GENERATION_TABLE_SCOPES,
        regional_summary_window=RowWindow(1, 1, 3, 3),
        state_energy_window=RowWindow(1, 2, 3, 8),
        state_forecast_window=RowWindow(1, 3, 3, 8),
        state_peak_window=RowWindow(1, 4, 3, 8),
        frequency_band_window=RowWindow(7, 2, 2, 2),
        frequency_summary_window=RowWindow(7, 3, 3, 3),
        voltage_tables=(
            VoltageWindow(RowWindow(7, 4), 765.0),
            VoltageWindow(RowWindow(7, 5), 400.0),
            VoltageWindow(RowWindow(7, 6), 220.0),
        ),
        physical_exchange_tables=(RowWindow(6, 4),),
        schedule_exchange_table=RowWindow(7, 1),
        reservoir_tables=(RowWindow(7, 7), RowWindow(8, 1)),
        market_point_tables=((RowWindow(8, 2), "off_peak"), (RowWindow(8, 3), "evening_peak")),
        market_energy_table=RowWindow(8, 4),
        market_range_tables=(
            (RowWindow(8, 5), "daily_range", ("ISGS+GNA", "TGNA", "IEX GDAM", "PXIL GDAM", "HPX GDAM", "IEX DAM", "PXIL DAM")),
            (RowWindow(8, 6), "daily_range", ("HPX DAM", "IEX HPDAM", "PXIL HPDAM", "HPX HPDAM", "IEX RTM", "PXIL RTM", "HPX RTM")),
        ),
        curtailment_table=RowWindow(9, 2),
        compliance_table=RowWindow(9, 3),
        annotation_pages=(9,),
    ),
    SRLDC_FLAT_8_TEMPLATE_ID: SRLDCPromoterLayout(
        generation_table_scopes=FLAT_8_GENERATION_TABLE_SCOPES,
        regional_summary_window=RowWindow(1, 1, 4, 4),
        state_energy_window=RowWindow(1, 1, 8, 13),
        state_forecast_window=RowWindow(1, 1, 18, 23),
        state_peak_window=RowWindow(1, 1, 28, 33),
        frequency_band_window=RowWindow(6, 1, 8, 8),
        frequency_summary_window=RowWindow(6, 1, 12, 12),
        voltage_tables=(
            VoltageWindow(RowWindow(6, 1, 17, 29), 400.0),
            VoltageWindow(RowWindow(6, 1, 34, 44), 220.0),
            VoltageWindow(RowWindow(6, 1, 45, 47), 765.0),
        ),
        physical_exchange_tables=(RowWindow(5, 1, 56, 74),),
        schedule_exchange_table=RowWindow(6, 1, 3, 5),
        reservoir_tables=(RowWindow(6, 1, 51, 58),),
        market_point_tables=((RowWindow(6, 1, 63, 68), "off_peak"), (RowWindow(7, 1, 4, 9), "evening_peak")),
        market_energy_table=RowWindow(7, 1, 14, 19),
        market_range_tables=((RowWindow(7, 1, 24, 29), "daily_range", ("ISGS+GNA", "TGNA", "IEX GDAM", "PXIL GDAM", "HPX GDAM", "IEX DAM", "PXIL DAM")),),
        curtailment_table=RowWindow(7, 1, 51, 56),
        compliance_table=RowWindow(7, 1, 60, 65),
        annotation_pages=(7,),
    ),
    SRLDC_FLAT_8_2025_TEMPLATE_ID: SRLDCPromoterLayout(
        generation_table_scopes=FLAT_8_GENERATION_TABLE_SCOPES,
        regional_summary_window=RowWindow(1, 1, 4, 4),
        state_energy_window=RowWindow(1, 1, 8, 13),
        state_forecast_window=RowWindow(1, 1, 18, 23),
        state_peak_window=RowWindow(1, 1, 28, 33),
        frequency_band_window=RowWindow(6, 1, 11, 11),
        frequency_summary_window=RowWindow(6, 1, 15, 15),
        voltage_tables=(
            VoltageWindow(RowWindow(6, 1, 19, 30), 400.0),
            VoltageWindow(RowWindow(6, 1, 34, 43), 220.0),
            VoltageWindow(RowWindow(6, 1, 47, 50), 765.0),
        ),
        physical_exchange_tables=(RowWindow(6, 1, 1, 3),),
        schedule_exchange_table=RowWindow(6, 1, 6, 8),
        reservoir_tables=(RowWindow(6, 1, 54, 62),),
        market_point_tables=((RowWindow(7, 1, 4, 10), "off_peak"), (RowWindow(7, 1, 14, 20), "evening_peak")),
        market_energy_table=RowWindow(7, 1, 24, 30),
        market_range_tables=(
            (RowWindow(7, 1, 34, 39), "daily_range", ("ISGS+GNA", "TGNA", "IEX GDAM", "PXIL GDAM", "HPX GDAM", "IEX DAM", "PXIL DAM")),
            (RowWindow(7, 1, 43, 48), "daily_range", ("HPX DAM", "IEX HPDAM", "PXIL HPDAM", "HPX HPDAM", "IEX RTM", "PXIL RTM", "HPX RTM")),
        ),
        curtailment_table=RowWindow(8, 1, 5, 10),
        compliance_table=RowWindow(8, 1, 14, 19),
        annotation_pages=(7, 8),
    ),
    SRLDC_FLAT_6_2023_TEMPLATE_ID: SRLDCPromoterLayout(
        generation_table_scopes=FLAT_6_2023_GENERATION_TABLE_SCOPES,
        regional_summary_window=RowWindow(1, 1, 4, 4),
        state_energy_window=RowWindow(1, 1, 8, 13),
        state_forecast_window=RowWindow(1, 1, 18, 23),
        state_peak_window=RowWindow(1, 1, 28, 33),
        frequency_band_window=RowWindow(5, 1, 15, 15),
        frequency_summary_window=RowWindow(5, 1, 19, 19),
        voltage_tables=(
            VoltageWindow(RowWindow(5, 1, 23, 34), 400.0),
            VoltageWindow(RowWindow(5, 1, 38, 47), 220.0),
            VoltageWindow(RowWindow(5, 1, 51, 54), 765.0),
        ),
        physical_exchange_tables=(RowWindow(4, 1, 64, 74), RowWindow(5, 1, 1, 7)),
        schedule_exchange_table=RowWindow(5, 1, 10, 12),
        reservoir_tables=(RowWindow(5, 1, 58, 65),),
        market_point_tables=(),
        market_energy_table=RowWindow(6, 1, 14, 20),
        market_range_tables=(),
        curtailment_table=RowWindow(6, 1, 44, 43),
        compliance_table=RowWindow(6, 1, 44, 43),
        annotation_pages=(6,),
        physical_exchange_columns=(
            ("EveningPeakMW", 10), ("OffPeakMW", 14),
            ("MaximumImportMW", 18), ("MaximumExportMW", 22),
            ("ImportEnergyMU", 27), ("ExportEnergyMU", 31), ("NetEnergyMU", 35),
        ),
        schedule_exchange_columns=(
            ("ISGS+URS+GNA", 4), ("TGNA", 7), ("GDAM", 12),
            ("DAM", 16), ("RTM", 21), ("TOTAL_SCHEDULE", 26),
        ),
        schedule_actual_columns=(("TOTAL_ACTUAL", "ActualMU", 30), ("NET_UI", "DeviationMU", 34)),
        market_point_column_maps=(
            (RowWindow(6, 1, 4, 10), "off_peak", (
                (3, "TGNA"), (5, "IEX GDAM"), (7, "IEX DAM"),
                (10, "IEX RTM"), (12, "PXIL GDAM"), (15, "PXIL DAM"), (17, "PXIL RTM"),
            )),
            (RowWindow(6, 1, 4, 10), "evening_peak", (
                (20, "TGNA"), (22, "IEX GDAM"), (25, "IEX DAM"),
                (27, "IEX RTM"), (30, "PXIL GDAM"), (33, "PXIL DAM"), (36, "PXIL RTM"),
            )),
        ),
        market_energy_columns=(
            (7, "ISGS+GNA"), (12, "TGNA"), (17, "GDAM"),
            (22, "DAM"), (27, "RTM"), (33, "TOTAL"),
        ),
        market_range_column_maps=(
            (RowWindow(6, 1, 24, 29), (("ISGS+GNA", 4, 8), ("TGNA", 13, 19), ("IEX GDAM", 24, 28), ("PXIL GDAM", 32, 35))),
            (RowWindow(6, 1, 33, 38), (("IEX DAM", 6, 11), ("PXIL DAM", 14, 18), ("IEX RTM", 21, 26), ("PXIL RTM", 29, 34))),
        ),
    ),
    SRLDC_FLAT_7_2023_TEMPLATE_ID: SRLDCPromoterLayout(
        generation_table_scopes=FLAT_7_2023_GENERATION_TABLE_SCOPES,
        regional_summary_window=RowWindow(1, 1, 4, 4),
        state_energy_window=RowWindow(1, 1, 8, 13),
        state_forecast_window=RowWindow(1, 1, 18, 23),
        state_peak_window=RowWindow(1, 1, 28, 33),
        frequency_band_window=RowWindow(5, 1, 39, 39),
        frequency_summary_window=RowWindow(5, 1, 43, 43),
        voltage_tables=(
            VoltageWindow(RowWindow(5, 1, 47, 58), 400.0),
            VoltageWindow(RowWindow(5, 1, 62, 71), 220.0),
            VoltageWindow(RowWindow(6, 1, 1, 4), 765.0),
        ),
        physical_exchange_tables=(RowWindow(5, 1, 15, 31),),
        schedule_exchange_table=RowWindow(5, 1, 34, 36),
        reservoir_tables=(RowWindow(6, 1, 8, 15),),
        market_point_tables=(),
        market_energy_table=RowWindow(6, 1, 30, 36),
        market_range_tables=(),
        curtailment_table=RowWindow(7, 1, 5, 10),
        compliance_table=RowWindow(7, 1, 12, 11),
        annotation_pages=(7,),
        physical_exchange_columns=(
            ("EveningPeakMW", 10), ("OffPeakMW", 14),
            ("MaximumImportMW", 18), ("MaximumExportMW", 22),
            ("ImportEnergyMU", 27), ("ExportEnergyMU", 31), ("NetEnergyMU", 35),
        ),
        schedule_exchange_columns=(
            ("ISGS+URS+GNA", 4), ("TGNA", 7), ("GDAM", 12),
            ("DAM", 16), ("RTM", 21), ("TOTAL_SCHEDULE", 26),
        ),
        schedule_actual_columns=(("TOTAL_ACTUAL", "ActualMU", 30), ("NET_UI", "DeviationMU", 34)),
        market_point_column_maps=(
            (RowWindow(6, 1, 20, 26), "off_peak", (
                (3, "TGNA"), (5, "IEX GDAM"), (7, "IEX DAM"),
                (10, "IEX RTM"), (12, "PXIL GDAM"), (15, "PXIL DAM"), (17, "PXIL RTM"),
            )),
            (RowWindow(6, 1, 20, 26), "evening_peak", (
                (20, "TGNA"), (22, "IEX GDAM"), (25, "IEX DAM"),
                (27, "IEX RTM"), (30, "PXIL GDAM"), (33, "PXIL DAM"), (36, "PXIL RTM"),
            )),
        ),
        market_energy_columns=(
            (7, "ISGS+GNA"), (12, "TGNA"), (17, "GDAM"),
            (22, "DAM"), (27, "RTM"), (33, "TOTAL"),
        ),
        market_range_column_maps=(
            (RowWindow(6, 1, 50, 55), (("ISGS+GNA", 4, 8), ("TGNA", 13, 19), ("IEX GDAM", 24, 28), ("PXIL GDAM", 33, 36))),
            (RowWindow(6, 1, 59, 64), (("IEX DAM", 6, 11), ("PXIL DAM", 14, 19), ("IEX RTM", 21, 26), ("PXIL RTM", 29, 34))),
        ),
    ),
    SRLDC_FLAT_6_2024_WIDE_TEMPLATE_ID: SRLDCPromoterLayout(
        generation_table_scopes=FLAT_6_2024_WIDE_GENERATION_TABLE_SCOPES,
        regional_summary_window=RowWindow(1, 1, 4, 4),
        state_energy_window=RowWindow(1, 1, 8, 13),
        state_forecast_window=RowWindow(1, 1, 18, 23),
        state_peak_window=RowWindow(1, 1, 28, 33),
        frequency_band_window=RowWindow(5, 1, 19, 19),
        frequency_summary_window=RowWindow(5, 1, 23, 23),
        voltage_tables=(
            VoltageWindow(RowWindow(5, 1, 30, 39), 220.0),
            VoltageWindow(RowWindow(5, 1, 43, 46), 765.0),
        ),
        physical_exchange_tables=(RowWindow(4, 1, 68, 73), RowWindow(5, 1, 1, 11)),
        schedule_exchange_table=RowWindow(5, 1, 14, 16),
        reservoir_tables=(RowWindow(5, 1, 50, 58),),
        market_point_tables=(),
        market_energy_table=RowWindow(6, 1, 14, 20),
        market_range_tables=(),
        curtailment_table=RowWindow(6, 1, 47, 52),
        compliance_table=RowWindow(6, 1, 53, 52),
        annotation_pages=(1, 6),
        physical_exchange_columns=(
            ("EveningPeakMW", 4), ("OffPeakMW", 6),
            ("MaximumImportMW", 8), ("MaximumExportMW", 10),
            ("ImportEnergyMU", 12), ("ExportEnergyMU", 14), ("NetEnergyMU", 17),
        ),
        schedule_exchange_columns=(
            ("ISGS+URS+GNA", 4), ("TGNA", 10), ("GDAM", 14),
            ("DAM", 18), ("HPDAM", 23), ("RTM", 29),
            ("TOTAL_SCHEDULE", 34),
        ),
        schedule_actual_columns=(
            ("TOTAL_ACTUAL", "ActualMU", 40), ("NET_UI", "DeviationMU", 44),
        ),
        market_point_column_maps=(
            (RowWindow(5, 1, 62, 68), "off_peak", (
                (3, "TGNA"), (7, "IEX GDAM"), (9, "IEX DAM"),
                (12, "IEX HPDAM"), (16, "IEX RTM"), (19, "PXIL GDAM"),
                (21, "PXIL DAM"), (26, "PXIL HPDAM"), (30, "PXIL RTM"),
                (36, "HPX GDAM"), (38, "HPX DAM"), (42, "HPX HPDAM"),
                (47, "HPX RTM"),
            )),
            (RowWindow(6, 1, 4, 10), "evening_peak", (
                (3, "TGNA"), (5, "IEX GDAM"), (6, "IEX DAM"),
                (10, "IEX HPDAM"), (13, "IEX RTM"), (15, "PXIL GDAM"),
                (18, "PXIL DAM"), (21, "PXIL HPDAM"), (25, "PXIL RTM"),
                (29, "HPX GDAM"), (32, "HPX DAM"), (36, "HPX HPDAM"),
                (40, "HPX RTM"),
            )),
        ),
        market_energy_columns=(
            (6, "ISGS+GNA"), (11, "TGNA"), (16, "GDAM"),
            (20, "DAM"), (26, "HPDAM"), (31, "RTM"), (38, "TOTAL"),
        ),
        market_range_column_maps=(
            (RowWindow(6, 1, 24, 29), (
                ("ISGS+GNA", 3, 5), ("TGNA", 6, 9),
                ("IEX GDAM", 12, 14), ("PXIL GDAM", 17, 19),
                ("HPX GDAM", 23, 27), ("IEX DAM", 30, 34),
                ("PXIL DAM", 37, 41),
            )),
            (RowWindow(6, 1, 33, 38), (
                ("HPX DAM", 3, 5), ("IEX HPDAM", 6, 9),
                ("PXIL HPDAM", 12, 14), ("HPX HPDAM", 17, 19),
                ("IEX RTM", 23, 27), ("PXIL RTM", 30, 34),
                ("HPX RTM", 37, 41),
            )),
        ),
        curtailment_columns=(
            ("load_curtailment", 8, 4),
            ("wind_curtailment", 18, 22),
            ("solar_curtailment", 28, 33),
        ),
        curtailment_reason_column=39,
    ),
}


def promote_report_to_curated(conn: sqlite3.Connection, report_document_id: int) -> None:
    """Promote one approved source-specific report with coverage evidence."""

    report = _fetch_report(conn, report_document_id)
    if not report:
        return
    if report["rldc"] == "nrldc":
        from psp_pipeline.storage.sqlite_nrldc_promoter import (
            promote_nrldc_report_to_curated,
        )

        promote_nrldc_report_to_curated(conn, report_document_id)
        return
    if report["rldc"] == "wrldc":
        from psp_pipeline.storage.sqlite_wrldc_promoter import (
            promote_wrldc_report_to_curated,
        )

        promote_wrldc_report_to_curated(conn, report_document_id)
        return
    if report["rldc"] == "erldc":
        from psp_pipeline.storage.sqlite_erldc_promoter import promote_erldc_report_to_curated
        promote_erldc_report_to_curated(conn, report_document_id)
        return
    if report["rldc"] == "nerldc":
        from psp_pipeline.storage.sqlite_nerldc_promoter import promote_nerldc_report_to_curated

        promote_nerldc_report_to_curated(conn, report_document_id)
        return
    if report["rldc"] != "srldc":
        return
    layout = _layout_for_report(report)
    if report["semantic_pass_required"] or layout is None:
        _record_unrecognized_report(conn, report_document_id, report)
        return

    date_id = _get_or_create_date_id(conn, report["report_date"])
    if date_id is None:
        return
    _upsert_dim_report(conn, date_id, report)
    conn.execute("DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?", (report_document_id,))

    mapped_cells: set[int] = set()
    populated_fields: set[str] = set()
    validation_failures = 0
    _promote_regional_summary(
        conn, report_document_id, date_id, mapped_cells, populated_fields, layout
    )
    validation_failures += _promote_state_positions(
        conn, report_document_id, date_id, mapped_cells, populated_fields, layout
    )
    validation_failures += _promote_generation(
        conn, report_document_id, date_id, mapped_cells, populated_fields, layout
    )
    validation_failures += _promote_frequency(
        conn, report_document_id, date_id, mapped_cells, populated_fields, layout
    )
    validation_failures += _validate_state_energy_balance(
        conn, report_document_id, date_id
    )
    _promote_voltage(
        conn, report_document_id, date_id, mapped_cells, populated_fields, layout
    )
    _promote_reservoirs(
        conn, report_document_id, date_id, mapped_cells, populated_fields, layout
    )
    _promote_interregional_exchange(
        conn, report_document_id, date_id, mapped_cells, populated_fields, layout
    )
    _promote_market_transactions(
        conn, report_document_id, date_id, mapped_cells, populated_fields, layout
    )
    _promote_operational_events(
        conn, report_document_id, date_id, mapped_cells, populated_fields, layout
    )
    _promote_report_annotations(conn, report_document_id, layout)
    _record_coverage(
        conn,
        report_document_id,
        str(report["template_id"]),
        mapped_cells,
        populated_fields,
        validation_failures,
    )


def repromote_srldc_reports(conn: sqlite3.Connection) -> dict[str, int]:
    """Recompute curated SRLDC facts and coverage from persisted raw cells.

    Reports that were intentionally gated for semantic review remain untouched;
    their stored raw cells and pending schema proposals are preserved.  The
    caller owns the transaction so a backfill can be committed atomically.
    """

    reports = conn.execute(
        """
        SELECT id, semantic_pass_required, template_id
        FROM psp_report_document
        WHERE rldc = 'srldc'
        ORDER BY report_date, id
        """
    ).fetchall()
    promoted = 0
    skipped = 0
    for report_id, semantic_pass_required, template_id in reports:
        if semantic_pass_required or str(template_id or "") not in SRLDC_TEMPLATE_IDS:
            skipped += 1
            continue
        promote_report_to_curated(conn, int(report_id))
        promoted += 1
    return {"reports_total": len(reports), "promoted": promoted, "skipped": skipped}


def _layout_for_report(report: dict[str, object]) -> SRLDCPromoterLayout | None:
    """Return the approved SRLDC promoter layout for a persisted template."""

    template_id = str(report.get("template_id") or "")
    if template_id not in SRLDC_TEMPLATE_IDS:
        return None
    return SRLDC_PROMOTER_LAYOUTS.get(template_id)


def _fetch_report(conn: sqlite3.Connection, report_document_id: int) -> dict[str, object] | None:
    """Fetch report metadata required for promotion."""

    row = conn.execute(
        """
        SELECT
            rldc,
            local_path,
            report_date,
            template_id,
            semantic_pass_required,
            structure_deviation_reason
        FROM psp_report_document WHERE id = ?
        """,
        (report_document_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "rldc": row[0],
        "local_path": row[1],
        "report_date": row[2],
        "template_id": row[3],
        "semantic_pass_required": bool(row[4]),
        "structure_deviation_reason": row[5],
    }


def _get_or_create_date_id(conn: sqlite3.Connection, report_date: str | None) -> int | None:
    """Return the date dimension key, creating it when necessary."""

    if not report_date:
        return None
    date_obj = datetime.fromisoformat(report_date).date()
    conn.execute(
        """
        INSERT OR IGNORE INTO DimDates(ActualDate, DayOfWeek, DayOfMonth, Month, Quarter, Year)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            date_obj.isoformat(), date_obj.strftime("%A"), date_obj.day,
            date_obj.month, (date_obj.month - 1) // 3 + 1, date_obj.year,
        ),
    )
    row = conn.execute(
        "SELECT DateID FROM DimDates WHERE ActualDate = ?", (date_obj.isoformat(),)
    ).fetchone()
    return int(row[0]) if row else None


def _upsert_dim_report(conn: sqlite3.Connection, date_id: int, report: dict[str, object]) -> None:
    """Upsert report metadata into the shared report dimension."""

    report_path = str(report["local_path"])
    report_name = report_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    conn.execute(
        """
        INSERT OR REPLACE INTO DimReports(DateID, ReportName, ReportPath, Source)
        VALUES (?, ?, ?, 'SRLDC')
        """,
        (date_id, report_name, report_path),
    )


def _promote_regional_summary(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
    populated_fields: set[str],
    layout: SRLDCPromoterLayout,
) -> None:
    """Promote regional demand, energy, and exchange totals."""

    region_id = _lookup_id(
        conn, "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (SR_REGION_NAME,)
    )
    row = _table_row_from_window(conn, report_id, layout.regional_summary_window)
    if _is_flat_8_layout(layout) or _is_flat_2023_layout(layout):
        total_load = _table_row_from_window(conn, report_id, layout.state_forecast_window, offset=6)
        peak = _table_row_from_window(conn, report_id, layout.state_peak_window, offset=6)
    else:
        total_load = _table_row(conn, report_id, 1, 2, 9)
        peak = _table_row(conn, report_id, 1, 4, 9)
    if region_id is None or not row:
        return

    values: dict[str, object] = {}
    sources: dict[str, int] = {}
    for (_, col_no), mapping in REGIONAL_MAPPINGS.items():
        raw = row.get(col_no)
        value = _to_float(raw[1]) if raw else None
        values[mapping.destination_column] = value
        if raw and value is not None:
            sources[mapping.destination_column] = raw[0]
            populated_fields.add(mapping.canonical_name)

    supplemental = {
        "MaximumDemandMetMW": (peak, 2, _to_float),
        "MaximumDemandTime": (peak, 3, _normalize_time),
        "ScheduleDrawalMU": (total_load, 8, _to_float),
        "ActualDrawalMU": (total_load, 9, _to_float),
        "OverUnderDrawalMU": (total_load, 10, _to_float),
    }
    for column, (source_row, col_no, converter) in supplemental.items():
        raw = source_row.get(col_no) if source_row else None
        values[column] = converter(raw[1]) if raw else None
        if raw and values[column] is not None:
            sources[column] = raw[0]

    columns = list(values)
    conn.execute(
        f"""
        INSERT OR REPLACE INTO FactSRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, {', '.join(columns)}
        ) VALUES (?, ?, ?, {', '.join('?' for _ in columns)})
        """,
        (report_id, date_id, region_id, *(values[column] for column in columns)),
    )
    destination_key = f"report={report_id};date={date_id};region={region_id}"
    for column, raw_cell_id in sources.items():
        _insert_lineage(
            conn, report_id, "FactSRLDCRegionalDaily", destination_key,
            column, raw_cell_id, mapped_cells
        )


def _promote_state_positions(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
    populated_fields: set[str],
    layout: SRLDCPromoterLayout,
) -> int:
    """Promote state position and forecast rows, returning validation failures."""

    validation_failures = 0
    energy_rows = _table_rows_for_window(conn, report_id, layout.state_energy_window)
    forecast_rows = _table_rows_for_window(conn, report_id, layout.state_forecast_window)
    peak_rows = _table_rows_for_window(conn, report_id, layout.state_peak_window)
    row_count = min(len(energy_rows), len(forecast_rows), len(peak_rows))
    for index in range(row_count):
        energy = energy_rows[index]
        forecast = forecast_rows[index]
        peak = peak_rows[index]
        state_raw = energy.get(1)
        state_name = state_raw[1].strip() if state_raw else ""
        state_id = _state_id(conn, state_name)
        if state_id is None:
            continue
        if state_raw:
            mapped_cells.add(state_raw[0])

        values: dict[str, object] = {}
        sources: dict[str, int] = {}
        for col_no, (canonical, column, unit) in _state_energy_mappings(layout).items():
            _assign(values, sources, populated_fields, energy, col_no, canonical, column, unit)
        for col_no, (canonical, column, unit) in _state_forecast_mappings(layout).items():
            _assign(values, sources, populated_fields, forecast, col_no, canonical, column, unit)
        for col_no, (canonical, column, unit) in _state_peak_mappings(layout).items():
            _assign(values, sources, populated_fields, peak, col_no, canonical, column, unit)

        if _is_flat_8_layout(layout):
            forecast_value = _cell_float(forecast, 31)
            deviation = _cell_float(forecast, 37)
            actual = (
                forecast_value - deviation
                if forecast_value is not None and deviation is not None
                else None
            )
            forecast_sources = {
                "ForecastDemandMU": forecast.get(31),
                "ForecastDeviationMU": forecast.get(37),
            }
        elif _is_flat_6_2023_layout(layout):
            forecast_value = _cell_float(forecast, 27)
            deviation = _cell_float(forecast, 33)
            actual = (
                forecast_value - deviation
                if forecast_value is not None and deviation is not None
                else None
            )
            forecast_sources = {
                "ForecastDemandMU": forecast.get(27),
                "ForecastDeviationMU": forecast.get(33),
            }
        elif _is_flat_7_2023_layout(layout):
            forecast_value = _cell_float(forecast, 31)
            deviation = _cell_float(forecast, 37)
            actual = (
                forecast_value - deviation
                if forecast_value is not None and deviation is not None
                else None
            )
            forecast_sources = {
                "ForecastDemandMU": forecast.get(31),
                "ForecastDeviationMU": forecast.get(37),
            }
        else:
            forecast_value = _cell_float(forecast, 9)
            deviation = _cell_float(forecast, 10)
            actual = _cell_float(energy, 12)
            forecast_sources = {
                "ForecastDemandMU": forecast.get(9),
                "ActualDemandMU": energy.get(12),
                "ForecastDeviationMU": forecast.get(10),
            }
        deviation_pct = None
        if forecast_value not in (None, 0) and actual is not None:
            deviation_pct = round(100.0 * (actual - forecast_value) / forecast_value, 4)
            if deviation is not None and abs(abs(actual - forecast_value) - abs(deviation)) > 0.05:
                validation_failures += 1
        values.update(
            {
                "ForecastType": "LGBR",
                "ForecastDemandMU": forecast_value,
                "ActualDemandMU": actual,
                "ForecastDeviationMU": deviation,
                "ForecastDeviationPct": deviation_pct,
            }
        )
        for column, source in forecast_sources.items():
            if source and _to_float(source[1]) is not None:
                sources[column] = source[0]
        if forecast_value is not None:
            populated_fields.add("state_forecast_demand_mu")
        if deviation is not None:
            populated_fields.add("state_forecast_deviation_mu")

        columns = list(values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactSRLDCStateDaily(
                ReportDocumentID, DateID, StateID, {', '.join(columns)}
            ) VALUES (?, ?, ?, {', '.join('?' for _ in columns)})
            """,
            (report_id, date_id, state_id, *(values[column] for column in columns)),
        )
        destination_key = f"report={report_id};date={date_id};state={state_id}"
        for column, raw_cell_id in sources.items():
            _insert_lineage(
                conn, report_id, "FactSRLDCStateDaily", destination_key,
                column, raw_cell_id, mapped_cells
            )
    return validation_failures


def _is_flat_6_2023_layout(layout: SRLDCPromoterLayout) -> bool:
    """Return whether the active layout is the sparse 2023 flat-six family."""

    return layout == SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_6_2023_TEMPLATE_ID]


def _is_flat_7_2023_layout(layout: SRLDCPromoterLayout) -> bool:
    """Return whether the active layout is the sparse 2023 flat-seven family."""

    return layout == SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_7_2023_TEMPLATE_ID]


def _state_energy_mappings(
    layout: SRLDCPromoterLayout,
) -> dict[int, tuple[str, str, str]]:
    """Return approved state-energy columns for the active report layout."""

    if _is_flat_6_2023_layout(layout):
        return FLAT_6_2023_STATE_ENERGY_MAPPINGS
    if _is_flat_7_2023_layout(layout):
        return FLAT_7_2023_STATE_ENERGY_MAPPINGS
    return STATE_ENERGY_MAPPINGS


def _state_forecast_mappings(
    layout: SRLDCPromoterLayout,
) -> dict[int, tuple[str, str, str]]:
    """Return approved state demand/forecast columns for the active layout."""

    if _is_flat_6_2023_layout(layout):
        return FLAT_6_2023_STATE_FORECAST_MAPPINGS
    if _is_flat_7_2023_layout(layout):
        return FLAT_7_2023_STATE_FORECAST_MAPPINGS
    return STATE_FORECAST_MAPPINGS


def _state_peak_mappings(
    layout: SRLDCPromoterLayout,
) -> dict[int, tuple[str, str, str]]:
    """Return approved state maximum-demand columns for the active layout."""

    if _is_flat_6_2023_layout(layout):
        return FLAT_6_2023_STATE_PEAK_MAPPINGS
    if _is_flat_7_2023_layout(layout):
        return FLAT_7_2023_STATE_PEAK_MAPPINGS
    return STATE_PEAK_MAPPINGS


def _promote_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
    populated_fields: set[str],
    layout: SRLDCPromoterLayout,
) -> int:
    """Promote all station and aggregate generation rows for the template."""

    conn.execute(
        "DELETE FROM FactSRLDCGenerationDaily WHERE ReportDocumentID = ?",
        (report_id,),
    )
    region_id = _lookup_id(
        conn, "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (SR_REGION_NAME,)
    )
    if region_id is None:
        return 0
    validation_failures = 0
    for scope in layout.generation_table_scopes:
        state_id = _state_id(conn, scope.state_name) if scope.state_name else None
        current_source_name = _initial_generation_source(scope.section_name)
        if scope.state_name and state_id is None:
            record_resolution_issue(
                conn, report_id, "srldc", "state", scope.state_name,
                "state alias is not approved",
            )
            continue
        for row in _table_rows_for_window(conn, report_id, scope.window):
            entity_cell = row.get(1)
            source_columns = _generation_source_columns(
                layout, scope.window.page_no, row
            )
            capacity_cell = row.get(source_columns["InstalledCapacityMW"])
            entity_name = entity_cell[1].strip() if entity_cell else ""
            capacity = _to_float(capacity_cell[1]) if capacity_cell else None
            source_name, current_source_name = _classify_generation_source(
                entity_name, scope.section_name, current_source_name
            )
            if not entity_name or capacity is None:
                continue
            is_total = entity_name.lower().startswith("total ")
            source_id = _lookup_generation_source_id(conn, source_name)
            try:
                identity = resolve_generation_identity(
                    conn, "srldc", entity_name, state_id, region_id,
                    source_id, capacity, is_total,
                )
            except DimensionResolutionError as exc:
                record_resolution_issue(
                    conn, report_id, "srldc", "generation_entity",
                    entity_name, str(exc),
                )
                continue
            entity_id = _get_or_create_grid_entity(
                conn,
                entity_name,
                "generation_aggregate" if is_total else "generating_entity",
                state_id,
                region_id,
                source_id,
                capacity,
                is_total,
                identity,
            )
            values, source_columns = _generation_values_for_layout(
                row, capacity, layout, scope.window.page_no
            )
            columns = list(values)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO FactSRLDCGenerationDaily(
                    ReportDocumentID, DateID, EntityID, StateID,
                    GenerationSourceID, StationID, GeneratingUnitID,
                    AggregateID, IsTotalRow, GenerationGrain, SectionName,
                    {', '.join(columns)}
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {', '.join('?' for _ in columns)})
                """,
                (
                    report_id, date_id, entity_id, state_id,
                    source_id, identity.station_id,
                    identity.generating_unit_id, identity.aggregate_id,
                    int(is_total), identity.entity_type, scope.section_name,
                    *(values[column] for column in columns),
                ),
            )
            destination_key = (
                f"report={report_id};date={date_id};entity={entity_id};"
                f"section={scope.section_name}"
            )
            if entity_cell:
                mapped_cells.add(entity_cell[0])
            for column, col_no in source_columns.items():
                raw = row.get(col_no)
                if raw and values[column] is not None:
                    _insert_lineage(
                        conn, report_id, "FactSRLDCGenerationDaily",
                        destination_key, column, raw[0], mapped_cells
                    )
            populated_fields.add("generation_daily_row")
            net_energy = values["NetEnergyMU"]
            average_mw = values["AverageMW"]
            if net_energy is not None and average_mw is not None:
                expected = float(net_energy) * 1000.0 / 24.0
                tolerance = max(5.0, abs(expected) * 0.01)
                if abs(float(average_mw) - expected) > tolerance:
                    validation_failures += 1
    return validation_failures


def _generation_values_for_layout(
    row: dict[int, tuple[int, str]],
    capacity: float,
    layout: SRLDCPromoterLayout,
    page_no: int,
) -> tuple[dict[str, float | str | None], dict[str, int]]:
    """Map generation columns for the applicable SRLDC table geometry."""

    source_columns = _generation_source_columns(layout, page_no, row)
    if _uses_compact_generation_row(layout, page_no, row):
        return {
            "InstalledCapacityMW": capacity,
            "EveningPeakMW": _cell_float(row, source_columns["EveningPeakMW"]),
            "OffPeakMW": _cell_float(row, source_columns["OffPeakMW"]),
            "DayPeakMW": _cell_float(row, source_columns["DayPeakMW"]),
            "DayPeakTime": _cell_time(row, source_columns["DayPeakTime"]),
            "MinimumGenerationMW": None,
            "MinimumGenerationTime": None,
            "GrossEnergyMU": _cell_float(row, source_columns["GrossEnergyMU"]),
            "NetEnergyMU": _cell_float(row, source_columns["NetEnergyMU"]),
            "AverageMW": _cell_float(row, source_columns["AverageMW"]),
        }, source_columns

    return {
        "InstalledCapacityMW": capacity,
        "EveningPeakMW": _cell_float(row, source_columns["EveningPeakMW"]),
        "OffPeakMW": _cell_float(row, source_columns["OffPeakMW"]),
        "DayPeakMW": _cell_float(row, source_columns["DayPeakMW"]),
        "DayPeakTime": _cell_time(row, source_columns["DayPeakTime"]),
        "MinimumGenerationMW": _cell_float(row, source_columns["MinimumGenerationMW"]),
        "MinimumGenerationTime": _cell_time(row, source_columns["MinimumGenerationTime"]),
        "GrossEnergyMU": _cell_float(row, source_columns["GrossEnergyMU"]),
        "NetEnergyMU": _cell_float(row, source_columns["NetEnergyMU"]),
        "AverageMW": _cell_float(row, source_columns["AverageMW"]),
    }, source_columns


def _generation_source_columns(
    layout: SRLDCPromoterLayout,
    page_no: int,
    row: dict[int, tuple[int, str]],
) -> dict[str, int]:
    """Return source columns for one SRLDC generation-table page."""

    if _uses_wide_page_four_generation_columns(layout, page_no, row):
        return {
            "InstalledCapacityMW": 3,
            "EveningPeakMW": 5,
            "OffPeakMW": 7,
            "DayPeakMW": 9,
            "DayPeakTime": 11,
            "GrossEnergyMU": 13,
            "NetEnergyMU": 15,
            "AverageMW": 16,
        }
    if _uses_sparse_page_one_generation_columns(layout, page_no, row):
        return {
            "InstalledCapacityMW": 10,
            "EveningPeakMW": 13,
            "OffPeakMW": 18,
            "DayPeakMW": 22,
            "DayPeakTime": 26,
            "GrossEnergyMU": 29,
            "NetEnergyMU": 32,
            "AverageMW": 34,
        }
    if _uses_compact_generation_row(layout, page_no, row):
        return {
            "InstalledCapacityMW": 2,
            "EveningPeakMW": 3,
            "OffPeakMW": 4,
            "DayPeakMW": 5,
            "DayPeakTime": 6,
            "GrossEnergyMU": 7,
            "NetEnergyMU": 8,
            "AverageMW": 9,
        }
    return {
        "InstalledCapacityMW": 2,
        "EveningPeakMW": 3,
        "OffPeakMW": 4,
        "DayPeakMW": 5,
        "DayPeakTime": 6,
        "MinimumGenerationMW": 7,
        "MinimumGenerationTime": 8,
        "GrossEnergyMU": 9,
        "NetEnergyMU": 10,
        "AverageMW": 11,
    }


def _uses_wide_page_four_generation_columns(
    layout: SRLDCPromoterLayout,
    page_no: int,
    row: dict[int, tuple[int, str]],
) -> bool:
    """Return whether one Page 4 generation row uses interstitial columns."""

    if page_no != 4:
        return False
    if layout == SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_6_2023_TEMPLATE_ID]:
        return True
    return (
        layout == SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_7_2023_TEMPLATE_ID]
        and _cell_float(row, 2) is None
        and _cell_float(row, 3) is not None
    )


def _uses_sparse_page_one_generation_columns(
    layout: SRLDCPromoterLayout,
    page_no: int,
    row: dict[int, tuple[int, str]],
) -> bool:
    """Return whether a flat-06/07 Page 1 row uses sparse station columns."""

    return (
        page_no == 1
        and layout in {
            SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_6_2023_TEMPLATE_ID],
            SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_7_2023_TEMPLATE_ID],
        }
        and _cell_float(row, 10) is not None
    )


def _uses_compact_generation_row(
    layout: SRLDCPromoterLayout,
    page_no: int,
    row: dict[int, tuple[int, str]],
) -> bool:
    """Identify a nine-column generation row without minimum-generation fields."""

    if _uses_wide_page_four_generation_columns(layout, page_no, row):
        return True
    if _uses_sparse_page_one_generation_columns(layout, page_no, row):
        return True
    if _uses_compact_generation_columns(layout):
        return True
    if layout != SRLDC_PROMOTER_LAYOUTS[SRLDC_FLAT_7_2023_TEMPLATE_ID]:
        return False
    column_eight = row.get(8)
    return column_eight is not None and _to_float(column_eight[1]) is not None


def _promote_frequency(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
    populated_fields: set[str],
    layout: SRLDCPromoterLayout,
) -> int:
    """Promote exact SRLDC frequency summary and cumulative band statistics."""

    region_id = _lookup_id(
        conn, "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (SR_REGION_NAME,)
    )
    if region_id is None:
        return 0
    bands = _table_row_from_window(conn, report_id, layout.frequency_band_window)
    summary = _table_row_from_window(conn, report_id, layout.frequency_summary_window)
    if _is_flat_2024_wide_layout(layout):
        mappings = {
            "DurationBelow48_80Pct": (bands, 5, _to_float),
            "DurationBelow49_00Pct": (bands, 8, _to_float),
            "DurationBelow49_20Pct": (bands, 13, _to_float),
            "DurationBelow49_50Pct": (bands, 17, _to_float),
            "DurationBelow49_70Pct": (bands, 21, _to_float),
            "DurationBelow49_90Pct": (bands, 27, _to_float),
            "Duration49_90To50_05InclusivePct": (bands, 33, _to_float),
            "Duration49_90To50_05Pct": (bands, 33, _to_float),
            "DurationAbove50_00Pct": (bands, 39, _to_float),
            "DurationAbove50_05Pct": (bands, 43, _to_float),
            "MaximumFrequencyHz": (summary, 1, _to_float),
            "MaximumFrequencyTime": (summary, 5, _normalize_time),
            "MinimumFrequencyHz": (summary, 8, _to_float),
            "MinimumFrequencyTime": (summary, 13, _normalize_time),
            "AverageFrequencyHz": (summary, 17, _to_float),
            "FrequencyVariationIndex": (summary, 25, _to_float),
            "StandardDeviationHz": (summary, 31, _to_float),
        }
    elif _is_flat_2023_layout(layout):
        mappings = {
            "DurationBelow48_80Pct": (bands, 3, _to_float),
            "DurationBelow49_00Pct": (bands, 6, _to_float),
            "DurationBelow49_20Pct": (bands, 9, _to_float),
            "DurationBelow49_50Pct": (bands, 13, _to_float),
            "DurationBelow49_70Pct": (bands, 17, _to_float),
            "DurationBelow49_90Pct": (bands, 22, _to_float),
            "Duration49_90To50_05InclusivePct": (bands, 27, _to_float),
            "Duration49_90To50_05Pct": (bands, 27, _to_float),
            "DurationAbove50_00Pct": (bands, 31, _to_float),
            "DurationAbove50_05Pct": (bands, 35, _to_float),
            "MaximumFrequencyHz": (summary, 1, _to_float),
            "MaximumFrequencyTime": (summary, 3, _normalize_time),
            "MinimumFrequencyHz": (summary, 6, _to_float),
            "MinimumFrequencyTime": (summary, 9, _normalize_time),
            "AverageFrequencyHz": (summary, 13, _to_float),
            "FrequencyVariationIndex": (summary, 20, _to_float),
            "StandardDeviationHz": (summary, 24, _to_float),
            "Maximum15MinuteBlockFrequencyHz": (summary, 31, _to_float),
            "Minimum15MinuteBlockFrequencyHz": (summary, 35, _to_float),
        }
    elif _is_flat_8_2025_layout(layout):
        mappings = {
            "DurationBelow48_80Pct": (bands, 4, _to_float),
            "DurationBelow49_00Pct": (bands, 6, _to_float),
            "DurationBelow49_20Pct": (bands, 9, _to_float),
            "DurationBelow49_50Pct": (bands, 13, _to_float),
            "DurationBelow49_70Pct": (bands, 17, _to_float),
            "DurationBelow49_90Pct": (bands, 22, _to_float),
            "Duration49_90To50_05InclusivePct": (bands, 27, _to_float),
            "Duration49_90To50_05Pct": (bands, 27, _to_float),
            "DurationAbove50_00Pct": (bands, 31, _to_float),
            "DurationAbove50_05Pct": (bands, 34, _to_float),
            "MaximumFrequencyHz": (summary, 1, _to_float),
            "MaximumFrequencyTime": (summary, 4, _normalize_time),
            "MinimumFrequencyHz": (summary, 6, _to_float),
            "MinimumFrequencyTime": (summary, 9, _normalize_time),
            "AverageFrequencyHz": (summary, 13, _to_float),
            "FrequencyVariationIndex": (summary, 21, _to_float),
            "StandardDeviationHz": (summary, 25, _to_float),
        }
    elif _is_flat_8_layout(layout):
        mappings = {
            "DurationBelow48_80Pct": (bands, 4, _to_float),
            "DurationBelow49_00Pct": (bands, 7, _to_float),
            "DurationBelow49_20Pct": (bands, 12, _to_float),
            "DurationBelow49_50Pct": (bands, 15, _to_float),
            "DurationBelow49_70Pct": (bands, 19, _to_float),
            "DurationBelow49_90Pct": (bands, 24, _to_float),
            "Duration49_90To50_05InclusivePct": (bands, 29, _to_float),
            "Duration49_90To50_05Pct": (bands, 29, _to_float),
            "DurationAbove50_00Pct": (bands, 34, _to_float),
            "DurationAbove50_05Pct": (bands, 38, _to_float),
            "MaximumFrequencyHz": (summary, 1, _to_float),
            "MaximumFrequencyTime": (summary, 4, _normalize_time),
            "MinimumFrequencyHz": (summary, 7, _to_float),
            "MinimumFrequencyTime": (summary, 12, _normalize_time),
            "AverageFrequencyHz": (summary, 15, _to_float),
            "FrequencyVariationIndex": (summary, 22, _to_float),
            "StandardDeviationHz": (summary, 27, _to_float),
        }
    else:
        mappings = {
            "DurationBelow48_80Pct": (bands, 2, _to_float),
            "DurationBelow49_00Pct": (bands, 3, _to_float),
            "DurationBelow49_20Pct": (bands, 4, _to_float),
            "DurationBelow49_50Pct": (bands, 5, _to_float),
            "DurationBelow49_70Pct": (bands, 6, _to_float),
            "DurationBelow49_90Pct": (bands, 7, _to_float),
            "Duration49_90To50_05InclusivePct": (bands, 8, _to_float),
            "Duration49_90To50_05Pct": (bands, 8, _to_float),
            "DurationAbove50_00Pct": (bands, 9, _to_float),
            "DurationAbove50_05Pct": (bands, 10, _to_float),
            "MaximumFrequencyHz": (summary, 1, _to_float),
            "MaximumFrequencyTime": (summary, 2, _normalize_time),
            "MinimumFrequencyHz": (summary, 3, _to_float),
            "MinimumFrequencyTime": (summary, 4, _normalize_time),
            "AverageFrequencyHz": (summary, 5, _to_float),
            "FrequencyVariationIndex": (summary, 6, _to_float),
            "StandardDeviationHz": (summary, 7, _to_float),
        }
    assignments: list[str] = []
    parameters: list[object] = []
    destination_key = f"report={report_id};date={date_id};region={region_id}"
    for column, (row, col_no, converter) in mappings.items():
        raw = row.get(col_no)
        value = converter(raw[1]) if raw else None
        assignments.append(f"{column} = ?")
        parameters.append(value)
        if raw and value is not None:
            _insert_lineage(
                conn, report_id, "FactSRLDCRegionalDaily", destination_key,
                column, raw[0], mapped_cells
            )
    assignments.append("FrequencyBandDefinitionVersion = ?")
    parameters.append("SRLDC-2026.05-cumulative")
    parameters.extend((report_id, date_id, region_id))
    conn.execute(
        f"""
        UPDATE FactSRLDCRegionalDaily SET {', '.join(assignments)}
        WHERE ReportDocumentID = ? AND DateID = ? AND RegionID = ?
        """,
        parameters,
    )
    populated_fields.add("frequency_profile")
    below = _mapping_value(mappings, "DurationBelow49_90Pct")
    within = _mapping_value(mappings, "Duration49_90To50_05InclusivePct")
    above = _mapping_value(mappings, "DurationAbove50_05Pct")
    if None not in (below, within, above):
        if abs(float(below) + float(within) + float(above) - 100.0) > 0.1:
            return 1
    return 0


def _mapping_value(
    mappings: dict[str, tuple[dict[int, tuple[int, str]], int, object]],
    column: str,
) -> float | None:
    """Read one numeric value from a resolved frequency source mapping."""

    row, col_no, converter = mappings[column]
    raw = row.get(col_no)
    value = converter(raw[1]) if raw else None
    return float(value) if value is not None else None


def _validate_state_energy_balance(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
) -> int:
    """Validate state demand energy against the report's regional energy total.

    The two-percent allowance accommodates published rounding and reported
    regional transmission losses without treating operational differences as
    parser failures.
    """

    state_total = conn.execute(
        """
        SELECT SUM(DemandMetMU) FROM FactSRLDCStateDaily
        WHERE ReportDocumentID = ? AND DateID = ?
        """,
        (report_id, date_id),
    ).fetchone()[0]
    regional_total = conn.execute(
        """
        SELECT DayEnergyMetMU FROM FactSRLDCRegionalDaily
        WHERE ReportDocumentID = ? AND DateID = ?
        """,
        (report_id, date_id),
    ).fetchone()
    if state_total is None or regional_total is None or regional_total[0] is None:
        return 0
    tolerance = max(0.5, abs(float(regional_total[0])) * 0.02)
    return int(abs(float(state_total) - float(regional_total[0])) > tolerance)


def _promote_voltage(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
    populated_fields: set[str],
    layout: SRLDCPromoterLayout,
) -> None:
    """Promote 765, 400 and 220 kV daily voltage extrema and thresholds."""

    conn.execute(
        "DELETE FROM FactSRLDCVoltageProfile WHERE ReportDocumentID = ?", (report_id,)
    )
    region_id = _lookup_id(
        conn, "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (SR_REGION_NAME,)
    )
    if region_id is None:
        return
    for voltage_window in layout.voltage_tables:
        for row in _table_rows_for_window(conn, report_id, voltage_window.window):
            name_cell = row.get(1)
            node_name = name_cell[1].strip() if name_cell else ""
            if _is_flat_2024_wide_layout(layout):
                gate_col = 8
            elif _is_flat_8_2025_layout(layout) or _is_flat_2023_layout(layout):
                gate_col = 6
            elif _is_flat_8_layout(layout):
                gate_col = 7
            else:
                gate_col = 2
            if not node_name or _cell_float(row, gate_col) is None:
                continue
            node_id = _get_or_create_voltage_node(
                conn, node_name, voltage_window.nominal_kv, region_id
            )
            if _is_flat_2024_wide_layout(layout):
                value_cols = {
                    "MaximumKV": 8,
                    "MaximumTime": 13,
                    "MinimumKV": 17,
                    "MinimumTime": 21,
                    "LowCriticalPct": 27,
                    "LowWarningPct": 33,
                    "HighWarningPct": 39,
                    "HighCriticalPct": 43,
                    "BelowBandPct": 33,
                    "AboveBandPct": 39,
                }
            elif _is_flat_2023_layout(layout):
                value_cols = {
                    "MaximumKV": 6,
                    "MaximumTime": 9,
                    "MinimumKV": 13,
                    "MinimumTime": 17,
                    "LowCriticalPct": 22,
                    "LowWarningPct": 27,
                    "HighWarningPct": 31,
                    "HighCriticalPct": 35,
                    "BelowBandPct": 27,
                    "AboveBandPct": 31,
                }
            elif _is_flat_8_2025_layout(layout):
                value_cols = {
                    "MaximumKV": 6,
                    "MaximumTime": 9,
                    "MinimumKV": 13,
                    "MinimumTime": 17,
                    "LowCriticalPct": 22,
                    "LowWarningPct": 27,
                    "HighWarningPct": 31,
                    "HighCriticalPct": 34,
                    "BelowBandPct": 27,
                    "AboveBandPct": 31,
                }
            elif _is_flat_8_layout(layout):
                value_cols = {
                    "MaximumKV": 7,
                    "MaximumTime": 12,
                    "MinimumKV": 15,
                    "MinimumTime": 19,
                    "LowCriticalPct": 24,
                    "LowWarningPct": 29,
                    "HighWarningPct": 34,
                    "HighCriticalPct": 38,
                    "BelowBandPct": 29,
                    "AboveBandPct": 34,
                }
            else:
                value_cols = {
                    "MaximumKV": 2,
                    "MaximumTime": 3,
                    "MinimumKV": 4,
                    "MinimumTime": 5,
                    "LowCriticalPct": 6,
                    "LowWarningPct": 7,
                    "HighWarningPct": 8,
                    "HighCriticalPct": 9,
                    "BelowBandPct": 7,
                    "AboveBandPct": 8,
                }
            values = {
                column: (
                    _cell_time(row, col_no)
                    if "Time" in column
                    else _cell_float(row, col_no)
                )
                for column, col_no in value_cols.items()
            }
            columns = list(values)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO FactSRLDCVoltageProfile(
                    ReportDocumentID, DateID, VoltageNodeID, {', '.join(columns)}
                ) VALUES (?, ?, ?, {', '.join('?' for _ in columns)})
                """,
                (report_id, date_id, node_id, *(values[c] for c in columns)),
            )
            key = f"report={report_id};date={date_id};voltage_node={node_id}"
            if name_cell:
                mapped_cells.add(name_cell[0])
            for column in columns:
                col_no = value_cols[column]
                raw = row.get(col_no)
                if raw and values[column] is not None:
                    _insert_lineage(
                        conn, report_id, "FactSRLDCVoltageProfile", key,
                        column, raw[0], mapped_cells
                    )
            populated_fields.add("voltage_profile_row")


def _promote_reservoirs(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
    populated_fields: set[str],
    layout: SRLDCPromoterLayout,
) -> None:
    """Promote reservoir design, current, prior-year and monthly measures."""

    conn.execute(
        "DELETE FROM FactSRLDCReservoirDaily WHERE ReportDocumentID = ?", (report_id,)
    )
    region_id = _lookup_id(
        conn, "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (SR_REGION_NAME,)
    )
    if region_id is None:
        return
    for window in layout.reservoir_tables:
        for row in _table_rows_for_window(conn, report_id, window):
            name_cell = row.get(1)
            name = name_cell[1].strip() if name_cell else ""
            if not name or name.lower() in {"reservoir", "total"}:
                continue
            if _is_flat_2024_wide_layout(layout):
                designed_col = 11
            elif _is_flat_8_2025_layout(layout) or _is_flat_2023_layout(layout):
                designed_col = 8
            elif _is_flat_8_layout(layout):
                designed_col = 10
            else:
                designed_col = 4
            if _cell_float(row, designed_col) is None:
                continue
            reservoir_id = _get_or_create_reservoir(conn, name, region_id)
            if _is_flat_2024_wide_layout(layout):
                value_cols = {
                    "MinimumDrawdownLevelM": 6,
                    "FullReservoirLevelM": 8,
                    "DesignedEnergyMU": 11,
                    "CurrentLevelM": 16,
                    "CurrentEnergyMU": 20,
                    "PreviousYearLevelM": 24,
                    "PreviousYearEnergyMU": 27,
                    "InflowMU": 32,
                    "UsageMU": 37,
                    "ProgressiveInflowMU": 41,
                    "ProgressiveUsageMU": 46,
                }
            elif _is_flat_2023_layout(layout):
                value_cols = {
                    "MinimumDrawdownLevelM": 5,
                    "FullReservoirLevelM": 6,
                    "DesignedEnergyMU": 8,
                    "CurrentLevelM": 11,
                    "CurrentEnergyMU": 15,
                    "PreviousYearLevelM": 19,
                    "PreviousYearEnergyMU": 22,
                    "InflowMU": 25,
                    "UsageMU": 29,
                    "ProgressiveInflowMU": 33,
                    "ProgressiveUsageMU": 37,
                }
            elif _is_flat_8_2025_layout(layout):
                value_cols = {
                    "MinimumDrawdownLevelM": 5,
                    "FullReservoirLevelM": 6,
                    "DesignedEnergyMU": 8,
                    "CurrentLevelM": 12,
                    "CurrentEnergyMU": 16,
                    "PreviousYearLevelM": 20,
                    "PreviousYearEnergyMU": 22,
                    "InflowMU": 26,
                    "UsageMU": 30,
                    "ProgressiveInflowMU": 33,
                    "ProgressiveUsageMU": 37,
                }
            elif _is_flat_8_layout(layout):
                value_cols = {
                    "MinimumDrawdownLevelM": 5,
                    "FullReservoirLevelM": 7,
                    "DesignedEnergyMU": 10,
                    "CurrentLevelM": 14,
                    "CurrentEnergyMU": 18,
                    "PreviousYearLevelM": 21,
                    "PreviousYearEnergyMU": 24,
                    "InflowMU": 28,
                    "UsageMU": 32,
                    "ProgressiveInflowMU": 36,
                    "ProgressiveUsageMU": 40,
                }
            else:
                value_cols = {
                    "MinimumDrawdownLevelM": 2,
                    "FullReservoirLevelM": 3,
                    "DesignedEnergyMU": 4,
                    "CurrentLevelM": 5,
                    "CurrentEnergyMU": 6,
                    "PreviousYearLevelM": 7,
                    "PreviousYearEnergyMU": 8,
                    "InflowMU": 9,
                    "UsageMU": 10,
                    "ProgressiveInflowMU": 11,
                    "ProgressiveUsageMU": 12,
                }
            values = {
                column: _cell_float(row, col_no)
                for column, col_no in value_cols.items()
            }
            columns = list(values)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO FactSRLDCReservoirDaily(
                    ReportDocumentID, DateID, ReservoirID, {', '.join(columns)}
                ) VALUES (?, ?, ?, {', '.join('?' for _ in columns)})
                """,
                (report_id, date_id, reservoir_id, *(values[c] for c in columns)),
            )
            key = f"report={report_id};date={date_id};reservoir={reservoir_id}"
            if name_cell:
                mapped_cells.add(name_cell[0])
            for column in columns:
                col_no = value_cols[column]
                raw = row.get(col_no)
                if raw and values[column] is not None:
                    _insert_lineage(
                        conn, report_id, "FactSRLDCReservoirDaily", key,
                        column, raw[0], mapped_cells
                    )
            populated_fields.add("reservoir_daily_row")


def _promote_interregional_exchange(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
    populated_fields: set[str],
    layout: SRLDCPromoterLayout,
) -> None:
    """Promote physical corridor flows and schedule-versus-actual summaries."""

    conn.execute(
        "DELETE FROM FactSRLDCInterRegionalExchange WHERE ReportDocumentID = ?",
        (report_id,),
    )
    for window in layout.physical_exchange_tables:
        for row in _table_rows_for_window(conn, report_id, window):
            name_cell = row.get(2)
            if not name_cell or not name_cell[1].strip():
                name_cell = row.get(1)
            name = name_cell[1].strip() if name_cell else ""
            if not name or name.lower() in {"sl.no.", "element"}:
                continue
            physical_columns = _physical_exchange_columns(layout, window)
            values = {
                column: _cell_float(row, col_no)
                for column, col_no in physical_columns
            }
            if all(value is None for value in values.values()):
                continue
            direction = _exchange_direction(values["NetEnergyMU"])
            element_id = _get_or_create_transmission_element(conn, name)
            _insert_exchange_fact(
                conn, report_id, date_id, element_id, "physical_flow",
                direction, values
            )
            key = (
                f"report={report_id};date={date_id};element={element_id};"
                f"category=physical_flow;direction={direction}"
            )
            if name_cell:
                mapped_cells.add(name_cell[0])
            for column, col_no in physical_columns:
                raw = row.get(col_no)
                if raw and values[column] is not None:
                    _insert_lineage(
                        conn, report_id, "FactSRLDCInterRegionalExchange",
                        key, column, raw[0], mapped_cells
                    )
            populated_fields.add("inter_regional_physical_flow")

    schedule_categories = layout.schedule_exchange_columns or (
        ("ISGS+URS+GNA", 2), ("TGNA", 3), ("GDAM", 4),
        ("DAM", 5), ("HPDAM", 6), ("RTM", 7),
        ("TOTAL_SCHEDULE", 8),
    )
    for row in _table_rows_for_window(conn, report_id, layout.schedule_exchange_table):
        name_cell = row.get(1)
        name = name_cell[1].strip() if name_cell else ""
        if not name or name.lower() == "link":
            continue
        element_id = _get_or_create_transmission_element(conn, name)
        if name_cell:
            mapped_cells.add(name_cell[0])
        for category, col_no in schedule_categories:
            value = _cell_float(row, col_no)
            if value is None:
                continue
            direction = _exchange_direction(value)
            values = {"ScheduledMU": value}
            _insert_exchange_fact(
                conn, report_id, date_id, element_id, category, direction, values
            )
            key = (
                f"report={report_id};date={date_id};element={element_id};"
                f"category={category};direction={direction}"
            )
            _insert_lineage(
                conn, report_id, "FactSRLDCInterRegionalExchange", key,
                "ScheduledMU", row[col_no][0], mapped_cells
            )
        actual_columns = layout.schedule_actual_columns or (
            ("TOTAL_ACTUAL", "ActualMU", 9),
            ("NET_UI", "DeviationMU", 10),
        )
        for category, column, col_no in actual_columns:
            value = _cell_float(row, col_no)
            if value is None:
                continue
            direction = _exchange_direction(value)
            _insert_exchange_fact(
                conn, report_id, date_id, element_id, category, direction,
                {column: value}
            )
            key = (
                f"report={report_id};date={date_id};element={element_id};"
                f"category={category};direction={direction}"
            )
            _insert_lineage(
                conn, report_id, "FactSRLDCInterRegionalExchange", key,
                column, row[col_no][0], mapped_cells
            )
    populated_fields.add("inter_regional_schedule_row")


def _physical_exchange_columns(
    layout: SRLDCPromoterLayout,
    window: RowWindow,
) -> tuple[tuple[str, int], ...]:
    """Return page-aware physical inter-regional exchange columns."""

    if _is_flat_6_2023_layout(layout) and window.page_no == 5:
        return (
            ("EveningPeakMW", 10),
            ("OffPeakMW", 14),
            ("MaximumImportMW", 18),
            ("MaximumExportMW", 23),
            ("ImportEnergyMU", 28),
            ("ExportEnergyMU", 32),
            ("NetEnergyMU", 36),
        )
    return layout.physical_exchange_columns or (
        ("EveningPeakMW", 3),
        ("OffPeakMW", 4),
        ("MaximumImportMW", 5),
        ("MaximumExportMW", 6),
        ("ImportEnergyMU", 7),
        ("ExportEnergyMU", 8),
        ("NetEnergyMU", 9),
    )


def _promote_market_transactions(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
    populated_fields: set[str],
    layout: SRLDCPromoterLayout,
) -> None:
    """Promote state and regional market snapshots, daily energy and extrema."""

    conn.execute(
        "DELETE FROM FactSRLDCMarketTransaction WHERE ReportDocumentID = ?",
        (report_id,),
    )
    conn.execute(
        "DELETE FROM FactSRLDCRegionalMarketTransaction WHERE ReportDocumentID = ?",
        (report_id,),
    )
    for window, time_category in layout.market_point_tables:
        for row in _table_rows_for_window(conn, report_id, window):
            state_cell = row.get(1)
            state_name = state_cell[1].strip() if state_cell else ""
            target = _market_target(conn, state_name)
            if target is None:
                continue
            if state_cell:
                mapped_cells.add(state_cell[0])
            point_columns = layout.market_point_columns or tuple(MARKET_POINT_COLUMNS.items())
            for col_no, label in point_columns:
                value = _cell_float(row, col_no)
                if value is None:
                    continue
                _insert_market_target_fact(
                    conn, report_id, date_id, target, label,
                    time_category, scheduled_mw=value
                )
                _market_target_lineage(
                    conn, report_id, date_id, target, label, time_category,
                    "ScheduledMW", row[col_no][0], mapped_cells
                )
            populated_fields.add("market_point_schedule_row")

    for window, time_category, point_columns in layout.market_point_column_maps:
        for row in _table_rows_for_window(conn, report_id, window):
            state_cell = row.get(1)
            state_name = state_cell[1].strip() if state_cell else ""
            target = _market_target(conn, state_name)
            if target is None:
                continue
            if state_cell:
                mapped_cells.add(state_cell[0])
            for col_no, label in point_columns:
                value = _cell_float(row, col_no)
                if value is None:
                    continue
                _insert_market_target_fact(
                    conn, report_id, date_id, target, label,
                    time_category, scheduled_mw=value,
                )
                _market_target_lineage(
                    conn, report_id, date_id, target, label, time_category,
                    "ScheduledMW", row[col_no][0], mapped_cells,
                )
            populated_fields.add("market_point_schedule_row")

    for row in _table_rows_for_window(conn, report_id, layout.market_energy_table):
        state_cell = row.get(1)
        state_name = state_cell[1].strip() if state_cell else ""
        target = _market_target(conn, state_name)
        if target is None:
            continue
        if state_cell:
            mapped_cells.add(state_cell[0])
        energy_columns = layout.market_energy_columns or tuple(MARKET_ENERGY_COLUMNS.items())
        for col_no, label in energy_columns:
            value = _cell_float(row, col_no)
            if value is None:
                continue
            _insert_market_target_fact(
                conn, report_id, date_id, target, label,
                "daily_energy", energy_mu=value
            )
            _market_target_lineage(
                conn, report_id, date_id, target, label, "daily_energy",
                "EnergyMU", row[col_no][0], mapped_cells
            )
        populated_fields.add("market_daily_energy_row")

    for window, time_category, labels in layout.market_range_tables:
        for row in _table_rows_for_window(conn, report_id, window):
            state_cell = row.get(1)
            state_name = state_cell[1].strip() if state_cell else ""
            target = _market_target(conn, state_name)
            if target is None:
                continue
            if state_cell:
                mapped_cells.add(state_cell[0])
            for index, label in enumerate(labels):
                max_col = 2 + index * 2
                min_col = max_col + 1
                maximum = _cell_float(row, max_col)
                minimum = _cell_float(row, min_col)
                if maximum is None and minimum is None:
                    continue
                _insert_market_target_fact(
                    conn, report_id, date_id, target, label,
                    time_category, maximum_mw=maximum, minimum_mw=minimum
                )
                for column, col_no, value in (
                    ("MaximumMW", max_col, maximum),
                    ("MinimumMW", min_col, minimum),
                ):
                    if value is not None:
                        _market_target_lineage(
                            conn, report_id, date_id, target, label,
                            time_category, column, row[col_no][0], mapped_cells
                        )
            populated_fields.add("market_daily_range_row")

    for window, column_map in layout.market_range_column_maps:
        for row in _table_rows_for_window(conn, report_id, window):
            state_cell = row.get(1)
            state_name = state_cell[1].strip() if state_cell else ""
            target = _market_target(conn, state_name)
            if target is None:
                continue
            if state_cell:
                mapped_cells.add(state_cell[0])
            for label, max_col, min_col in column_map:
                maximum = _cell_float(row, max_col)
                minimum = _cell_float(row, min_col)
                if maximum is None and minimum is None:
                    continue
                _insert_market_target_fact(
                    conn, report_id, date_id, target, label,
                    "daily_range", maximum_mw=maximum, minimum_mw=minimum,
                )
                for column, col_no, value in (
                    ("MaximumMW", max_col, maximum),
                    ("MinimumMW", min_col, minimum),
                ):
                    if value is not None:
                        _market_target_lineage(
                            conn, report_id, date_id, target, label,
                            "daily_range", column, row[col_no][0], mapped_cells,
                        )
            populated_fields.add("market_daily_range_row")


def _promote_operational_events(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
    populated_fields: set[str],
    layout: SRLDCPromoterLayout,
) -> None:
    """Promote state curtailment and grid-code compliance observations."""

    conn.execute(
        "DELETE FROM FactSRLDCOperationalEvent WHERE ReportDocumentID = ?",
        (report_id,),
    )
    for row in _table_rows_for_window(conn, report_id, layout.curtailment_table):
        state_cell = row.get(1)
        state_name = state_cell[1].strip() if state_cell else ""
        state_id = _state_id(conn, state_name)
        if state_id is None:
            continue
        if state_cell:
            mapped_cells.add(state_cell[0])
        reason = row.get(layout.curtailment_reason_column, (0, ""))[1] or None
        curtailments = layout.curtailment_columns or (
            ("load_curtailment", 3, 2),
            ("wind_curtailment", 5, 6),
            ("solar_curtailment", 7, 8),
        )
        for event_name, mw_col, mu_col in curtailments:
            event_id = _insert_operational_event(
                conn, report_id, date_id, state_id, event_name,
                _cell_float(row, mw_col), _cell_float(row, mu_col),
                None, reason, None
            )
            key = f"report={report_id};event={event_id}"
            for column, col_no in (("EventMW", mw_col), ("EventMU", mu_col)):
                raw = row.get(col_no)
                if raw and _to_float(raw[1]) is not None:
                    _insert_lineage(
                        conn, report_id, "FactSRLDCOperationalEvent", key,
                        column, raw[0], mapped_cells
                    )
        populated_fields.add("curtailment_state_row")

    categories = ("frequency_deviation", "voltage", "ict_loading")
    severities = ("alert", "emergency", "extreme_emergency", "non_compliance")
    for row in _table_rows_for_window(conn, report_id, layout.compliance_table):
        state_cell = row.get(1)
        state_name = state_cell[1].strip() if state_cell else ""
        state_id = _state_id(conn, state_name)
        if state_id is None:
            continue
        if state_cell:
            mapped_cells.add(state_cell[0])
        for category_index, category in enumerate(categories):
            for severity_index, severity in enumerate(severities):
                col_no = 2 + category_index * 4 + severity_index
                count = _cell_float(row, col_no)
                if count is None:
                    continue
                event_name = f"{category}_{severity}"
                event_id = _insert_operational_event(
                    conn, report_id, date_id, state_id, event_name,
                    None, None, int(count), None, None
                )
                _insert_lineage(
                    conn, report_id, "FactSRLDCOperationalEvent",
                    f"report={report_id};event={event_id}", "OccurrenceCount",
                    row[col_no][0], mapped_cells
                )
        populated_fields.add("compliance_state_row")


def _promote_report_annotations(
    conn: sqlite3.Connection,
    report_id: int,
    layout: SRLDCPromoterLayout,
) -> None:
    """Promote significant events, constraints and weather narrative lines."""

    conn.execute(
        "DELETE FROM FactSRLDCReportAnnotation WHERE ReportDocumentID = ?",
        (report_id,),
    )
    if _is_flat_8_layout(layout) or _is_flat_8_2025_layout(layout):
        for annotation_page in layout.annotation_pages:
            if _is_flat_8_layout(layout):
                rows = _table_rows_for_window(conn, report_id, RowWindow(annotation_page, 1, 43, 46))
                grouped: list[tuple[str, int, str]] = []
                if len(rows) >= 2:
                    constraint_cell = rows[1].get(1)
                    if constraint_cell and constraint_cell[1].strip():
                        grouped.append(("transmission_constraints", int(constraint_cell[0]), constraint_cell[1].strip()))
                if len(rows) >= 4:
                    weather_cell = rows[3].get(1)
                    if weather_cell and weather_cell[1].strip():
                        grouped.append(("weather_condition", int(weather_cell[0]), weather_cell[1].strip()))
            else:
                lines = conn.execute(
                    """
                    SELECT id, line_text FROM psp_raw_line
                    WHERE report_document_id = ? AND page_no = ?
                    ORDER BY line_no
                    """,
                    (report_id, annotation_page),
                ).fetchall()
                section = None
                grouped = []
                for raw_line_id, line_text in lines:
                    text = str(line_text).strip()
                    lowered = text.lower()
                    if lowered.startswith("11.significantevents"):
                        section = "significant_events"
                        continue
                    if lowered.startswith("12.constraints"):
                        section = "transmission_constraints"
                        continue
                    if lowered.startswith("13.weathercondition"):
                        section = "weather_condition"
                        continue
                    if lowered.startswith("14.re/loadcurtailmentdetails"):
                        section = "load_curtailment_details"
                        continue
                    if lowered.startswith("15.instancesofpersistant"):
                        section = "non_compliance"
                        continue
                    if section is None or not text:
                        continue
                    if section == "transmission_constraints" and grouped:
                        previous_section, previous_id, previous_text = grouped[-1]
                        if previous_section == section and not re.match(r"^\d+\)", text):
                            grouped[-1] = (
                                previous_section, previous_id, f"{previous_text} {text}"
                            )
                            continue
                    grouped.append((section, int(raw_line_id), text))
            conn.executemany(
                """
                INSERT OR IGNORE INTO FactSRLDCReportAnnotation(
                    ReportDocumentID, SectionName, PageNo, RawLineID, AnnotationText
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ((report_id, section_name, annotation_page, raw_line_id, text)
                 for section_name, raw_line_id, text in grouped),
            )
        return

    for annotation_page in layout.annotation_pages:
        lines = conn.execute(
            """
            SELECT id, line_text FROM psp_raw_line
            WHERE report_document_id = ? AND page_no = ?
            ORDER BY line_no
            """,
            (report_id, annotation_page),
        ).fetchall()
        section: str | None = None
        grouped: list[tuple[str, int, str]] = []
        for raw_line_id, line_text in lines:
            text = str(line_text).strip()
            detected_section = _annotation_section_for_line(text)
            if detected_section is not None:
                section = detected_section
                continue
            if _is_structured_event_heading(text):
                section = None
                continue
            if _is_availability_note(text):
                grouped.append(("availability_note", int(raw_line_id), text))
                continue
            if section is None or not text:
                continue
            if section == "transmission_constraints" and grouped:
                previous_section, previous_id, previous_text = grouped[-1]
                if previous_section == section and not re.match(r"^\d+\)", text):
                    grouped[-1] = (
                        previous_section, previous_id, f"{previous_text} {text}"
                    )
                    continue
            grouped.append((section, int(raw_line_id), text))

        conn.executemany(
            """
            INSERT OR IGNORE INTO FactSRLDCReportAnnotation(
                ReportDocumentID, SectionName, PageNo, RawLineID, AnnotationText
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ((report_id, section_name, annotation_page, raw_line_id, text)
             for section_name, raw_line_id, text in grouped),
        )


def _assign(
    values: dict[str, object],
    sources: dict[str, int],
    populated_fields: set[str],
    row: dict[int, tuple[int, str]],
    col_no: int,
    canonical: str,
    column: str,
    unit: str,
) -> None:
    """Convert and assign one approved state mapping."""

    raw = row.get(col_no)
    converter = _normalize_time if unit == "HH:MM:SS" else _to_float
    value = converter(raw[1]) if raw else None
    values[column] = value
    if raw and value is not None:
        sources[column] = raw[0]
        populated_fields.add(canonical)


def _record_coverage(
    conn: sqlite3.Connection,
    report_id: int,
    template_id: str,
    mapped_cells: set[int],
    populated_fields: set[str],
    validation_failures: int,
) -> None:
    """Persist exhaustive dispositions and create proposals for ambiguities."""

    now = datetime.now(timezone.utc).isoformat()
    required = {
        row[0]
        for row in conn.execute(
            "SELECT CanonicalName FROM schema_field WHERE RequirementLevel = 'required'"
        )
    }
    missing = required - populated_fields
    rows = conn.execute(
        """
        SELECT id, page_no, table_no, row_no, col_no, cell_text
        FROM psp_raw_cell WHERE report_document_id = ? AND TRIM(COALESCE(cell_text, '')) <> ''
        """,
        (report_id,),
    ).fetchall()
    dispositions: list[tuple[int, str, str, str | None]] = []
    ambiguous_groups: dict[str, list[dict[str, object]]] = {}
    for raw_id, page, table, row, col, text in rows:
        reference = f"cell:{raw_id}:p{page}:t{table}:r{row}:c{col}"
        if raw_id in mapped_cells:
            disposition, reason = "mapped_value", "approved_mapping"
        elif _is_narrative_marker(str(text)):
            disposition, reason = "intentionally_excluded", "narrative_annotation_preserved_in_raw_lines"
        elif _is_header_cell(str(text)):
            disposition, reason = "header", "recognized_header_or_unit_label"
        elif col == 1:
            disposition, reason = "dimension", "row_label_or_entity"
        elif _is_structural_noise_cell(str(text)):
            disposition, reason = "intentionally_excluded", "structural_noise"
        elif _to_float(str(text)) is not None:
            disposition, reason = "ambiguous", "numeric_value_without_approved_mapping"
        else:
            disposition, reason = "ambiguous", "text_value_without_approved_mapping"
        dispositions.append((raw_id, reference, disposition, reason))
        if disposition == "ambiguous":
            key = f"p{page}:t{table}:c{col}"
            ambiguous_groups.setdefault(key, []).append(
                {"raw_cell_id": raw_id, "row": row, "value": str(text)[:200]}
            )

    expected = sum(
        1 for _, _, disposition, _ in dispositions
        if disposition not in {
            "header", "dimension", "derived", "duplicate", "decorative",
            "intentionally_excluded",
        }
    )
    mapped = int(conn.execute(
        "SELECT COUNT(*) FROM curated_field_lineage WHERE ReportDocumentID = ?",
        (report_id,),
    ).fetchone()[0])
    excluded = sum(
        1 for _, _, disposition, _ in dispositions
        if disposition in {"derived", "duplicate", "decorative", "intentionally_excluded"}
    )
    ambiguous = sum(1 for _, _, disposition, _ in dispositions if disposition == "ambiguous")
    coverage_pct = round(100.0 * mapped / expected, 2) if expected else 0.0
    status = "passed" if not ambiguous and not missing and not validation_failures else "review_required"
    previous_run = conn.execute(
        "SELECT CoverageRunID FROM schema_coverage_run WHERE ReportDocumentID = ?",
        (report_id,),
    ).fetchone()
    if previous_run:
        conn.execute(
            "DELETE FROM schema_coverage_item WHERE CoverageRunID = ?",
            (previous_run[0],),
        )
        conn.execute(
            "DELETE FROM schema_coverage_run WHERE CoverageRunID = ?",
            (previous_run[0],),
        )
    cursor = conn.execute(
        """
        INSERT INTO schema_coverage_run(
            ReportDocumentID, TemplateID, ExpectedFieldCount, MappedFieldCount,
            ExcludedFieldCount, AmbiguousFieldCount, MissingRequiredCount,
            LineageCompleteCount, ValidationFailureCount, CoveragePct, Status, ComputedAt
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id, template_id, expected, mapped, excluded, ambiguous, len(missing),
            mapped, validation_failures, coverage_pct, status, now,
        ),
    )
    coverage_run_id = int(cursor.lastrowid)
    conn.executemany(
        """
        INSERT INTO schema_coverage_item(
            CoverageRunID, RawCellID, SourceReference, Disposition, Reason
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ((coverage_run_id, raw_id, reference, disposition, reason)
         for raw_id, reference, disposition, reason in dispositions),
    )
    for canonical in sorted(missing):
        conn.execute(
            """
            INSERT INTO schema_coverage_item(
                CoverageRunID, SourceReference, Disposition, Reason
            ) VALUES (?, ?, 'missing', 'required_field_not_populated')
            """,
            (coverage_run_id, f"field:{canonical}"),
        )
    for candidate_key, evidence in ambiguous_groups.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_proposal(
                ReportDocumentID, ProposalType, CandidateKey, EvidenceJson,
                CompatibilityResult, Status, CreatedAt
            ) VALUES (?, 'unmapped_source_column', ?, ?, 'manual_review_required', 'pending', ?)
            """,
            (report_id, candidate_key, json.dumps(evidence[:20], sort_keys=True), now),
        )


def _is_narrative_marker(text: str) -> bool:
    """Return whether a cell is a narrative section retained through raw lines."""

    normalized = re.sub(r"\s+", " ", text).strip().lower()
    markers = (
        "significant events",
        "system constraints",
        "constraints and instances",
        "weather condition",
        "re/load curtailment",
        "non-complaint with grid code",
        "non-compliance with grid code",
    )
    return any(marker in normalized for marker in markers)


def _annotation_section_for_line(text: str) -> str | None:
    """Return the canonical annotation section for a numbered PSP heading."""

    compact = re.sub(r"\s+", "", text).lower()
    if compact.startswith("11.significantevents"):
        return "significant_events"
    if compact.startswith("12.constraints"):
        return "transmission_constraints"
    if compact.startswith("13.weathercondition"):
        return "weather_condition"
    return None


def _is_structured_event_heading(text: str) -> bool:
    """Return whether a heading starts a separately promoted fact section."""

    compact = re.sub(r"\s+", "", text).lower()
    return compact.startswith((
        "14.re/loadcurtailment",
        "15.instancesofpersistant",
    ))


def _is_availability_note(text: str) -> bool:
    """Return whether a raw line documents a published availability caveat."""

    compact = re.sub(r"\s+", "", text).lower()
    return compact.startswith("*mwavailabiltyindicatedaboveincludes")


def _is_header_cell(text: str) -> bool:
    """Return whether a non-empty cell is a known table heading or unit label."""

    normalized = re.sub(r"\s+", " ", text).strip().lower()
    exact_labels = {
        "state", "station", "station/constituents", "sl.no.", "sl.no",
        "total", "frequency", "range(hz)", "%", "maximum", "minimum",
        "time", "energy", "reason", "element", "link", "reservoir",
        "shortage", "shortage #", "requirement", "demand met", "net sch",
        "ui", "thermal", "hydro", "gas/diesel /naptha", "wind", "solar",
        "others", "ace", "avg", "hrs", "peak mw", "off peak mw",
    }
    if normalized in exact_labels:
        return True
    if _to_float(normalized) is not None:
        return False
    header_markers = (
        "(mw)", "(mu)", "(kv)", "(hz)", "(mts)", "maximum", "minimum",
        "schedule", "availability", "drawal", "frequency", "voltage", "energy",
        "installed capacity", "inst.capacity", "peak hours", "off-peak hours",
        "20:00", "03:00", "day peak", "daypeak", "peakmw", "offpeakmw", "grossgen",
        "netgen", "avg.mw", "mddl", "frl", "inflow", "usage", "import",
        "export", "inter-regional", "open access", "bilateral", "isgs", "t-gna",
        "gdam", "hpd", "rtm", "total ir", "netirui", "control area generation",
        "forecast", "deviation", "min generation", "inst. capacity",
    )
    return any(marker in normalized for marker in header_markers)


def _is_structural_noise_cell(text: str) -> bool:
    """Return whether a non-value cell is a known PSP presentation artefact."""

    normalized = re.sub(r"\s+", " ", text).strip().lower()
    if not normalized:
        return True
    if normalized in {"-", "nil", "n/a", "na"}:
        return True
    exact_labels = {
        "state",
        "station/constituents",
        "sl.no.",
        "sl.no",
        "total",
        "shift in charge",
        "frequency",
        "range(hz)",
        "%",
    }
    if normalized in exact_labels:
        return True
    boilerplate = (
        "grid controller of india",
        "southern regional load despatch centre",
        "daily operation report of southern region",
        "power supply position in southern region",
        "mw availability indicated above includes",
        "accuracy of shortage computation depends",
    )
    return any(marker in normalized for marker in boilerplate)


def _record_unrecognized_report(
    conn: sqlite3.Connection,
    report_id: int,
    report: dict[str, object],
) -> None:
    """Create a proposal when no approved template mapping can be applied."""

    now = datetime.now(timezone.utc).isoformat()
    evidence = {
        "template_id": report.get("template_id"),
        "semantic_pass_required": report.get("semantic_pass_required"),
        "local_path": report.get("local_path"),
    }
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_proposal(
            ReportDocumentID, ProposalType, CandidateKey, EvidenceJson,
            CompatibilityResult, Status, CreatedAt
        ) VALUES (?, 'new_template', ?, ?, 'template_mapping_required', 'pending', ?)
        """,
        (report_id, f"report:{report_id}", json.dumps(evidence, sort_keys=True), now),
    )
    persist_report_schema_proposals(conn, report_id)


def _table_row(
    conn: sqlite3.Connection,
    report_id: int,
    page_no: int,
    table_no: int,
    row_no: int,
) -> dict[int, tuple[int, str]]:
    """Return a raw table row keyed by column with source-cell identifiers."""

    rows = conn.execute(
        """
        SELECT id, col_no, cell_text FROM psp_raw_cell
        WHERE report_document_id = ? AND page_no = ? AND table_no = ? AND row_no = ?
        """,
        (report_id, page_no, table_no, row_no),
    ).fetchall()
    return {int(col): (int(raw_id), str(text or "").strip()) for raw_id, col, text in rows}


def _table_row_from_window(
    conn: sqlite3.Connection,
    report_id: int,
    window: RowWindow,
    offset: int = 0,
) -> dict[int, tuple[int, str]]:
    """Return one row from a configured row window with an optional relative offset."""

    return _table_row(
        conn,
        report_id,
        window.page_no,
        window.table_no,
        window.start_row + offset,
    )


def _exchange_direction(value: object) -> str:
    """Return the published net exchange direction while preserving its sign."""

    if value is None:
        return "unspecified"
    return "import" if float(value) >= 0 else "export"


def _get_or_create_transmission_element(
    conn: sqlite3.Connection,
    name: str,
) -> int:
    """Resolve a physical corridor or aggregate exchange link."""

    metadata = transmission_location(name)
    from_region_id = _region_id(conn, metadata.from_location.region_name)
    to_region_id = _region_id(conn, metadata.to_location.region_name)
    from_state_id = _state_id(conn, metadata.from_location.state_name)
    to_state_id = _state_id(conn, metadata.to_location.state_name)
    conn.execute(
        """
        INSERT OR IGNORE INTO DimTransmissionElements(
            ElementName, ElementType, NominalVoltageKV,
            FromRegionID, ToRegionID, FromStateID, ToStateID
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name, metadata.element_type, metadata.nominal_voltage_kv,
            from_region_id, to_region_id, from_state_id, to_state_id,
        ),
    )
    conn.execute(
        """
        UPDATE DimTransmissionElements
        SET ElementType = COALESCE(ElementType, ?),
            NominalVoltageKV = COALESCE(NominalVoltageKV, ?),
            FromRegionID = COALESCE(FromRegionID, ?),
            ToRegionID = COALESCE(ToRegionID, ?),
            FromStateID = COALESCE(FromStateID, ?),
            ToStateID = COALESCE(ToStateID, ?)
        WHERE ElementName = ?
        """,
        (
            metadata.element_type, metadata.nominal_voltage_kv,
            from_region_id, to_region_id, from_state_id, to_state_id, name,
        ),
    )
    return int(conn.execute(
        "SELECT ElementID FROM DimTransmissionElements WHERE ElementName = ?",
        (name,),
    ).fetchone()[0])


def _insert_exchange_fact(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    element_id: int,
    category: str,
    direction: str,
    values: dict[str, object],
) -> None:
    """Insert one grain-stable physical or scheduled exchange observation."""

    columns = list(values)
    conn.execute(
        f"""
        INSERT OR REPLACE INTO FactSRLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, ExchangeCategory, Direction,
            {', '.join(columns)}
        ) VALUES (?, ?, ?, ?, ?, {', '.join('?' for _ in columns)})
        """,
        (
            report_id, date_id, element_id, category, direction,
            *(values[column] for column in columns),
        ),
    )


def _get_or_create_exchange_mechanism(
    conn: sqlite3.Connection,
    label: str,
) -> int:
    """Resolve an exchange mechanism discovered in an SRLDC market table."""

    conn.execute(
        "INSERT OR IGNORE INTO DimExchangeMechanisms(MechanismName) VALUES (?)",
        (label,),
    )
    return int(conn.execute(
        "SELECT MechanismID FROM DimExchangeMechanisms WHERE MechanismName = ?",
        (label,),
    ).fetchone()[0])


def _insert_market_fact(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    state_id: int,
    label: str,
    time_category: str,
    energy_mu: float | None = None,
    scheduled_mw: float | None = None,
    maximum_mw: float | None = None,
    minimum_mw: float | None = None,
) -> None:
    """Insert one state market value at its published temporal grain."""

    mechanism_id = _get_or_create_exchange_mechanism(conn, label)
    product_name = label.split()[-1]
    signed_value = scheduled_mw if scheduled_mw is not None else energy_mu
    direction = "range" if time_category == "daily_range" else _exchange_direction(signed_value)
    conn.execute(
        """
        INSERT OR REPLACE INTO FactSRLDCMarketTransaction(
            ReportDocumentID, DateID, StateID, MechanismID, ProductName,
            Direction, TimeCategory, EnergyMU, ScheduledMW, MaximumMW, MinimumMW
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id, date_id, state_id, mechanism_id, product_name,
            direction, time_category, energy_mu, scheduled_mw,
            maximum_mw, minimum_mw,
        ),
    )


def _market_target(
    conn: sqlite3.Connection,
    published_name: str,
) -> tuple[str, int] | None:
    """Resolve a market row to its state or Southern Region reporting grain."""

    normalized = re.sub(r"[^a-z0-9]", "", published_name.lower())
    if normalized in {"total", "region", "southernregion"}:
        region_id = _lookup_id(
            conn,
            "SELECT RegionID FROM DimRegions WHERE RegionName = ?",
            (SR_REGION_NAME,),
        )
        return ("region", region_id) if region_id is not None else None
    state_id = _state_id(conn, published_name)
    return ("state", state_id) if state_id is not None else None


def _insert_market_target_fact(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    target: tuple[str, int],
    label: str,
    time_category: str,
    energy_mu: float | None = None,
    scheduled_mw: float | None = None,
    maximum_mw: float | None = None,
    minimum_mw: float | None = None,
) -> None:
    """Insert a market observation at its resolved state or regional grain."""

    target_kind, target_id = target
    if target_kind == "state":
        _insert_market_fact(
            conn,
            report_id,
            date_id,
            target_id,
            label,
            time_category,
            energy_mu,
            scheduled_mw,
            maximum_mw,
            minimum_mw,
        )
        return

    mechanism_id = _get_or_create_exchange_mechanism(conn, label)
    product_name = label.split()[-1]
    signed_value = scheduled_mw if scheduled_mw is not None else energy_mu
    direction = "range" if time_category == "daily_range" else _exchange_direction(signed_value)
    conn.execute(
        """
        INSERT OR REPLACE INTO FactSRLDCRegionalMarketTransaction(
            ReportDocumentID, DateID, RegionID, MechanismID, ProductName,
            Direction, TimeCategory, EnergyMU, ScheduledMW, MaximumMW, MinimumMW
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id,
            date_id,
            target_id,
            mechanism_id,
            product_name,
            direction,
            time_category,
            energy_mu,
            scheduled_mw,
            maximum_mw,
            minimum_mw,
        ),
    )


def _market_lineage(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    state_id: int,
    label: str,
    time_category: str,
    column: str,
    raw_cell_id: int,
    mapped_cells: set[int],
) -> None:
    """Persist one market fact lineage edge."""

    key = (
        f"report={report_id};date={date_id};state={state_id};"
        f"mechanism={label};time={time_category}"
    )
    _insert_lineage(
        conn, report_id, "FactSRLDCMarketTransaction", key,
        column, raw_cell_id, mapped_cells
    )


def _market_target_lineage(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    target: tuple[str, int],
    label: str,
    time_category: str,
    column: str,
    raw_cell_id: int,
    mapped_cells: set[int],
) -> None:
    """Persist lineage for a state or regional market observation."""

    target_kind, target_id = target
    if target_kind == "state":
        _market_lineage(
            conn,
            report_id,
            date_id,
            target_id,
            label,
            time_category,
            column,
            raw_cell_id,
            mapped_cells,
        )
        return
    key = (
        f"report={report_id};date={date_id};region={target_id};"
        f"mechanism={label};time={time_category}"
    )
    _insert_lineage(
        conn,
        report_id,
        "FactSRLDCRegionalMarketTransaction",
        key,
        column,
        raw_cell_id,
        mapped_cells,
    )


def _get_or_create_event_type(
    conn: sqlite3.Connection,
    name: str,
) -> int:
    """Resolve a curtailment or compliance event type."""

    category = "curtailment" if "curtailment" in name else "grid_compliance"
    conn.execute(
        """
        INSERT OR IGNORE INTO DimEventTypes(EventTypeName, EventCategory)
        VALUES (?, ?)
        """,
        (name, category),
    )
    return int(conn.execute(
        "SELECT EventTypeID FROM DimEventTypes WHERE EventTypeName = ?", (name,)
    ).fetchone()[0])


def _insert_operational_event(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    state_id: int,
    event_name: str,
    event_mw: float | None,
    event_mu: float | None,
    occurrence_count: int | None,
    reason: str | None,
    details: str | None,
) -> int:
    """Insert one operational observation and return its event key."""

    event_type_id = _get_or_create_event_type(conn, event_name)
    cursor = conn.execute(
        """
        INSERT INTO FactSRLDCOperationalEvent(
            ReportDocumentID, DateID, EventTypeID, StateID, EventText,
            OccurrenceCount, EventMW, EventMU, ReasonText, DetailsText
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id, date_id, event_type_id, state_id,
            event_name.replace("_", " "), occurrence_count,
            event_mw, event_mu, reason, details,
        ),
    )
    return int(cursor.lastrowid)


def _table_rows(
    conn: sqlite3.Connection,
    report_id: int,
    page_no: int,
    table_no: int,
) -> list[dict[int, tuple[int, str]]]:
    """Return every raw row from one extracted PDF table."""

    row_numbers = conn.execute(
        """
        SELECT DISTINCT row_no FROM psp_raw_cell
        WHERE report_document_id = ? AND page_no = ? AND table_no = ?
        ORDER BY row_no
        """,
        (report_id, page_no, table_no),
    ).fetchall()
    return [
        _table_row(conn, report_id, page_no, table_no, int(row[0]))
        for row in row_numbers
    ]


def _table_rows_for_window(
    conn: sqlite3.Connection,
    report_id: int,
    window: RowWindow,
) -> list[dict[int, tuple[int, str]]]:
    """Return raw rows constrained to a configured row window."""

    rows = _table_rows(conn, report_id, window.page_no, window.table_no)
    start_index = max(window.start_row - 1, 0)
    if window.end_row is None:
        return rows[start_index:]
    return rows[start_index:window.end_row]


def _initial_generation_source(section_name: str) -> str | None:
    """Return the starting source bucket for a generation table section."""

    if section_name == "regional_renewable_wind":
        return "Wind"
    if section_name == "regional_renewable_solar":
        return "Solar"
    if section_name == "regional_bess":
        return "Others"
    if section_name.startswith("state_") or section_name in {
        "regional_generation", "regional_generation_totals",
    }:
        return "Thermal"
    return None


def _classify_generation_source(
    entity_name: str,
    section_name: str,
    current_source_name: str | None,
) -> tuple[str, str | None]:
    """Classify a generation row using explicit labels and table-order context."""

    normalized = entity_name.lower()
    explicit_source: str | None
    if normalized.startswith("total thermal"):
        explicit_source = "Thermal"
    elif normalized.startswith("total hydro"):
        explicit_source = "Hydro"
    elif normalized.startswith("total gas") or normalized.startswith("total gas,"):
        explicit_source = "Gas, Naptha & Diesel"
    elif normalized.startswith("total nuclear"):
        explicit_source = "Nuclear"
    elif normalized.startswith("total wind"):
        explicit_source = "Wind"
    elif normalized.startswith("total solar"):
        explicit_source = "Solar"
    elif normalized.startswith("total ") and "state" in normalized:
        explicit_source = "Total"
    elif "thermal" in normalized or any(
        token in normalized for token in ("tps", "stps", "ntpc", "il&fs")
    ):
        explicit_source = "Thermal"
    elif "hydro" in normalized or any(
        token in normalized for token in ("hydel", "dam", "hep", "h.e.p")
    ):
        explicit_source = "Hydro"
    elif "gas" in normalized or "naptha" in normalized or "diesel" in normalized:
        explicit_source = "Gas, Naptha & Diesel"
    elif "wind" in normalized or normalized.endswith("_w"):
        explicit_source = "Wind"
    elif "solar" in normalized or normalized.endswith("_s"):
        explicit_source = "Solar"
    elif "nuclear" in normalized:
        explicit_source = "Nuclear"
    elif "bess" in normalized:
        explicit_source = "Others"
    else:
        explicit_source = current_source_name or _initial_generation_source(section_name)
    next_source_name = current_source_name
    if normalized.startswith("total ") and explicit_source in GENERATION_SOURCE_SEQUENCE:
        next_source_name = _next_generation_source(explicit_source)
    elif explicit_source is not None:
        next_source_name = explicit_source
    return explicit_source or "Others", next_source_name


def _next_generation_source(source_name: str) -> str | None:
    """Advance to the next expected source bucket after a subtotal row."""

    try:
        index = GENERATION_SOURCE_SEQUENCE.index(source_name)
    except ValueError:
        return None
    if index + 1 >= len(GENERATION_SOURCE_SEQUENCE):
        return None
    return GENERATION_SOURCE_SEQUENCE[index + 1]


def _lookup_generation_source_id(
    conn: sqlite3.Connection, source_name: str | None
) -> int | None:
    """Resolve a generation source name to its dimension identifier."""

    if source_name is None:
        return None
    return _lookup_id(
        conn,
        "SELECT GenerationSourceID FROM DimGenerationSources WHERE SourceName = ?",
        (source_name,),
    )


def _get_or_create_grid_entity(
    conn: sqlite3.Connection,
    name: str,
    entity_type: str,
    state_id: int | None,
    region_id: int,
    generation_source_id: int | None,
    capacity_mw: float,
    is_aggregate: bool,
    identity: GenerationIdentity,
) -> int:
    """Resolve a canonical generation entity without duplicating NULL-state rows."""

    row = conn.execute(
        """
        SELECT EntityID FROM DimGridEntities
        WHERE EntityName = ? AND EntityType = ? AND StateID IS ? AND RegionID = ?
        """,
        (name, entity_type, state_id, region_id),
    ).fetchone()
    if row:
        entity_id = int(row[0])
        conn.execute(
            """
            UPDATE DimGridEntities
            SET GenerationSourceID = ?, InstalledCapacityMW = ?, IsAggregate = ?,
                StationID = ?, GeneratingUnitID = ?, AggregateID = ?
            WHERE EntityID = ?
            """,
            (
                generation_source_id, capacity_mw, int(is_aggregate),
                identity.station_id, identity.generating_unit_id,
                identity.aggregate_id, entity_id,
            ),
        )
        return entity_id
    cursor = conn.execute(
        """
        INSERT INTO DimGridEntities(
            EntityName, EntityType, StateID, RegionID, GenerationSourceID,
            InstalledCapacityMW, IsAggregate, StationID, GeneratingUnitID,
            AggregateID
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name, entity_type, state_id, region_id, generation_source_id,
            capacity_mw, int(is_aggregate), identity.station_id,
            identity.generating_unit_id, identity.aggregate_id,
        ),
    )
    return int(cursor.lastrowid)


def _get_or_create_voltage_node(
    conn: sqlite3.Connection,
    name: str,
    nominal_kv: float,
    region_id: int,
) -> int:
    """Resolve a voltage monitoring node."""

    state_id = _state_id(conn, voltage_node_state_name(name))
    conn.execute(
        """
        INSERT OR IGNORE INTO DimVoltageNodes(
            NodeName, NominalVoltageKV, StateID, RegionID
        ) VALUES (?, ?, ?, ?)
        """,
        (name, nominal_kv, state_id, region_id),
    )
    conn.execute(
        """
        UPDATE DimVoltageNodes
        SET StateID = COALESCE(StateID, ?),
            RegionID = COALESCE(RegionID, ?)
        WHERE NodeName = ? AND NominalVoltageKV = ?
        """,
        (state_id, region_id, name, nominal_kv),
    )
    return int(conn.execute(
        """
        SELECT VoltageNodeID FROM DimVoltageNodes
        WHERE NodeName = ? AND NominalVoltageKV = ?
        """,
        (name, nominal_kv),
    ).fetchone()[0])


def _get_or_create_reservoir(
    conn: sqlite3.Connection,
    name: str,
    region_id: int,
) -> int:
    """Resolve a reservoir dimension row."""

    state_id = _state_id(conn, reservoir_state_name(name))
    conn.execute(
        """
        INSERT OR IGNORE INTO DimReservoirs(ReservoirName, StateID, RegionID)
        VALUES (?, ?, ?)
        """,
        (name, state_id, region_id),
    )
    conn.execute(
        """
        UPDATE DimReservoirs
        SET StateID = COALESCE(StateID, ?),
            RegionID = COALESCE(RegionID, ?)
        WHERE ReservoirName = ?
        """,
        (state_id, region_id, name),
    )
    return int(conn.execute(
        "SELECT ReservoirID FROM DimReservoirs WHERE ReservoirName = ?", (name,)
    ).fetchone()[0])


def _insert_lineage(
    conn: sqlite3.Connection,
    report_id: int,
    table: str,
    key: str,
    column: str,
    raw_cell_id: int,
    mapped_cells: set[int],
) -> None:
    """Insert one field-level lineage edge."""

    conn.execute(
        """
        INSERT OR IGNORE INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn,
            RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES (?, ?, ?, ?, ?, 'pdfplumber', 1.0, ?)
        """,
        (report_id, table, key, column, raw_cell_id, datetime.now(timezone.utc).isoformat()),
    )
    mapped_cells.add(raw_cell_id)


def _state_id(conn: sqlite3.Connection, state_name: str | None) -> int | None:
    """Resolve a Southern Region state using normalized aliases."""

    if not state_name:
        return None
    try:
        return resolve_state_id(conn, "srldc", state_name)
    except DimensionResolutionError:
        return _lookup_id(
            conn, "SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)
        )


def _region_id(conn: sqlite3.Connection, region_name: str | None) -> int | None:
    """Return a seeded region identifier by canonical region name."""

    if not region_name:
        return None
    return _lookup_id(
        conn, "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (region_name,)
    )


def _lookup_id(conn: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> int | None:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else None


def _cell_float(row: dict[int, tuple[int, str]], col_no: int) -> float | None:
    source = row.get(col_no)
    return _to_float(source[1]) if source else None


def _cell_time(row: dict[int, tuple[int, str]], col_no: int) -> str | None:
    """Return one normalized time from a raw table row."""

    source = row.get(col_no)
    return _normalize_time(source[1]) if source else None


def _to_float(value: str | None) -> float | None:
    """Convert report numeric text while preserving published blanks."""

    if value is None:
        return None
    text = value.strip().replace(",", "").replace("−", "-")
    if not text or text.lower() in {"-", "--", "nil", "na", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_time(value: str | None) -> str | None:
    """Normalize report times to HH:MM:SS."""

    if not value:
        return None
    text = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        return f"{text}:00"
    if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", text):
        return text
    return None
