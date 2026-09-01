"""Tests for automated LiteParse retries of pending promotion holds."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from psp_pipeline.pipelines.quarantine_retry import retry_pending_promotion_quarantine
from psp_pipeline.pipelines.rldc_daily_psp import RawTextItem, ensure_sqlite_schema
from psp_pipeline.quality.promotion_quarantine import record_promotion_quarantine


def _seed_hold(
    db_path: Path,
    pdf_path: Path,
    *,
    stage: str,
    reason_code: str,
    source_id: str = "erldc",
) -> None:
    """Persist one pending hold against a local PDF path."""

    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count
        ) VALUES (1, ?, 'fixture', ?, 'hash', ?, 1.0, 0, 'native', 1)
        """,
        (source_id, str(pdf_path), datetime.now(timezone.utc).isoformat()),
    )
    record_promotion_quarantine(
        conn,
        report_document_id=1,
        source_id=source_id,
        stage=stage,
        reason_code=reason_code,
        details={"raw_text_item_count": 0},
    )
    conn.commit()
    conn.close()


def test_retry_resolves_spatial_hold_after_liteparse_items(tmp_path, monkeypatch) -> None:
    """A Page 6 spatial hold closes when LiteParse returns coordinates."""

    db_path = tmp_path / "retry.sqlite"
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"pdf")
    _seed_hold(
        db_path,
        pdf_path,
        stage="spatial_reconstruction",
        reason_code="erldc_market_extrema",
    )
    items = [
        RawTextItem(6, 1, "WEST BENGAL", 1.0, 2.0, 3.0, 4.0, 1.0, "liteparse"),
        RawTextItem(6, 2, "255.99", 5.0, 6.0, 7.0, 8.0, 1.0, "liteparse"),
    ]
    monkeypatch.setattr(
        "psp_pipeline.pipelines.quarantine_retry.promote_report_to_curated",
        lambda *_args, **_kwargs: None,
    )

    result = retry_pending_promotion_quarantine(
        db_path,
        liteparse_available=True,
        extract_liteparse=lambda _path, target_pages=None: ("text", items),
    )

    assert result["resolved"] == 1
    assert result["holds_seen"] == 1
    with sqlite3.connect(db_path) as conn:
        status = conn.execute(
            "SELECT Status FROM promotion_quarantine WHERE ReasonCode = ?",
            ("erldc_market_extrema",),
        ).fetchone()[0]
        stored = conn.execute(
            "SELECT page_no, item_text FROM psp_raw_text_item ORDER BY item_no"
        ).fetchall()
    assert status == "resolved"
    assert stored == [(6, "WEST BENGAL"), (6, "255.99")]


def test_retry_leaves_semantic_review_pending(tmp_path) -> None:
    """Template-review holds stay open for human schema decisions."""

    db_path = tmp_path / "semantic.sqlite"
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"pdf")
    _seed_hold(
        db_path,
        pdf_path,
        stage="template_review",
        reason_code="semantic_review_required",
    )

    result = retry_pending_promotion_quarantine(db_path, liteparse_available=True)

    assert result["skipped_semantic"] == 1
    assert result["resolved"] == 0
    with sqlite3.connect(db_path) as conn:
        status = conn.execute("SELECT Status FROM promotion_quarantine").fetchone()[0]
    assert status == "pending"


def test_retry_records_empty_liteparse_without_closing_the_hold(
    tmp_path, monkeypatch
) -> None:
    """An unsuccessful OCR retry remains pending with a last-attempt timestamp."""

    db_path = tmp_path / "empty.sqlite"
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"pdf")
    _seed_hold(
        db_path,
        pdf_path,
        stage="ocr",
        reason_code="ocr_retry_required",
        source_id="wrldc",
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.quarantine_retry.promote_report_to_curated",
        lambda *_args, **_kwargs: None,
    )

    result = retry_pending_promotion_quarantine(
        db_path,
        liteparse_available=True,
        extract_liteparse=lambda _path, target_pages=None: ("", []),
    )

    assert result["reports_without_spatial_items"] == 1
    assert result["resolved"] == 0
    with sqlite3.connect(db_path) as conn:
        status, details = conn.execute(
            "SELECT Status, DetailsJson FROM promotion_quarantine"
        ).fetchone()
    assert status == "pending"
    assert "last_retry_at" in details


def test_retry_keeps_hold_pending_when_local_path_is_not_a_file(tmp_path) -> None:
    """An empty or directory path must not be treated as a retryable PDF."""

    db_path = tmp_path / "dir.sqlite"
    _seed_hold(
        db_path,
        tmp_path,
        stage="ocr",
        reason_code="ocr_retry_required",
    )

    result = retry_pending_promotion_quarantine(db_path, liteparse_available=True)

    assert result["reports_missing_local_file"] == 1
    assert result["resolved"] == 0
    with sqlite3.connect(db_path) as conn:
        status = conn.execute("SELECT Status FROM promotion_quarantine").fetchone()[0]
    assert status == "pending"


def test_retry_isolates_a_failed_promote_from_later_holds(tmp_path, monkeypatch) -> None:
    """One broken report cannot roll back a later successful LiteParse retry."""

    db_path = tmp_path / "fail_soft.sqlite"
    first_pdf = tmp_path / "first.pdf"
    second_pdf = tmp_path / "second.pdf"
    first_pdf.write_bytes(b"pdf")
    second_pdf.write_bytes(b"pdf")
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    fetched_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count
        ) VALUES (1, 'erldc', 'fixture', ?, 'h1', ?, 1.0, 0, 'native', 1),
                 (2, 'erldc', 'fixture', ?, 'h2', ?, 1.0, 0, 'native', 1)
        """,
        (str(first_pdf), fetched_at, str(second_pdf), fetched_at),
    )
    record_promotion_quarantine(
        conn,
        report_document_id=1,
        source_id="erldc",
        stage="spatial_reconstruction",
        reason_code="erldc_market_extrema",
    )
    record_promotion_quarantine(
        conn,
        report_document_id=2,
        source_id="erldc",
        stage="spatial_reconstruction",
        reason_code="erldc_market_extrema",
    )
    conn.commit()
    conn.close()

    def promote(_conn, report_id: int) -> None:
        if report_id == 1:
            raise RuntimeError("promotion exploded")

    monkeypatch.setattr(
        "psp_pipeline.pipelines.quarantine_retry.promote_report_to_curated",
        promote,
    )
    items = [RawTextItem(6, 1, "WEST BENGAL", 1.0, 2.0, 3.0, 4.0, 1.0, "liteparse")]

    result = retry_pending_promotion_quarantine(
        db_path,
        liteparse_available=True,
        extract_liteparse=lambda _path, target_pages=None: ("text", items),
    )

    assert result["retry_failed"] == 1
    assert result["resolved"] == 1
    with sqlite3.connect(db_path) as conn:
        statuses = dict(
            conn.execute(
                "SELECT ReportDocumentID, Status FROM promotion_quarantine"
            ).fetchall()
        )
    assert statuses == {1: "pending", 2: "resolved"}
