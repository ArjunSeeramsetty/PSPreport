"""Tests for idempotent NRLDC LiteParse continuation backfills."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from psp_pipeline.pipelines import rldc_daily_psp as pipeline
from psp_pipeline.pipelines.rldc_daily_psp import RawTextItem
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


def test_backfill_adds_missing_continuation_pages_and_is_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    """A 2026 report receives pages 6--9 once without reopening its PDF cells."""

    db_path = tmp_path / "nrldc.sqlite"
    pdf_path = tmp_path / "daily010526.pdf"
    pdf_path.write_bytes(b"fixture")
    _insert_nrldc_report(db_path, pdf_path)
    items = [
        RawTextItem(
            page_no=page_no,
            item_no=1,
            text=f"station-{page_no}",
            x=20.0,
            y=40.0,
            width=10.0,
            height=5.0,
            confidence=1.0,
            extraction_method="liteparse",
        )
        for page_no in range(6, 10)
    ]
    monkeypatch.setattr(pipeline, "_liteparse_available", lambda: True)
    monkeypatch.setattr(
        pipeline,
        "_extract_liteparse_content",
        lambda path, target_pages: ("spatial fixture", items),
    )

    first = pipeline.backfill_nrldc_continuation_spatial_items(db_path)
    second = pipeline.backfill_nrldc_continuation_spatial_items(db_path)

    assert first == {
        "reports_seen": 1,
        "reports_enriched": 1,
        "reports_already_complete": 0,
        "reports_missing_local_file": 0,
        "reports_without_spatial_items": 0,
        "liteparse_unavailable": 0,
    }
    assert second["reports_enriched"] == 0
    assert second["reports_already_complete"] == 1
    with sqlite3.connect(db_path) as conn:
        pages = conn.execute(
            """
            SELECT page_no FROM psp_raw_text_item
            WHERE extraction_method = 'liteparse'
            ORDER BY page_no
            """
        ).fetchall()
    assert pages == [(6,), (7,), (8,), (9,)]


def test_backfill_reports_unavailable_liteparse_without_changing_database(
    tmp_path,
    monkeypatch,
) -> None:
    """Unavailable LiteParse produces an explicit no-op result."""

    db_path = tmp_path / "nrldc.sqlite"
    pdf_path = tmp_path / "daily010526.pdf"
    pdf_path.write_bytes(b"fixture")
    _insert_nrldc_report(db_path, pdf_path)
    monkeypatch.setattr(pipeline, "_liteparse_available", lambda: False)

    result = pipeline.backfill_nrldc_continuation_spatial_items(db_path)

    assert result["liteparse_unavailable"] == 1
    assert result["reports_enriched"] == 0


def _insert_nrldc_report(db_path, pdf_path) -> None:
    """Create one eligible persisted NRLDC report for the backfill fixture."""

    with sqlite3.connect(db_path) as conn:
        ensure_curated_sqlite_schema(conn)
        conn.execute(
            """
            CREATE TABLE psp_report_document (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rldc TEXT NOT NULL,
                source_url TEXT NOT NULL,
                local_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                ocr_score REAL NOT NULL,
                ocr_used INTEGER NOT NULL,
                ocr_reason TEXT NOT NULL,
                extracted_char_count INTEGER NOT NULL,
                report_date TEXT,
                report_family TEXT,
                discovery_confidence REAL,
                response_content_length INTEGER,
                response_last_modified TEXT,
                template_id TEXT,
                template_version TEXT,
                template_confidence REAL,
                semantic_pass_required INTEGER,
                structure_deviation_reason TEXT,
                UNIQUE(rldc, content_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE psp_raw_cell (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_document_id INTEGER NOT NULL,
                page_no INTEGER NOT NULL,
                table_no INTEGER NOT NULL,
                row_no INTEGER NOT NULL,
                col_no INTEGER NOT NULL,
                cell_text TEXT,
                extraction_method TEXT NOT NULL,
                extracted_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO psp_report_document(
                rldc, source_url, local_path, content_hash, fetched_at,
                ocr_score, ocr_used, ocr_reason, extracted_char_count,
                report_date, report_family, discovery_confidence,
                template_id, template_version, template_confidence,
                semantic_pass_required, structure_deviation_reason
            ) VALUES (?, ?, ?, ?, ?, 1.0, 0, 'native', 1000, ?, 'psp', 1.0, ?, '1', 1.0, 0, '')
            """,
            (
                "nrldc",
                "https://example.test/daily010526.pdf",
                str(pdf_path),
                "fixture-hash",
                datetime.now(timezone.utc).isoformat(),
                "2026-05-01",
                "nrldc_daily_psp_v2026_standard_11_column_storage",
            ),
        )
