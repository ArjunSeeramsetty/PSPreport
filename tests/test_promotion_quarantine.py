"""Tests for explicit promotion-hold persistence."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.quality.promotion_quarantine import (
    record_promotion_quarantine,
    summarize_promotion_quarantine,
)


def _document(conn: sqlite3.Connection) -> None:
    """Seed the raw report identity required by quarantine records."""

    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count
        ) VALUES (1, 'erldc', 'fixture', 'fixture.pdf', 'hash', ?,
                  1.0, 0, 'native', 1)
        """,
        (datetime.now(timezone.utc).isoformat(),),
    )


def test_promotion_quarantine_upserts_evidence_without_duplicate_holds() -> None:
    """Repeated replay attempts retain one current, structured hold record."""

    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    _document(conn)

    record_promotion_quarantine(
        conn,
        report_document_id=1,
        source_id="erldc",
        stage="spatial_reconstruction",
        reason_code="erldc_market_extrema",
        details={"raw_text_item_count": 0},
    )
    record_promotion_quarantine(
        conn,
        report_document_id=1,
        source_id="erldc",
        stage="spatial_reconstruction",
        reason_code="erldc_market_extrema",
        details={"raw_text_item_count": 0, "liteparse_required": True},
    )

    rows = conn.execute(
        """
        SELECT SourceID, Stage, ReasonCode, DetailsJson, Status
        FROM promotion_quarantine
        """
    ).fetchall()
    assert rows == [
        (
            "erldc",
            "spatial_reconstruction",
            "erldc_market_extrema",
            '{"liteparse_required": true, "raw_text_item_count": 0}',
            "pending",
        )
    ]


def test_promotion_quarantine_summary_groups_open_holds(tmp_path) -> None:
    """Triage output remains compact while preserving report identifiers."""

    db_path = tmp_path / "quarantine.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    _document(conn)
    record_promotion_quarantine(
        conn,
        report_document_id=1,
        source_id="erldc",
        stage="template_review",
        reason_code="semantic_review_required",
        details={"confidence": 0.7},
    )
    conn.commit()
    conn.close()

    summary = summarize_promotion_quarantine(db_path)

    assert summary["total"] == 1
    assert summary["groups"] == [
        {
            "source_id": "erldc",
            "stage": "template_review",
            "reason_code": "semantic_review_required",
            "status": "pending",
            "count": 1,
            "report_document_ids": [1],
        }
    ]
