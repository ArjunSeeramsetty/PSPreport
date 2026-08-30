"""Promote raw Grid-India NLDC PSP cells into curated SQLite facts."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
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
    "EveningPeakDemandMetMW": ("Demand Met",),
    "PeakShortageMW": ("Shortage", "Shoratge"),
    "EnergyMetMU": ("Energy Met",),
    "HydroGenMU": ("Hydro Gen",),
    "WindGenMU": ("Wind Gen",),
    "SolarGenMU": ("Solar Gen",),
    "EnergyShortageMU": ("Energy Shortage",),
    "MaxDemandMetMW": ("Maximum Demand Met",),
    "TimeOfMaxDemand": ("Time Of Maximum Demand",),
}

LOGGER = logging.getLogger(__name__)
_GRID_SNAPSHOT_FIELDS = (
    ("NET TRANSNATIONAL EXCHANGE", "NetTransnationalExchangeMW"),
    ("TOTAL GENERATION", "TotalGenerationMW"),
    ("NET DEMAND MET", "NetDemandMetMW"),
    ("STORAGE DEMAND", "StorageDemandMW"),
    ("FREQUENCY", "FrequencyHz"),
    ("DEMAND MET", "DemandMetMW"),
    ("NUCLEAR", "NuclearGenerationMW"),
    ("WIND", "WindGenerationMW"),
    ("SOLAR", "SolarGenerationMW"),
    ("HYDRO", "HydroGenerationMW"),
    ("GAS", "GasGenerationMW"),
    ("THERMAL", "ThermalGenerationMW"),
    ("STORAGE", "StorageGenerationMW"),
    ("OTHERS", "OtherGenerationMW"),
)


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
        "FactNLDCDailyControlAreaDrawal",
        "FactNLDC15MinuteGridSnapshot",
        "FactNLDCCrossBorderExchangeDaily",
    ):
        conn.execute(f"DELETE FROM {table} WHERE ReportDocumentID = ?", (report_id,))
    conn.execute(
        "DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?",
        (report_id,),
    )
    _promote_regional_summary(conn, report_id, date_id)
    _promote_frequency(conn, report_id, date_id)
    _promote_control_area_drawal(conn, report_id, date_id)
    _promote_physical_exchanges(conn, report_id, date_id)
    _promote_15_minute_grid_snapshots(conn, report_id, date_id)
    _promote_cross_border_exchange(conn, report_id, date_id)


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
        for field, markers in _REGIONAL_COLUMNS.items():
            match = next(
                (
                    row
                    for row in rows[1:]
                    if any(
                        marker.upper()
                        in _normalized(row.get(1, (0, ""))[1])
                        for marker in markers
                    )
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


def _promote_control_area_drawal(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
) -> None:
    """Promote the NLDC state and control-area drawal matrix with lineage.

    The matrix contains both state grids and non-state demand entities such as
    railways and bulk consumers. Its grain is therefore a controlled grid
    entity within a reporting region, not ``StateID`` alone.
    """

    rows = _find_control_area_drawal_rows(conn, report_id)
    if len(rows) < 2:
        return
    current_region: tuple[int, str] | None = None
    for row in rows[1:]:
        region_label = _normalized(row.get(1, (0, ""))[1])
        if region_label in _REGION_NAMES:
            region_name = _REGION_NAMES[region_label]
            region = conn.execute(
                "SELECT RegionID FROM DimRegions WHERE RegionName = ?",
                (region_name,),
            ).fetchone()
            if region is not None:
                current_region = (int(region[0]), region_name)
        entity_name = row.get(2, (0, ""))[1].strip()
        if not entity_name or current_region is None:
            continue
        entity_id = _control_area_entity_id(
            conn,
            entity_name,
            current_region[0],
        )
        if entity_id is None:
            continue
        fields = {
            "MaximumDemandMetMW": _cell_number(row, 3),
            "MaximumDemandShortageMW": _cell_number(row, 4),
            "EnergyMetMU": _cell_number(row, 5),
            "DrawalScheduleMU": _cell_number(row, 6),
            "OverUnderDrawalMU": _cell_number(row, 7),
            "EnergyShortageMU": _cell_number(row, 9),
        }
        maximum_overdrawal, maximum_underdrawal, extrema_sources = (
            _drawal_extrema(row)
        )
        values = {
            field: value for field, (value, _) in fields.items() if value is not None
        }
        if maximum_overdrawal is not None:
            values["MaximumOverDrawalMW"] = maximum_overdrawal
        if maximum_underdrawal is not None:
            values["MaximumUnderDrawalMW"] = maximum_underdrawal
        if not values:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO FactNLDCDailyControlAreaDrawal("
            f"ReportDocumentID, DateID, EntityID, RegionID, {', '.join(values)}) "
            f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in values)})",
            (report_id, date_id, entity_id, current_region[0], *values.values()),
        )
        sources = {
            field: raw_id for field, (_, raw_id) in fields.items() if raw_id is not None
        }
        sources.update(extrema_sources)
        _lineage(
            conn,
            report_id,
            "FactNLDCDailyControlAreaDrawal",
            f"report={report_id};date={date_id};entity={entity_id};"
            f"region={current_region[0]}",
            sources,
        )


def _find_control_area_drawal_rows(
    conn: sqlite3.Connection,
    report_id: int,
) -> list[dict[int, tuple[int, str]]]:
    """Locate the control-area matrix by its invariant header signature."""

    locations = conn.execute(
        "SELECT DISTINCT page_no, table_no FROM psp_raw_cell "
        "WHERE report_document_id = ? AND page_no IN (1, 2) "
        "ORDER BY page_no, table_no",
        (report_id,),
    ).fetchall()
    for page_no, table_no in locations:
        rows = _table_rows(conn, report_id, int(page_no), int(table_no))
        if not rows:
            continue
        header = rows[0]
        labels = " ".join(_normalized(cell[1]) for cell in header.values())
        if (
            _normalized(header.get(1, (0, ""))[1]) == "REGION"
            and _normalized(header.get(2, (0, ""))[1]) == "STATES"
            and "DRAWAL SCHEDULE" in labels
            and "ENERGY MET" in labels
        ):
            return rows
    return []


def _control_area_entity_id(
    conn: sqlite3.Connection,
    entity_name: str,
    region_id: int,
) -> int | None:
    """Resolve or create one source-published control-area dimension entity."""

    row = conn.execute(
        "SELECT EntityID FROM DimGridEntities "
        "WHERE EntityName = ? AND EntityType = 'control_area' AND RegionID = ? "
        "ORDER BY EntityID LIMIT 1",
        (entity_name, region_id),
    ).fetchone()
    if row is not None:
        return int(row[0])
    conn.execute(
        "INSERT INTO DimGridEntities(EntityName, EntityType, RegionID) "
        "VALUES (?, 'control_area', ?)",
        (entity_name, region_id),
    )
    row = conn.execute(
        "SELECT EntityID FROM DimGridEntities "
        "WHERE EntityName = ? AND EntityType = 'control_area' AND RegionID = ? "
        "ORDER BY EntityID DESC LIMIT 1",
        (entity_name, region_id),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _drawal_extrema(
    row: dict[int, tuple[int, str]],
) -> tuple[float | None, float | None, dict[str, int]]:
    """Read legacy Max OD and modern signed Max OD/UD values from column eight."""

    cell = row.get(8)
    if cell is None:
        return None, None, {}
    raw_id, raw_text = cell
    values = [
        float(value)
        for value in re.findall(r"[+-]?\d+(?:\.\d+)?", raw_text.replace(",", ""))
    ]
    if not values:
        return None, None, {}
    sources = {"MaximumOverDrawalMW": raw_id}
    if len(values) == 1:
        return values[0], None, sources
    sources["MaximumUnderDrawalMW"] = raw_id
    return values[0], values[1], sources


def _promote_physical_exchanges(
    conn: sqlite3.Connection, report_id: int, date_id: int
) -> None:
    rows = _table_rows(conn, report_id, page_no=3, table_no=1)
    if len(rows) < 2:
        return
    counterparty = ""
    for row in rows[1:]:
        label = row.get(1, (0, ""))[1].strip()
        if _normalized(label).startswith("INTERNATIONAL EXCHANGES"):
            # The remainder of the page is a different country-exchange table
            # with a distinct column contract and is intentionally gated.
            break
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


def _promote_15_minute_grid_snapshots(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
) -> None:
    """Promote a verified NLDC 96-block SCADA grid snapshot table.

    The table is accepted only when its invariant title, time column, and all
    96 published quarter-hour rows are present. The 2025 and 2026 variants
    differ only by optional storage demand/generation fields.
    """

    rows = _find_grid_snapshot_rows(conn, report_id)
    if not rows:
        return
    header = next(
        (row for row in rows if _is_grid_snapshot_header(row)),
        None,
    )
    if header is None:
        return
    columns = _grid_snapshot_columns(header)
    if not {"FrequencyHz", "DemandMetMW"}.issubset(columns.values()):
        return

    blocks = [row for row in rows if _block_start_time(row.get(1, (0, ""))[1])]
    if len(blocks) != 96:
        LOGGER.warning(
            "NLDC grid snapshot gate rejected report %s: expected 96 blocks, found %s",
            report_id,
            len(blocks),
        )
        return
    for row in blocks:
        time_raw_id, time_text = row[1]
        block_start = _block_start_time(time_text)
        if block_start is None:
            continue
        values: dict[str, float | str] = {"BlockStartTime": block_start}
        sources: dict[str, int] = {"BlockStartTime": time_raw_id}
        for column_no, field in columns.items():
            value, raw_id = _cell_number(row, column_no)
            if value is not None:
                values[field] = value
            if raw_id is not None:
                sources[field] = raw_id
        if len(values) == 1:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO FactNLDC15MinuteGridSnapshot("
            f"ReportDocumentID, DateID, {', '.join(values)}) "
            f"VALUES (?, ?, {', '.join('?' for _ in values)})",
            (report_id, date_id, *values.values()),
        )
        _lineage(
            conn,
            report_id,
            "FactNLDC15MinuteGridSnapshot",
            f"report={report_id};date={date_id};block={block_start}",
            sources,
        )


def _find_grid_snapshot_rows(
    conn: sqlite3.Connection,
    report_id: int,
) -> list[dict[int, tuple[int, str]]]:
    """Locate the 15-minute SCADA table by its invariant title text."""

    locations = conn.execute(
        "SELECT DISTINCT page_no, table_no FROM psp_raw_cell "
        "WHERE report_document_id = ? ORDER BY page_no, table_no",
        (report_id,),
    ).fetchall()
    for page_no, table_no in locations:
        rows = _table_rows(conn, report_id, int(page_no), int(table_no))
        table_text = "".join(
            _grid_heading_key(text)
            for row in rows[:4]
            for _, text in row.values()
        )
        if (
            "15MIN" in table_text
            and "ALLINDIAGRIDFREQUENCY" in table_text
            and "TOTALGENERATION" in table_text
        ):
            return rows
    return []


def _is_grid_snapshot_header(row: dict[int, tuple[int, str]]) -> bool:
    """Return whether a raw row is the published snapshot metric header."""

    text = "".join(_grid_heading_key(value) for _, value in row.values())
    return "TIME" in text and "FREQUENCY" in text and "DEMANDMET" in text


def _grid_snapshot_columns(
    header: dict[int, tuple[int, str]],
) -> dict[int, str]:
    """Map published metric headings to canonical snapshot fields."""

    columns: dict[int, str] = {}
    for column_no, (_, text) in header.items():
        normalized = _grid_heading_key(text)
        if normalized == "TIME":
            continue
        for marker, field in _GRID_SNAPSHOT_FIELDS:
            marker_key = _grid_heading_key(marker)
            if marker_key in normalized:
                if marker_key == "STORAGE" and "DEMAND" in normalized:
                    continue
                columns[column_no] = field
                break
    return columns


def _grid_heading_key(value: str) -> str:
    """Return a resilient key for wrapped NLDC snapshot headings."""

    return re.sub(r"[^A-Z0-9]+", "", _normalized(value))


def _promote_cross_border_exchange(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
) -> None:
    """Promote NLDC's page-four cross-border export, import, and net MU tables."""

    directions = ((1, "export"), (2, "import"), (3, "net"))
    fields = (
        "GNAMU", "TGNABilateralMU", "IEXIDAMMU", "PXILIDAMMU",
        "HPXIDAMMU", "IEXRTMMU", "PXILRTMMU", "HPXRTMMU", "TotalMU",
    )
    for table_no, direction in directions:
        rows = _table_rows(conn, report_id, page_no=4, table_no=table_no)
        if len(rows) != 9 or _normalized(rows[0].get(1, (0, ""))[1]) != "COUNTRY":
            continue
        for row in rows[4:]:
            country_name = row.get(1, (0, ""))[1].strip()
            if not country_name:
                continue
            country_id = _country_id(conn, country_name)
            values: dict[str, float] = {}
            sources: dict[str, int] = {}
            for column_no, field in enumerate(fields, start=2):
                value, raw_id = _cell_number(row, column_no)
                if value is not None:
                    values[field] = value
                if raw_id is not None:
                    sources[field] = raw_id
            if not values:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO FactNLDCCrossBorderExchangeDaily("
                f"ReportDocumentID, DateID, CountryID, Direction, {', '.join(values)}) "
                f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in values)})",
                (report_id, date_id, country_id, direction, *values.values()),
            )
            _lineage(
                conn,
                report_id,
                "FactNLDCCrossBorderExchangeDaily",
                f"report={report_id};date={date_id};country={country_id};direction={direction}",
                sources,
            )


def _country_id(conn: sqlite3.Connection, country_name: str) -> int:
    """Resolve a published country or total row without discarding its grain."""

    conn.execute("INSERT OR IGNORE INTO DimCountries(CountryName) VALUES (?)", (country_name,))
    row = conn.execute(
        "SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country_name,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Unable to resolve NLDC cross-border entity: {country_name}")
    return int(row[0])


def _block_start_time(value: str) -> str | None:
    """Normalize a published quarter-hour label to a stable HH:MM key."""

    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*", value)
    if match is None:
        return None
    hour, minute = (int(match.group(1)), int(match.group(2)))
    if hour > 23 or minute > 59 or minute % 15 != 0:
        return None
    return f"{hour:02d}:{minute:02d}"


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
