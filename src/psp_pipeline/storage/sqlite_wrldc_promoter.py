"""Promote verified WRLDC PSP regional, state, and station-generation facts."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3

from psp_pipeline.parsing.rldc.templates import (
    WRLDC_2023_REVISED_TEMPLATE,
    WRLDC_2023_TEMPLATE,
    WRLDC_2024_TEMPLATE,
    WRLDC_2024_REVISED_TEMPLATE,
    WRLDC_2024_TRANSITION_TEMPLATE,
    WRLDC_2025_REVISED_TEMPLATE,
    WRLDC_2025_TEMPLATE,
    WRLDC_2026_EARLY_TEMPLATE,
    WRLDC_2026_TEMPLATE,
)
from psp_pipeline.storage.sqlite_dimensions import (
    DimensionResolutionError,
    record_resolution_issue,
    resolve_generation_identity,
    resolve_state_id,
)
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema
from psp_pipeline.storage.sqlite_wrldc_enrichment import (
    transmission_location,
    voltage_node_location,
)


WR_REGION_NAME = "Western Region"
WRLDC_11_COLUMN_TEMPLATE_IDS = frozenset(
    template.template_id
    for template in (
        WRLDC_2024_REVISED_TEMPLATE,
        WRLDC_2024_TRANSITION_TEMPLATE,
        WRLDC_2025_TEMPLATE,
        WRLDC_2025_REVISED_TEMPLATE,
        WRLDC_2026_EARLY_TEMPLATE,
        WRLDC_2026_TEMPLATE,
    )
)
WRLDC_9_COLUMN_TEMPLATE_IDS = frozenset(
    template.template_id
    for template in (
        WRLDC_2023_TEMPLATE,
        WRLDC_2023_REVISED_TEMPLATE,
        WRLDC_2024_TEMPLATE,
    )
)
WRLDC_GENERATION_TEMPLATE_IDS = (
    WRLDC_9_COLUMN_TEMPLATE_IDS | WRLDC_11_COLUMN_TEMPLATE_IDS
)
WRLDC_OPERATIONAL_TEMPLATE_IDS = frozenset({WRLDC_2025_TEMPLATE.template_id})

_REGIONAL_COLUMNS = {
    "EveningPeakDemandMetMW": 1,
    "EveningPeakShortageMW": 2,
    "EveningPeakRequirementMW": 7,
    "EveningPeakFrequencyHz": 11,
    "OffPeakDemandMetMW": 14,
    "OffPeakShortageMW": 18,
    "OffPeakRequirementMW": 25,
    "OffPeakFrequencyHz": 30,
    "DayEnergyMetMU": 32,
    "DayEnergyShortageMU": 38,
}
_STATE_BALANCE_COLUMNS = {
    "ThermalGenerationMU": 4,
    "HydroGenerationMU": 5,
    "GasNapthaDieselGenerationMU": 9,
    "WindGenerationMU": 12,
    "SolarGenerationMU": 14,
    "OtherGenerationMU": 16,
    "TotalGenerationMU": 20,
    "ScheduledDrawalMU": 24,
    "ActualDrawalMU": 28,
    "UIMU": 31,
    "TotalAvailabilityMU": 33,
    "RequirementMU": 36,
    "EnergyShortageMU": 39,
    "ConsumptionMU": 42,
}
_STATE_FORECAST_COLUMNS = {
    "EveningPeakDemandMetMW": 3,
    "EveningPeakShortageMW": 6,
    "EveningPeakRequirementMW": 13,
    "OffPeakDemandMetMW": 15,
    "OffPeakShortageMW": 21,
    "OffPeakRequirementMW": 29,
    "AverageDemandMW": 32,
    "ForecastDemandMU": 35,
    "ForecastDeviationMU": 40,
}
_STATE_PEAK_COLUMNS = {
    "MaximumDemandMetMW": 3,
    "MaximumDemandTime": 8,
    "MaximumDemandShortageMW": 13,
    "MaximumDemandRequirementMW": 19,
    "MaximumACEMW": 26,
    "MaximumACETime": 31,
    "MinimumACEMW": 35,
    "MinimumACETime": 41,
}
_GENERATION_COLUMNS = {
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
_NINE_COLUMN_GENERATION_COLUMNS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 4,
    "DayPeakMW": 5,
    "DayPeakTime": 6,
    "GrossEnergyMU": 7,
    "NetEnergyMU": 8,
    "AverageMW": 9,
}


def promote_wrldc_report_to_curated(
    conn: sqlite3.Connection,
    report_document_id: int,
) -> None:
    """Promote stable WRLDC pages one through three with raw-cell lineage.

    Approved nine- and eleven-column state-generation layouts are supported.
    IPP and renewable continuation pages remain review-gated until their
    distinct mappings are verified.
    """
    ensure_curated_sqlite_schema(conn)
    report = _fetch_report(conn, report_document_id)
    if not report or report["rldc"] != "wrldc":
        return
    template_id = str(report["template_id"] or "")
    if template_id not in WRLDC_GENERATION_TEMPLATE_IDS or _scope_is_affected(report):
        return

    date_id = _get_or_create_date_id(conn, str(report["report_date"]))
    region_id = _region_id(conn)
    if date_id is None or region_id is None:
        return

    _upsert_dim_report(conn, date_id, report)
    _clear_wrldc_facts(conn, report_document_id)
    mapped_cells: set[int] = set()
    _promote_regional_daily(conn, report_document_id, date_id, region_id, mapped_cells)
    _promote_state_sections(conn, report_document_id, date_id, mapped_cells)
    _promote_state_generation(
        conn,
        report_document_id,
        date_id,
        region_id,
        template_id,
        mapped_cells,
    )
    if template_id in WRLDC_OPERATIONAL_TEMPLATE_IDS:
        _promote_physical_exchanges(conn, report_document_id, date_id, mapped_cells)
        _promote_voltage_profiles(
            conn, report_document_id, date_id, region_id, mapped_cells
        )
        _promote_reservoirs(conn, report_document_id, date_id, region_id, mapped_cells)
        _promote_frequency_daily(conn, report_document_id, date_id, region_id)


def _scope_is_affected(report: sqlite3.Row) -> bool:
    """Block only structural drift that touches WRLDC pages owned by this promoter."""
    if not report["semantic_pass_required"]:
        return False
    reason = str(report["structure_deviation_reason"] or "")
    return bool(re.search(r"(?:p[1-3]_t|missing_table=p[1-3]_)", reason))


def _promote_regional_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    row = _table_row(conn, report_id, 1, 1, 4)
    values, sources = _values(row, _REGIONAL_COLUMNS)
    if not any(value is not None for value in values.values()):
        return
    _insert_fact(
        conn,
        "FactWRLDCRegionalDaily",
        {"ReportDocumentID": report_id, "DateID": date_id, "RegionID": region_id, **values},
    )
    _write_lineage(
        conn,
        report_id,
        "FactWRLDCRegionalDaily",
        f"report={report_id};date={date_id};region={region_id}",
        sources,
        mapped_cells,
    )


def _promote_state_sections(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
) -> None:
    sections = (("2(a)", _STATE_BALANCE_COLUMNS), ("2(b)", _STATE_FORECAST_COLUMNS), ("2(c)", _STATE_PEAK_COLUMNS))
    rows = _table_rows(conn, report_id, 1, 1)
    for marker, columns in sections:
        for row in _section_rows(rows, marker):
            state_cell = row.get(1)
            state_id = _resolve_state_id(conn, report_id, state_cell[1] if state_cell else "")
            if state_id is None:
                continue
            values, sources = _values(row, columns)
            if not any(value is not None for value in values.values()):
                continue
            _upsert_state_daily(conn, report_id, date_id, state_id, values)
            if state_cell:
                mapped_cells.add(state_cell[0])
            _write_lineage(
                conn,
                report_id,
                "FactWRLDCStateDaily",
                f"report={report_id};date={date_id};state={state_id}",
                sources,
                mapped_cells,
            )


def _promote_state_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    generation_columns = _generation_columns(template_id)
    capacity_column = generation_columns["InstalledCapacityMW"]
    for page_no in (2, 3):
        current_state_id: int | None = None
        current_source_id: int | None = None
        for row in _table_rows(conn, report_id, page_no, 1):
            entity_cell = row.get(1)
            label = _clean_label(entity_cell[1]) if entity_cell else ""
            state_id = _resolve_state_id(conn, report_id, label, record=False)
            if state_id is not None and _cell_float(row, capacity_column) is None:
                current_state_id = state_id
                current_source_id = None
                if entity_cell:
                    mapped_cells.add(entity_cell[0])
                continue
            source_id = _source_id(conn, label)
            if source_id is not None and _cell_float(row, capacity_column) is None:
                current_source_id = source_id
                if entity_cell:
                    mapped_cells.add(entity_cell[0])
                continue
            if current_state_id is None or not label:
                continue
            values, sources = _generation_values(row, generation_columns)
            capacity = values["InstalledCapacityMW"]
            if capacity is None:
                continue
            is_total = _is_total_row(label)
            try:
                identity = resolve_generation_identity(
                    conn, "wrldc", label, current_state_id, region_id,
                    current_source_id, float(capacity), is_total,
                )
            except DimensionResolutionError as error:
                record_resolution_issue(conn, report_id, "wrldc", "generation_entity", label, str(error))
                continue
            entity_id = _get_or_create_grid_entity(
                conn, label, "generation_aggregate" if is_total else "generating_entity",
                current_state_id, region_id, current_source_id, float(capacity), is_total, identity,
            )
            section_name = f"state_generation_{current_state_id}"
            _insert_fact(
                conn,
                "FactWRLDCGenerationDaily",
                {
                    "ReportDocumentID": report_id, "DateID": date_id, "EntityID": entity_id,
                    "StateID": current_state_id, "GenerationSourceID": current_source_id,
                    "StationID": identity.station_id, "GeneratingUnitID": identity.generating_unit_id,
                    "AggregateID": identity.aggregate_id, "IsTotalRow": int(is_total),
                    "GenerationGrain": identity.entity_type, "SectionName": section_name, **values,
                },
            )
            if entity_cell:
                mapped_cells.add(entity_cell[0])
            _write_lineage(
                conn, report_id, "FactWRLDCGenerationDaily",
                f"report={report_id};date={date_id};entity={entity_id};section={section_name}",
                sources, mapped_cells,
            )
            _validate_average_mw(conn, report_id, label, values)


def _fetch_report(conn: sqlite3.Connection, report_id: int) -> dict[str, object] | None:
    """Fetch only the report metadata needed by the WRLDC promoter."""
    row = conn.execute(
        """
        SELECT rldc, local_path, report_date, template_id,
               semantic_pass_required, structure_deviation_reason
        FROM psp_report_document WHERE id = ?
        """,
        (report_id,),
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


def _get_or_create_date_id(conn: sqlite3.Connection, report_date: str) -> int | None:
    conn.execute("INSERT OR IGNORE INTO DimDates(ActualDate) VALUES (?)", (report_date,))
    row = conn.execute("SELECT DateID FROM DimDates WHERE ActualDate = ?", (report_date,)).fetchone()
    return int(row[0]) if row else None


def _region_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT RegionID FROM DimRegions WHERE RegionName = ?", (WR_REGION_NAME,)).fetchone()
    return int(row[0]) if row else None


def _canonical_state_id(conn: sqlite3.Connection, state_name: str | None) -> int | None:
    """Return a seeded dimension identifier for a registry state name."""

    canonical_name = {
        "Dadra and Nagar Haveli and Daman and Diu": "DNHDDPDCL",
        "Madhya Pradesh": "MP",
        "Uttar Pradesh": "UP",
    }.get(state_name or "", state_name)
    if canonical_name is None:
        return None
    row = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = ?", (canonical_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _canonical_region_id(conn: sqlite3.Connection, region_name: str | None) -> int | None:
    """Return a seeded dimension identifier for a registry region name."""

    if region_name is None:
        return None
    row = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (region_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _upsert_dim_report(conn: sqlite3.Connection, date_id: int, report: sqlite3.Row) -> None:
    path = str(report["local_path"])
    conn.execute(
        "INSERT OR REPLACE INTO DimReports(DateID, ReportName, ReportPath, Source) VALUES (?, ?, ?, 'WRLDC')",
        (date_id, path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1], path),
    )


def _clear_wrldc_facts(conn: sqlite3.Connection, report_id: int) -> None:
    for table_name in (
        "FactWRLDCRegionalDaily",
        "FactWRLDCStateDaily",
        "FactWRLDCGenerationDaily",
        "FactWRLDCFrequencyDaily",
        "FactWRLDCVoltageProfile",
        "FactWRLDCReservoirDaily",
        "FactWRLDCInterRegionalExchange",
    ):
        conn.execute(f"DELETE FROM {table_name} WHERE ReportDocumentID = ?", (report_id,))
    conn.execute("DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?", (report_id,))


def _table_rows(conn: sqlite3.Connection, report_id: int, page_no: int, table_no: int) -> list[dict[int, tuple[int, str]]]:
    rows: dict[int, dict[int, tuple[int, str]]] = {}
    for raw_id, row_no, col_no, text in conn.execute(
        "SELECT id, row_no, col_no, cell_text FROM psp_raw_cell WHERE report_document_id = ? AND page_no = ? AND table_no = ? ORDER BY row_no, col_no",
        (report_id, page_no, table_no),
    ):
        rows.setdefault(int(row_no), {})[int(col_no)] = (int(raw_id), str(text))
    return [rows[key] for key in sorted(rows)]


def _table_row(conn: sqlite3.Connection, report_id: int, page_no: int, table_no: int, row_no: int) -> dict[int, tuple[int, str]]:
    return {int(col): (int(raw_id), str(text)) for raw_id, col, text in conn.execute(
        "SELECT id, col_no, cell_text FROM psp_raw_cell WHERE report_document_id = ? AND page_no = ? AND table_no = ? AND row_no = ?",
        (report_id, page_no, table_no, row_no),
    )}


def _section_rows(rows: list[dict[int, tuple[int, str]]], marker: str) -> list[dict[int, tuple[int, str]]]:
    active = False
    selected: list[dict[int, tuple[int, str]]] = []
    for row in rows:
        label = re.sub(r"\s+", "", _clean_label(row.get(1, (0, ""))[1]).lower())
        if label.startswith(marker):
            active = True
            continue
        if active and label.startswith(("2(a)", "2(b)", "2(c)")):
            break
        if active:
            selected.append(row)
    return selected


def _values(row: dict[int, tuple[int, str]], columns: dict[str, int]) -> tuple[dict[str, float | str | None], dict[str, int]]:
    values: dict[str, float | str | None] = {}
    sources: dict[str, int] = {}
    time_fields = {"MaximumDemandTime", "MaximumACETime", "MinimumACETime", "DayPeakTime", "MinimumGenerationTime"}
    for name, column in columns.items():
        raw = row.get(column)
        value = _time(raw[1]) if raw and name in time_fields else _float(raw[1]) if raw else None
        values[name] = value
        if raw and value is not None:
            sources[name] = raw[0]
    return values, sources


def _generation_values(
    row: dict[int, tuple[int, str]],
    columns: dict[str, int],
) -> tuple[dict[str, float | str | None], dict[str, int]]:
    """Map the verified generation columns for the report's template family."""
    return _values(row, columns)


def _generation_columns(template_id: str) -> dict[str, int]:
    """Return the approved state-generation layout for a WRLDC template."""
    if template_id in WRLDC_9_COLUMN_TEMPLATE_IDS:
        return _NINE_COLUMN_GENERATION_COLUMNS
    return _GENERATION_COLUMNS


def _upsert_state_daily(conn: sqlite3.Connection, report_id: int, date_id: int, state_id: int, values: dict[str, float | str | None]) -> None:
    columns = list(values)
    assignments = ", ".join(f"{column} = excluded.{column}" for column in columns)
    conn.execute(
        f"INSERT INTO FactWRLDCStateDaily(ReportDocumentID, DateID, StateID, {', '.join(columns)}) VALUES (?, ?, ?, {', '.join('?' for _ in columns)}) ON CONFLICT(ReportDocumentID, DateID, StateID) DO UPDATE SET {assignments}",
        (report_id, date_id, state_id, *(values[column] for column in columns)),
    )


def _insert_fact(conn: sqlite3.Connection, table: str, values: dict[str, object]) -> None:
    columns = list(values)
    conn.execute(
        f"INSERT OR REPLACE INTO {table}({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(values[column] for column in columns),
    )


def _resolve_state_id(conn: sqlite3.Connection, report_id: int, raw_name: str, record: bool = True) -> int | None:
    try:
        return resolve_state_id(conn, "wrldc", raw_name)
    except DimensionResolutionError:
        if record and raw_name:
            record_resolution_issue(conn, report_id, "wrldc", "state", raw_name, "state alias is not approved")
        return None


def _source_id(conn: sqlite3.Connection, label: str) -> int | None:
    normalized = re.sub(r"[^a-z]", "", label.lower())
    source_name = next((name for token, name in (("thermal", "Thermal"), ("hydel", "Hydro"), ("hydro", "Hydro"), ("gas", "Gas, Naptha & Diesel"), ("wind", "Wind"), ("solar", "Solar")) if token in normalized), None)
    if source_name is None:
        return None
    row = conn.execute("SELECT GenerationSourceID FROM DimGenerationSources WHERE SourceName = ?", (source_name,)).fetchone()
    return int(row[0]) if row else None


def _get_or_create_grid_entity(*args: object, **kwargs: object) -> int:
    from psp_pipeline.storage.sqlite_curated_promoter import _get_or_create_grid_entity as resolver
    return resolver(*args, **kwargs)


def _write_lineage(conn: sqlite3.Connection, report_id: int, table: str, key: str, sources: dict[str, int], mapped_cells: set[int]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for column, raw_cell_id in sources.items():
        conn.execute("INSERT OR IGNORE INTO curated_field_lineage(ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt) VALUES (?, ?, ?, ?, ?, 'pdfplumber', 1.0, ?)", (report_id, table, key, column, raw_cell_id, now))
        mapped_cells.add(raw_cell_id)


def _write_line_lineage(
    conn: sqlite3.Connection,
    report_id: int,
    table: str,
    key: str,
    sources: dict[str, int],
) -> None:
    """Record immutable provenance for values parsed from native PDF text lines."""

    now = datetime.now(timezone.utc).isoformat()
    for column, raw_line_id in sources.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO curated_field_lineage(
                ReportDocumentID, DestinationTable, DestinationKey,
                DestinationColumn, RawLineID, ExtractionMethod, Confidence,
                CreatedAt
            ) VALUES (?, ?, ?, ?, ?, 'pdfplumber_text', 1.0, ?)
            """,
            (report_id, table, key, column, raw_line_id, now),
        )


def _cell_float(row: dict[int, tuple[int, str]], column: int) -> float | None:
    raw = row.get(column)
    return _float(raw[1]) if raw else None


def _float(value: str) -> float | None:
    text = value.strip().replace(",", "").replace("−", "-")
    if not text or text.lower() in {"-", "--", "nil", "na", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _time(value: str) -> str | None:
    text = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        return f"{text}:00"
    if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", text):
        return text
    return None


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _is_total_row(value: str) -> bool:
    return re.sub(r"[^a-z]", "", value.lower()).startswith(("total", "subtotal"))


def _promote_physical_exchanges(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote verified 2025 Section 4(A) line-level exchanges."""

    in_section = False
    counterparty: str | None = None
    for page_no in (5, 6):
        for row in _table_rows(conn, report_id, page_no, 1):
            label = _clean_label(row.get(1, (0, ""))[1])
            normalized = re.sub(r"[^a-z0-9]", "", label.lower())
            if normalized.startswith("4a") and "interregional" in normalized:
                in_section = True
                continue
            if in_section and normalized.startswith("4b"):
                return
            if not in_section:
                continue
            counterparty = _counterparty_region(label) or counterparty
            name_cell = row.get(2)
            element_name = _clean_label(name_cell[1]) if name_cell else ""
            if counterparty is None or not _is_transmission_element(element_name):
                continue
            columns = (
                {
                    "EveningPeakMW": 7,
                    "OffPeakMW": 9,
                    "MaximumImportMW": 11,
                    "MaximumExportMW": 14,
                    "ImportEnergyMU": 17,
                    "ExportEnergyMU": 19,
                    "NetEnergyMU": 22,
                }
                if page_no == 5
                else {
                    "EveningPeakMW": 9,
                    "OffPeakMW": 11,
                    "MaximumImportMW": 13,
                    "MaximumExportMW": 16,
                    "ImportEnergyMU": 19,
                    "ExportEnergyMU": 22,
                    "NetEnergyMU": 25,
                }
            )
            values, sources = _values(row, columns)
            if not any(value is not None for value in values.values()):
                continue
            element_id = _get_or_create_transmission_element(conn, element_name)
            _insert_fact(
                conn,
                "FactWRLDCInterRegionalExchange",
                {
                    "ReportDocumentID": report_id,
                    "DateID": date_id,
                    "ElementID": element_id,
                    "CounterpartyRegion": counterparty,
                    **values,
                },
            )
            if name_cell:
                mapped_cells.add(name_cell[0])
            _write_lineage(
                conn,
                report_id,
                "FactWRLDCInterRegionalExchange",
                f"report={report_id};date={date_id};element={element_id};region={counterparty}",
                sources,
                mapped_cells,
            )


def _promote_voltage_profiles(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote 400 and 765 kV Section 6 monitoring-node profiles."""

    nominal_kv: float | None = None
    for page_no in (6, 7):
        for row in _table_rows(conn, report_id, page_no, 1):
            label = _clean_label(row.get(1, (0, ""))[1])
            normalized = re.sub(r"\s+", "", label.lower())
            match = re.search(r"voltageprofile:?(\d+)kv", normalized)
            if match:
                nominal_kv = float(match.group(1))
                continue
            if normalized.startswith("7a"):
                return
            node_nominal_kv = _nominal_voltage_from_node(label) or nominal_kv
            if node_nominal_kv is None or _is_total_row(label):
                continue
            values, sources = _values(
                row,
                {
                    "MaximumKV": 4,
                    "MinimumKV": 8,
                    "LowCriticalPct": 13,
                    "IEGCBandPct": 15,
                    "HighCriticalPct": 17,
                    "VoltageDeviationIndexPct": 19,
                },
            )
            values["MaximumTime"] = _time(row[6][1]) if row.get(6) else None
            values["MinimumTime"] = _time(row[10][1]) if row.get(10) else None
            for field_name, column in (("MaximumTime", 6), ("MinimumTime", 10)):
                raw = row.get(column)
                if raw and values[field_name] is not None:
                    sources[field_name] = raw[0]
            if values["MaximumKV"] is None or values["MinimumKV"] is None:
                continue
            node_id = _get_or_create_voltage_node(
                conn, label, node_nominal_kv, region_id
            )
            _insert_fact(
                conn,
                "FactWRLDCVoltageProfile",
                {
                    "ReportDocumentID": report_id,
                    "DateID": date_id,
                    "VoltageNodeID": node_id,
                    "NominalVoltageKV": node_nominal_kv,
                    **values,
                },
            )
            if row.get(1):
                mapped_cells.add(row[1][0])
            _write_lineage(
                conn,
                report_id,
                "FactWRLDCVoltageProfile",
                f"report={report_id};date={date_id};node={node_id}",
                sources,
                mapped_cells,
            )


def _promote_reservoirs(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote verified 2025 Section 8 major-reservoir measures."""

    in_section = False
    for row in _table_rows(conn, report_id, 8, 1):
        label = _clean_label(row.get(1, (0, ""))[1])
        normalized = re.sub(r"\s+", "", label.lower())
        if normalized.startswith("8.majorreservoir"):
            in_section = True
            continue
        if in_section and normalized.startswith("9."):
            return
        if not in_section or not label or _is_total_row(label):
            continue
        values, sources = _values(
            row,
            {
                "MinimumDrawdownLevelM": 2,
                "FullReservoirLevelM": 5,
                "DesignedEnergyMU": 8,
                "CurrentLevelM": 11,
                "CurrentEnergyMU": 13,
                "PreviousYearLevelM": 16,
                "PreviousYearEnergyMU": 18,
                "InflowMU": 21,
                "ProgressiveInflowMU": 26,
                "ProgressiveUsageMU": 29,
            },
        )
        if values["MinimumDrawdownLevelM"] is None or values["FullReservoirLevelM"] is None:
            continue
        reservoir_id = _get_or_create_reservoir(conn, label, region_id)
        _insert_fact(
            conn,
            "FactWRLDCReservoirDaily",
            {
                "ReportDocumentID": report_id,
                "DateID": date_id,
                "ReservoirID": reservoir_id,
                **values,
            },
        )
        if row.get(1):
            mapped_cells.add(row[1][0])
        _write_lineage(
            conn,
            report_id,
            "FactWRLDCReservoirDaily",
            f"report={report_id};date={date_id};reservoir={reservoir_id}",
            sources,
            mapped_cells,
        )


def _promote_frequency_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
) -> None:
    """Promote Section 5 frequency measures from their native text-line layout.

    The WRLDC PDF prints the extrema and the two IEGC-band measures as text
    lines rather than extractable table cells.  Their lineage is therefore
    retained through ``RawLineID`` instead of manufacturing a cell coordinate.
    """

    rows = conn.execute(
        """
        SELECT id, line_text
        FROM psp_raw_line
        WHERE report_document_id = ? AND page_no = 6
        ORDER BY line_no
        """,
        (report_id,),
    ).fetchall()
    values: dict[str, float | str | None] = {
        "MaximumFrequencyHz": None,
        "MaximumFrequencyTime": None,
        "MinimumFrequencyHz": None,
        "MinimumFrequencyTime": None,
        "AverageFrequencyHz": None,
        "FrequencyVariationIndex": None,
        "StandardDeviationHz": None,
        "Maximum15MinuteBlockFrequencyHz": None,
        "Minimum15MinuteBlockFrequencyHz": None,
        "PercentageOutsideIEGCBand": None,
        "HoursOutsideIEGCBand": None,
    }
    sources: dict[str, int] = {}
    for raw_line_id, line_text in rows:
        text = str(line_text or "")
        normalized = re.sub(r"\s+", "", text.lower())
        if "percentageoftimefrequencyremainedoutside" in normalized:
            value = _trailing_float(text)
            if value is not None:
                values["PercentageOutsideIEGCBand"] = value
                sources["PercentageOutsideIEGCBand"] = int(raw_line_id)
        elif "no.ofhoursfrequencyoutside" in normalized:
            value = _trailing_float(text)
            if value is not None:
                values["HoursOutsideIEGCBand"] = value
                sources["HoursOutsideIEGCBand"] = int(raw_line_id)

        extrema = _frequency_extrema_values(text)
        if extrema is not None:
            values.update(extrema)
            sources.update({field_name: int(raw_line_id) for field_name in extrema})

    if values["MaximumFrequencyHz"] is None or values["MinimumFrequencyHz"] is None:
        return
    _insert_fact(
        conn,
        "FactWRLDCFrequencyDaily",
        {
            "ReportDocumentID": report_id,
            "DateID": date_id,
            "RegionID": region_id,
            **values,
        },
    )
    _write_line_lineage(
        conn,
        report_id,
        "FactWRLDCFrequencyDaily",
        f"report={report_id};date={date_id};region={region_id}",
        sources,
    )


def _frequency_extrema_values(text: str) -> dict[str, float | str] | None:
    """Parse the one WRLDC Section 5 extrema line when its shape is verified."""

    tokens = re.findall(r"\d{1,2}:\d{2}(?::\d{2})?|[-−]?\d+(?:\.\d+)?", text)
    if len(tokens) != 9:
        return None
    maximum_time = _time(tokens[1])
    minimum_time = _time(tokens[3])
    numbers = [_float(token) for token in (tokens[0], tokens[2], *tokens[4:])]
    if maximum_time is None or minimum_time is None or any(value is None for value in numbers):
        return None
    maximum, minimum, average, fvi, standard_deviation, maximum_block, minimum_block = numbers
    if not (45.0 <= maximum <= 55.0 and 45.0 <= minimum <= 55.0):
        return None
    return {
        "MaximumFrequencyHz": float(maximum),
        "MaximumFrequencyTime": maximum_time,
        "MinimumFrequencyHz": float(minimum),
        "MinimumFrequencyTime": minimum_time,
        "AverageFrequencyHz": float(average),
        "FrequencyVariationIndex": float(fvi),
        "StandardDeviationHz": float(standard_deviation),
        "Maximum15MinuteBlockFrequencyHz": float(maximum_block),
        "Minimum15MinuteBlockFrequencyHz": float(minimum_block),
    }


def _trailing_float(text: str) -> float | None:
    """Return the final numeric token from a labelled report line."""

    values = re.findall(r"[-−]?\d+(?:\.\d+)?", text)
    return _float(values[-1]) if values else None


def _counterparty_region(label: str) -> str | None:
    """Return a neighbouring region named by a Section 4(A) group heading."""

    normalized = re.sub(r"[^a-z]", "", label.lower())
    for token, name in (
        ("northregion", "NR"),
        ("eastregion", "ER"),
        ("southregion", "SR"),
        ("northeasternregion", "NER"),
    ):
        if token in normalized:
            return name
    return None


def _is_transmission_element(label: str) -> bool:
    """Recognize a printed AC or HVDC transmission-element label."""

    return bool(re.search(r"(?:\d{3,4}\s*kv|hvdc)", label, re.IGNORECASE))


def _nominal_voltage_from_node(label: str) -> float | None:
    """Read the printed nominal voltage when a profile heading split across pages."""

    match = re.search(r"(\d{3,4})\s*kv", label, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _get_or_create_transmission_element(
    conn: sqlite3.Connection,
    name: str,
) -> int:
    """Resolve a WRLDC physical exchange element without inferring endpoints."""

    metadata = transmission_location(name)
    conn.execute(
        """
        INSERT OR IGNORE INTO DimTransmissionElements(
            ElementName, ElementType, NominalVoltageKV, FromRegionID,
            ToRegionID, FromStateID, ToStateID
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            metadata.element_type,
            metadata.nominal_voltage_kv,
            _canonical_region_id(conn, metadata.from_location.region_name),
            _canonical_region_id(conn, metadata.to_location.region_name),
            _canonical_state_id(conn, metadata.from_location.state_name),
            _canonical_state_id(conn, metadata.to_location.state_name),
        ),
    )
    return int(
        conn.execute(
            "SELECT ElementID FROM DimTransmissionElements WHERE ElementName = ?",
            (name,),
        ).fetchone()[0]
    )


def _get_or_create_voltage_node(
    conn: sqlite3.Connection,
    name: str,
    nominal_kv: float,
    region_id: int,
) -> int:
    """Resolve a WRLDC voltage node at a known nominal voltage level."""

    location = voltage_node_location(name)
    conn.execute(
        """
        INSERT OR IGNORE INTO DimVoltageNodes(
            NodeName, NominalVoltageKV, StateID, RegionID
        ) VALUES (?, ?, ?, ?)
        """,
        (
            name,
            nominal_kv,
            _canonical_state_id(conn, location.state_name),
            _canonical_region_id(conn, location.region_name) or region_id,
        ),
    )
    return int(
        conn.execute(
            """
            SELECT VoltageNodeID FROM DimVoltageNodes
            WHERE NodeName = ? AND NominalVoltageKV = ?
            """,
            (name, nominal_kv),
        ).fetchone()[0]
    )


def _get_or_create_reservoir(
    conn: sqlite3.Connection,
    name: str,
    region_id: int,
) -> int:
    """Resolve a known WRLDC reservoir and its approved state association."""

    state_names = {
        "indirasagar": "Madhya Pradesh",
        "omkareshwar": "Madhya Pradesh",
        "uk\u00e4i": "Gujarat",
        "ukai": "Gujarat",
        "kadana": "Gujarat",
        "ssp": "Gujarat",
        "koyna": "Maharashtra",
        "tatabhira": "Maharashtra",
    }
    normalized = re.sub(r"[^a-z]", "", name.lower())
    state_name = state_names.get(normalized)
    state_id = _resolve_state_id(conn, 0, state_name, record=False) if state_name else None
    conn.execute(
        """
        INSERT OR IGNORE INTO DimReservoirs(ReservoirName, StateID, RegionID)
        VALUES (?, ?, ?)
        """,
        (name, state_id, region_id),
    )
    return int(
        conn.execute(
            "SELECT ReservoirID FROM DimReservoirs WHERE ReservoirName = ?",
            (name,),
        ).fetchone()[0]
    )


def _validate_average_mw(
    conn: sqlite3.Connection,
    report_id: int,
    entity_name: str,
    values: dict[str, float | str | None],
) -> None:
    """Record an auditable warning when net energy and reported average disagree."""
    net_energy = values.get("NetEnergyMU")
    average_mw = values.get("AverageMW")
    if not isinstance(net_energy, float) or not isinstance(average_mw, float):
        return
    expected_average = net_energy * 1000.0 / 24.0
    tolerance = max(5.0, abs(expected_average) * 0.01)
    if abs(average_mw - expected_average) > tolerance:
        record_resolution_issue(
            conn,
            report_id,
            "wrldc",
            "generation_average_mw",
            entity_name,
            f"reported={average_mw};expected={expected_average:.2f};tolerance={tolerance:.2f}",
        )
