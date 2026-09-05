"""Promote verified NERLDC PSP facts into curated SQLite tables."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3

from psp_pipeline.storage.sqlite_dimensions import (
    DimensionResolutionError,
    record_resolution_issue,
    resolve_generation_identity,
)
from psp_pipeline.parsing.frequency_operating_bands import (
    collect_frequency_operating_bands,
)
from psp_pipeline.parsing.layout_resolution import resolve_header_layout
from psp_pipeline.storage.sqlite_nerldc_enrichment import (
    generation_entity_canonical_name,
    transmission_location,
    voltage_node_location,
)


TEMPLATE_IDS = frozenset({
    "nerldc_daily_psp_v2023_standard_09_column_generation",
    "nerldc_daily_psp_v2024_standard_09_column_generation",
    "nerldc_daily_psp_v2025_standard_10_column_generation",
    "nerldc_daily_psp_v2026_standard_09_column_generation",
})
STATE_NAMES = {
    "ARUNACHALPRADESH": "Arunachal Pradesh", "ASSAM": "Assam",
    "MANIPUR": "Manipur", "MEGHALAYA": "Meghalaya", "MIZORAM": "Mizoram",
    "NAGALAND": "Nagaland", "TRIPURA": "Tripura",
}
_REGIONAL_SCHEDULE_FIELDS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 4,
    "DayPeakMW": 5,
    "DayPeakTime": 6,
    "GrossEnergyMU": 7,
    "NetEnergyMU": 8,
    "AverageMW": 9,
    "ScheduledEnergyMU": 10,
    "UIMU": 11,
    "RRASScheduleMU": 12,
}
_NINE_COLUMN_REGIONAL_FIELDS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 4,
    "DayPeakMW": 5,
    "DayPeakTime": 6,
    "GrossEnergyMU": 7,
    "NetEnergyMU": 8,
    "AverageMW": 9,
}
_REGIONAL_CORE_HEADER_TOKENS = {
    "InstalledCapacityMW": ("inst",),
    "GrossEnergyMU": ("gross",),
    "NetEnergyMU": ("net",),
    "AverageMW": ("avg",),
}


def promote_nerldc_report_to_curated(conn: sqlite3.Connection, report_id: int) -> None:
    """Promote approved NERLDC core and operational PSP facts with lineage."""
    report = conn.execute(
        "SELECT rldc, report_date, template_id, semantic_pass_required "
        "FROM psp_report_document WHERE id = ?", (report_id,)
    ).fetchone()
    if not report or report[0] != "nerldc" or report[3] or report[2] not in TEMPLATE_IDS:
        return
    date_id = _date_id(conn, str(report[1]))
    region = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'North Eastern Region'"
    ).fetchone()
    if date_id is None or region is None:
        return
    _clear(conn, report_id)
    region_id = int(region[0])
    _regional(conn, report_id, date_id, region_id)
    _states(conn, report_id, date_id)
    _generation(conn, report_id, date_id, region_id, str(report[2]))
    _regional_generation(conn, report_id, date_id, region_id)
    _frequency(conn, report_id, date_id, region_id)
    _voltage(conn, report_id, date_id, region_id)
    _reservoirs(conn, report_id, date_id, region_id)
    _exchanges(conn, report_id, date_id)


def _date_id(conn: sqlite3.Connection, report_date: str) -> int | None:
    conn.execute("INSERT OR IGNORE INTO DimDates(ActualDate) VALUES (?)", (report_date,))
    row = conn.execute("SELECT DateID FROM DimDates WHERE ActualDate = ?", (report_date,)).fetchone()
    return int(row[0]) if row else None


def _clear(conn: sqlite3.Connection, report_id: int) -> None:
    for table in (
        "FactNERLDCRegionalDaily", "FactNERLDCStateDaily", "FactNERLDCGenerationDaily",
        "FactNERLDCFrequencyDaily", "FactNERLDCVoltageProfile",
        "FactNERLDCReservoirDaily",
        "FactNERLDCInterRegionalExchange", "FactNERLDCInternationalExchange",
    ):
        conn.execute(f"DELETE FROM {table} WHERE ReportDocumentID = ?", (report_id,))
    conn.execute("DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?", (report_id,))


def _rows(conn: sqlite3.Connection, report: int, page: int, table: int) -> list[dict[int, tuple[int, str]]]:
    grouped: dict[int, dict[int, tuple[int, str]]] = {}
    for raw_id, row_no, col_no, cell in conn.execute(
        "SELECT id, row_no, col_no, cell_text FROM psp_raw_cell "
        "WHERE report_document_id = ? AND page_no = ? AND table_no = ? ORDER BY row_no, col_no",
        (report, page, table),
    ):
        grouped.setdefault(int(row_no), {})[int(col_no)] = (int(raw_id), str(cell or ""))
    return [grouped[index] for index in sorted(grouped)]


def _all_tables(conn: sqlite3.Connection, report: int) -> list[list[dict[int, tuple[int, str]]]]:
    pairs = conn.execute(
        "SELECT DISTINCT page_no, table_no FROM psp_raw_cell "
        "WHERE report_document_id = ? ORDER BY page_no, table_no", (report,)
    ).fetchall()
    return [_rows(conn, report, int(page), int(table)) for page, table in pairs]


def _number(row: dict[int, tuple[int, str]], column: int) -> tuple[float | None, int | None]:
    raw = row.get(column)
    if raw is None:
        return None, None
    try:
        return float(raw[1].replace(",", "").strip()), raw[0]
    except ValueError:
        return None, None


def _time(value: str) -> str | None:
    match = re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", value)
    return match.group(0) if match else None


def _state_id(conn: sqlite3.Connection, raw_name: str) -> int | None:
    state_name = STATE_NAMES.get(re.sub(r"\s+", "", raw_name).upper())
    if state_name is None:
        return None
    row = conn.execute("SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)).fetchone()
    return int(row[0]) if row else None


def _regional(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    fields = {
        "EveningPeakDemandMetMW": 1, "EveningPeakShortageMW": 2,
        "EveningPeakRequirementMW": 3, "EveningPeakFrequencyHz": 4,
        "OffPeakDemandMetMW": 5, "OffPeakShortageMW": 6,
        "OffPeakRequirementMW": 7, "OffPeakFrequencyHz": 8,
        "DayEnergyMetMU": 9, "DayEnergyShortageMU": 10,
    }
    for row in _rows(conn, report, 1, 1):
        if sum(_number(row, column)[0] is not None for column in fields.values()) >= 4:
            _insert(conn, "FactNERLDCRegionalDaily", ("ReportDocumentID", "DateID", "RegionID"),
                    (report, date_id, region_id), fields, row, report,
                    f"report={report};date={date_id};region={region_id}")
            return


def _states(conn: sqlite3.Connection, report: int, date_id: int) -> None:
    fields = {
        "ThermalGenerationMU": 2, "HydroGenerationMU": 3,
        "GasNapthaDieselGenerationMU": 4, "WindGenerationMU": 5,
        "SolarGenerationMU": 6, "OtherGenerationMU": 7, "TotalGenerationMU": 8,
        "ScheduledDrawalMU": 9, "ActualDrawalMU": 10, "UIMU": 11,
        "TotalAvailabilityMU": 12, "DemandMetMU": 13, "EnergyShortageMU": 14,
    }
    for row in _rows(conn, report, 1, 2):
        state_id = _state_id(conn, row.get(1, (0, ""))[1])
        if state_id is not None:
            _insert(conn, "FactNERLDCStateDaily", ("ReportDocumentID", "DateID", "StateID"),
                    (report, date_id, state_id), fields, row, report,
                    f"report={report};date={date_id};state={state_id}")


def _generation(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
    template_id: str,
) -> None:
    """Promote state generation tables for the approved NERLDC layouts."""

    fields = {
        "InstalledCapacityMW": 2, "EveningPeakMW": 3, "OffPeakMW": 4,
        "DayPeakMW": 5, "DayPeakTime": 6, "MinimumGenerationMW": 7,
        "MinimumGenerationTime": 8, "NetEnergyMU": 9, "AverageMW": 10,
    }
    if template_id != "nerldc_daily_psp_v2025_standard_10_column_generation":
        fields = {
            "InstalledCapacityMW": 2,
            "EveningPeakMW": 3,
            "OffPeakMW": 4,
            "DayPeakMW": 5,
            "DayPeakTime": 6,
            "NetEnergyMU": 8,
            "AverageMW": 9,
        }

    table_numbers = conn.execute(
        "SELECT DISTINCT table_no FROM psp_raw_cell "
        "WHERE report_document_id = ? AND page_no = 2 ORDER BY table_no",
        (report,),
    ).fetchall()
    for (table,) in table_numbers:
        rows = _rows(conn, report, 2, table)
        if not any("station/constituents" in row.get(1, (0, ""))[1].lower() for row in rows):
            continue
        current_state_id: int | None = None
        for row in rows:
            label = row.get(1, (0, ""))[1].strip()
            capacity, _ = _number(row, 2)
            state_id = _state_id(conn, label)
            if state_id is not None and capacity is None:
                current_state_id = state_id
                continue
            if not label or capacity is None or current_state_id is None or "station/constituents" in label.lower():
                continue
            is_total = re.sub(r"\s+", "", label).lower().startswith(("total", "subtotal"))
            values, sources = _values(row, fields)
            canonical_label = generation_entity_canonical_name(label)
            try:
                identity = resolve_generation_identity(
                    conn,
                    "nerldc",
                    canonical_label,
                    current_state_id,
                    region_id,
                    None,
                    capacity,
                    is_total,
                )
            except DimensionResolutionError as error:
                record_resolution_issue(conn, report, "nerldc", "generation_entity", label, str(error))
                continue
            entity_id = _grid_entity(
                conn,
                canonical_label,
                "generation_aggregate" if is_total else "generating_entity",
                current_state_id,
                region_id,
                None,
                capacity,
                is_total,
                identity,
            )
            conn.execute(
                "INSERT OR REPLACE INTO FactNERLDCGenerationDaily("
                "ReportDocumentID, DateID, EntityID, StateID, StationID, GeneratingUnitID, "
                "AggregateID, IsTotalRow, GenerationGrain, SectionName, "
                f"{', '.join(values)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {', '.join('?' for _ in values)})",
                (report, date_id, entity_id, current_state_id, identity.station_id,
                 identity.generating_unit_id, identity.aggregate_id, int(is_total), identity.entity_type,
                 f"state_generation_{current_state_id}", *values.values()),
            )
            _lineage(conn, report, "FactNERLDCGenerationDaily",
                     f"report={report};date={date_id};entity={entity_id};section=state_generation_{current_state_id}", sources)


def _regional_generation(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote the owner-grouped NERLDC regional generation table.

    The schedule/UI/RRAS contract stays authoritative when those headers are
    published. Historical 9-column and wide families without those columns are
    promoted from unique Installed/Gross/Net/Average headers only. State
    generation on page 2 is left to ``_generation``.
    """
    pairs = conn.execute(
        "SELECT DISTINCT page_no, table_no FROM psp_raw_cell "
        "WHERE report_document_id = ? ORDER BY page_no, table_no",
        (report,),
    ).fetchall()
    for page, table in pairs:
        rows = _rows(conn, report, int(page), int(table))
        fields = _regional_generation_fields(rows, page=int(page))
        if fields is None:
            continue
        _promote_regional_generation_rows(
            conn,
            report,
            date_id,
            region_id,
            rows,
            fields,
        )


def _regional_generation_fields(
    rows: list[dict[int, tuple[int, str]]],
    *,
    page: int,
) -> dict[str, int] | None:
    """Return a verified regional-generation column map, or None."""

    if _is_regional_generation_table(rows):
        return _REGIONAL_SCHEDULE_FIELDS
    if page < 3 or not _has_station_constituents_header(rows):
        return None
    header = resolve_header_layout(
        rows[:3],
        _REGIONAL_CORE_HEADER_TOKENS,
        layout_id="nerldc_regional_core",
    )
    if not header.resolved or not header.mapping:
        return None
    if header.mapping == {
        "InstalledCapacityMW": 2,
        "GrossEnergyMU": 7,
        "NetEnergyMU": 8,
        "AverageMW": 9,
    }:
        return _NINE_COLUMN_REGIONAL_FIELDS
    return header.mapping


def _promote_regional_generation_rows(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
    rows: list[dict[int, tuple[int, str]]],
    fields: dict[str, int],
) -> None:
    """Persist one owner-grouped regional generation table."""

    owner_group: str | None = None
    for row in rows:
        label = row.get(1, (0, ""))[1].strip()
        if not label or "station/constituents" in label.lower():
            continue
        capacity, _ = _number(row, fields["InstalledCapacityMW"])
        is_total = _is_total_generation_row(label)
        if capacity is None:
            if not is_total:
                owner_group = _owner_group_key(label)
            continue
        if owner_group is None:
            continue
        values, sources = _values(row, fields)
        canonical_label = generation_entity_canonical_name(label)
        try:
            identity = resolve_generation_identity(
                conn,
                "nerldc",
                canonical_label,
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
                "nerldc",
                "generation_entity",
                label,
                str(error),
            )
            continue
        entity_id = _grid_entity(
            conn,
            canonical_label,
            "generation_aggregate" if is_total else "generating_entity",
            None,
            region_id,
            None,
            capacity,
            is_total,
            identity,
        )
        section = f"regional_generation:{owner_group}"
        conn.execute(
            "INSERT OR REPLACE INTO FactNERLDCGenerationDaily("
            "ReportDocumentID, DateID, EntityID, StateID, StationID, "
            "GeneratingUnitID, AggregateID, IsTotalRow, GenerationGrain, "
            f"SectionName, {', '.join(values)}) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {', '.join('?' for _ in values)})",
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
        _lineage(
            conn,
            report,
            "FactNERLDCGenerationDaily",
            f"report={report};date={date_id};entity={entity_id};section={section}",
            sources,
        )


def _has_station_constituents_header(
    rows: list[dict[int, tuple[int, str]]],
) -> bool:
    """Return whether the first rows publish the station/constituents heading."""

    return any(
        "station/constituents" in row.get(1, (0, ""))[1].lower()
        for row in rows[:3]
    )


def _is_regional_generation_table(
    rows: list[dict[int, tuple[int, str]]],
) -> bool:
    """Return whether rows are the schedule/UI/RRAS regional generation table."""

    header_rows = rows[:3]
    has_station_header = _has_station_constituents_header(rows)
    has_schedule_header = any(
        "schedule" in row.get(10, (0, ""))[1].lower()
        and row.get(11, (0, ""))[1].strip().upper() == "UI"
        and row.get(12, (0, ""))[1].strip().upper() == "RRAS"
        for row in header_rows
    )
    return has_station_header and has_schedule_header


def _is_total_generation_row(value: str) -> bool:
    """Return whether a regional generation label is an aggregate row."""

    normalized = re.sub(r"\s+", "", value).lower()
    return normalized.startswith(("total", "subtotal", "sub-total"))


def _owner_group_key(value: str) -> str:
    """Produce a stable owner context for repeated regional aggregate labels."""

    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unclassified"


def _frequency(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    for rows in _all_tables(conn, report):
        if not any(row.get(1, (0, ""))[1].strip().lower() == "maximum" and
                   "average" in row.get(5, (0, ""))[1].lower() for row in rows[:2]):
            continue
        for row in rows:
            maximum, max_raw = _number(row, 1)
            minimum, min_raw = _number(row, 3)
            if maximum is None or minimum is None or not (45 <= maximum <= 55 and 45 <= minimum <= 55):
                continue
            fields = {"MaximumFrequencyHz": (maximum, max_raw), "MinimumFrequencyHz": (minimum, min_raw),
                      "AverageFrequencyHz": _number(row, 5), "FrequencyVariationIndex": _number(row, 6),
                      "StandardDeviationHz": _number(row, 7), "Maximum15MinuteBlockFrequencyHz": _number(row, 8),
                      "Minimum15MinuteBlockFrequencyHz": _number(row, 9)}
            values = {name: value for name, (value, _) in fields.items() if value is not None}
            conn.execute("INSERT OR REPLACE INTO FactNERLDCFrequencyDaily(ReportDocumentID, DateID, RegionID, "
                         f"{', '.join(values)}) VALUES (?, ?, ?, {', '.join('?' for _ in values)})",
                         (report, date_id, region_id, *values.values()))
            _lineage(conn, report, "FactNERLDCFrequencyDaily", f"report={report};date={date_id};region={region_id}",
                     {name: raw for name, (_, raw) in fields.items() if raw is not None})
            _merge_frequency_operating_bands(conn, report, date_id, region_id, rows)
            return
    for rows in _all_tables(conn, report):
        if collect_frequency_operating_bands(rows)[0]:
            _merge_frequency_operating_bands(conn, report, date_id, region_id, rows)
            return


def _merge_frequency_operating_bands(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
    rows: list[dict[int, tuple[int, str]]],
) -> None:
    """Attach unique IEGC operating-band percentages to the daily frequency fact."""

    values, sources = collect_frequency_operating_bands(rows)
    if not values:
        return
    existing = conn.execute(
        "SELECT 1 FROM FactNERLDCFrequencyDaily "
        "WHERE ReportDocumentID = ? AND DateID = ? AND RegionID = ?",
        (report, date_id, region_id),
    ).fetchone()
    assignments = ", ".join(f"{name} = ?" for name in values)
    if existing:
        conn.execute(
            f"UPDATE FactNERLDCFrequencyDaily SET {assignments} "
            "WHERE ReportDocumentID = ? AND DateID = ? AND RegionID = ?",
            (*values.values(), report, date_id, region_id),
        )
    else:
        conn.execute(
            "INSERT INTO FactNERLDCFrequencyDaily("
            f"ReportDocumentID, DateID, RegionID, {', '.join(values)}) "
            f"VALUES (?, ?, ?, {', '.join('?' for _ in values)})",
            (report, date_id, region_id, *values.values()),
        )
    if sources:
        _lineage(
            conn,
            report,
            "FactNERLDCFrequencyDaily",
            f"report={report};date={date_id};region={region_id}",
            sources,
        )


def _voltage(conn: sqlite3.Connection, report: int, date_id: int, region_id: int) -> None:
    for rows in _all_tables(conn, report):
        if not any(row.get(1, (0, ""))[1].strip().upper() == "STATION" and
                   "voltage" in row.get(2, (0, ""))[1].lower() for row in rows[:3]):
            continue
        for row in rows:
            name = row.get(1, (0, ""))[1].strip()
            match = re.search(r"(\d{3,4})\s*KV", name, re.IGNORECASE)
            maximum, max_raw = _number(row, 2)
            minimum, min_raw = _number(row, 4)
            if match is None or maximum is None or minimum is None:
                continue
            nominal = float(match.group(1))
            location = voltage_node_location(name)
            conn.execute(
                "INSERT OR IGNORE INTO DimVoltageNodes("
                "NodeName, NominalVoltageKV, StateID, RegionID) VALUES (?, ?, ?, ?)",
                (name, nominal, _state_id_by_name(conn, location.state_name), region_id),
            )
            node = conn.execute("SELECT VoltageNodeID FROM DimVoltageNodes WHERE NodeName = ?", (name,)).fetchone()
            if node is None:
                continue
            percent = [_number(row, column)[0] for column in (6, 7, 8)]
            conn.execute("INSERT OR REPLACE INTO FactNERLDCVoltageProfile(ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV, MaximumTime, MinimumKV, MinimumTime, LowCriticalPct, IEGCBandPct, HighCriticalPct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (report, date_id, node[0], nominal, maximum, _time(row.get(3, (0, ""))[1]), minimum,
                          _time(row.get(5, (0, ""))[1]), *percent))
            sources = {"MaximumKV": max_raw, "MinimumKV": min_raw}
            for field, column in (("LowCriticalPct", 6), ("IEGCBandPct", 7), ("HighCriticalPct", 8)):
                _, raw = _number(row, column)
                if raw is not None:
                    sources[field] = raw
            _lineage(conn, report, "FactNERLDCVoltageProfile", f"report={report};date={date_id};node={node[0]}", sources)


def _reservoirs(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote the verified Page 4/Table 6 NERLDC reservoir status table.

    The 2024 through 2026 reports share eight explicitly headed measures.
    ``PreviousDayEnergyMU`` is added only where its column heading is present;
    the 2025 extraction leaves that heading blank and is intentionally not
    inferred from the numeric cell position.
    """

    for rows in _all_tables(conn, report):
        if len(rows) < 3:
            continue
        first_header, second_header = rows[0], rows[1]
        is_reservoir_table = (
            second_header.get(1, (0, ""))[1].strip().upper() == "RESERVOIR"
            and "MDDL" in second_header.get(2, (0, ""))[1].upper()
            and first_header.get(2, (0, ""))[1].strip().upper() == "DESIGNED"
        )
        if not is_reservoir_table:
            continue

        fields = {
            "MinimumDrawdownLevelM": 2,
            "FullReservoirLevelM": 3,
            "DesignedEnergyMU": 4,
            "CurrentLevelM": 5,
            "CurrentEnergyMU": 6,
            "PreviousYearLevelM": 7,
            "PreviousYearEnergyMU": 8,
            "PreviousDayLevelM": 9,
        }
        if "ENERGY" in second_header.get(10, (0, ""))[1].upper():
            fields["PreviousDayEnergyMU"] = 10

        for row in rows[2:]:
            label = row.get(1, (0, ""))[1].strip()
            if not label or label.upper() == "TOTAL":
                continue
            values, sources = _values(row, fields)
            if not values:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO DimReservoirs(ReservoirName, RegionID) "
                "VALUES (?, ?)",
                (label, region_id),
            )
            reservoir = conn.execute(
                "SELECT ReservoirID FROM DimReservoirs WHERE ReservoirName = ?",
                (label,),
            ).fetchone()
            if reservoir is None:
                continue
            reservoir_id = int(reservoir[0])
            _insert(
                conn,
                "FactNERLDCReservoirDaily",
                ("ReportDocumentID", "DateID", "ReservoirID"),
                (report, date_id, reservoir_id),
                fields,
                row,
                report,
                f"report={report};date={date_id};reservoir={reservoir_id}",
            )
        return


def _exchanges(conn: sqlite3.Connection, report: int, date_id: int) -> None:
    for rows in _all_tables(conn, report):
        if not any(row.get(2, (0, ""))[1].strip().lower() == "element" and
                   "import" in row.get(7, (0, ""))[1].lower() for row in rows[:2]):
            continue
        counterparty, country = None, None
        for row in rows:
            label = row.get(1, (0, ""))[1].strip()
            text = re.sub(r"\s+", " ", label).upper()
            if text.startswith("IMPORT/EXPORT BETWEEN"):
                counterparty, country = _counterparty(text)
                continue
            if country and text.startswith("SUB-TOTAL"):
                net, raw = _number(row, 9)
                country_id = _country_total(conn, report, date_id, country, net)
                if country_id is not None and raw is not None:
                    _lineage(conn, report, "FactNERLDCInternationalExchange", f"report={report};date={date_id};country={country_id}", {"NetEnergyMU": raw})
                continue
            name = row.get(2, (0, ""))[1].strip()
            if not counterparty or not name:
                continue
            fields = {"EveningPeakMW": _number(row, 3), "OffPeakMW": _number(row, 4),
                      "MaximumImportMW": _number(row, 5), "MaximumExportMW": _number(row, 6),
                      "ImportEnergyMU": _number(row, 7), "ExportEnergyMU": _number(row, 8), "NetEnergyMU": _number(row, 9)}
            values = {field: value for field, (value, _) in fields.items() if value is not None}
            if not values:
                continue
            metadata = transmission_location(name)
            conn.execute(
                "INSERT OR IGNORE INTO DimTransmissionElements("
                "ElementName, ElementType, NominalVoltageKV, FromRegionID, ToRegionID, "
                "FromStateID, ToStateID, FromCountryID, ToCountryID) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    metadata.element_type,
                    metadata.nominal_voltage_kv,
                    _region_id_by_name(conn, metadata.from_location.region_name),
                    _region_id_by_name(conn, metadata.to_location.region_name),
                    _state_id_by_name(conn, metadata.from_location.state_name),
                    _state_id_by_name(conn, metadata.to_location.state_name),
                    _country_id_by_name(conn, metadata.from_location.country_name),
                    _country_id_by_name(conn, metadata.to_location.country_name),
                ),
            )
            element = conn.execute("SELECT ElementID FROM DimTransmissionElements WHERE ElementName = ?", (name,)).fetchone()
            if element is None:
                continue
            conn.execute("INSERT OR REPLACE INTO FactNERLDCInterRegionalExchange(ReportDocumentID, DateID, ElementID, CounterpartyRegion, "
                         f"{', '.join(values)}) VALUES (?, ?, ?, ?, {', '.join('?' for _ in values)})",
                         (report, date_id, element[0], counterparty, *values.values()))
            _lineage(conn, report, "FactNERLDCInterRegionalExchange", f"report={report};date={date_id};element={element[0]};counterparty={counterparty}",
                     {field: raw for field, (_, raw) in fields.items() if raw is not None})


def _counterparty(heading: str) -> tuple[str, str | None]:
    if "BHUTAN" in heading:
        return "Bhutan", "Bhutan"
    if "BANGLADESH" in heading:
        return "Bangladesh", "Bangladesh"
    if "EAST REGION" in heading:
        return "Eastern Region", None
    if "NORTH REGION" in heading:
        return "Northern Region", None
    return "Unknown", None


def _country_total(conn: sqlite3.Connection, report: int, date_id: int, country: str, net: float | None) -> int | None:
    if net is None:
        return None
    conn.execute("INSERT OR IGNORE INTO DimCountries(CountryName) VALUES (?)", (country,))
    row = conn.execute("SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country,)).fetchone()
    if row is None:
        return None
    conn.execute("INSERT OR REPLACE INTO FactNERLDCInternationalExchange(ReportDocumentID, DateID, CountryID, CounterpartyCountry, NetEnergyMU) VALUES (?, ?, ?, ?, ?)",
                 (report, date_id, row[0], country, net))
    return int(row[0])


def _insert(conn: sqlite3.Connection, table: str, keys: tuple[str, ...], key_values: tuple[int, ...], fields: dict[str, int], row: dict[int, tuple[int, str]], report: int, key: str) -> None:
    values, sources = _values(row, fields)
    if values:
        conn.execute(f"INSERT OR REPLACE INTO {table}({', '.join(keys)}, {', '.join(values)}) VALUES ({', '.join('?' for _ in key_values)}, {', '.join('?' for _ in values)})", (*key_values, *values.values()))
        _lineage(conn, report, table, key, sources)


def _values(row: dict[int, tuple[int, str]], fields: dict[str, int]) -> tuple[dict[str, float | str], dict[str, int]]:
    values: dict[str, float | str] = {}
    sources: dict[str, int] = {}
    for field, column in fields.items():
        raw = row.get(column)
        if raw is None:
            continue
        value: float | str | None = _time(raw[1]) if field.endswith("Time") else _number(row, column)[0]
        if value is not None:
            values[field], sources[field] = value, raw[0]
    return values, sources


def _lineage(conn: sqlite3.Connection, report: int, table: str, key: str, sources: dict[str, int]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for column, raw_id in sources.items():
        conn.execute("INSERT OR IGNORE INTO curated_field_lineage(ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt) VALUES (?, ?, ?, ?, ?, 'pdfplumber', 1.0, ?)",
                     (report, table, key, column, raw_id, now))


def _voltage_from_name(name: str) -> float | None:
    match = re.search(r"(\d{3,4})\s*KV", name, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _state_id_by_name(conn: sqlite3.Connection, state_name: str | None) -> int | None:
    """Return a canonical state identifier without inferring an unknown state."""

    if state_name is None:
        return None
    row = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _region_id_by_name(conn: sqlite3.Connection, region_name: str | None) -> int | None:
    """Return a canonical region identifier without creating topology records."""

    if region_name is None:
        return None
    row = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (region_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _country_id_by_name(conn: sqlite3.Connection, country_name: str | None) -> int | None:
    """Return a canonical country identifier for a verified foreign endpoint."""

    if country_name is None:
        return None
    conn.execute("INSERT OR IGNORE INTO DimCountries(CountryName) VALUES (?)", (country_name,))
    row = conn.execute(
        "SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _grid_entity(*args: object, **kwargs: object) -> int:
    from psp_pipeline.storage.sqlite_curated_promoter import _get_or_create_grid_entity
    return _get_or_create_grid_entity(*args, **kwargs)
