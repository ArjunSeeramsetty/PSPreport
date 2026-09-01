"""Retry pending promotion holds with local LiteParse spatial or OCR extraction."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any

from psp_pipeline.pipelines.rldc_daily_psp import (
    RawTextItem,
    _extract_liteparse_content,
    _liteparse_available,
    _upsert_raw_text_items,
    ensure_sqlite_schema,
)
from psp_pipeline.quality.promotion_quarantine import (
    list_pending_promotion_quarantine,
    record_promotion_quarantine,
    resolve_promotion_quarantine,
)
from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated


LOGGER = logging.getLogger(__name__)

_SPATIAL_TARGET_PAGES = {
    "nrldc_continuation": "6-9",
    "erldc_regional_generation": "3",
    "erldc_market_extrema": "6",
}
_AUTOMATED_STAGES = frozenset({"spatial_reconstruction", "ocr"})


def retry_pending_promotion_quarantine(
    sqlite_db_path: Path | str,
    *,
    liteparse_available: bool | None = None,
    extract_liteparse=_extract_liteparse_content,
) -> dict[str, Any]:
    """Replay LiteParse for pending spatial and OCR holds, then re-promote.

    Template-review holds stay pending because they need a human schema decision.
    Missing local PDFs and empty LiteParse output remain pending with updated
    evidence so the next scheduled run can try again.

    Args:
        sqlite_db_path: Curated SQLite replay containing quarantine rows.
        liteparse_available: Optional override used by tests.
        extract_liteparse: Optional LiteParse callable used by tests.

    Returns:
        Counts of pending, resolved, skipped, and failed retry attempts.
    """

    result = {
        "holds_seen": 0,
        "resolved": 0,
        "skipped_semantic": 0,
        "reports_missing_local_file": 0,
        "reports_without_spatial_items": 0,
        "liteparse_unavailable": 0,
        "unknown_reason": 0,
        "retry_failed": 0,
    }
    path = Path(sqlite_db_path)
    if not path.exists():
        return result
    available = (
        _liteparse_available() if liteparse_available is None else liteparse_available
    )
    with sqlite3.connect(path) as conn:
        ensure_sqlite_schema(conn)
        holds = list_pending_promotion_quarantine(conn)
        result["holds_seen"] = len(holds)
        for hold in holds:
            try:
                _retry_one_hold(
                    conn,
                    hold,
                    available=available,
                    extract_liteparse=extract_liteparse,
                    result=result,
                )
                conn.commit()
            except Exception:
                LOGGER.exception(
                    "quarantine_retry_failed report_id=%s reason=%s",
                    hold.get("report_document_id"),
                    hold.get("reason_code"),
                )
                conn.rollback()
                result["retry_failed"] += 1
    return result


def _retry_one_hold(
    conn: sqlite3.Connection,
    hold: dict[str, Any],
    *,
    available: bool,
    extract_liteparse,
    result: dict[str, int],
) -> None:
    """Attempt one pending hold and record whether it can be closed."""

    if hold["stage"] not in _AUTOMATED_STAGES:
        result["skipped_semantic"] += 1
        return
    if hold["stage"] == "spatial_reconstruction":
        target_pages = _SPATIAL_TARGET_PAGES.get(str(hold["reason_code"]))
        if target_pages is None:
            result["unknown_reason"] += 1
            return
    else:
        target_pages = None
    if not available:
        result["liteparse_unavailable"] += 1
        return
    pdf_path = Path(str(hold["local_path"] or ""))
    if not pdf_path.is_file():
        LOGGER.warning(
            "quarantine_retry_missing_file report_id=%s path=%s",
            hold["report_document_id"],
            pdf_path,
        )
        result["reports_missing_local_file"] += 1
        return
    _, items = extract_liteparse(pdf_path, target_pages=target_pages)
    items = _filter_items(items, target_pages)
    if not items:
        LOGGER.warning(
            "quarantine_retry_empty report_id=%s reason=%s",
            hold["report_document_id"],
            hold["reason_code"],
        )
        record_promotion_quarantine(
            conn,
            report_document_id=int(hold["report_document_id"]),
            source_id=str(hold["source_id"]),
            stage=str(hold["stage"]),
            reason_code=str(hold["reason_code"]),
            details={
                **dict(hold.get("details") or {}),
                "raw_text_item_count": 0,
                "liteparse_required": True,
                "last_retry_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        result["reports_without_spatial_items"] += 1
        return
    _upsert_raw_text_items(
        conn.cursor(),
        int(hold["report_document_id"]),
        items,
        datetime.now(timezone.utc).isoformat(),
    )
    promote_report_to_curated(conn, int(hold["report_document_id"]))
    resolve_promotion_quarantine(
        conn,
        report_document_id=int(hold["report_document_id"]),
        stage=str(hold["stage"]),
        reason_code=str(hold["reason_code"]),
        details={"raw_text_item_count": len(items), "retry": "liteparse"},
    )
    result["resolved"] += 1


def _filter_items(
    items: list[RawTextItem],
    target_pages: str | None,
) -> list[RawTextItem]:
    """Keep only items on the pages named by a LiteParse page selector."""

    if not target_pages:
        return [item for item in items if item.text]
    allowed = _parse_page_selector(target_pages)
    return [item for item in items if item.page_no in allowed and item.text]


def _parse_page_selector(target_pages: str) -> set[int]:
    """Parse a LiteParse ``target-pages`` value such as ``6-9`` or ``3,6``."""

    pages: set[int] = set()
    for part in target_pages.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start, end = token.split("-", 1)
            pages.update(range(int(start), int(end) + 1))
        else:
            pages.add(int(token))
    return pages
