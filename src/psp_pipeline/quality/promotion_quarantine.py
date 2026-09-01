"""Persist explicit reasons why raw PSP content was not promoted."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


def record_promotion_quarantine(
    conn: sqlite3.Connection,
    *,
    report_document_id: int,
    source_id: str,
    stage: str,
    reason_code: str,
    details: Mapping[str, object] | None = None,
    status: str = "pending",
) -> None:
    """Upsert one source-scoped promotion hold with structured evidence.

    Args:
        conn: Curated SQLite connection with the governance schema installed.
        report_document_id: Immutable raw report identity.
        source_id: Source whose promotion is constrained.
        stage: Pipeline stage such as ``template_review`` or ``spatial``.
        reason_code: Stable machine-readable hold reason.
        details: Optional evidence retained for a later fixture or backfill.
        status: Current triage state.
    """

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO promotion_quarantine(
            ReportDocumentID, SourceID, Stage, ReasonCode, DetailsJson,
            Status, CreatedAt, UpdatedAt
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ReportDocumentID, Stage, ReasonCode) DO UPDATE SET
            SourceID = excluded.SourceID,
            DetailsJson = excluded.DetailsJson,
            Status = excluded.Status,
            UpdatedAt = excluded.UpdatedAt
        """,
        (
            report_document_id,
            source_id,
            stage,
            reason_code,
            json.dumps(details or {}, sort_keys=True),
            status,
            now,
            now,
        ),
    )


def list_pending_promotion_quarantine(
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Return open holds joined to the local report path needed for retry."""

    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("promotion_quarantine",),
    ).fetchone()
    if not has_table:
        return []
    rows = conn.execute(
        """
        SELECT
            hold.QuarantineID,
            hold.ReportDocumentID,
            hold.SourceID,
            hold.Stage,
            hold.ReasonCode,
            hold.DetailsJson,
            hold.Status,
            document.local_path
        FROM promotion_quarantine AS hold
        JOIN psp_report_document AS document
          ON document.id = hold.ReportDocumentID
        WHERE hold.Status = 'pending'
        ORDER BY hold.ReportDocumentID, hold.Stage, hold.ReasonCode
        """
    ).fetchall()
    return [
        {
            "quarantine_id": int(quarantine_id),
            "report_document_id": int(report_id),
            "source_id": source_id,
            "stage": stage,
            "reason_code": reason_code,
            "details": json.loads(details_json or "{}"),
            "status": status,
            "local_path": local_path,
        }
        for (
            quarantine_id,
            report_id,
            source_id,
            stage,
            reason_code,
            details_json,
            status,
            local_path,
        ) in rows
    ]


def resolve_promotion_quarantine(
    conn: sqlite3.Connection,
    *,
    report_document_id: int,
    stage: str,
    reason_code: str,
    details: Mapping[str, object] | None = None,
) -> bool:
    """Mark one hold resolved after a successful retry or backfill.

    Returns:
        True when a pending row was updated.
    """

    now = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(details or {}, sort_keys=True)
    cursor = conn.execute(
        """
        UPDATE promotion_quarantine
        SET Status = 'resolved',
            DetailsJson = ?,
            UpdatedAt = ?
        WHERE ReportDocumentID = ? AND Stage = ? AND ReasonCode = ?
          AND Status = 'pending'
        """,
        (payload, now, report_document_id, stage, reason_code),
    )
    return cursor.rowcount > 0


def summarize_promotion_quarantine(
    db_path: Path | str,
) -> dict[str, Any]:
    """Return grouped, source-scoped promotion holds for triage.

    Raises:
        FileNotFoundError: If the requested SQLite replay database is absent.
    """

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")
    with sqlite3.connect(path) as conn:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("promotion_quarantine",),
        ).fetchone()
        if not has_table:
            return {"database_path": str(path), "total": 0, "groups": []}
        rows = conn.execute(
            """
            SELECT
                hold.SourceID,
                hold.Stage,
                hold.ReasonCode,
                hold.Status,
                COUNT(*) AS hold_count,
                GROUP_CONCAT(hold.ReportDocumentID) AS report_ids
            FROM promotion_quarantine AS hold
            GROUP BY hold.SourceID, hold.Stage, hold.ReasonCode, hold.Status
            ORDER BY hold_count DESC, hold.SourceID, hold.Stage, hold.ReasonCode
            """
        ).fetchall()
    groups = [
        {
            "source_id": source_id,
            "stage": stage,
            "reason_code": reason_code,
            "status": status,
            "count": int(count),
            "report_document_ids": [int(value) for value in str(report_ids).split(",")],
        }
        for source_id, stage, reason_code, status, count, report_ids in rows
    ]
    return {"database_path": str(path), "total": sum(group["count"] for group in groups), "groups": groups}
