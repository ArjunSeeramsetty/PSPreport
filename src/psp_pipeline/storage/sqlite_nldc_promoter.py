"""Promote raw Grid-India NLDC PSP cells into curated SQLite facts."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3


_REGION_NAMES = {
    "NR": "Northern Region",
    "WR": "Western Region",
    "SR": "Southern Region",
    "ER": "Eastern Region",
    "NER": "North Eastern Region",
}
_REGIONAL_COLUMNS = {
    "EveningPeakDemandMetMW": "Demand Met",
    "PeakShortageMW": "Shortage",
    "EnergyMetMU": "Energy Met",
    "HydroGenMU": "Hydro Gen",
    "WindGenMU": "Wind Gen",
    "SolarGenMU": "Solar Gen",
    "EnergyShortageMU": "Energy Shortage",
    "MaxDemandMetMW": "Maximum Demand Met",
    "TimeOfMaxDemand": "Time Of Maximum Demand",
}


def promote_nldc_report_to_curated(conn: sqlite3.Connection, report_id: int) -> None:
    """Promote one persisted Grid-India NLDC report with exact raw-cell lineage.

    Unsupported or incomplete documents are skipped without creating partial
    curated rows. Page two supplies national, regional, and frequency facts;
    page three supplies physical inter-regional line flows.
    """

    report = conn.execute(
        "SELECT rldc, report_date FROM psp_report_document WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not report or str(report[0]) != "grid_india_national" or not report[1]:
        return
    date_id = _date_id(conn, str(report[1]))
    if date_id is None:
        return
    for table in (
        "FactNLDCDailyNational",
        "FactNLDCDailyRegional",
        "FactNLDCDailyFrequency",
        "FactNLDCDailyInterRegionalExchange",
    ):
        conn.execute(f"DELETE FROM {table} WHERE ReportDocumentID = ?", (report_id,))
    conn.execute(
        "DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?",
        (report_id,),
    )
    _promote_regional_summary(conn, report_id, date_id)
    _promote_frequency(conn, report_id, date_id)
    _promote_physical_exchanges(conn, report_id, date_id)


def _date_id(conn: sqlite3.Connection, report_date: str) -> int | None:
    """Resolve the canonical date dimension for a source report date."""

    conn.execute("INSERT OR IGNORE INTO DimDates(ActualDate) VALUES (?)", (report_date,))
    row = conn.execute(
        "SELECT DateID FROM DimDates WHERE ActualDate = ?", (report_date,)
    ).fetchone()
    return int(row[0]) if row else None


def _table_rows(
    conn: sqlite3.Connection,
    report_id: int,
    page_no: int,
    table_no: int,
) -> list[dict[int, tuple[int, str]]]:
    """Return one persisted raw table as row and column maps with raw IDs."""

    rows: dict[int, dict[int, tuple[int, str]]] = {}
    for raw_id, row_no, col_no, cell_text in conn.execute(
        "SELECT id, row_no, col_no, cell_text FROM psp_raw_cell "
        "WHERE report_document_id = ? AND page_no = ? AND table_no = ? "
        "ORDER BY row_no, col_no",
        (report_id, page_no, table_no),
    ):
        rows.setdefault(int(row_no), {})[int(col_no)] = (
            int(raw_id),
            str(cell_text or ""),
        )
    return [rows[key] for key in sorted(rows)]


def _cell_number(
    row: dict[int, tuple[int, str]], col_no: int
) -> tuple[float | None, int | None]:
    """Return a numeric raw-cell value and its stable raw ID."""

    cell = row.get(col_no)
    if cell is None:
        return None, None
    text = cell[1].replace(",", "").strip()
    if not text or text in {"-", "--", "N/A"}:
        return None, cell[0]
    try:
        return float(text), cell[0]
    except ValueError:
        return None, cell[0]


def _lineage(
    conn: sqlite3.Connection,
    report_id: int,
    table: str,
    destination_key: str,
    sources: dict[str, int],
) -> None:
    """Persist cell-level source lineage for one curated fact row."""

    now = datetime.now(timezone.utc).isoformat()
    for column, raw_id in sources.items():
        conn.execute(
            "INSERT OR IGNORE INTO curated_field_lineage("
            "ReportDocumentID, DestinationTable, DestinationKey, "
            "DestinationColumn, RawCellID, ExtractionMethod, Confidence, "
            "CreatedAt) VALUES (?, ?, ?, ?, ?, 'pdfplumber', 1.0, ?)",
            (report_id, table, destination_key, column, raw_id, now),
        )


def _normalized(value: str) -> str:
    """Return a compact comparison form for PSP headings."""

    return " ".join(value.replace("\n", " ").upper().split())


def _promote_regional_summary(
    conn: sqlite3.Connection, report_id: int, date_id: int
) -> None:
    rows = _table_rows(conn, report_id, page_no=2, table_no=1)
    if len(rows) < 2:
        return
    headers = {_normalized(text): col for col, (_, text) in rows[0].items()}
    for abbrev, region_name in (*_REGION_NAMES.items(), ("TOTAL", "All India")):
        col = headers.get(abbrev)
        if col is None:
            continue
        values: dict[str, float | str] = {}
        sources: dict[str, int] = {}
        for field, marker in _REGIONAL_COLUMNS.items():
            match = next(
                (
                    row
                    for row in rows[1:]
                    if marker.upper() in _normalized(row.get(1, (0, ""))[1])
                ),
                None,
            )
            if match is None:
                continue
            raw_id, raw_text = match.get(col, (None, ""))
            if field == "TimeOfMaxDemand":
                value = raw_text.strip() or None
                if value:
                    values[field] = value
            else:
                value, numeric_raw_id = _cell_number(match, col)
                if value is not None:
                    values[field] = value
                raw_id = numeric_raw_id
            if raw_id is not None:
                sources[field] = int(raw_id)
        if not values:
            continue
        if abbrev == "TOTAL":
            conn.execute(
                "INSERT OR REPLACE INTO FactNLDCDailyNational("
                f"ReportDocumentID, DateID, {', '.join(values)}) "
                f"VALUES (?, ?, {', '.join('?' for _ in values)})",
                (report_id, date_id, *values.values()),
            )
            _lineage(
                conn,
                report_id,
                "FactNLDCDailyNational",
                f"report={report_id};date={date_id}",
                sources,
            )
            continue
        region = conn.execute(
            "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (region_name,)
        ).fetchone()
        if region is None:
            continue
        region_id = int(region[0])
        conn.execute(
            "INSERT OR REPLACE INTO FactNLDCDailyRegional("
            f"ReportDocumentID, DateID, RegionID, {', '.join(values)}) "
            f"VALUES (?, ?, ?, {', '.join('?' for _ in values)})",
            (report_id, date_id, region_id, *values.values()),
        )
        _lineage(
            conn,
            report_id,
            "FactNLDCDailyRegional",
            f"report={report_id};date={date_id};region={region_id}",
            sources,
        )


def _promote_frequency(conn: sqlite3.Connection, report_id: int, date_id: int) -> None:
    rows = _table_rows(conn, report_id, page_no=2, table_no=2)
    if len(rows) < 2 or _normalized(rows[1].get(1, (0, ""))[1]) != "ALL INDIA":
        return
    mapping = {
        "FVI": 2,
        "Below_49_7": 3,
        "From_49_7_to_49_8": 4,
        "From_49_8_to_49_9": 5,
        "Below_49_9": 6,
        "From_49_9_to_50_05": 7,
        "Above_50_05": 8,
    }
    values: dict[str, float] = {}
    sources: dict[str, int] = {}
    for field, col in mapping.items():
        value, raw_id = _cell_number(rows[1], col)
        if value is not None:
            values[field] = value
        if raw_id is not None:
            sources[field] = raw_id
    if not values:
        return
    conn.execute(
        "INSERT OR REPLACE INTO FactNLDCDailyFrequency("
        f"ReportDocumentID, DateID, {', '.join(values)}) "
        f"VALUES (?, ?, {', '.join('?' for _ in values)})",
        (report_id, date_id, *values.values()),
    )
    _lineage(
        conn,
        report_id,
        "FactNLDCDailyFrequency",
        f"report={report_id};date={date_id}",
        sources,
    )


def _promote_physical_exchanges(
    conn: sqlite3.Connection, report_id: int, date_id: int
) -> None:
    rows = _table_rows(conn, report_id, page_no=3, table_no=1)
    if len(rows) < 2:
        return
    counterparty = ""
    for row in rows[1:]:
        label = row.get(1, (0, ""))[1].strip()
        section = re.fullmatch(r"Import/Export of (.+?) \(With (.+?)\)", label, re.I)
        if section:
            counterparty = _counterparty_region(section.group(2))
            continue
        line_name = row.get(3, (0, ""))[1].strip()
        if not line_name or not counterparty:
            continue
        voltage_level = row.get(2, (0, ""))[1].strip() or None
        circuit_count, circuit_raw_id = _integer_cell(row, 4)
        fields = {
            "MaxImportMW": _cell_number(row, 5),
            "MaxExportMW": _cell_number(row, 6),
            "ImportMU": _cell_number(row, 7),
            "ExportMU": _cell_number(row, 8),
            "NetMU": _cell_number(row, 9),
        }
        values = {
            field: value for field, (value, _) in fields.items() if value is not None
        }
        if not values:
            continue
        element_id = _element_id(conn, line_name, voltage_level, circuit_count)
        if element_id is None:
            continue
        if voltage_level:
            values["VoltageLevel"] = voltage_level
        if circuit_count is not None:
            values["CircuitCount"] = circuit_count
        conn.execute(
            "INSERT OR REPLACE INTO FactNLDCDailyInterRegionalExchange("
            f"ReportDocumentID, DateID, ElementID, CounterpartyRegion, {', '.join(values)}) "
            f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in values)})",
            (report_id, date_id, element_id, counterparty, *values.values()),
        )
        sources = {
            field: raw_id for field, (_, raw_id) in fields.items() if raw_id is not None
        }
        if circuit_raw_id is not None:
            sources["CircuitCount"] = circuit_raw_id
        if voltage_level:
            sources["VoltageLevel"] = row[2][0]
        _lineage(
            conn,
            report_id,
            "FactNLDCDailyInterRegionalExchange",
            f"report={report_id};date={date_id};element={element_id};counterparty={counterparty}",
            sources,
        )


def _counterparty_region(value: str) -> str:
    """Normalize a page-three counterpart label without guessing unknown text."""

    compact = _normalized(value).replace(" ", "")
    return {
        "NR": "Northern Region",
        "WR": "Western Region",
        "SR": "Southern Region",
        "ER": "Eastern Region",
        "NER": "North Eastern Region",
    }.get(compact, value.strip())


def _integer_cell(
    row: dict[int, tuple[int, str]], col_no: int
) -> tuple[int | None, int | None]:
    """Return an integer circuit count when the published cell is numeric."""

    value, raw_id = _cell_number(row, col_no)
    if value is None or not value.is_integer():
        return None, raw_id
    return int(value), raw_id


def _element_id(
    conn: sqlite3.Connection,
    element_name: str,
    voltage_level: str | None,
    circuit_count: int | None,
) -> int | None:
    """Resolve a physical tie line into the controlled transmission dimension."""

    nominal = _nominal_voltage_kv(voltage_level)
    conn.execute(
        "INSERT OR IGNORE INTO DimTransmissionElements("
        "ElementName, ElementType, NominalVoltageKV, CircuitCount) VALUES (?, ?, ?, ?)",
        (element_name, "hvdc" if voltage_level == "HVDC" else "line", nominal, circuit_count),
    )
    row = conn.execute(
        "SELECT ElementID FROM DimTransmissionElements WHERE ElementName = ?",
        (element_name,),
    ).fetchone()
    return int(row[0]) if row else None


def _nominal_voltage_kv(voltage_level: str | None) -> float | None:
    """Extract a numeric nominal voltage from NLDC's published label."""

    if not voltage_level:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*KV", voltage_level, re.I)
    return float(match.group(1)) if match else None
