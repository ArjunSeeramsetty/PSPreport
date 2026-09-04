"""Promote verified RPC DSM and REA tables into curated SQLite facts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import sqlite3

from psp_pipeline.parsing.rpc.contracts import (
    RPC_SUPPORTED_TEMPLATE_IDS,
    RPC_UNSUPPORTED_FAMILIES,
    classify_rpc_document,
)
from psp_pipeline.parsing.rpc.dsm import DsmParseResult, parse_weekly_dsm_tables
from psp_pipeline.parsing.rpc.rea import ReaParseResult, parse_monthly_rea_tables
from psp_pipeline.parsing.rpc.tables import ExtractedTable
from psp_pipeline.quality.promotion_quarantine import record_promotion_quarantine
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema
from psp_pipeline.storage.sqlite_dimensions import (
    normalize_dimension_name,
)


LOGGER = logging.getLogger(__name__)

RPC_SOURCE_IDS = frozenset({"erpc", "nrpc", "srpc", "wrpc", "nerpc"})
RPC_REGION_NAMES = {
    "erpc": "Eastern Region",
    "nrpc": "Northern Region",
    "srpc": "Southern Region",
    "wrpc": "Western Region",
    "nerpc": "North Eastern Region",
}
_RPC_FACT_TABLES = (
    "FactRPCWeeklyDSMEntity",
    "FactRPCWeeklyDSMAncillary",
    "FactRPCMonthlyREAStation",
    "FactRPCMonthlyREAAllocation",
)


def promote_rpc_report_to_curated(conn: sqlite3.Connection, report_id: int) -> None:
    """Promote one RPC settlement report when its table contract matches.

    Unsupported families (UI-era DSM, 9-column REA matrices) are quarantined
    without writing guessed facts. Malformed charge pairs are skipped while
    clean energy columns on the same table still promote.
    """

    ensure_curated_sqlite_schema(conn)
    report = conn.execute(
        """
        SELECT rldc, report_date, template_id, semantic_pass_required,
               report_family, local_path, structure_deviation_reason
        FROM psp_report_document WHERE id = ?
        """,
        (report_id,),
    ).fetchone()
    if not report or str(report[0]).lower() not in RPC_SOURCE_IDS:
        return
    source_id = str(report[0]).lower()
    template_id = str(report[2] or "")
    family = str(report[4] or "")
    local_path = str(report[5] or "")
    classified = classify_rpc_document(f"{local_path} {template_id} {family}")
    if template_id in RPC_UNSUPPORTED_FAMILIES or classified.template_id in RPC_UNSUPPORTED_FAMILIES:
        _quarantine_unsupported(conn, report_id, source_id, classified.template_id or template_id)
        return
    if template_id and template_id not in RPC_SUPPORTED_TEMPLATE_IDS | {""}:
        if template_id not in RPC_SUPPORTED_TEMPLATE_IDS:
            _quarantine_unsupported(conn, report_id, source_id, template_id)
            return
    date_id = _date_id(conn, str(report[1] or ""))
    region_id = _region_id(conn, source_id)
    if date_id is None or region_id is None:
        return
    _clear_rpc_facts(conn, report_id)
    tables = _tables_from_raw_cells(conn, report_id)
    if family == "monthly_rea" or template_id.endswith("station_pafm") or classified.family == "monthly_rea":
        result = parse_monthly_rea_tables(tables)
        if result.unsupported_family:
            _quarantine_unsupported(conn, report_id, source_id, result.unsupported_family)
            return
        if not result.contract_matched:
            _quarantine_contract_mismatch(
            conn,
            report_id,
            source_id,
            result.reasons,
            rejected_row_count=result.rejected_row_count,
            rejected_reasons=result.rejected_reasons,
        )
            return
        period_month = classified.period_month or str(report[1] or "")[:7]
        _promote_rea(conn, report_id, date_id, region_id, source_id, result, period_month)
        _record_skipped_coverage(
        conn,
        report_id,
        template_id,
        result.skipped_fields,
        result.skipped_reasons,
        rejected_row_count=result.rejected_row_count,
        rejected_reasons=result.rejected_reasons,
    )
        return
    result = parse_weekly_dsm_tables(tables)
    if "unsupported_ui_era_dsm" in result.reasons:
        _quarantine_unsupported(conn, report_id, source_id, "rpc_weekly_dsm_v2014_ui_charges")
        return
    if not result.contract_matched:
        _quarantine_contract_mismatch(
            conn,
            report_id,
            source_id,
            result.reasons,
            rejected_row_count=result.rejected_row_count,
            rejected_reasons=result.rejected_reasons,
        )
        return
    week_end = (classified.week_end.isoformat() if classified.week_end else _week_end(str(report[1] or "")))
    _promote_dsm(conn, report_id, date_id, region_id, source_id, result, week_end)
    _record_skipped_coverage(
        conn,
        report_id,
        template_id,
        result.skipped_fields,
        result.skipped_reasons,
        rejected_row_count=result.rejected_row_count,
        rejected_reasons=result.rejected_reasons,
    )


def _tables_from_raw_cells(conn: sqlite3.Connection, report_id: int) -> tuple[ExtractedTable, ...]:
    """Rebuild extracted tables from persisted raw cells, ignoring page numbers."""

    grouped: dict[tuple[int, int], dict[int, dict[int, str]]] = {}
    for page_no, table_no, row_no, col_no, text in conn.execute(
        """
        SELECT page_no, table_no, row_no, col_no, cell_text
        FROM psp_raw_cell
        WHERE report_document_id = ?
        ORDER BY page_no, table_no, row_no, col_no
        """,
        (report_id,),
    ):
        table = grouped.setdefault((int(page_no), int(table_no)), {})
        table.setdefault(int(row_no), {})[int(col_no)] = str(text or "")
    extracted: list[ExtractedTable] = []
    for (page_no, table_no), rows in grouped.items():
        max_row = max(rows)
        width = max((max(columns) for columns in rows.values()), default=0)
        matrix = []
        for row_no in range(1, max_row + 1):
            cells = rows.get(row_no, {})
            matrix.append(tuple(cells.get(col, "") for col in range(1, width + 1)))
        if matrix:
            extracted.append(ExtractedTable(page_no, table_no, None, tuple(matrix)))
    return tuple(extracted)


def _promote_dsm(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    source_id: str,
    result: DsmParseResult,
    week_end: str,
) -> None:
    """Persist DSM entity charges and ancillary payments with cell lineage."""

    for row in result.entity_rows:
        entity_id = _settlement_entity_id(conn, source_id, row.entity_name, region_id)
        columns = list(row.values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactRPCWeeklyDSMEntity(
                ReportDocumentID, DateID, RegionID, EntityID, WeekEndDate,
                {", ".join(columns)}
            ) VALUES (?, ?, ?, ?, ?, {", ".join("?" for _ in columns)})
            """,
            (report_id, date_id, region_id, entity_id, week_end, *(row.values[name] for name in columns)),
        )
        _write_lineage(
            conn,
            report_id,
            "FactRPCWeeklyDSMEntity",
            f"report={report_id};date={date_id};entity={entity_id}",
            row.sources,
        )
    for row in result.ancillary_rows:
        entity_id = _settlement_entity_id(conn, source_id, row.entity_name, region_id)
        columns = list(row.values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactRPCWeeklyDSMAncillary(
                ReportDocumentID, DateID, RegionID, EntityID, ServiceType, WeekEndDate,
                {", ".join(columns)}
            ) VALUES (?, ?, ?, ?, ?, ?, {", ".join("?" for _ in columns)})
            """,
            (
                report_id,
                date_id,
                region_id,
                entity_id,
                row.service_type,
                week_end,
                *(row.values[name] for name in columns),
            ),
        )
        _write_lineage(
            conn,
            report_id,
            "FactRPCWeeklyDSMAncillary",
            f"report={report_id};date={date_id};entity={entity_id};service={row.service_type}",
            row.sources,
        )


def _promote_rea(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    source_id: str,
    result: ReaParseResult,
    period_month: str,
) -> None:
    """Persist REA station PAFM and beneficiary allocations with cell lineage."""

    for row in result.station_rows:
        entity_id = _settlement_entity_id(
            conn, source_id, row.station_name, region_id, entity_type="isgs_station"
        )
        columns = list(row.values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactRPCMonthlyREAStation(
                ReportDocumentID, DateID, RegionID, EntityID, PeriodMonth,
                {", ".join(columns)}
            ) VALUES (?, ?, ?, ?, ?, {", ".join("?" for _ in columns)})
            """,
            (report_id, date_id, region_id, entity_id, period_month, *(row.values[name] for name in columns)),
        )
        _write_lineage(
            conn,
            report_id,
            "FactRPCMonthlyREAStation",
            f"report={report_id};date={date_id};entity={entity_id}",
            row.sources,
        )
    for row in result.allocation_rows:
        beneficiary_id = _settlement_entity_id(
            conn, source_id, row.beneficiary_name, region_id, entity_type="settlement_beneficiary"
        )
        station_id = _station_id(conn, source_id, row.station_name, region_id)
        columns = list(row.values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactRPCMonthlyREAAllocation(
                ReportDocumentID, DateID, RegionID, EntityID, StationID,
                AllocationWindow, PeriodMonth, {", ".join(columns)}
            ) VALUES (?, ?, ?, ?, ?, ?, ?, {", ".join("?" for _ in columns)})
            """,
            (
                report_id,
                date_id,
                region_id,
                beneficiary_id,
                station_id,
                row.allocation_window,
                period_month,
                *(row.values[name] for name in columns),
            ),
        )
        _write_lineage(
            conn,
            report_id,
            "FactRPCMonthlyREAAllocation",
            (
                f"report={report_id};date={date_id};entity={beneficiary_id};"
                f"station={station_id};window={row.allocation_window}"
            ),
            row.sources,
        )


def _settlement_entity_id(
    conn: sqlite3.Connection,
    source_id: str,
    raw_name: str,
    region_id: int,
    *,
    entity_type: str = "settlement_entity",
) -> int:
    """Resolve or create a regional settlement participant without inventing a state."""

    name = " ".join(raw_name.split())
    existing = conn.execute(
        """
        SELECT EntityID FROM DimGridEntities
        WHERE EntityName = ? AND EntityType = ? AND RegionID = ?
        """,
        (name, entity_type, region_id),
    ).fetchone()
    if existing:
        return int(existing[0])
    cursor = conn.execute(
        """
        INSERT INTO DimGridEntities(EntityName, EntityType, RegionID)
        VALUES (?, ?, ?)
        """,
        (name, entity_type, region_id),
    )
    _ = source_id
    return int(cursor.lastrowid)


def _station_id(
    conn: sqlite3.Connection,
    source_id: str,
    raw_name: str,
    region_id: int,
) -> int:
    """Resolve an ISGS station used as the REA allocation grain."""

    name = " ".join(raw_name.split())
    existing = conn.execute(
        """
        SELECT StationID FROM DimPowerStations
        WHERE CanonicalStationName = ? AND RegionID = ?
        """,
        (name, region_id),
    ).fetchone()
    if existing:
        return int(existing[0])
    from psp_pipeline.storage.sqlite_dimensions import _stable_code

    cursor = conn.execute(
        """
        INSERT INTO DimPowerStations(StationCode, CanonicalStationName, RegionID)
        VALUES (?, ?, ?)
        """,
        (_stable_code("STN", source_id, normalize_dimension_name(name), region_id), name, region_id),
    )
    return int(cursor.lastrowid)


def _write_lineage(
    conn: sqlite3.Connection,
    report_id: int,
    table: str,
    destination_key: str,
    sources: dict[str, tuple[int, int, int, int]],
) -> None:
    """Attach the raw cell that supplied each promoted numeric measure."""

    now = datetime.now(timezone.utc).isoformat()
    for column, (page_no, table_no, row_no, col_no) in sources.items():
        raw = conn.execute(
            """
            SELECT id FROM psp_raw_cell
            WHERE report_document_id = ? AND page_no = ? AND table_no = ?
              AND row_no = ? AND col_no = ?
            """,
            (report_id, page_no, table_no, row_no, col_no),
        ).fetchone()
        if not raw:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO curated_field_lineage(
                ReportDocumentID, DestinationTable, DestinationKey,
                DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt
            ) VALUES (?, ?, ?, ?, ?, 'rpc_header', 1.0, ?)
            """,
            (report_id, table, destination_key, column, int(raw[0]), now),
        )


def _record_skipped_coverage(
    conn: sqlite3.Connection,
    report_id: int,
    template_id: str,
    skipped_fields: tuple[str, ...],
    skipped_reasons: dict[str, str],
    *,
    rejected_row_count: int = 0,
    rejected_reasons: dict[str, int] | None = None,
) -> None:
    """Mark malformed header pairs and rejected rows in coverage evidence."""

    if not skipped_fields and not rejected_row_count:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO schema_coverage_run(
            ReportDocumentID, TemplateID, ExpectedFieldCount, MappedFieldCount,
            ExcludedFieldCount, AmbiguousFieldCount, MissingRequiredCount,
            LineageCompleteCount, ValidationFailureCount, CoveragePct, Status, ComputedAt
        ) VALUES (?, ?, 0, 0, ?, 0, 0, 0, 0, 0, 'passed', ?)
        ON CONFLICT(ReportDocumentID) DO UPDATE SET
            ExcludedFieldCount = excluded.ExcludedFieldCount,
            ComputedAt = excluded.ComputedAt
        """,
        (report_id, template_id or None, len(skipped_fields), now),
    )
    run_id = conn.execute(
        "SELECT CoverageRunID FROM schema_coverage_run WHERE ReportDocumentID = ?",
        (report_id,),
    ).fetchone()
    if not run_id:
        return
    for field_name in skipped_fields:
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_coverage_item(
                CoverageRunID, SourceReference, Disposition, Reason
            ) VALUES (?, ?, 'intentionally_excluded', ?)
            """,
            (int(run_id[0]), field_name, skipped_reasons.get(field_name, "malformed_pair")),
        )
    if rejected_row_count:
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_coverage_item(
                CoverageRunID, SourceReference, Disposition, Reason
            ) VALUES (?, ?, 'intentionally_excluded', ?)
            """,
            (
                int(run_id[0]),
                "rejected_rows",
                "rejected_row_count=%s;%s"
                % (
                    rejected_row_count,
                    ",".join(
                        f"{reason}:{count}"
                        for reason, count in sorted((rejected_reasons or {}).items())
                    ),
                ),
            ),
        )


def _quarantine_unsupported(
    conn: sqlite3.Connection,
    report_id: int,
    source_id: str,
    template_id: str,
) -> None:
    """Hold families whose matrix is outside the published settlement contract."""

    record_promotion_quarantine(
        conn,
        report_document_id=report_id,
        source_id=source_id,
        stage="template_review",
        reason_code="rpc_unsupported_family",
        details={"template_id": template_id},
    )
    LOGGER.info(
        "rpc_unsupported_family source=%s report=%s template=%s",
        source_id,
        report_id,
        template_id,
    )


def _quarantine_contract_mismatch(
    conn: sqlite3.Connection,
    report_id: int,
    source_id: str,
    reasons: tuple[str, ...],
    *,
    rejected_row_count: int = 0,
    rejected_reasons: dict[str, int] | None = None,
) -> None:
    """Hold documents whose tables were seen but did not match the schema."""

    mismatch_reasons = list(reasons)
    if rejected_row_count:
        mismatch_reasons.append("rejected_required_rows")
    record_promotion_quarantine(
        conn,
        report_document_id=report_id,
        source_id=source_id,
        stage="template_review",
        reason_code="rpc_contract_mismatch",
        details={
            "reasons": mismatch_reasons,
            "rejected_row_count": rejected_row_count,
            "rejected_reasons": rejected_reasons or {},
        },
    )


def _clear_rpc_facts(conn: sqlite3.Connection, report_id: int) -> None:
    """Replace curated RPC facts for one report during replay."""

    conn.execute("DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?", (report_id,))
    for table in _RPC_FACT_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE ReportDocumentID = ?", (report_id,))


def _date_id(conn: sqlite3.Connection, value: str) -> int | None:
    """Resolve the week-start or month-start date dimension."""

    if not value:
        return None
    conn.execute("INSERT OR IGNORE INTO DimDates(ActualDate) VALUES (?)", (value[:10],))
    row = conn.execute("SELECT DateID FROM DimDates WHERE ActualDate = ?", (value[:10],)).fetchone()
    return int(row[0]) if row else None


def _region_id(conn: sqlite3.Connection, source_id: str) -> int | None:
    """Return the seeded region key for one RPC source."""

    name = RPC_REGION_NAMES.get(source_id)
    if not name:
        return None
    row = conn.execute("SELECT RegionID FROM DimRegions WHERE RegionName = ?", (name,)).fetchone()
    return int(row[0]) if row else None


def _week_end(week_start: str) -> str:
    """Default DSM weeks to Monday-Sunday when the title omitted the end date."""

    start = datetime.fromisoformat(week_start[:10]).date()
    return (start + timedelta(days=6)).isoformat()
