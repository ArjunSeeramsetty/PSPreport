"""Export curated SRLDC daily facts into portable time-series observations."""

from __future__ import annotations

from datetime import datetime, time, timezone
import sqlite3
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from psp_pipeline.models.contracts import FactObservation


SOURCE_REGION = "SR"
REPORT_TYPE = "srldc_daily_psp"
_DIMENSION_COLUMNS = {
    "ReportDocumentID",
    "DateID",
    "RegionID",
    "StateID",
}


def export_srldc_daily_observations(
    conn: sqlite3.Connection,
    report_document_id: int | None = None,
    *,
    ingested_at: datetime | None = None,
) -> list[FactObservation]:
    """Return numeric regional and state SRLDC facts as bitemporal observations.

    The function is intentionally read-only.  The calling persistence stage owns
    the Timescale transaction and may retain every later ingestion as a new
    system-time version.
    """

    recorded_at = ingested_at or datetime.now(timezone.utc)
    return [
        *_export_table(
            conn,
            table_name="FactSRLDCRegionalDaily",
            entity_expression="'SR:region:' || region.RegionName",
            joins="JOIN DimRegions AS region ON region.RegionID = fact.RegionID",
            report_document_id=report_document_id,
            ingested_at=recorded_at,
        ),
        *_export_table(
            conn,
            table_name="FactSRLDCStateDaily",
            entity_expression="'SR:state:' || state.StateCode",
            joins="JOIN DimStates AS state ON state.StateID = fact.StateID",
            report_document_id=report_document_id,
            ingested_at=recorded_at,
        ),
    ]


def _export_table(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    entity_expression: str,
    joins: str,
    report_document_id: int | None,
    ingested_at: datetime,
) -> Iterable[FactObservation]:
    """Yield each non-null numeric fact column from one daily curated table."""

    numeric_columns = _numeric_columns(conn, table_name)
    if not numeric_columns:
        return []
    predicates = ["document.rldc = 'srldc'"]
    parameters: list[object] = []
    if report_document_id is not None:
        predicates.append("fact.ReportDocumentID = ?")
        parameters.append(report_document_id)
    rows = conn.execute(
        f"""
        SELECT fact.ReportDocumentID, date.ActualDate, {entity_expression},
               {', '.join(f'fact.{column}' for column in numeric_columns)}
        FROM {table_name} AS fact
        JOIN DimDates AS date ON date.DateID = fact.DateID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        {joins}
        WHERE {' AND '.join(predicates)}
        ORDER BY fact.ReportDocumentID
        """,
        parameters,
    ).fetchall()
    observations: list[FactObservation] = []
    for row in rows:
        report_id, actual_date, entity_key, *values = row
        valid_from = datetime.combine(
            datetime.fromisoformat(str(actual_date)).date(),
            time.min,
            tzinfo=timezone.utc,
        )
        for column, value in zip(numeric_columns, values, strict=True):
            if value is None:
                continue
            metric_name = f"srldc.{table_name}.{column}"
            observations.append(
                FactObservation(
                    entity_key=str(entity_key),
                    metric_name=metric_name,
                    time_block=None,
                    operational_value=float(value),
                    settlement_value=None,
                    variance_pct=None,
                    report_type=REPORT_TYPE,
                    source_region=SOURCE_REGION,
                    valid_from=valid_from,
                    valid_to=None,
                    version_no=1,
                    ingested_at=ingested_at,
                    timeseries_uuid=str(
                        uuid5(
                            NAMESPACE_URL,
                            f"{entity_key}|{metric_name}|{valid_from.isoformat()}|{report_id}",
                        )
                    ),
                )
            )
    return observations


def _numeric_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Return numeric measure columns, excluding physical keys and dimensions."""

    return [
        str(name)
        for _, name, column_type, _, _, _ in conn.execute(
            f"PRAGMA table_info({table_name})"
        )
        if str(name) not in _DIMENSION_COLUMNS
        and str(column_type).upper() in {"REAL", "INTEGER"}
    ]
