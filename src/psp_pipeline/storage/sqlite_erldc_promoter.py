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

logger = logging.getLogger(__name__)


def promote_erldc_report_to_curated(conn: sqlite3.Connection, report_id: int) -> None:
    """Promote verified ERLDC PSP sections with raw-cell lineage.

    Split-table layouts currently promote their stable Page 1 regional and state
    tables. Multi-page generation and operational sections remain gated until
    their continuation geometry has a fixture-backed contract.
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
    ):
        conn.execute(f"DELETE FROM {table} WHERE ReportDocumentID = ?", (report_id,))
    if report[2] in ERLDC_SPLIT_TEMPLATE_IDS:
        _split_regional(conn, report_id, date_id, int(region[0]))
        _split_states(conn, report_id, date_id)
        _split_generation(conn, report_id, date_id, int(region[0]))
        _split_frequency(conn, report_id, date_id, int(region[0]))
        _split_reservoirs(conn, report_id, date_id, int(region[0]))
        _split_voltage_and_exchanges(conn, report_id, date_id, int(region[0]))
        return
    _regional(conn, report_id, date_id, int(region[0]))
    _states(conn, report_id, date_id)
    _generation(conn, report_id, date_id, int(region[0]))
    _frequency(conn, report_id, date_id, int(region[0]))
    _reservoirs(conn, report_id, date_id, int(region[0]))
    _voltage_and_exchanges(conn, report_id, date_id, int(region[0]))


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


def _regional(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    rows = _rows(conn, report, 1)
    if len(rows) < 4:
        return
    row = rows[3]
    fields = ({"EveningPeakDemandMetMW": 1, "OffPeakDemandMetMW": 2, "DayEnergyMetMU": 3}
              if max(row, default=0) <= 3 else {"EveningPeakDemandMetMW": 1, "OffPeakDemandMetMW": 6, "DayEnergyMetMU": 12})
    values, sources = {}, {}
    for name, col in fields.items():
        value, raw = _number(row, col)
        if value is not None: values[name] = value
        if raw: sources[name] = raw
    if not values:
        return
    columns = ", ".join(values)
    conn.execute(f"INSERT OR REPLACE INTO FactERLDCRegionalDaily(ReportDocumentID, DateID, RegionID, {columns}) VALUES (?, ?, ?, {', '.join('?' for _ in values)})", (report, date_id, region_id, *values.values()))
    _lineage(conn, report, "FactERLDCRegionalDaily", f"report={report};date={date_id};region={region_id}", sources)


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
    for row in _rows(conn, report, 1):
        label = row.get(1, (0, ""))[1].replace(" ", "").upper()
        state_name = _STATE_ALIASES.get(label)
        if not state_name:
            continue
        state = conn.execute("SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)).fetchone()
        if not state:
            continue
        values, sources = {}, {}
        columns = ({"ThermalGenerationMU": 2, "HydroGenerationMU": 3, "TotalGenerationMU": 4, "RequirementMU": 5, "ConsumptionMU": 6}
                   if max(row, default=0) <= 6 else {"ThermalGenerationMU": 2, "HydroGenerationMU": 3, "TotalGenerationMU": 7, "RequirementMU": 15, "ConsumptionMU": 18})
        for name, col in columns.items():
            value, raw = _number(row, col)
            if value is not None: values[name] = value
            if raw: sources[name] = raw
        if not values: continue
        columns = ", ".join(values)
        conn.execute(f"INSERT OR REPLACE INTO FactERLDCStateDaily(ReportDocumentID, DateID, StateID, {columns}) VALUES (?, ?, ?, {', '.join('?' for _ in values)})", (report, date_id, state[0], *values.values()))
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
    for row in _rows(conn, report, 2):
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
        values, sources = {"InstalledCapacityMW": capacity}, {"InstalledCapacityMW": cap_raw}
        columns = {"GrossEnergyMU": 3, "NetEnergyMU": 4, "AverageMW": 5} if max(row, default=0) <= 5 else {"GrossEnergyMU": 7, "NetEnergyMU": 8, "AverageMW": 9}
        for name, col in columns.items():
            value, raw = _number(row, col)
            if value is not None: values[name] = value
            if raw: sources[name] = raw
        columns = ", ".join(values)
        conn.execute(f"INSERT OR REPLACE INTO FactERLDCGenerationDaily(ReportDocumentID, DateID, EntityID, AggregateID, SectionName, {columns}) VALUES (?, ?, ?, ?, 'state_generation', {', '.join('?' for _ in values)})", (report, date_id, entity[0], entity[0], *values.values()))
        _lineage(conn, report, "FactERLDCGenerationDaily", f"report={report};date={date_id};entity={entity[0]};section=state_generation", sources)


def _frequency(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    """Promote native flattened Section 6 frequency extrema and statistics."""
    rows = _rows(conn, report, 5)
    for row in rows:
        if not (45.0 <= (_number(row, 1)[0] or 0) <= 55.0):
            continue
        wide = max(row, default=0) > 20
        columns = ({"MaximumFrequencyHz": 1, "MinimumFrequencyHz": 6, "AverageFrequencyHz": 12, "FrequencyVariationIndex": 16, "StandardDeviationHz": 20, "Maximum15MinuteBlockFrequencyHz": 23, "Minimum15MinuteBlockFrequencyHz": 27} if wide else {"MaximumFrequencyHz": 1, "MinimumFrequencyHz": 4, "AverageFrequencyHz": 8, "FrequencyVariationIndex": 10, "StandardDeviationHz": 12, "Maximum15MinuteBlockFrequencyHz": 14, "Minimum15MinuteBlockFrequencyHz": 17})
        values, sources = {}, {}
        for name, col in columns.items():
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
