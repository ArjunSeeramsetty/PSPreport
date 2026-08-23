"""Promote verified NRLDC daily PSP sections into curated SQLite facts."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3

from psp_pipeline.parsing.rldc.templates import (
    NRLDC_2024_TEMPLATE,
    NRLDC_2025_TEMPLATE,
    NRLDC_2026_TEMPLATE,
)
from psp_pipeline.storage.sqlite_dimensions import (
    DimensionResolutionError,
    record_resolution_issue,
    resolve_generation_identity,
    resolve_state_id,
)


NR_REGION_NAME = "Northern Region"
NRLDC_TEMPLATE_IDS = frozenset(
    (
        NRLDC_2024_TEMPLATE.template_id,
        NRLDC_2025_TEMPLATE.template_id,
        NRLDC_2026_TEMPLATE.template_id,
    )
)

_REGIONAL_COLUMNS = {
    NRLDC_2024_TEMPLATE.template_id: {
        "EveningPeakDemandMetMW": 1,
        "EveningPeakShortageMW": 3,
        "EveningPeakRequirementMW": 7,
        "EveningPeakFrequencyHz": 9,
        "OffPeakDemandMetMW": 12,
        "OffPeakShortageMW": 15,
        "OffPeakRequirementMW": 20,
        "OffPeakFrequencyHz": 23,
        "DayEnergyMetMU": 28,
        "DayEnergyShortageMU": 35,
    },
    NRLDC_2025_TEMPLATE.template_id: {
        "EveningPeakDemandMetMW": 1,
        "EveningPeakShortageMW": 3,
        "EveningPeakRequirementMW": 7,
        "EveningPeakFrequencyHz": 10,
        "OffPeakDemandMetMW": 13,
        "OffPeakShortageMW": 16,
        "OffPeakRequirementMW": 21,
        "OffPeakFrequencyHz": 27,
        "DayEnergyMetMU": 30,
        "DayEnergyShortageMU": 37,
    },
    NRLDC_2026_TEMPLATE.template_id: {
        "EveningPeakDemandMetMW": 1,
        "EveningPeakShortageMW": 3,
        "EveningPeakRequirementMW": 7,
        "EveningPeakFrequencyHz": 10,
        "OffPeakDemandMetMW": 13,
        "OffPeakShortageMW": 16,
        "OffPeakRequirementMW": 21,
        "OffPeakFrequencyHz": 27,
        "DayEnergyMetMU": 30,
        "DayEnergyShortageMU": 37,
    },
}

_STATE_POSITION_COLUMNS = {
    NRLDC_2024_TEMPLATE.template_id: {
        "ThermalGenerationMU": 4,
        "HydroGenerationMU": 6,
        "GasNapthaDieselGenerationMU": 8,
        "SolarGenerationMU": 10,
        "WindGenerationMU": 13,
        "OtherGenerationMU": 16,
        "TotalGenerationMU": 21,
        "ScheduledDrawalMU": 22,
        "ActualDrawalMU": 25,
        "UIMU": 29,
        "RequirementMU": 32,
        "EnergyShortageMU": 35,
        "ConsumptionMU": 37,
    },
    NRLDC_2025_TEMPLATE.template_id: {
        "ThermalGenerationMU": 4,
        "HydroGenerationMU": 6,
        "GasNapthaDieselGenerationMU": 8,
        "SolarGenerationMU": 11,
        "WindGenerationMU": 14,
        "OtherGenerationMU": 17,
        "TotalGenerationMU": 22,
        "ScheduledDrawalMU": 24,
        "ActualDrawalMU": 28,
        "UIMU": 31,
        "RequirementMU": 34,
        "EnergyShortageMU": 37,
        "ConsumptionMU": 39,
    },
    NRLDC_2026_TEMPLATE.template_id: {
        "ThermalGenerationMU": 4,
        "HydroGenerationMU": 6,
        "GasNapthaDieselGenerationMU": 8,
        "SolarGenerationMU": 11,
        "WindGenerationMU": 14,
        "OtherGenerationMU": 17,
        "TotalGenerationMU": 22,
        "ScheduledDrawalMU": 24,
        "ActualDrawalMU": 28,
        "UIMU": 31,
        "RequirementMU": 34,
        "EnergyShortageMU": 37,
        "ConsumptionMU": 39,
    },
}

_GENERATION_COLUMNS = {
    NRLDC_2024_TEMPLATE.template_id: {
        "InstalledCapacityMW": 2,
        "EveningPeakMW": 3,
        "OffPeakMW": 4,
        "DayPeakMW": 5,
        "DayPeakTime": 6,
        "GrossEnergyMU": 7,
        "NetEnergyMU": 8,
        "AverageMW": 9,
    },
    NRLDC_2025_TEMPLATE.template_id: {
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
    },
    NRLDC_2026_TEMPLATE.template_id: {
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
    },
}


def promote_nrldc_report_to_curated(
    conn: sqlite3.Connection,
    report_document_id: int,
) -> None:
    """Promote verified NRLDC regional, state, and generation sections."""
    from psp_pipeline.storage.sqlite_curated_promoter import (
        _fetch_report,
        _get_or_create_date_id,
        _record_unrecognized_report,
    )

    report = _fetch_report(conn, report_document_id)
    if not report or report["rldc"] != "nrldc":
        return
    template_id = str(report.get("template_id") or "")
    if template_id not in NRLDC_TEMPLATE_IDS or _has_curated_scope_deviation(report):
        _clear_nrldc_curated_report(conn, report_document_id)
        _record_unrecognized_report(conn, report_document_id, report)
        return

    date_id = _get_or_create_date_id(conn, report["report_date"])
    region_id = _lookup_region_id(conn)
    if date_id is None or region_id is None:
        return

    _upsert_dim_report(conn, date_id, report)
    _clear_nrldc_curated_report(conn, report_document_id)

    mapped_cells: set[int] = set()
    validation_failures = 0
    _promote_regional_daily(
        conn, report_document_id, date_id, region_id, template_id, mapped_cells
    )
    validation_failures += _promote_state_daily(
        conn, report_document_id, date_id, template_id, mapped_cells
    )
    validation_failures += _promote_state_generation(
        conn, report_document_id, date_id, region_id, template_id, mapped_cells
    )
    _record_initial_coverage(
        conn, report_document_id, template_id, mapped_cells, validation_failures
    )


def _has_curated_scope_deviation(report: sqlite3.Row) -> bool:
    """Return whether template drift affects sections promoted by this module.

    This promoter owns regional, state-position, and station-generation data on
    pages 1 through 4. Differences in later sections remain visible on the
    report record but do not discard verified facts from this stable scope.
    """

    if not report["semantic_pass_required"]:
        return False
    reason = str(report.get("structure_deviation_reason") or "")
    return bool(re.search(r"(?:p[1-4]_t|missing_table=p[1-4]_)", reason))


def _clear_nrldc_curated_report(
    conn: sqlite3.Connection,
    report_document_id: int,
) -> None:
    """Remove NRLDC facts and coverage that an updated gate no longer permits."""

    coverage = conn.execute(
        "SELECT CoverageRunID FROM schema_coverage_run WHERE ReportDocumentID = ?",
        (report_document_id,),
    ).fetchone()
    if coverage:
        conn.execute(
            "DELETE FROM schema_coverage_item WHERE CoverageRunID = ?",
            (coverage[0],),
        )
        conn.execute(
            "DELETE FROM schema_coverage_run WHERE CoverageRunID = ?",
            (coverage[0],),
        )
    conn.execute(
        "DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?",
        (report_document_id,),
    )
    conn.execute(
        "DELETE FROM FactNRLDCRegionalDaily WHERE ReportDocumentID = ?",
        (report_document_id,),
    )
    conn.execute(
        "DELETE FROM FactNRLDCStateDaily WHERE ReportDocumentID = ?",
        (report_document_id,),
    )
    conn.execute(
        "DELETE FROM FactNRLDCGenerationDaily WHERE ReportDocumentID = ?",
        (report_document_id,),
    )


def repromote_nrldc_reports(conn: sqlite3.Connection) -> dict[str, int]:
    """Replay eligible NRLDC reports from persisted raw cells into curated facts.

    This is intentionally independent of PDF extraction. It lets an operator
    apply a corrected field mapping to an existing local SQLite corpus while
    preserving each report's immutable raw-cell lineage.
    """

    reports = conn.execute(
        """
        SELECT id
        FROM psp_report_document
        WHERE rldc = 'nrldc'
          AND template_id IN (?, ?, ?)
        ORDER BY report_date, id
        """,
        tuple(sorted(NRLDC_TEMPLATE_IDS)),
    ).fetchall()
    for (report_document_id,) in reports:
        promote_nrldc_report_to_curated(conn, int(report_document_id))
    return {"reports_repromoted": len(reports)}


def _promote_regional_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    """Promote Section 1 regional demand, shortage, energy, and frequency values."""
    row = _table_row(conn, report_id, 1, 1, 4)
    if not row:
        return
    values, sources = _mapped_values(row, _REGIONAL_COLUMNS[template_id])
    columns = list(values)
    conn.execute(
        f"""
        INSERT OR REPLACE INTO FactNRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, {', '.join(columns)}
        ) VALUES (?, ?, ?, {', '.join('?' for _ in columns)})
        """,
        (report_id, date_id, region_id, *(values[column] for column in columns)),
    )
    key = f"report={report_id};date={date_id};region={region_id}"
    _write_lineage(
        conn, report_id, "FactNRLDCRegionalDaily", key, sources, mapped_cells
    )


def _promote_state_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> int:
    """Promote Section 2(A) state generation and drawal balances."""
    validation_failures = 0
    for row in _state_position_rows(conn, report_id):
        state_cell = row.get(1)
        state_name = state_cell[1].strip() if state_cell else ""
        state_id = _resolve_state_id(conn, report_id, state_name)
        if state_id is None:
            continue
        values, sources = _mapped_values(row, _STATE_POSITION_COLUMNS[template_id])
        if not any(value is not None for value in values.values()):
            continue
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCStateDaily(
                ReportDocumentID, DateID, StateID, {', '.join(values)}
            ) VALUES (?, ?, ?, {', '.join('?' for _ in values)})
            """,
            (report_id, date_id, state_id, *values.values()),
        )
        if state_cell:
            mapped_cells.add(state_cell[0])
        key = f"report={report_id};date={date_id};state={state_id}"
        _write_lineage(
            conn, report_id, "FactNRLDCStateDaily", key, sources, mapped_cells
        )
        component_columns = (
            "ThermalGenerationMU",
            "HydroGenerationMU",
            "GasNapthaDieselGenerationMU",
            "SolarGenerationMU",
            "WindGenerationMU",
            "OtherGenerationMU",
        )
        components = [values[column] for column in component_columns]
        total = values["TotalGenerationMU"]
        if total is not None and all(value is not None for value in components):
            if abs(sum(float(value) for value in components) - float(total)) > 0.05:
                validation_failures += 1
    return validation_failures


def _state_position_rows(
    conn: sqlite3.Connection,
    report_id: int,
) -> list[dict[int, tuple[int, str]]]:
    """Return only Section 2(A) state-balance rows from page one."""
    rows: list[dict[int, tuple[int, str]]] = []
    in_section = False
    for row in _table_rows(conn, report_id, 1, 1):
        label = _clean_label(row.get(1, (0, ""))[1]).lower()
        compact_label = re.sub(r"\s+", "", label)
        if compact_label.startswith("2(a)"):
            in_section = True
            continue
        if in_section and compact_label.startswith(("2(b)", "2(c)")):
            break
        if in_section:
            rows.append(row)
    return rows


def _promote_state_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> int:
    """Promote the verified state-entity generation tables on pages two through four."""
    validation_failures = 0
    for page_no in (2, 3, 4):
        current_state_id: int | None = None
        for row in _table_rows(conn, report_id, page_no, 1):
            entity_cell = row.get(1)
            entity_name = _clean_label(entity_cell[1]) if entity_cell else ""
            candidate_state_id = _resolve_state_id(conn, report_id, entity_name, record=False)
            if candidate_state_id is not None and _cell_float(row, 2) is None:
                current_state_id = candidate_state_id
                if entity_cell:
                    mapped_cells.add(entity_cell[0])
                continue
            if current_state_id is None or not entity_name:
                continue

            values, sources = _generation_values(row, _GENERATION_COLUMNS[template_id])
            capacity = values["InstalledCapacityMW"]
            if capacity is None:
                continue
            is_total = _is_total_row(entity_name)
            source_id = _generation_source_id(conn, entity_name)
            try:
                identity = resolve_generation_identity(
                    conn,
                    "nrldc",
                    entity_name,
                    current_state_id,
                    region_id,
                    source_id,
                    float(capacity),
                    is_total,
                )
            except DimensionResolutionError as error:
                record_resolution_issue(
                    conn, report_id, "nrldc", "generation_entity", entity_name, str(error)
                )
                continue
            entity_id = _get_or_create_grid_entity(
                conn,
                entity_name,
                "generation_aggregate" if is_total else "generating_entity",
                current_state_id,
                region_id,
                source_id,
                float(capacity),
                is_total,
                identity,
            )
            section_name = f"state_generation_{current_state_id}"
            columns = list(values)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO FactNRLDCGenerationDaily(
                    ReportDocumentID, DateID, EntityID, StateID, GenerationSourceID,
                    StationID, GeneratingUnitID, AggregateID, IsTotalRow,
                    GenerationGrain, SectionName, {', '.join(columns)}
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {', '.join('?' for _ in columns)})
                """,
                (
                    report_id,
                    date_id,
                    entity_id,
                    current_state_id,
                    source_id,
                    identity.station_id,
                    identity.generating_unit_id,
                    identity.aggregate_id,
                    int(is_total),
                    identity.entity_type,
                    section_name,
                    *(values[column] for column in columns),
                ),
            )
            if entity_cell:
                mapped_cells.add(entity_cell[0])
            key = f"report={report_id};date={date_id};entity={entity_id};section={section_name}"
            _write_lineage(
                conn, report_id, "FactNRLDCGenerationDaily", key, sources, mapped_cells
            )
            net_energy = values["NetEnergyMU"]
            average_mw = values["AverageMW"]
            if net_energy is not None and average_mw is not None:
                expected_average = float(net_energy) * 1000.0 / 24.0
                tolerance = max(5.0, abs(expected_average) * 0.01)
                if abs(float(average_mw) - expected_average) > tolerance:
                    validation_failures += 1
    return validation_failures


def _mapped_values(
    row: dict[int, tuple[int, str]],
    columns: dict[str, int],
) -> tuple[dict[str, float | None], dict[str, int]]:
    values: dict[str, float | None] = {}
    sources: dict[str, int] = {}
    for column, col_no in columns.items():
        raw = row.get(col_no)
        value = _to_float(raw[1]) if raw else None
        values[column] = value
        if raw and value is not None:
            sources[column] = raw[0]
    return values, sources


def _generation_values(
    row: dict[int, tuple[int, str]],
    columns: dict[str, int],
) -> tuple[dict[str, float | str | None], dict[str, int]]:
    values, sources = _mapped_values(row, columns)
    for field_name in ("DayPeakTime", "MinimumGenerationTime"):
        col_no = columns.get(field_name)
        raw = row.get(col_no) if col_no else None
        values[field_name] = _normalize_time(raw[1]) if raw else None
        if raw and values[field_name] is not None:
            sources[field_name] = raw[0]
    for field_name in (
        "MinimumGenerationMW",
        "DayPeakTime",
        "MinimumGenerationTime",
    ):
        values.setdefault(field_name, None)
    return values, sources


def _resolve_state_id(
    conn: sqlite3.Connection,
    report_id: int,
    raw_name: str,
    record: bool = True,
) -> int | None:
    """Resolve one NRLDC state heading through approved aliases only."""
    if not raw_name:
        return None
    try:
        return resolve_state_id(conn, "nrldc", raw_name)
    except DimensionResolutionError:
        if record and _looks_like_state_label(raw_name):
            record_resolution_issue(
                conn, report_id, "nrldc", "state", raw_name, "state alias is not approved"
            )
        return None


def _generation_source_id(conn: sqlite3.Connection, entity_name: str) -> int | None:
    normalized = entity_name.lower()
    source_name = None
    if "thermal" in normalized or any(token in normalized for token in ("tps", "stps")):
        source_name = "Thermal"
    elif "hydro" in normalized or "hps" in normalized:
        source_name = "Hydro"
    elif any(token in normalized for token in ("gas", "naptha", "diesel")):
        source_name = "Gas, Naptha & Diesel"
    elif "solar" in normalized:
        source_name = "Solar"
    elif "wind" in normalized:
        source_name = "Wind"
    if source_name is None:
        return None
    row = conn.execute(
        "SELECT GenerationSourceID FROM DimGenerationSources WHERE SourceName = ?",
        (source_name,),
    ).fetchone()
    return int(row[0]) if row else None


def _record_initial_coverage(
    conn: sqlite3.Connection,
    report_id: int,
    template_id: str,
    mapped_cells: set[int],
    validation_failures: int,
) -> None:
    """Record transparent initial coverage without borrowing SRLDC field contracts."""
    now = datetime.now(timezone.utc).isoformat()
    dispositions: list[tuple[int, str, str, str]] = []
    for raw_id, row_no, col_no, cell_text in conn.execute(
        """
        SELECT id, row_no, col_no, cell_text
        FROM psp_raw_cell
        WHERE report_document_id = ? AND TRIM(COALESCE(cell_text, '')) <> ''
        """,
        (report_id,),
    ):
        text = str(cell_text)
        if int(raw_id) in mapped_cells:
            disposition, reason = "mapped_value", "approved_initial_nrldc_mapping"
        elif int(col_no) == 1:
            disposition, reason = "dimension", "row_label_or_entity"
        elif _is_header_or_unit(text):
            disposition, reason = "header", "recognized_header_or_unit_label"
        elif _to_float(text) is not None:
            disposition, reason = "ambiguous", "numeric_value_without_approved_mapping"
        else:
            disposition, reason = "ambiguous", "text_value_without_approved_mapping"
        reference = f"cell:{raw_id}:r{row_no}:c{col_no}"
        dispositions.append((int(raw_id), reference, disposition, reason))

    expected = sum(
        1
        for _, _, disposition, _ in dispositions
        if disposition not in {"header", "dimension"}
    )
    mapped = sum(1 for _, _, disposition, _ in dispositions if disposition == "mapped_value")
    ambiguous = sum(1 for _, _, disposition, _ in dispositions if disposition == "ambiguous")
    coverage_pct = round(100.0 * mapped / expected, 2) if expected else 0.0
    previous = conn.execute(
        "SELECT CoverageRunID FROM schema_coverage_run WHERE ReportDocumentID = ?",
        (report_id,),
    ).fetchone()
    if previous:
        conn.execute("DELETE FROM schema_coverage_item WHERE CoverageRunID = ?", (previous[0],))
        conn.execute("DELETE FROM schema_coverage_run WHERE CoverageRunID = ?", (previous[0],))
    cursor = conn.execute(
        """
        INSERT INTO schema_coverage_run(
            ReportDocumentID, TemplateID, ExpectedFieldCount, MappedFieldCount,
            ExcludedFieldCount, AmbiguousFieldCount, MissingRequiredCount,
            LineageCompleteCount, ValidationFailureCount, CoveragePct, Status, ComputedAt
        ) VALUES (?, ?, ?, ?, 0, ?, 0, ?, ?, ?, 'review_required', ?)
        """,
        (
            report_id,
            template_id,
            expected,
            mapped,
            ambiguous,
            mapped,
            validation_failures,
            coverage_pct,
            now,
        ),
    )
    coverage_run_id = int(cursor.lastrowid)
    conn.executemany(
        """
        INSERT INTO schema_coverage_item(
            CoverageRunID, RawCellID, SourceReference, Disposition, Reason
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ((coverage_run_id, *item) for item in dispositions),
    )


def _upsert_dim_report(
    conn: sqlite3.Connection,
    date_id: int,
    report: dict[str, object],
) -> None:
    report_path = str(report["local_path"])
    report_name = report_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    conn.execute(
        """
        INSERT OR REPLACE INTO DimReports(DateID, ReportName, ReportPath, Source)
        VALUES (?, ?, ?, 'NRLDC')
        """,
        (date_id, report_name, report_path),
    )


def _table_rows(
    conn: sqlite3.Connection,
    report_id: int,
    page_no: int,
    table_no: int,
) -> list[dict[int, tuple[int, str]]]:
    rows: dict[int, dict[int, tuple[int, str]]] = {}
    for raw_id, row_no, col_no, cell_text in conn.execute(
        """
        SELECT id, row_no, col_no, cell_text
        FROM psp_raw_cell
        WHERE report_document_id = ? AND page_no = ? AND table_no = ?
        ORDER BY row_no, col_no
        """,
        (report_id, page_no, table_no),
    ):
        rows.setdefault(int(row_no), {})[int(col_no)] = (int(raw_id), str(cell_text))
    return [rows[row_no] for row_no in sorted(rows)]


def _table_row(
    conn: sqlite3.Connection,
    report_id: int,
    page_no: int,
    table_no: int,
    row_no: int,
) -> dict[int, tuple[int, str]]:
    """Return one raw table row by its published row coordinate."""
    return {
        int(col_no): (int(raw_id), str(cell_text))
        for raw_id, col_no, cell_text in conn.execute(
            """
            SELECT id, col_no, cell_text
            FROM psp_raw_cell
            WHERE report_document_id = ? AND page_no = ?
              AND table_no = ? AND row_no = ?
            ORDER BY col_no
            """,
            (report_id, page_no, table_no, row_no),
        )
    }


def _lookup_region_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (NR_REGION_NAME,)
    ).fetchone()
    return int(row[0]) if row else None


def _get_or_create_grid_entity(*args: object, **kwargs: object) -> int:
    """Reuse the shared canonical grid-entity dimension implementation."""
    from psp_pipeline.storage.sqlite_curated_promoter import _get_or_create_grid_entity as resolver

    return resolver(*args, **kwargs)


def _write_lineage(
    conn: sqlite3.Connection,
    report_id: int,
    table_name: str,
    destination_key: str,
    sources: dict[str, int],
    mapped_cells: set[int],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for column, raw_cell_id in sources.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO curated_field_lineage(
                ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn,
                RawCellID, ExtractionMethod, Confidence, CreatedAt
            ) VALUES (?, ?, ?, ?, ?, 'pdfplumber', 1.0, ?)
            """,
            (report_id, table_name, destination_key, column, raw_cell_id, now),
        )
        mapped_cells.add(raw_cell_id)


def _cell_float(row: dict[int, tuple[int, str]], col_no: int) -> float | None:
    raw = row.get(col_no)
    return _to_float(raw[1]) if raw else None


def _to_float(value: str | None) -> float | None:
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
    if not value:
        return None
    text = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        return f"{text}:00"
    if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", text):
        return text
    return None


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _is_total_row(value: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", value.lower())
    return normalized.startswith(("total", "subtotal"))


def _looks_like_state_label(value: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", value.lower())
    return normalized in {
        "punjab",
        "haryana",
        "rajasthan",
        "delhi",
        "uttarpradesh",
        "uttarakhand",
        "himachalpradesh",
        "chandigarh",
    }


def _is_header_or_unit(value: str) -> bool:
    """Return whether an NRLDC cell is structural rather than a report fact."""
    normalized = re.sub(r"\s+", " ", value).strip().lower()
    return normalized in {
        "state",
        "station/constituents",
        "inst.capacity",
        "(mw)",
        "peakmw",
        "offpeakmw",
        "dayenergy",
        "avg.mw",
        "demand met",
        "shortage",
        "requirement",
        "freq(hz)",
        "thermal",
        "hydro",
        "gas/naptha/ diesel",
        "solar",
        "wind",
    }
