"""Promote verified flattened ERLDC PSP sections into curated SQLite facts."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
import sqlite3

from psp_pipeline.storage.sqlite_dimensions import (
    DimensionResolutionError,
    record_resolution_issue,
    resolve_generation_identity,
)
from psp_pipeline.storage.sqlite_erldc_enrichment import (
    generation_entity_state_name,
    reservoir_location,
    transmission_location,
    voltage_node_location,
)
from psp_pipeline.parsing.layout_resolution import (
    LayoutResolution,
    resolve_exclusive_layouts,
    resolve_header_layout,
)
from psp_pipeline.parsing.rldc.spatial_rows import (
    SpatialTextItem,
    reconstruct_generation_rows,
)
from psp_pipeline.quality.promotion_quarantine import record_promotion_quarantine


ERLDC_FLAT_TEMPLATE_IDS = frozenset({
    "erldc_daily_psp_v2023_flat_09_column_generation",
    "erldc_daily_psp_v2024_flat_09_column_generation",
    "erldc_daily_psp_v2025_flat_11_column_generation",
})
ERLDC_SPLIT_TEMPLATE_IDS = frozenset({
    "erldc_daily_psp_v2024_split_11_column_generation",
    "erldc_daily_psp_v2025_split_11_column_generation",
})
_STATE_ALIASES = {
    "WESTBENGAL": "West Bengal",
    "ODISHA": "Odisha",
    "BIHAR": "Bihar",
    "JHARKHAND": "Jharkhand",
    "SIKKIM": "Sikkim",
    "DVC": "DVC",
}
_ERLDC_MARKET_GEOGRAPHIC_LABELS = frozenset({
    "BIHAR",
    "JHARKHAND",
    "ODISHA",
    "SIKKIM",
    "WESTBENGAL",
})
_ERLDC_MARKET_PARTICIPANT_ALIASES = {
    "RAILWAYSERISTS": "Railways_ER ISTS",
}
_ERLDC_REGIONAL_GENERATION_SPATIAL_CENTERS = {
    "InstalledCapacityMW": 157.9,
    "EveningPeakMW": 209.7,
    "OffPeakMW": 261.4,
    "DayPeakMW": 311.6,
    "DayPeakTime": 359.8,
    "MinimumGenerationMW": 408.6,
    "MinimumGenerationTime": 456.9,
    "ScheduledEnergyMU": 504.0,
    "GrossEnergyMU": 546.1,
    "NetEnergyMU": 588.2,
    "AverageMW": 629.7,
}
_ERLDC_MARKET_EXTREMA_SPATIAL_TABLES = (
    (
        (320.0, 455.0),
        {
            "GNAScheduleMaximumMW": 76.0,
            "GNAScheduleMinimumMW": 118.0,
            "TGNABilateralMaximumMW": 172.0,
            "TGNABilateralMinimumMW": 214.0,
            "IEXGDAMMaximumMW": 249.0,
            "IEXGDAMMinimumMW": 298.0,
            "PXILGDAMMaximumMW": 340.0,
            "PXILGDAMMinimumMW": 382.0,
            "HPXGDAMMaximumMW": 424.0,
            "HPXGDAMMinimumMW": 466.0,
            "IEXDAMMaximumMW": 501.0,
            "IEXDAMMinimumMW": 540.0,
            "PXILDAMMaximumMW": 592.0,
            "PXILDAMMinimumMW": 634.0,
        },
    ),
    (
        (455.0, 575.0),
        {
            "HPXDAMMaximumMW": 88.0,
            "HPXDAMMinimumMW": 130.0,
            "IEXHPDAMMaximumMW": 172.0,
            "IEXHPDAMMinimumMW": 214.0,
            "PXILHPDAMMaximumMW": 256.0,
            "PXILHPDAMMinimumMW": 298.0,
            "HPXHPDAMMaximumMW": 340.0,
            "HPXHPDAMMinimumMW": 382.0,
            "IEXRTMMaximumMW": 417.0,
            "IEXRTMMinimumMW": 458.0,
            "PXILRTMMaximumMW": 508.0,
            "PXILRTMMinimumMW": 550.0,
        },
    ),
)

_ERLDC_REGIONAL_HEADER_TOKENS = {
    "EveningPeakDemandMetMW": ("evening", "peak", "demand", "met"),
    "OffPeakDemandMetMW": ("off", "peak", "demand", "met"),
    "DayEnergyMetMU": ("day", "energy", "met"),
}
_ERLDC_REGIONAL_COMPACT = {
    "EveningPeakDemandMetMW": 1,
    "OffPeakDemandMetMW": 2,
    "DayEnergyMetMU": 3,
}
_ERLDC_REGIONAL_WIDE = {
    "EveningPeakDemandMetMW": 1,
    "OffPeakDemandMetMW": 6,
    "DayEnergyMetMU": 12,
}
_ERLDC_STATE_HEADER_TOKENS = {
    "ThermalGenerationMU": ("thermal",),
    "HydroGenerationMU": ("hydro",),
    "TotalGenerationMU": ("total",),
    "RequirementMU": ("req",),
    "ConsumptionMU": ("cons",),
}
_ERLDC_STATE_COMPACT = {
    "ThermalGenerationMU": 2,
    "HydroGenerationMU": 3,
    "TotalGenerationMU": 4,
    "RequirementMU": 5,
    "ConsumptionMU": 6,
}
_ERLDC_STATE_WIDE = {
    "ThermalGenerationMU": 2,
    "HydroGenerationMU": 3,
    "TotalGenerationMU": 7,
    "RequirementMU": 15,
    "ConsumptionMU": 18,
}
_ERLDC_GENERATION_HEADER_TOKENS = {
    "GrossEnergyMU": ("gross",),
    "NetEnergyMU": ("net",),
    "AverageMW": ("avg",),
}
_ERLDC_GENERATION_COMPACT = {
    "GrossEnergyMU": 3,
    "NetEnergyMU": 4,
    "AverageMW": 5,
}
_ERLDC_GENERATION_WIDE = {
    "GrossEnergyMU": 7,
    "NetEnergyMU": 8,
    "AverageMW": 9,
}
_ERLDC_FREQUENCY_COMPACT = {
    "MaximumFrequencyHz": 1,
    "MinimumFrequencyHz": 4,
    "AverageFrequencyHz": 8,
    "FrequencyVariationIndex": 10,
    "StandardDeviationHz": 12,
    "Maximum15MinuteBlockFrequencyHz": 14,
    "Minimum15MinuteBlockFrequencyHz": 17,
}
_ERLDC_FREQUENCY_WIDE = {
    "MaximumFrequencyHz": 1,
    "MinimumFrequencyHz": 6,
    "AverageFrequencyHz": 12,
    "FrequencyVariationIndex": 16,
    "StandardDeviationHz": 20,
    "Maximum15MinuteBlockFrequencyHz": 23,
    "Minimum15MinuteBlockFrequencyHz": 27,
}

logger = logging.getLogger(__name__)


def promote_erldc_report_to_curated(conn: sqlite3.Connection, report_id: int) -> None:
    """Promote verified ERLDC PSP sections with raw-cell lineage.

    Split-table layouts promote their stable Page 1 regional and state tables
    plus generation, frequency, reservoir, voltage, and exchange sections when
    those tables match a fixture-backed contract. Market day-energy and extrema
    are promoted for every approved flat and split family after a complete
    header match. HPX RTM stays outside the extrema contract when both columns
    are labeled ``Minimum``. Nepal line-detail remains out of scope.
    """
    report = conn.execute(
        "SELECT rldc, report_date, template_id, semantic_pass_required "
        "FROM psp_report_document WHERE id = ?",
        (report_id,),
    ).fetchone()
    if (
        not report
        or report[0] != "erldc"
        or report[3]
        or report[2] not in ERLDC_FLAT_TEMPLATE_IDS | ERLDC_SPLIT_TEMPLATE_IDS
    ):
        return
    date_id = _date_id(conn, str(report[1]))
    region = conn.execute("SELECT RegionID FROM DimRegions WHERE RegionName = 'Eastern Region'").fetchone()
    if date_id is None or not region:
        return
    conn.execute("DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?", (report_id,))
    for table in (
        "FactERLDCRegionalDaily",
        "FactERLDCStateDaily",
        "FactERLDCGenerationDaily",
        "FactERLDCFrequencyDaily",
        "FactERLDCReservoirDaily",
        "FactERLDCVoltageProfile",
        "FactERLDCInterRegionalExchange",
        "FactERLDCInternationalExchange",
        "FactERLDCMarketEnergyDaily",
        "FactERLDCMarketExtremaDaily",
    ):
        conn.execute(f"DELETE FROM {table} WHERE ReportDocumentID = ?", (report_id,))
    if report[2] in ERLDC_SPLIT_TEMPLATE_IDS:
        _split_regional(conn, report_id, date_id, int(region[0]))
        _split_states(conn, report_id, date_id)
        _split_generation(conn, report_id, date_id, int(region[0]))
        _split_frequency(conn, report_id, date_id, int(region[0]))
        _split_reservoirs(conn, report_id, date_id, int(region[0]))
        _split_voltage_and_exchanges(conn, report_id, date_id, int(region[0]))
        _promote_market_sections(conn, report_id, date_id)
        return
    _regional(conn, report_id, date_id, int(region[0]))
    _states(conn, report_id, date_id)
    if report[2] == "erldc_daily_psp_v2025_flat_11_column_generation":
        _promote_2025_flat_state_generation(
            conn,
            report_id,
            date_id,
            int(region[0]),
        )
        _promote_2025_flat_regional_generation(
            conn,
            report_id,
            date_id,
            int(region[0]),
        )
    else:
        _generation(conn, report_id, date_id, int(region[0]))
    _frequency(conn, report_id, date_id, int(region[0]))
    _reservoirs(conn, report_id, date_id, int(region[0]))
    if report[2] == "erldc_daily_psp_v2025_flat_11_column_generation":
        _promote_2025_flat_operational_sections(
            conn,
            report_id,
            date_id,
            int(region[0]),
        )
    else:
        _voltage_and_exchanges(conn, report_id, date_id, int(region[0]))
    _promote_market_sections(conn, report_id, date_id)


def _date_id(conn: sqlite3.Connection, value: str) -> int | None:
    conn.execute("INSERT OR IGNORE INTO DimDates(ActualDate) VALUES (?)", (value,))
    row = conn.execute("SELECT DateID FROM DimDates WHERE ActualDate = ?", (value,)).fetchone()
    return int(row[0]) if row else None


def _rows(
    conn: sqlite3.Connection,
    report_id: int,
    page: int,
    table: int = 1,
) -> list[dict[int, tuple[int, str]]]:
    result: dict[int, dict[int, tuple[int, str]]] = {}
    table_name = "psp_raw_cell"
    has_cell = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_raw_cell'"
    ).fetchone()
    if has_cell:
        query = (
            "SELECT id, row_no, col_no, cell_text FROM psp_raw_cell "
            "WHERE report_document_id = ? AND page_no = ? AND table_no = ? "
            "ORDER BY row_no, col_no"
        )
    else:
        query = (
            "SELECT id, RowIndex, ColumnIndex, CellText FROM psp_raw_table_cell "
            "WHERE ReportDocumentID = ? AND PageNumber = ? AND TableIndex = ? "
            "ORDER BY RowIndex, ColumnIndex"
        )
    for raw_id, row, col, text in conn.execute(query, (report_id, page, table)):
        result.setdefault(int(row), {})[int(col)] = (int(raw_id), str(text or ""))
    return [result[key] for key in sorted(result)]


def _number(row: dict[int, tuple[int, str]], col: int) -> tuple[float | None, int | None]:
    raw = row.get(col)
    if not raw:
        return None, None
    try:
        return float(raw[1].replace(",", "").strip()), raw[0]
    except ValueError:
        return None, None


def _lineage(conn: sqlite3.Connection, report: int, table: str, key: str, sources: dict[str, int]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for column, raw_id in sources.items():
        conn.execute("INSERT OR IGNORE INTO curated_field_lineage(ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt) VALUES (?, ?, ?, ?, ?, 'pdfplumber', 1.0, ?)", (report, table, key, column, raw_id, now))


def _quarantine_layout(
    conn: sqlite3.Connection,
    report: int,
    *,
    section: str,
    resolution: LayoutResolution,
    columns: list[int],
) -> None:
    """Hold an extract whose layout is ambiguous or outside fixture signatures."""

    logger.warning(
        "erldc_layout_%s section=%s report_id=%s layout=%s columns=%s",
        resolution.status,
        section,
        report,
        resolution.layout_id,
        columns,
    )
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'promotion_quarantine'"
    ).fetchone()
    if not has_table:
        return
    record_promotion_quarantine(
        conn,
        report_document_id=report,
        source_id="erldc",
        stage="layout_resolution",
        reason_code=resolution.quarantine_reason or "unsupported_layout",
        details={
            "section": section,
            "status": resolution.status,
            "layout_id": resolution.layout_id,
            "evidence": resolution.evidence,
            "columns": columns,
        },
    )


def _spatial_lineage(
    conn: sqlite3.Connection,
    report: int,
    table: str,
    key: str,
    sources: dict[str, int],
) -> None:
    """Record LiteParse text-item provenance for reconstructed measurements."""

    now = datetime.now(timezone.utc).isoformat()
    for column, raw_text_item_id in sources.items():
        conn.execute(
            "INSERT OR IGNORE INTO curated_field_lineage("
            "ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn, "
            "RawTextItemID, ExtractionMethod, Confidence, CreatedAt"
            ") VALUES (?, ?, ?, ?, ?, 'liteparse', 1.0, ?)",
            (report, table, key, column, raw_text_item_id, now),
        )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return whether an optional raw staging table is available."""

    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _regional(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    """Promote the Page 1 flattened regional demand and energy summary."""

    rows = _rows(conn, report, 1)
    if len(rows) < 4:
        return
    row = rows[3]
    resolution = _flat_regional_fields(rows[:3], row)
    if not resolution.resolved or not resolution.mapping:
        _quarantine_layout(
            conn,
            report,
            section="regional_summary",
            resolution=resolution,
            columns=sorted(row),
        )
        return
    _insert_regional_values(conn, report, date_id, region_id, row, resolution.mapping)


def _flat_regional_fields(
    header_rows: list[dict[int, tuple[int, str]]],
    data_row: dict[int, tuple[int, str]],
) -> LayoutResolution:
    """Resolve regional summary columns without relying on a row's width.

    Published labels are authoritative when every headline field binds.
    Otherwise the compact ``1,2,3`` and wide ``1,6,12`` signatures are chosen
    only by exclusive numeric occupancy. A label-less row that satisfies both
    is quarantined instead of guessed.
    """

    header = resolve_header_layout(
        header_rows,
        _ERLDC_REGIONAL_HEADER_TOKENS,
        layout_id="header",
    )
    if header.resolved:
        return header
    return resolve_exclusive_layouts(
        layouts={"compact": _ERLDC_REGIONAL_COMPACT, "wide": _ERLDC_REGIONAL_WIDE},
        exclusive_columns={
            "compact": frozenset({2, 3}),
            "wide": frozenset({6, 12}),
        },
        populated=lambda column: _number(data_row, column)[0] is not None,
    )


def _split_regional(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote the stable Page 1 split-layout regional summary table."""
    rows = _rows(conn, report, 1, table=1)
    fields = {
        "EveningPeakDemandMetMW": 1,
        "EveningPeakShortageMW": 2,
        "EveningPeakRequirementMW": 3,
        "EveningPeakFrequencyHz": 4,
        "OffPeakDemandMetMW": 5,
        "OffPeakShortageMW": 6,
        "OffPeakRequirementMW": 7,
        "OffPeakFrequencyHz": 8,
        "DayEnergyMetMU": 9,
        "DayEnergyShortageMU": 10,
    }
    for row in rows:
        if sum(_number(row, col)[0] is not None for col in fields.values()) >= 3:
            _insert_regional_values(conn, report, date_id, region_id, row, fields)
            return


def _insert_regional_values(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
    row: dict[int, tuple[int, str]],
    fields: dict[str, int],
) -> None:
    """Write a regional fact row and its raw-cell lineage."""
    values: dict[str, float] = {}
    sources: dict[str, int] = {}
    for name, col in fields.items():
        value, raw = _number(row, col)
        if value is not None:
            values[name] = value
        if raw is not None:
            sources[name] = raw
    if not values:
        return
    names = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        "INSERT OR REPLACE INTO FactERLDCRegionalDaily("
        f"ReportDocumentID, DateID, RegionID, {names}) VALUES (?, ?, ?, {placeholders})",
        (report, date_id, region_id, *values.values()),
    )
    _lineage(
        conn,
        report,
        "FactERLDCRegionalDaily",
        f"report={report};date={date_id};region={region_id}",
        sources,
    )


def _states(conn: sqlite3.Connection, report: int, date_id: int) -> None:
    rows = _rows(conn, report, 1)
    header = resolve_header_layout(rows, _ERLDC_STATE_HEADER_TOKENS, layout_id="header")
    quarantined = False
    for row in rows:
        label = row.get(1, (0, ""))[1].replace(" ", "").upper()
        state_name = _STATE_ALIASES.get(label)
        if not state_name:
            continue
        state = conn.execute("SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)).fetchone()
        if not state:
            continue
        if header.resolved and header.mapping:
            columns = header.mapping
        else:
            resolution = resolve_exclusive_layouts(
                layouts={"compact": _ERLDC_STATE_COMPACT, "wide": _ERLDC_STATE_WIDE},
                exclusive_columns={
                    "compact": frozenset({4, 5, 6}),
                    "wide": frozenset({7, 15, 18}),
                },
                populated=lambda column, current=row: _number(current, column)[0] is not None,
                default_layout_id="compact",
            )
            if not resolution.resolved or not resolution.mapping:
                if not quarantined:
                    _quarantine_layout(
                        conn,
                        report,
                        section="state_energy",
                        resolution=resolution,
                        columns=sorted(row),
                    )
                    quarantined = True
                continue
            columns = resolution.mapping
        values, sources = {}, {}
        for name, col in columns.items():
            value, raw = _number(row, col)
            if value is not None: values[name] = value
            if raw: sources[name] = raw
        if not values: continue
        names = ", ".join(values)
        conn.execute(
            f"INSERT OR REPLACE INTO FactERLDCStateDaily(ReportDocumentID, DateID, StateID, {names}) "
            f"VALUES (?, ?, ?, {', '.join('?' for _ in values)})",
            (report, date_id, state[0], *values.values()),
        )
        _lineage(conn, report, "FactERLDCStateDaily", f"report={report};date={date_id};state={state[0]}", sources)


def _split_states(conn: sqlite3.Connection, report: int, date_id: int) -> None:
    """Promote the stable Page 1 split-layout state energy-balance table."""
    fields = {
        "ThermalGenerationMU": 2,
        "HydroGenerationMU": 3,
        "GasNapthaDieselGenerationMU": 4,
        "RenewableGenerationMU": 5,
        "OtherGenerationMU": 6,
        "TotalGenerationMU": 7,
        "ScheduledDrawalMU": 9,
        "ActualDrawalMU": 10,
        "UIMU": 11,
        "TotalAvailabilityMU": 12,
        "RequirementMU": 13,
        "EnergyShortageMU": 14,
        "ConsumptionMU": 15,
    }
    for row in _rows(conn, report, 1, table=2):
        label = row.get(1, (0, ""))[1].replace(" ", "").upper()
        state_name = _STATE_ALIASES.get(label)
        if not state_name:
            continue
        state = conn.execute(
            "SELECT StateID FROM DimStates WHERE StateName = ?",
            (state_name,),
        ).fetchone()
        if not state:
            continue
        values: dict[str, float] = {}
        sources: dict[str, int] = {}
        for name, col in fields.items():
            value, raw = _number(row, col)
            if value is not None:
                values[name] = value
            if raw is not None:
                sources[name] = raw
        if not values:
            continue
        names = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        conn.execute(
            "INSERT OR REPLACE INTO FactERLDCStateDaily("
            f"ReportDocumentID, DateID, StateID, {names}) VALUES (?, ?, ?, {placeholders})",
            (report, date_id, state[0], *values.values()),
        )
        _lineage(
            conn,
            report,
            "FactERLDCStateDaily",
            f"report={report};date={date_id};state={state[0]}",
            sources,
        )


def _split_generation(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote verified 11-column state-generation tables across page breaks."""
    columns = {
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
    current_state_id: int | None = None
    for page in range(2, 5):
        for table in _table_numbers(conn, report, page):
            rows = _rows(conn, report, page, table)
            has_station_header = any(
                "station/constituents" in row.get(1, (0, ""))[1].lower()
                for row in rows
            )
            if _is_scheduled_regional_generation_table(rows):
                continue
            if not has_station_header and current_state_id is None:
                continue
            for row in rows:
                label_cell = row.get(1)
                label = label_cell[1].strip() if label_cell else ""
                state_id = _state_id(conn, label)
                capacity, capacity_raw = _number(row, columns["InstalledCapacityMW"])
                if state_id is not None and capacity is None:
                    current_state_id = state_id
                    continue
                if current_state_id is None or capacity is None or not label:
                    continue
                if _is_generation_header(label):
                    continue
                values: dict[str, float | str] = {"InstalledCapacityMW": capacity}
                sources: dict[str, int] = {
                    "InstalledCapacityMW": capacity_raw,
                }
                for field, column in columns.items():
                    if field == "InstalledCapacityMW":
                        continue
                    if field in {"DayPeakTime", "MinimumGenerationTime"}:
                        raw = row.get(column)
                        value = _time(raw[1]) if raw else None
                        raw_id = raw[0] if raw else None
                    else:
                        value, raw_id = _number(row, column)
                    if value is not None:
                        values[field] = value
                    if raw_id is not None:
                        sources[field] = raw_id
                is_total = _is_total_generation_row(label)
                try:
                    identity = resolve_generation_identity(
                        conn,
                        "erldc",
                        label,
                        current_state_id,
                        region_id,
                        None,
                        capacity,
                        is_total,
                    )
                except DimensionResolutionError as error:
                    record_resolution_issue(
                        conn,
                        report,
                        "erldc",
                        "generation_entity",
                        label,
                        str(error),
                    )
                    continue
                entity_id = _get_or_create_grid_entity(
                    conn,
                    label,
                    "generation_aggregate" if is_total else "generating_entity",
                    current_state_id,
                    region_id,
                    None,
                    capacity,
                    is_total,
                    identity,
                )
                section = f"state_generation_{current_state_id}"
                field_names = ", ".join(values)
                placeholders = ", ".join("?" for _ in values)
                conn.execute(
                    "INSERT OR REPLACE INTO FactERLDCGenerationDaily("
                    "ReportDocumentID, DateID, EntityID, StateID, StationID, "
                    "GeneratingUnitID, AggregateID, IsTotalRow, GenerationGrain, "
                    f"SectionName, {field_names}) "
                    f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {placeholders})",
                    (
                        report,
                        date_id,
                        entity_id,
                        current_state_id,
                        identity.station_id,
                        identity.generating_unit_id,
                        identity.aggregate_id,
                        int(is_total),
                        identity.entity_type,
                        section,
                        *values.values(),
                    ),
                )
                key = (
                    f"report={report};date={date_id};entity={entity_id};"
                    f"section={section}"
                )
                _lineage(conn, report, "FactERLDCGenerationDaily", key, sources)
                _validate_generation_average(conn, report, label, values)


def _table_numbers(conn: sqlite3.Connection, report: int, page: int) -> list[int]:
    """Return source table numbers in their published page order."""
    table_name = "psp_raw_cell"
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone():
        query = (
            "SELECT DISTINCT table_no FROM psp_raw_cell "
            "WHERE report_document_id = ? AND page_no = ? ORDER BY table_no"
        )
    else:
        query = (
            "SELECT DISTINCT TableIndex FROM psp_raw_table_cell "
            "WHERE ReportDocumentID = ? AND PageNumber = ? ORDER BY TableIndex"
        )
    return [int(row[0]) for row in conn.execute(query, (report, page))]


def _state_id(conn: sqlite3.Connection, label: str) -> int | None:
    """Resolve an ERLDC state heading without fuzzy matching."""
    normalized = re.sub(r"\s+", "", label).upper()
    state_name = _STATE_ALIASES.get(normalized)
    if state_name is None:
        return None
    row = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _is_generation_header(label: str) -> bool:
    """Return whether a label is a published table heading rather than an entity."""
    normalized = re.sub(r"\s+", "", label).lower()
    return normalized in {"station/constituents", "station", "constituents"}


def _is_scheduled_regional_generation_table(
    rows: list[dict[int, tuple[int, str]]],
) -> bool:
    """Identify the separate 12-column regional schedule/generation section.

    Its schedule column shifts gross, net, and average fields one position and
    its entities are not state-owned rows. It is promoted only after a separate
    regional-generation contract is verified.
    """
    return any(
        "schd(mu)" in row.get(9, (0, ""))[1].replace(" ", "").lower()
        for row in rows[:3]
    )


def _is_total_generation_row(label: str) -> bool:
    """Return whether the publisher labels a generation row as an aggregate."""
    normalized = re.sub(r"\s+", "", label).lower()
    return normalized.startswith(("total", "sub-total", "subtotal"))


def _time(value: str) -> str | None:
    """Return a published HH:MM value when the cell contains one."""
    match = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", value)
    return match.group(0) if match else None


def _get_or_create_grid_entity(*args: object, **kwargs: object) -> int:
    """Reuse the shared canonical grid-entity dimension implementation."""
    from psp_pipeline.storage.sqlite_curated_promoter import (
        _get_or_create_grid_entity as resolver,
    )

    return resolver(*args, **kwargs)


def _validate_generation_average(
    conn: sqlite3.Connection,
    report: int,
    label: str,
    values: dict[str, float | str],
) -> None:
    """Record, without changing source data, a material net-energy mismatch."""
    net_energy = values.get("NetEnergyMU")
    average_mw = values.get("AverageMW")
    if not isinstance(net_energy, float) or not isinstance(average_mw, float):
        return
    expected = net_energy * 1000.0 / 24.0
    if abs(average_mw - expected) <= max(5.0, abs(expected) * 0.01):
        return
    logger.warning(
        "erldc_generation_average_mismatch report_id=%s entity=%s "
        "reported_average_mw=%s expected_average_mw=%.3f",
        report,
        label,
        average_mw,
        expected,
    )


def _split_frequency(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote the compact split-layout frequency-extrema table."""
    for _, _, rows in _all_tables(conn, report):
        if not _has_frequency_signature(rows):
            continue
        for row in rows:
            maximum, maximum_raw = _number(row, 1)
            minimum, minimum_raw = _number(row, 3)
            if not (_is_frequency(maximum) and _is_frequency(minimum)):
                continue
            fields = {
                "MaximumFrequencyHz": (maximum, maximum_raw),
                "MinimumFrequencyHz": (minimum, minimum_raw),
                "AverageFrequencyHz": _number(row, 5),
                "FrequencyVariationIndex": _number(row, 6),
                "StandardDeviationHz": _number(row, 7),
                "Maximum15MinuteBlockFrequencyHz": _number(row, 8),
                "Minimum15MinuteBlockFrequencyHz": _number(row, 9),
            }
            values = {name: value for name, (value, _) in fields.items() if value is not None}
            sources = {name: raw for name, (_, raw) in fields.items() if raw is not None}
            conn.execute(
                "INSERT OR REPLACE INTO FactERLDCFrequencyDaily("
                f"ReportDocumentID, DateID, RegionID, {', '.join(values)}) "
                f"VALUES (?, ?, ?, {', '.join('?' for _ in values)})",
                (report, date_id, region_id, *values.values()),
            )
            _lineage(
                conn,
                report,
                "FactERLDCFrequencyDaily",
                f"report={report};date={date_id};region={region_id}",
                sources,
            )
            return


def _split_reservoirs(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote split-layout reservoir rows using their published header signature."""
    for _, _, rows in _all_tables(conn, report):
        if not _has_reservoir_signature(rows):
            continue
        for row in rows:
            name = row.get(1, (0, ""))[1].strip()
            location = reservoir_location(name)
            if location.evidence == "unverified":
                continue
            fields = {
                "MinimumDrawdownLevelM": _number(row, 2),
                "FullReservoirLevelM": _number(row, 3),
                "DesignedEnergyMU": _number(row, 4),
                "CurrentLevelM": _number(row, 5),
                "CurrentEnergyMU": _number(row, 6),
                "PreviousYearLevelM": _number(row, 7),
                "PreviousYearEnergyMU": _number(row, 8),
                "InflowMU": _number(row, 9),
                "UsageMU": _number(row, 10),
            }
            values = {key: value for key, (value, _) in fields.items() if value is not None}
            sources = {key: raw for key, (_, raw) in fields.items() if raw is not None}
            if not values:
                continue
            state_id = _state_id_by_name(conn, location.state_name)
            conn.execute(
                "INSERT OR IGNORE INTO DimReservoirs(ReservoirName, StateID, RegionID) "
                "VALUES (?, ?, ?)",
                (name, state_id, region_id),
            )
            reservoir = conn.execute(
                "SELECT ReservoirID FROM DimReservoirs WHERE ReservoirName = ?", (name,)
            ).fetchone()
            if reservoir is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO FactERLDCReservoirDaily("
                f"ReportDocumentID, DateID, ReservoirID, {', '.join(values)}) "
                f"VALUES (?, ?, ?, {', '.join('?' for _ in values)})",
                (report, date_id, reservoir[0], *values.values()),
            )
            _lineage(
                conn,
                report,
                "FactERLDCReservoirDaily",
                f"report={report};date={date_id};reservoir={reservoir[0]}",
                sources,
            )


def _split_voltage_and_exchanges(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote exact-match voltage, physical-exchange, and border-exchange facts."""
    for _, _, rows in _all_tables(conn, report):
        if _has_voltage_signature(rows):
            _promote_split_voltage_rows(conn, report, date_id, region_id, rows)
        elif _has_physical_exchange_signature(rows):
            _promote_split_exchange_rows(conn, report, date_id, rows)
        elif _has_international_exchange_signature(rows):
            _promote_split_international_rows(conn, report, date_id, rows)


def _all_tables(
    conn: sqlite3.Connection, report: int
) -> list[tuple[int, int, list[dict[int, tuple[int, str]]]]]:
    """Return every extracted source table in published page/table order."""
    has_production_cells = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_raw_cell'"
    ).fetchone()
    if has_production_cells:
        pages = conn.execute(
            "SELECT DISTINCT page_no FROM psp_raw_cell WHERE report_document_id = ? "
            "ORDER BY page_no",
            (report,),
        ).fetchall()
    else:
        pages = conn.execute(
            "SELECT DISTINCT PageNumber FROM psp_raw_table_cell "
            "WHERE ReportDocumentID = ? ORDER BY PageNumber",
            (report,),
        ).fetchall()
    return [
        (int(page[0]), table, _rows(conn, report, int(page[0]), table))
        for page in pages
        for table in _table_numbers(conn, report, int(page[0]))
    ]


def _has_frequency_signature(rows: list[dict[int, tuple[int, str]]]) -> bool:
    return any(
        "averagefrequency" in _compact_text(row.get(5, (0, ""))[1])
        and "freqvariation" in _compact_text(row.get(6, (0, ""))[1])
        for row in rows[:2]
    )


def _has_reservoir_signature(rows: list[dict[int, tuple[int, str]]]) -> bool:
    return any(
        "reserv" in row.get(1, (0, ""))[1].lower()
        and "designed" in row.get(2, (0, ""))[1].lower()
        and "present" in row.get(5, (0, ""))[1].lower()
        for row in rows[:2]
    )


def _has_voltage_signature(rows: list[dict[int, tuple[int, str]]]) -> bool:
    return any(
        row.get(1, (0, ""))[1].strip().upper() == "STATION"
        and "voltage" in row.get(2, (0, ""))[1].lower()
        for row in rows[:3]
    )


def _has_physical_exchange_signature(rows: list[dict[int, tuple[int, str]]]) -> bool:
    return any(
        row.get(2, (0, ""))[1].strip().lower() == "element"
        and "import" in row.get(7, (0, ""))[1].lower()
        for row in rows[:2]
    )


def _has_international_exchange_signature(rows: list[dict[int, tuple[int, str]]]) -> bool:
    return any(
        "scheduledenergy" in _compact_text(row.get(2, (0, ""))[1])
        and "actualenergy" in _compact_text(row.get(3, (0, ""))[1])
        for row in rows[:2]
    )


def _promote_split_voltage_rows(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
    rows: list[dict[int, tuple[int, str]]],
) -> None:
    for row in rows:
        name = row.get(1, (0, ""))[1].strip()
        location = voltage_node_location(name)
        maximum, maximum_raw = _number(row, 2)
        minimum, minimum_raw = _number(row, 4)
        if location.evidence == "unverified" or maximum is None or minimum is None:
            continue
        match = re.search(r"(\d{3,4})\s*KV", name, re.IGNORECASE)
        if match is None:
            continue
        nominal_kv = float(match.group(1))
        state_id = _state_id_by_name(conn, location.state_name)
        conn.execute(
            "INSERT OR IGNORE INTO DimVoltageNodes("
            "NodeName, NominalVoltageKV, StateID, RegionID) VALUES (?, ?, ?, ?)",
            (name, nominal_kv, state_id, region_id),
        )
        node = conn.execute(
            "SELECT VoltageNodeID FROM DimVoltageNodes WHERE NodeName = ?", (name,)
        ).fetchone()
        if node is None:
            continue
        values = {
            "MaximumKV": maximum,
            "MaximumTime": _time(row.get(3, (0, ""))[1]),
            "MinimumKV": minimum,
            "MinimumTime": _time(row.get(5, (0, ""))[1]),
            "LowCriticalPct": _number(row, 6)[0],
            "IEGCBandPct": _number(row, 7)[0],
            "HighCriticalPct": _number(row, 8)[0],
        }
        conn.execute(
            "INSERT OR REPLACE INTO FactERLDCVoltageProfile("
            "ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV, "
            "MaximumTime, MinimumKV, MinimumTime, LowCriticalPct, IEGCBandPct, "
            "HighCriticalPct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (report, date_id, node[0], nominal_kv, *values.values()),
        )
        _lineage(
            conn,
            report,
            "FactERLDCVoltageProfile",
            f"report={report};date={date_id};node={node[0]}",
            {
                "MaximumKV": maximum_raw,
                "MinimumKV": minimum_raw,
                **{
                    name: raw_id
                    for name, (_, raw_id) in {
                        "LowCriticalPct": _number(row, 6),
                        "IEGCBandPct": _number(row, 7),
                        "HighCriticalPct": _number(row, 8),
                    }.items()
                    if raw_id is not None
                },
            },
        )


def _promote_split_exchange_rows(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    rows: list[dict[int, tuple[int, str]]],
) -> None:
    for row in rows:
        name = row.get(2, (0, ""))[1].strip()
        location = transmission_location(name)
        if location.evidence == "unverified":
            continue
        fields = {
            "EveningPeakMW": _number(row, 3),
            "OffPeakMW": _number(row, 4),
            "MaximumImportMW": _number(row, 5),
            "MaximumExportMW": _number(row, 6),
            "ImportEnergyMU": _number(row, 7),
            "ExportEnergyMU": _number(row, 8),
            "NetEnergyMU": _number(row, 9),
        }
        values = {field: value for field, (value, _) in fields.items() if value is not None}
        if not values:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO DimTransmissionElements("
            "ElementName, ElementType, NominalVoltageKV, FromRegionID, ToRegionID) "
            "VALUES (?, ?, ?, (SELECT RegionID FROM DimRegions WHERE RegionName = ?), "
            "(SELECT RegionID FROM DimRegions WHERE RegionName = ?))",
            (
                name,
                location.element_type,
                location.nominal_voltage_kv,
                location.from_location.region_name,
                location.to_location.region_name,
            ),
        )
        element = conn.execute(
            "SELECT ElementID FROM DimTransmissionElements WHERE ElementName = ?", (name,)
        ).fetchone()
        if element is None:
            continue
        counterparty = location.to_location.region_name or "unknown"
        conn.execute(
            "INSERT OR REPLACE INTO FactERLDCInterRegionalExchange("
            f"ReportDocumentID, DateID, ElementID, CounterpartyRegion, {', '.join(values)}) "
            f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in values)})",
            (report, date_id, element[0], counterparty, *values.values()),
        )
        _lineage(
            conn,
            report,
            "FactERLDCInterRegionalExchange",
            f"report={report};date={date_id};element={element[0]};counterparty={counterparty}",
            {field: raw for field, (_, raw) in fields.items() if raw is not None},
        )


def _promote_split_international_rows(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    rows: list[dict[int, tuple[int, str]]],
) -> None:
    country: str | None = None
    for row in rows:
        label = row.get(1, (0, ""))[1].strip()
        candidate = label.title()
        if candidate in {"Bhutan", "Bangladesh", "Nepal"}:
            country = candidate
        if country is None:
            continue
        fields = {
            "ScheduledEnergyMU": _number(row, 2),
            "ActualEnergyMU": _number(row, 3),
            "DayPeakMW": _number(row, 4),
            "DayMinimumMW": _number(row, 5),
            "AverageMW": _number(row, 6),
        }
        values = {field: value for field, (value, _) in fields.items() if value is not None}
        if not values:
            continue
        conn.execute("INSERT OR IGNORE INTO DimCountries(CountryName) VALUES (?)", (country,))
        country_row = conn.execute(
            "SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country,)
        ).fetchone()
        if country_row is None:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO FactERLDCInternationalExchange("
            f"ReportDocumentID, DateID, CountryID, CounterpartyCountry, {', '.join(values)}) "
            f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in values)})",
            (report, date_id, country_row[0], country, *values.values()),
        )
        _lineage(
            conn,
            report,
            "FactERLDCInternationalExchange",
            f"report={report};date={date_id};country={country_row[0]}",
            {field: raw for field, (_, raw) in fields.items() if raw is not None},
        )


def _state_id_by_name(conn: sqlite3.Connection, state_name: str | None) -> int | None:
    if state_name is None:
        return None
    row = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _is_frequency(value: float | None) -> bool:
    return value is not None and 45.0 <= value <= 55.0


def _compact_text(value: str) -> str:
    """Normalize PDF whitespace for a structural header comparison."""
    return re.sub(r"\s+", "", value).lower()


def _generation(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    rows = _rows(conn, report, 2)
    header = resolve_header_layout(rows, _ERLDC_GENERATION_HEADER_TOKENS, layout_id="header")
    if not header.resolved:
        header = resolve_header_layout(
            rows,
            {
                "GrossEnergyMU": ("gross",),
                "NetEnergyMU": ("net",),
                "AverageMW": ("average",),
            },
            layout_id="header",
        )
    quarantined = False
    for row in rows:
        label = row.get(1, (0, ""))[1].strip()
        capacity, cap_raw = _number(row, 2)
        if not label or capacity is None or label.lower().startswith(("station", "total", "sub-total")):
            continue
        entity = conn.execute("SELECT EntityID FROM DimGridEntities WHERE EntityName = ?", (label,)).fetchone()
        if not entity:
            state_name = generation_entity_state_name(label)
            state_id = None
            if state_name:
                state = conn.execute("SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)).fetchone()
                state_id = state[0] if state else None
            conn.execute("INSERT OR IGNORE INTO DimGridEntities(EntityName, EntityType, StateID, RegionID) VALUES (?, 'power_station', ?, ?)", (label, state_id, region_id))
            entity = conn.execute("SELECT EntityID FROM DimGridEntities WHERE EntityName = ?", (label,)).fetchone()
        if not entity: continue
        if header.resolved and header.mapping:
            columns = header.mapping
        else:
            resolution = resolve_exclusive_layouts(
                layouts={"compact": _ERLDC_GENERATION_COMPACT, "wide": _ERLDC_GENERATION_WIDE},
                exclusive_columns={
                    "compact": frozenset({3, 4, 5}),
                    "wide": frozenset({7, 8, 9}),
                },
                populated=lambda column, current=row: _number(current, column)[0] is not None,
                default_layout_id="compact",
            )
            if not resolution.resolved or not resolution.mapping:
                if not quarantined:
                    _quarantine_layout(
                        conn,
                        report,
                        section="legacy_generation",
                        resolution=resolution,
                        columns=sorted(row),
                    )
                    quarantined = True
                continue
            columns = resolution.mapping
        values, sources = {"InstalledCapacityMW": capacity}, {"InstalledCapacityMW": cap_raw}
        for name, col in columns.items():
            value, raw = _number(row, col)
            if value is not None: values[name] = value
            if raw: sources[name] = raw
        names = ", ".join(values)
        conn.execute(f"INSERT OR REPLACE INTO FactERLDCGenerationDaily(ReportDocumentID, DateID, EntityID, AggregateID, SectionName, {names}) VALUES (?, ?, ?, ?, 'state_generation', {', '.join('?' for _ in values)})", (report, date_id, entity[0], entity[0], *values.values()))
        _lineage(conn, report, "FactERLDCGenerationDaily", f"report={report};date={date_id};entity={entity[0]};section=state_generation", sources)


def _promote_2025_flat_state_generation(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote verified 2025-flat state generation across pages 2 and 3.

    The published family has two state-owned geometries: a compact 11-column
    table on page 2 and a sparse continuation on page 3. Page 3 later changes
    to the separately scheduled regional-entity table, so promotion stops at
    that heading rather than inferring a state for those rows.
    """
    compact_columns = {
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
    sparse_columns = {
        "InstalledCapacityMW": 3,
        "EveningPeakMW": 5,
        "OffPeakMW": 7,
        "DayPeakMW": 9,
        "DayPeakTime": 10,
        "MinimumGenerationMW": 13,
        "MinimumGenerationTime": 15,
        "GrossEnergyMU": 17,
        "NetEnergyMU": 19,
        "AverageMW": 21,
    }
    current_state_id: int | None = None

    for page, columns in ((2, compact_columns), (3, sparse_columns)):
        rows = _rows(conn, report, page)
        for row in rows:
            label = row.get(1, (0, ""))[1].strip()
            normalized_label = _compact_text(label)
            if normalized_label.startswith("3(b)regionalentitiesgeneration"):
                return
            state_id = _state_id(conn, label)
            capacity, _ = _number(row, columns["InstalledCapacityMW"])
            if state_id is not None and capacity is None:
                current_state_id = state_id
                continue
            if (
                current_state_id is None
                or capacity is None
                or not label
                or _is_generation_header(label)
            ):
                continue
            _insert_2025_flat_state_generation(
                conn,
                report,
                date_id,
                region_id,
                current_state_id,
                label,
                row,
                columns,
            )


def _insert_2025_flat_state_generation(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
    state_id: int,
    label: str,
    row: dict[int, tuple[int, str]],
    columns: dict[str, int],
) -> None:
    """Insert one verified 2025-flat state generation row and its lineage."""
    values: dict[str, float | str] = {}
    sources: dict[str, int] = {}
    for field, column in columns.items():
        if field in {"DayPeakTime", "MinimumGenerationTime"}:
            raw = row.get(column)
            value = _time(raw[1]) if raw else None
            raw_id = raw[0] if raw else None
        else:
            value, raw_id = _number(row, column)
        if value is not None:
            values[field] = value
        if raw_id is not None:
            sources[field] = raw_id
    capacity = values.get("InstalledCapacityMW")
    if not isinstance(capacity, float):
        return
    is_total = _is_total_generation_row(label)
    try:
        identity = resolve_generation_identity(
            conn,
            "erldc",
            label,
            state_id,
            region_id,
            None,
            capacity,
            is_total,
        )
    except DimensionResolutionError as error:
        record_resolution_issue(
            conn,
            report,
            "erldc",
            "generation_entity",
            label,
            str(error),
        )
        return
    entity_id = _get_or_create_grid_entity(
        conn,
        label,
        "generation_aggregate" if is_total else "generating_entity",
        state_id,
        region_id,
        None,
        capacity,
        is_total,
        identity,
    )
    section = f"state_generation_{state_id}"
    field_names = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        "INSERT OR REPLACE INTO FactERLDCGenerationDaily("
        "ReportDocumentID, DateID, EntityID, StateID, StationID, "
        "GeneratingUnitID, AggregateID, IsTotalRow, GenerationGrain, "
        f"SectionName, {field_names}) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {placeholders})",
        (
            report,
            date_id,
            entity_id,
            state_id,
            identity.station_id,
            identity.generating_unit_id,
            identity.aggregate_id,
            int(is_total),
            identity.entity_type,
            section,
            *values.values(),
        ),
    )
    key = f"report={report};date={date_id};entity={entity_id};section={section}"
    _lineage(conn, report, "FactERLDCGenerationDaily", key, sources)
    _validate_generation_average(conn, report, label, values)


def _promote_2025_flat_regional_generation(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote 2025-flat regional entities after their exact section heading.

    This is deliberately separate from state generation. The published table
    contains a scheduled-energy measure and reuses aggregate labels beneath
    owner headings, so ``SectionName`` carries that owner context.
    """
    page_three_columns = {
        "InstalledCapacityMW": 2,
        "EveningPeakMW": 4,
        "OffPeakMW": 6,
        "DayPeakMW": 8,
        "DayPeakTime": 11,
        "MinimumGenerationMW": 12,
        "MinimumGenerationTime": 14,
        "ScheduledEnergyMU": 16,
        "GrossEnergyMU": 18,
        "NetEnergyMU": 20,
        "AverageMW": 21,
    }
    page_four_columns = {
        "InstalledCapacityMW": 3,
        "EveningPeakMW": 5,
        "OffPeakMW": 7,
        "DayPeakMW": 10,
        "DayPeakTime": 12,
        "MinimumGenerationMW": 15,
        "MinimumGenerationTime": 16,
        "ScheduledEnergyMU": 20,
        "GrossEnergyMU": 22,
        "NetEnergyMU": 24,
        "AverageMW": 25,
    }
    in_section = False
    owner_group: str | None = None
    for page, columns in ((3, page_three_columns), (4, page_four_columns)):
        for row in _rows(conn, report, page):
            label = row.get(1, (0, ""))[1].strip()
            normalized_label = _compact_text(label)
            if normalized_label.startswith("3(b)regionalentitiesgeneration"):
                in_section = True
                owner_group = None
                continue
            if not in_section:
                continue
            if normalized_label.startswith("4(a)interregionalexchanges"):
                return
            if _is_regional_generation_summary_label(label):
                return
            if _is_generation_header(label) or not label:
                continue
            capacity, _ = _number(row, columns["InstalledCapacityMW"])
            if capacity is None:
                if _looks_like_collapsed_generation_row(label):
                    _promote_2025_flat_spatial_regional_generation_row(
                        conn,
                        report,
                        date_id,
                        region_id,
                        label,
                        owner_group,
                    )
                    continue
                if not _is_total_generation_row(label):
                    owner_group = _regional_owner_key(label)
                continue
            if owner_group is None:
                continue
            _insert_2025_flat_regional_generation(
                conn,
                report,
                date_id,
                region_id,
                label,
                owner_group,
                row,
                columns,
            )


def _is_regional_generation_summary_label(value: str) -> bool:
    """Return whether a Page 4 regional summary closes generation rows.

    These labels share the same sparse columns as station rows but summarize
    the whole regional balance, not an owner-scoped generating asset.  They
    must terminate the owner context before exchange or demand values can be
    mistaken for generation facts.
    """

    normalized = re.sub(r"[^a-z]", "", value.lower())
    return normalized.startswith(
        (
            "totalisgs",
            "totalstate",
            "totalcpp",
            "renewableother",
            "netexchange",
            "regionaltotal",
        )
    )


def _promote_2025_flat_spatial_regional_generation_row(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
    collapsed_label: str,
    owner_group: str | None,
) -> None:
    """Promote one fully reconstructed Page 3 station with text-item lineage."""

    if owner_group is None or not _table_exists(conn, "psp_raw_text_item"):
        return
    items = [
        SpatialTextItem(int(raw_id), int(page_no), str(text), float(x), float(y))
        for raw_id, page_no, text, x, y in conn.execute(
            """
            SELECT id, page_no, item_text, x, y
            FROM psp_raw_text_item
            WHERE report_document_id = ? AND page_no = 3
              AND extraction_method = 'liteparse' AND x IS NOT NULL AND y IS NOT NULL
            ORDER BY item_no
            """,
            (report,),
        )
    ]
    expected_label = _collapsed_station_label(collapsed_label)
    for spatial_row in reconstruct_generation_rows(
        items,
        column_centers=_ERLDC_REGIONAL_GENERATION_SPATIAL_CENTERS,
        label_x_max=125.0,
        minimum_value_count=len(_ERLDC_REGIONAL_GENERATION_SPATIAL_CENTERS),
    ):
        if _compact_spatial_label(spatial_row.label) != _compact_spatial_label(expected_label):
            continue
        if set(spatial_row.values) != set(_ERLDC_REGIONAL_GENERATION_SPATIAL_CENTERS):
            return
        values: dict[str, float | str] = {}
        for name, value in spatial_row.values.items():
            parsed = _time(value) if name.endswith("Time") else _spatial_number(value)
            if parsed is None:
                return
            values[name] = parsed
        capacity = values["InstalledCapacityMW"]
        if not isinstance(capacity, float):
            return
        try:
            identity = resolve_generation_identity(
                conn, "erldc", expected_label, None, region_id, None, capacity, False
            )
        except DimensionResolutionError as error:
            record_resolution_issue(
                conn, report, "erldc", "spatial_generation_entity", expected_label, str(error)
            )
            return
        entity_id = _get_or_create_grid_entity(
            conn, expected_label, "generating_entity", None, region_id, None,
            capacity, False, identity,
        )
        section = f"regional_entities_generation:{owner_group}"
        names = list(values)
        conn.execute(
            "INSERT OR REPLACE INTO FactERLDCGenerationDaily("
            "ReportDocumentID, DateID, EntityID, StateID, StationID, GeneratingUnitID, "
            "AggregateID, IsTotalRow, GenerationGrain, SectionName, "
            f"{', '.join(names)}) VALUES (?, ?, ?, NULL, ?, ?, ?, 0, ?, ?, "
            f"{', '.join('?' for _ in names)})",
            (
                report, date_id, entity_id, identity.station_id, identity.generating_unit_id,
                identity.aggregate_id, identity.entity_type, section,
                *(values[name] for name in names),
            ),
        )
        _spatial_lineage(
            conn,
            report,
            "FactERLDCGenerationDaily",
            f"report={report};date={date_id};entity={entity_id};section={section}",
            spatial_row.value_item_ids,
        )
        _validate_generation_average(conn, report, expected_label, values)
        return


def _collapsed_station_label(value: str) -> str:
    """Keep the station identifier before metrics collapsed into column one."""

    match = re.match(r"^(.*?\))", value)
    return match.group(1).strip() if match else value.strip()


def _compact_spatial_label(value: str) -> str:
    """Normalize station labels for exact spatial/native matching."""

    return re.sub(r"[^a-z0-9]", "", value.lower())


def _spatial_number(value: str) -> float | None:
    """Convert one LiteParse numeric token without inferring missing values."""

    try:
        return float(value.replace(",", "").strip())
    except ValueError:
        return None


def _looks_like_collapsed_generation_row(value: str) -> bool:
    """Return whether a wrapped station row has collapsed into its label cell.

    The source row cannot be safely promoted without spatial reconstruction,
    but it also cannot replace the preceding owner context for a valid
    continuation on the next page.  Owner headings never carry a run of daily
    measurements, unlike these collapsed station rows.
    """

    measurements = re.findall(r"[-+]?\d+(?:\.\d+)?", value)
    return len(measurements) >= 5


def _regional_owner_key(value: str) -> str:
    """Return a stable owner context for repeated regional aggregate labels."""

    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "unclassified"


def _insert_2025_flat_regional_generation(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
    label: str,
    owner_group: str,
    row: dict[int, tuple[int, str]],
    columns: dict[str, int],
) -> None:
    """Insert one regional-entity row with owner-scoped raw-cell lineage."""
    values: dict[str, float | str] = {}
    sources: dict[str, int] = {}
    for field, column in columns.items():
        if field in {"DayPeakTime", "MinimumGenerationTime"}:
            raw = row.get(column)
            value = _time(raw[1]) if raw else None
            raw_id = raw[0] if raw else None
        else:
            value, raw_id = _number(row, column)
        if value is not None:
            values[field] = value
        if raw_id is not None:
            sources[field] = raw_id
    capacity = values.get("InstalledCapacityMW")
    if not isinstance(capacity, float):
        return
    is_total = _is_total_generation_row(label)
    try:
        identity = resolve_generation_identity(
            conn,
            "erldc",
            label,
            None,
            region_id,
            None,
            capacity,
            is_total,
        )
    except DimensionResolutionError as error:
        record_resolution_issue(
            conn,
            report,
            "erldc",
            "generation_entity",
            label,
            str(error),
        )
        return
    entity_id = _get_or_create_grid_entity(
        conn,
        label,
        "generation_aggregate" if is_total else "generating_entity",
        None,
        region_id,
        None,
        capacity,
        is_total,
        identity,
    )
    section = f"regional_entities_generation:{owner_group}"
    field_names = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        "INSERT OR REPLACE INTO FactERLDCGenerationDaily("
        "ReportDocumentID, DateID, EntityID, StateID, StationID, "
        "GeneratingUnitID, AggregateID, IsTotalRow, GenerationGrain, "
        f"SectionName, {field_names}) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {placeholders})",
        (
            report,
            date_id,
            entity_id,
            None,
            identity.station_id,
            identity.generating_unit_id,
            identity.aggregate_id,
            int(is_total),
            identity.entity_type,
            section,
            *values.values(),
        ),
    )
    key = f"report={report};date={date_id};entity={entity_id};section={section}"
    _lineage(conn, report, "FactERLDCGenerationDaily", key, sources)
    _validate_generation_average(conn, report, label, values)


def _frequency(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    """Promote native flattened Section 6 frequency extrema and statistics."""
    rows = _rows(conn, report, 5)
    for row in rows:
        if not (45.0 <= (_number(row, 1)[0] or 0) <= 55.0):
            continue
        resolution = resolve_exclusive_layouts(
            layouts={"compact": _ERLDC_FREQUENCY_COMPACT, "wide": _ERLDC_FREQUENCY_WIDE},
            exclusive_columns={
                "compact": frozenset({4}),
                "wide": frozenset({6, 23, 27}),
            },
            populated=lambda column, current=row: (
                _is_frequency(_number(current, column)[0])
                if column in {4, 6}
                else _number(current, column)[0] is not None
            ),
        )
        if not resolution.resolved or not resolution.mapping:
            _quarantine_layout(
                conn,
                report,
                section="frequency",
                resolution=resolution,
                columns=sorted(row),
            )
            return
        values, sources = {}, {}
        for name, col in resolution.mapping.items():
            value, raw = _number(row, col)
            if value is not None: values[name] = value
            if raw: sources[name] = raw
        if "MinimumFrequencyHz" not in values:
            return
        names = ", ".join(values)
        conn.execute(f"INSERT OR REPLACE INTO FactERLDCFrequencyDaily(ReportDocumentID, DateID, RegionID, {names}) VALUES (?, ?, ?, {', '.join('?' for _ in values)})", (report, date_id, region_id, *values.values()))
        _lineage(conn, report, "FactERLDCFrequencyDaily", f"report={report};date={date_id};region={region_id}", sources)
        return


def _reservoirs(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    """Promote flattened Section 11 reservoir rows without location inference."""
    for row in _rows(conn, report, 7):
        name = row.get(1, (0, ""))[1].strip()
        if not name or name.lower().startswith(("reserv", "designed", "present", "last", "11.")):
            continue
        values, sources = {}, {}
        for field, col in {"MinimumDrawdownLevelM": 2, "FullReservoirLevelM": 3, "DesignedEnergyMU": 4, "CurrentLevelM": 5, "CurrentEnergyMU": 6, "PreviousYearLevelM": 7, "PreviousYearEnergyMU": 8, "InflowMU": 9, "UsageMU": 10}.items():
            value, raw = _number(row, col)
            if value is not None: values[field] = value
            if raw: sources[field] = raw
        if not values:
            continue
        location = reservoir_location(name)
        state_id = None
        if location.state_name:
            state = conn.execute("SELECT StateID FROM DimStates WHERE StateName = ?", (location.state_name,)).fetchone()
            state_id = state[0] if state else None
        conn.execute("INSERT OR IGNORE INTO DimReservoirs(ReservoirName, StateID, RegionID) VALUES (?, ?, ?)", (name, state_id, region_id))
        reservoir = conn.execute("SELECT ReservoirID FROM DimReservoirs WHERE ReservoirName = ?", (name,)).fetchone()
        if not reservoir: continue
        names = ", ".join(values)
        conn.execute(f"INSERT OR REPLACE INTO FactERLDCReservoirDaily(ReportDocumentID, DateID, ReservoirID, {names}) VALUES (?, ?, ?, {', '.join('?' for _ in values)})", (report, date_id, reservoir[0], *values.values()))
        _lineage(conn, report, "FactERLDCReservoirDaily", f"report={report};date={date_id};reservoir={reservoir[0]}", sources)


def _promote_2025_flat_operational_sections(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote verified 2025-flat voltage and physical exchange sections.

    The 2025-flat family places physical inter-regional exchange on page 4
    and voltage profiles on page 5, with sparse spacer columns. The nearby
    Nepal line-detail matrix remains intentionally outside this country-grain
    fact contract until it receives its own line-level schema.
    """
    _promote_2025_flat_physical_exchanges(conn, report, date_id)
    _promote_2025_flat_voltage_profiles(conn, report, date_id, region_id)
    _promote_2025_flat_country_exchanges(conn, report, date_id)


def _promote_market_sections(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
) -> None:
    """Promote day-energy and extrema from any ERLDC family that publishes them.

    Day-energy uses native cells after a complete header match. Extrema first
    tries native max/min columns, then LiteParse reconstruction for collapsed
    2025-flat rows. HPX RTM stays outside the contract when both columns are
    labeled ``Minimum``. Nepal line-detail is not handled here.
    """

    for page_no, _table_no, rows in _all_tables(conn, report):
        _promote_market_day_energy_from_rows(conn, report, date_id, rows)
        _promote_market_extrema_from_native_rows(conn, report, date_id, rows)
        if _market_extrema_headers_are_verified(rows):
            _promote_market_extrema_from_spatial_items(
                conn,
                report,
                date_id,
                page_no,
            )


def _promote_market_day_energy_from_rows(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    rows: list[dict[int, tuple[int, str]]],
) -> None:
    """Promote one header-verified ERLDC day-energy market matrix."""

    for index, row in enumerate(rows[:-1]):
        if not any(
            _compact_text(text) == "dayenergy(mu)"
            for _, text in row.values()
        ):
            continue
        fields = _market_day_energy_columns(rows[index + 1])
        if fields is None:
            return
        for data_row in rows[index + 2:]:
            label_cell = data_row.get(1)
            label = label_cell[1].strip() if label_cell else ""
            compact_label = _compact_text(label)
            if compact_label.startswith("8(b)") or compact_label == "total":
                return
            if not compact_label:
                continue

            state_id = _market_state_id(conn, label)
            entity_id = _market_participant_entity_id(conn, label, state_id)
            values: dict[str, float] = {}
            sources: dict[str, int] = {}
            for name, col in fields.items():
                value, raw = _number(data_row, col)
                if value is not None:
                    values[name] = value
                if raw is not None:
                    sources[name] = raw
            if not values:
                continue

            names = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            conn.execute(
                "INSERT OR REPLACE INTO FactERLDCMarketEnergyDaily("
                f"ReportDocumentID, DateID, EntityID, StateID, {names}) "
                f"VALUES (?, ?, ?, ?, {placeholders})",
                (report, date_id, entity_id, state_id, *values.values()),
            )
            _lineage(
                conn,
                report,
                "FactERLDCMarketEnergyDaily",
                f"report={report};date={date_id};entity={entity_id}",
                sources,
            )
        return


def _erldc_market_mechanism_columns(
    row: dict[int, tuple[int, str]],
) -> dict[str, int]:
    """Resolve published ERLDC market mechanism headers to raw columns."""

    names = {
        "gnaschedule": "GNASchedule",
        "isgsgnaschedule": "GNASchedule",
        "isgsgnasched": "GNASchedule",
        "tgnabilateral": "TGNABilateral",
        "tgnabilateralmw": "TGNABilateral",
        "isgstgnabilateral": "TGNABilateral",
        "gdamschedule": "GDAMSchedule",
        "iexgdamschedule": "GDAMSchedule",
        "iexgdammw": "IEXGDAM",
        "damschedule": "DAMSchedule",
        "iexdamschedule": "DAMSchedule",
        "iexdammw": "IEXDAM",
        "hpdamschedule": "HPDAMSchedule",
        "iexhpdamschedule": "HPDAMSchedule",
        "iexhpdammw": "IEXHPDAM",
        "rtmschedule": "RTMSchedule",
        "iexrtmschedule": "RTMSchedule",
        "iexrtmmw": "IEXRTM",
        "pxilgdammw": "PXILGDAM",
        "pxildammw": "PXILDAM",
        "pxilhpdammw": "PXILHPDAM",
        "pxilrtmmw": "PXILRTM",
        "pxirtmmw": "PXILRTM",
        "hpxgdammw": "HPXGDAM",
        "hpxdammw": "HPXDAM",
        "hpxhpdammw": "HPXHPDAM",
        "hpxrtm": "HPXRTM",
        "hpxrtmmw": "HPXRTM",
        "hpxrtmschedule": "HPXRTM",
    }
    result: dict[str, int] = {}
    for column, (_, text) in row.items():
        name = names.get(re.sub(r"[^a-z]", "", text.lower()))
        if name:
            result[name] = column
    return result


def _erldc_market_extrema_pairs(
    mechanisms: dict[str, int],
    row: dict[int, tuple[int, str]],
) -> dict[str, tuple[int, int]]:
    """Return complete Maximum/Minimum column pairs, skipping malformed ones.

    HPX RTM is omitted when both of its columns are labeled ``Minimum`` instead
    of aborting the rest of a verified 8(B) table.
    """

    columns = sorted(mechanisms.items(), key=lambda item: item[1])
    last_column = max(row) + 1 if row else 0
    pairs: dict[str, tuple[int, int]] = {}
    for index, (mechanism, start) in enumerate(columns):
        end = columns[index + 1][1] if index + 1 < len(columns) else last_column
        maximum = [
            column
            for column in range(start, end)
            if _market_extrema_header_text(row.get(column, (0, ""))[1]) == "maximum"
        ]
        minimum = [
            column
            for column in range(start, end)
            if _market_extrema_header_text(row.get(column, (0, ""))[1]) == "minimum"
        ]
        if len(maximum) != 1 or len(minimum) != 1:
            continue
        pairs[mechanism] = (maximum[0], minimum[0])
    return pairs


def _promote_market_extrema_from_native_rows(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    rows: list[dict[int, tuple[int, str]]],
) -> None:
    """Promote complete native max/min pairs, skipping malformed HPX RTM."""

    for index, row in enumerate(rows[:-1]):
        mechanisms = _erldc_market_mechanism_columns(row)
        if len(mechanisms) < 6:
            continue
        pairs = _erldc_market_extrema_pairs(mechanisms, rows[index + 1])
        if not pairs:
            continue
        for data_row in rows[index + 2:]:
            label_cell = data_row.get(1)
            label = label_cell[1].strip() if label_cell else ""
            compact_label = _compact_text(label)
            if compact_label.startswith("8(b)") or compact_label == "total":
                break
            if not compact_label or compact_label == "state":
                continue
            state_id = _market_state_id(conn, label)
            entity_id = _market_participant_entity_id(conn, label, state_id)
            promoted = False
            for mechanism, (maximum_col, minimum_col) in pairs.items():
                maximum, maximum_raw = _number(data_row, maximum_col)
                minimum, minimum_raw = _number(data_row, minimum_col)
                if maximum is None or minimum is None:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO FactERLDCMarketExtremaDaily("
                    "ReportDocumentID, DateID, EntityID, StateID, Mechanism, MaximumMW, MinimumMW"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (report, date_id, entity_id, state_id, mechanism, maximum, minimum),
                )
                sources = {
                    name: raw_id
                    for name, raw_id in (
                        ("MaximumMW", maximum_raw),
                        ("MinimumMW", minimum_raw),
                    )
                    if raw_id is not None
                }
                _lineage(
                    conn,
                    report,
                    "FactERLDCMarketExtremaDaily",
                    f"report={report};date={date_id};entity={entity_id};mechanism={mechanism}",
                    sources,
                )
                promoted = True
            if not promoted and not label:
                break
        return


def _promote_market_extrema_from_spatial_items(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    page_no: int,
) -> None:
    """Promote collapsed Section 8(B) extrema from LiteParse boxes on one page.

    The native table can merge West Bengal, Jharkhand, and Railways rows.
    Promotion therefore requires both published headers and a complete spatial
    reconstruction. HPX RTM is omitted from the spatial contracts.
    """

    if not _table_exists(conn, "psp_raw_text_item"):
        return
    items = [
        SpatialTextItem(int(raw_id), int(item_page), str(text), float(x), float(y))
        for raw_id, item_page, text, x, y in conn.execute(
            """
            SELECT id, page_no, item_text, x, y
            FROM psp_raw_text_item
            WHERE report_document_id = ? AND page_no = ?
              AND extraction_method = 'liteparse' AND x IS NOT NULL AND y IS NOT NULL
            ORDER BY item_no
            """,
            (report, page_no),
        )
    ]
    for (lower_y, upper_y), centers in _ERLDC_MARKET_EXTREMA_SPATIAL_TABLES:
        table_items = [item for item in items if lower_y < item.y < upper_y]
        for spatial_row in reconstruct_generation_rows(
            table_items,
            column_centers=centers,
            label_x_max=65.0,
            minimum_value_count=len(centers),
        ):
            if set(spatial_row.values) != set(centers):
                continue
            state_id = _market_state_id(conn, spatial_row.label)
            entity_id = _market_participant_entity_id(conn, spatial_row.label, state_id)
            for mechanism in _market_extrema_mechanisms(centers):
                maximum_name = f"{mechanism}MaximumMW"
                minimum_name = f"{mechanism}MinimumMW"
                maximum = _spatial_number(spatial_row.values[maximum_name])
                minimum = _spatial_number(spatial_row.values[minimum_name])
                if maximum is None or minimum is None:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO FactERLDCMarketExtremaDaily("
                    "ReportDocumentID, DateID, EntityID, StateID, Mechanism, MaximumMW, MinimumMW"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        report,
                        date_id,
                        entity_id,
                        state_id,
                        mechanism,
                        maximum,
                        minimum,
                    ),
                )
                _spatial_lineage(
                    conn,
                    report,
                    "FactERLDCMarketExtremaDaily",
                    f"report={report};date={date_id};entity={entity_id};mechanism={mechanism}",
                    {
                        "MaximumMW": spatial_row.value_item_ids[maximum_name],
                        "MinimumMW": spatial_row.value_item_ids[minimum_name],
                    },
                )


def _market_extrema_headers_are_verified(
    rows: list[dict[int, tuple[int, str]]],
) -> bool:
    """Require published Section 8(B) labels before accepting spatial values."""

    expected_headers = (
        (
            {
                2: "gnaschedule", 7: "tgnabilateralmw", 12: "iexgdammw",
                18: "pxilgdammw", 24: "hpxgdammw", 31: "iexdammw", 37: "pxildammw",
            },
            {2: 4, 7: 10, 12: 16, 18: 21, 24: 27, 31: 35, 37: 40},
        ),
        (
            {
                2: "hpxdammw", 7: "iexhpdammw", 12: "pxilhpdammw",
                18: "hpxhpdammw", 24: "iexrtmmw", 31: "pxilrtmmw",
            },
            {2: 4, 7: 10, 12: 16, 18: 21, 24: 27, 31: 35},
        ),
    )
    for expected, pairs in expected_headers:
        for index, row in enumerate(rows[:-1]):
            if not all(
                _market_extrema_header_text(row.get(column, (0, ""))[1]) == label
                for column, label in expected.items()
            ):
                continue
            maximum_minimum = rows[index + 1]
            if all(
                _market_extrema_header_text(
                    maximum_minimum.get(column, (0, ""))[1]
                ) == "maximum"
                and _market_extrema_header_text(
                    maximum_minimum.get(pairs[column], (0, ""))[1]
                ) == "minimum"
                for column in pairs
            ):
                break
        else:
            return False
    return True


def _market_extrema_header_text(value: str) -> str:
    """Normalize punctuation variants used in Page 6 market headers."""

    return re.sub(r"[^a-z0-9]", "", value.lower())


def _market_extrema_mechanisms(centers: dict[str, float]) -> tuple[str, ...]:
    """Return fully specified mechanism names from one spatial table contract."""

    return tuple(
        name.removesuffix("MaximumMW")
        for name in centers
        if name.endswith("MaximumMW") and f"{name.removesuffix('MaximumMW')}MinimumMW" in centers
    )


def _market_day_energy_columns(
    header_row: dict[int, tuple[int, str]],
) -> dict[str, int] | None:
    """Resolve the published ERLDC Page 6 day-energy columns by header."""

    expected = {
        "gnaschedule": "GNAScheduleMU",
        "isgsgnaschedule": "GNAScheduleMU",
        "tgnabilateral": "TGNABilateralMU",
        "tgnabilateralmw": "TGNABilateralMU",
        "gdamschedule": "GDAMScheduleMU",
        "damschedule": "DAMScheduleMU",
        "hpdamschedule": "HPDAMScheduleMU",
        "rtmschedule": "RTMScheduleMU",
        "totalmu": "TotalMU",
    }
    required = {
        "GNAScheduleMU",
        "TGNABilateralMU",
        "GDAMScheduleMU",
        "DAMScheduleMU",
        "HPDAMScheduleMU",
        "RTMScheduleMU",
        "TotalMU",
    }
    columns: dict[str, int] = {}
    for column, (_, text) in header_row.items():
        field_name = expected.get(re.sub(r"[^a-z]", "", text.lower()))
        if field_name:
            columns[field_name] = column
    return columns if set(columns) == required else None


def _market_state_id(
    conn: sqlite3.Connection,
    label: str,
) -> int | None:
    """Resolve only published geographical market participants as states."""

    normalized = re.sub(r"[^A-Z]", "", label.upper())
    if normalized not in _ERLDC_MARKET_GEOGRAPHIC_LABELS:
        return None
    return _state_id(conn, label)


def _market_participant_entity_id(
    conn: sqlite3.Connection,
    label: str,
    state_id: int | None,
) -> int:
    """Resolve an ERLDC market participant without inventing a state identity."""

    normalized = re.sub(r"[^A-Z0-9]", "", label.upper())
    entity_name = _ERLDC_MARKET_PARTICIPANT_ALIASES.get(
        normalized,
        re.sub(r"\s+", " ", label).strip(),
    )
    region = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Eastern Region'"
    ).fetchone()
    if region is None:
        raise RuntimeError("Eastern Region dimension is required for market promotion")
    existing = conn.execute(
        "SELECT EntityID FROM DimGridEntities "
        "WHERE EntityName = ? AND EntityType = 'market_participant' "
        "AND StateID IS ? AND RegionID = ?",
        (entity_name, state_id, region[0]),
    ).fetchone()
    if existing:
        return int(existing[0])
    cursor = conn.execute(
        "INSERT INTO DimGridEntities(EntityName, EntityType, StateID, RegionID) "
        "VALUES (?, 'market_participant', ?, ?)",
        (entity_name, state_id, region[0]),
    )
    return int(cursor.lastrowid)


def _promote_2025_flat_physical_exchanges(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
) -> None:
    """Promote registry-resolved page-4 inter-regional physical exchanges."""
    rows = _rows(conn, report, 4)
    in_section = False
    for row in rows:
        label = row.get(1, (0, ""))[1].strip()
        compact_label = _compact_text(label)
        if compact_label.startswith("4(a)") and "inter" in compact_label:
            in_section = True
            continue
        if compact_label.startswith("4(b)"):
            return
        if not in_section:
            continue

        name = row.get(2, (0, ""))[1].strip()
        location = transmission_location(name)
        if location.evidence == "unverified":
            continue
        fields = {
            "EveningPeakMW": _number(row, 9),
            "OffPeakMW": _number(row, 13),
            "MaximumImportMW": _number(row, 17),
            "MaximumExportMW": _number(row, 19),
            "ImportEnergyMU": _number(row, 21),
            "ExportEnergyMU": _number(row, 23),
            "NetEnergyMU": _number(row, 25),
        }
        _upsert_interregional_exchange(
            conn,
            report,
            date_id,
            name,
            location,
            fields,
        )


def _promote_2025_flat_voltage_profiles(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote exact-match page-5 400/765 kV voltage profile rows."""
    rows = _rows(conn, report, 5)
    in_voltage_section = False
    for row in rows:
        label = row.get(1, (0, ""))[1].strip()
        compact_label = _compact_text(label)
        if compact_label.startswith("7.voltageprofile"):
            in_voltage_section = True
            continue
        if in_voltage_section and compact_label.startswith("8("):
            return
        if not in_voltage_section:
            continue

        location = voltage_node_location(label)
        maximum, maximum_raw = _number(row, 5)
        minimum, minimum_raw = _number(row, 12)
        if location.evidence == "unverified" or maximum is None or minimum is None:
            continue
        match = re.search(r"(\d{3,4})\s*KV", label, re.IGNORECASE)
        if match is None:
            continue
        nominal_kv = float(match.group(1))
        state_id = _state_id_by_name(conn, location.state_name)
        conn.execute(
            "INSERT OR IGNORE INTO DimVoltageNodes("
            "NodeName, NominalVoltageKV, StateID, RegionID) VALUES (?, ?, ?, ?)",
            (label, nominal_kv, state_id, region_id),
        )
        node = conn.execute(
            "SELECT VoltageNodeID FROM DimVoltageNodes WHERE NodeName = ?", (label,)
        ).fetchone()
        if node is None:
            continue
        fields = {
            "MaximumKV": maximum,
            "MaximumTime": _time(row.get(8, (0, ""))[1]),
            "MinimumKV": minimum,
            "MinimumTime": _time(row.get(17, (0, ""))[1]),
            "LowCriticalPct": _number(row, 22)[0],
            "IEGCBandPct": _number(row, 27)[0],
            "HighCriticalPct": _number(row, 29)[0],
        }
        conn.execute(
            "INSERT OR REPLACE INTO FactERLDCVoltageProfile("
            "ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV, "
            "MaximumTime, MinimumKV, MinimumTime, LowCriticalPct, IEGCBandPct, "
            "HighCriticalPct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (report, date_id, node[0], nominal_kv, *fields.values()),
        )
        _lineage(
            conn,
            report,
            "FactERLDCVoltageProfile",
            f"report={report};date={date_id};node={node[0]}",
            {
                "MaximumKV": maximum_raw,
                "MinimumKV": minimum_raw,
                **{
                    column: raw_id
                    for column, (_, raw_id) in {
                        "LowCriticalPct": _number(row, 22),
                        "IEGCBandPct": _number(row, 27),
                        "HighCriticalPct": _number(row, 29),
                    }.items()
                    if raw_id is not None
                },
            },
        )


def _promote_2025_flat_country_exchanges(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
) -> None:
    """Promote the country-grain page-5 transnational exchange summary."""
    rows = _rows(conn, report, 5, table=2)
    for row in rows:
        label = row.get(1, (0, ""))[1].strip()
        country = _country_from_exchange_label(label)
        if country is None:
            continue
        fields = {
            "ScheduledEnergyMU": _number(row, 2),
            "ActualEnergyMU": _number(row, 3),
            "DayPeakMW": _number(row, 4),
            "DayMinimumMW": _number(row, 5),
            "AverageMW": _number(row, 6),
        }
        _upsert_international_exchange(conn, report, date_id, country, fields)


def _upsert_interregional_exchange(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    name: str,
    location: object,
    fields: dict[str, tuple[float | None, int | None]],
) -> None:
    """Persist a resolved physical exchange and the provenance of every value."""
    values = {field: value for field, (value, _) in fields.items() if value is not None}
    if not values:
        return
    conn.execute(
        "INSERT OR IGNORE INTO DimTransmissionElements("
        "ElementName, ElementType, NominalVoltageKV, FromRegionID, ToRegionID) "
        "VALUES (?, ?, ?, (SELECT RegionID FROM DimRegions WHERE RegionName = ?), "
        "(SELECT RegionID FROM DimRegions WHERE RegionName = ?))",
        (
            name,
            location.element_type,
            location.nominal_voltage_kv,
            location.from_location.region_name,
            location.to_location.region_name,
        ),
    )
    element = conn.execute(
        "SELECT ElementID FROM DimTransmissionElements WHERE ElementName = ?", (name,)
    ).fetchone()
    if element is None:
        return
    counterparty = location.to_location.region_name or "unknown"
    conn.execute(
        "INSERT OR REPLACE INTO FactERLDCInterRegionalExchange("
        f"ReportDocumentID, DateID, ElementID, CounterpartyRegion, {', '.join(values)}) "
        f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in values)})",
        (report, date_id, element[0], counterparty, *values.values()),
    )
    _lineage(
        conn,
        report,
        "FactERLDCInterRegionalExchange",
        f"report={report};date={date_id};element={element[0]};counterparty={counterparty}",
        {field: raw_id for field, (_, raw_id) in fields.items() if raw_id is not None},
    )


def _upsert_international_exchange(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    country: str,
    fields: dict[str, tuple[float | None, int | None]],
) -> None:
    """Persist a country-grain transnational exchange with raw-cell lineage."""
    values = {field: value for field, (value, _) in fields.items() if value is not None}
    if not values:
        return
    conn.execute("INSERT OR IGNORE INTO DimCountries(CountryName) VALUES (?)", (country,))
    country_row = conn.execute(
        "SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country,)
    ).fetchone()
    if country_row is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO FactERLDCInternationalExchange("
        f"ReportDocumentID, DateID, CountryID, CounterpartyCountry, {', '.join(values)}) "
        f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in values)})",
        (report, date_id, country_row[0], country, *values.values()),
    )
    _lineage(
        conn,
        report,
        "FactERLDCInternationalExchange",
        f"report={report};date={date_id};country={country_row[0]}",
        {field: raw_id for field, (_, raw_id) in fields.items() if raw_id is not None},
    )


def _country_from_exchange_label(label: str) -> str | None:
    """Resolve a published transnational summary label to its country grain."""
    normalized = _compact_text(label)
    if normalized.startswith("bhutan"):
        return "Bhutan"
    if normalized.startswith("bangladesh"):
        return "Bangladesh"
    if normalized.startswith("nepal"):
        return "Nepal"
    return None


def _voltage_and_exchanges(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    """Promote only exact registry-resolved voltage nodes and exchange labels."""
    section = ""
    for row in _rows(conn, report, 5):
        label = row.get(1, (0, ""))[1].strip()
        normalized = label.lower()
        if normalized.startswith("5.") or "bus voltage" in normalized or "voltageprofile" in normalized:
            section = "voltage"; continue
        if normalized.startswith("4(a)"):
            section = "interregional"; continue
        if normalized.startswith("4(b)"):
            section = "international"; continue
        value, raw = _number(row, 2)
        if section == "voltage":
            location = voltage_node_location(label)
            if location.evidence == "unverified": continue
            minimum, minimum_raw = _number(row, 4)
            maximum_time = row.get(3, (0, ""))[1]
            minimum_time = row.get(5, (0, ""))[1]
            if value is None or minimum is None: continue
            conn.execute("INSERT OR IGNORE INTO DimVoltageNodes(NodeName, NominalVoltageKV, StateID, RegionID) VALUES (?, ?, (SELECT StateID FROM DimStates WHERE StateName = ?), ?)", (label, float(label.split("-")[-1].replace("KV", "")), location.state_name, region_id))
            node = conn.execute("SELECT VoltageNodeID FROM DimVoltageNodes WHERE NodeName = ?", (label,)).fetchone()
            if not node: continue
            conn.execute("INSERT OR REPLACE INTO FactERLDCVoltageProfile(ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV, MaximumTime, MinimumKV, MinimumTime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (report, date_id, node[0], float(label.split("-")[-1].replace("KV", "")), value, maximum_time, minimum, minimum_time))
            _lineage(conn, report, "FactERLDCVoltageProfile", f"report={report};date={date_id};node={node[0]}", {"MaximumKV": raw, "MinimumKV": minimum_raw})
        elif section == "interregional":
            location = transmission_location(label)
            if location.evidence == "unverified" or value is None: continue
            conn.execute("INSERT OR IGNORE INTO DimTransmissionElements(ElementName, ElementType, NominalVoltageKV, FromRegionID, ToRegionID) VALUES (?, ?, ?, (SELECT RegionID FROM DimRegions WHERE RegionName = ?), (SELECT RegionID FROM DimRegions WHERE RegionName = ?))", (label, location.element_type, location.nominal_voltage_kv, location.from_location.region_name, location.to_location.region_name))
            element = conn.execute("SELECT ElementID FROM DimTransmissionElements WHERE ElementName = ?", (label,)).fetchone()
            if element: conn.execute("INSERT OR REPLACE INTO FactERLDCInterRegionalExchange(ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU) VALUES (?, ?, ?, ?, ?)", (report, date_id, element[0], location.to_location.region_name or "unknown", value))
        elif section == "international" and label.upper() in {"BHUTAN", "BANGLADESH", "NEPAL"} and value is not None:
            country = label.title(); conn.execute("INSERT OR IGNORE INTO DimCountries(CountryName) VALUES (?)", (country,))
            country_id = conn.execute("SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country,)).fetchone()[0]
            conn.execute("INSERT OR REPLACE INTO FactERLDCInternationalExchange(ReportDocumentID, DateID, CountryID, CounterpartyCountry, NetEnergyMU) VALUES (?, ?, ?, ?, ?)", (report, date_id, country_id, country, value))
