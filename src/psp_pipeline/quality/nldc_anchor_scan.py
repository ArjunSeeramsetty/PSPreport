"""Replayable monthly-anchor ingestion scan for Grid-India NLDC PSP archives."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
import logging
import multiprocessing
from pathlib import Path
from queue import Empty
import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psp_pipeline.schema_design.service import MonthlyAnchorSample

logger = logging.getLogger(__name__)
DEFAULT_ANCHOR_TIMEOUT_SECONDS = 120
SOURCE_ID = "grid_india_national"


@dataclass(frozen=True)
class NLDCAnchorScanResult:
    """Outcome recorded for one monthly anchor document."""

    sample: MonthlyAnchorSample
    outcome: str
    error: str | None = None


def scan_nldc_monthly_anchors(
    input_dir: Path,
    sqlite_db_path: Path,
    *,
    timeout_seconds: int = DEFAULT_ANCHOR_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Ingest local NLDC monthly anchors with checkpoint resumption and fail-soft gating.

    Existing source documents in SQLite are treated as completed checkpoints.
    Reports lacking approved structure are recorded as gated/rejected rather than promoted.
    """
    from psp_pipeline.schema_design.service import select_monthly_anchor_paths

    if not input_dir.exists() or not input_dir.is_dir():
        return {
            "rldc": SOURCE_ID,
            "sqlite_db_path": str(sqlite_db_path),
            "anchor_count": 0,
            "persisted_report_count": 0,
            "outcome_counts": {},
            "failed_reports": [],
        }

    all_pdfs = sorted(input_dir.glob("*.pdf"))
    samples = _unique_samples(
        select_monthly_anchor_paths(all_pdfs, source_id=SOURCE_ID)
    )
    completed_paths = _load_completed_paths(sqlite_db_path, SOURCE_ID)
    results: list[NLDCAnchorScanResult] = []

    for index, sample in enumerate(samples, start=1):
        logger.info(
            "nldc_anchor_scan_progress index=%s total=%s date=%s anchor=%s",
            index, len(samples), sample.report_date, sample.anchor,
        )
        if str(sample.pdf_path) in completed_paths:
            results.append(NLDCAnchorScanResult(sample, "already_persisted"))
            continue

        ingestion, error = _ingest_anchor_with_timeout(
            sqlite_db_path,
            sample,
            SOURCE_ID,
            timeout_seconds,
        )
        if error is not None:
            logger.warning(
                "nldc_anchor_scan_failed path=%s error=%s",
                sample.pdf_path, error,
            )
            results.append(NLDCAnchorScanResult(sample, "failed", error))
            continue

        outcome = "skipped"
        if ingestion and ingestion.get("report_family_rejected", 0) > 0:
            outcome = "gated"
        elif ingestion and ingestion.get("reports_persisted", 0) > 0:
            outcome = "persisted"
        results.append(NLDCAnchorScanResult(sample, outcome))

    return _build_summary(sqlite_db_path, SOURCE_ID, results)


def _unique_samples(samples: list[MonthlyAnchorSample]) -> list[MonthlyAnchorSample]:
    """Preserve anchor order while avoiding duplicate paths."""
    seen: set[Path] = set()
    unique: list[MonthlyAnchorSample] = []
    for sample in samples:
        if sample.pdf_path in seen:
            continue
        seen.add(sample.pdf_path)
        unique.append(sample)
    return unique


def _load_completed_paths(sqlite_db_path: Path, source_id: str) -> set[str]:
    """Return source-scoped local PDF paths already persisted in SQLite."""
    if not sqlite_db_path.exists():
        return set()
    conn = sqlite3.connect(str(sqlite_db_path))
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_report_document'",
        ).fetchone()
        if table_exists is None:
            return set()
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT local_path FROM psp_report_document WHERE rldc = ?",
                (source_id,),
            )
        }
    finally:
        conn.close()


def _ingest_anchor_with_timeout(
    sqlite_db_path: Path,
    sample: MonthlyAnchorSample,
    source_id: str,
    timeout_seconds: int,
) -> tuple[dict[str, int] | None, str | None]:
    """Run one local ingestion in an isolated worker process with timeout protection."""
    context = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue[tuple[str, Any]] = context.Queue()
    worker = context.Process(
        target=_ingest_anchor_worker,
        args=(sqlite_db_path, sample.pdf_path, sample.report_date, source_id, result_queue),
    )
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        worker.terminate()
        worker.join(timeout=5)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=5)
        result_queue.cancel_join_thread()
        result_queue.close()
        return None, f"timed out after {timeout_seconds} seconds"
    try:
        status, payload = result_queue.get(timeout=2)
    except Empty:
        return None, f"worker exited without an outcome (exit code {worker.exitcode})"
    finally:
        result_queue.close()
        result_queue.join_thread()
    if status == "error":
        return None, str(payload)
    return payload, None


def _ingest_anchor_worker(
    sqlite_db_path: Path,
    pdf_path: Path,
    report_date: str,
    source_id: str,
    result_queue: multiprocessing.Queue[tuple[str, Any]],
) -> None:
    """Run local PDF ingestion in a child process."""
    from psp_pipeline.pipelines.rldc_daily_psp import (
        LocalReportInput,
        run_rldc_local_pdf_ingestion,
    )

    try:
        ingestion = run_rldc_local_pdf_ingestion(
            sqlite_db_path,
            [
                LocalReportInput(
                    rldc=source_id,
                    local_path=pdf_path,
                    report_date=date.fromisoformat(report_date),
                )
            ],
        )
    except Exception as error:
        result_queue.put(("error", repr(error)))
        return
    result_queue.put(("ok", ingestion))


def _build_summary(
    sqlite_db_path: Path, source_id: str, results: list[NLDCAnchorScanResult]
) -> dict[str, Any]:
    """Build a structured JSON-serializable scan outcome summary."""
    outcomes = Counter(r.outcome for r in results)
    persisted_count = _persisted_report_count(sqlite_db_path, source_id)
    return {
        "rldc": source_id,
        "sqlite_db_path": str(sqlite_db_path),
        "anchor_count": len(results),
        "persisted_report_count": persisted_count,
        "outcome_counts": dict(sorted(outcomes.items())),
        "failed_reports": [
            {
                "report_name": r.sample.pdf_path.name,
                "report_date": r.sample.report_date,
                "anchor": r.sample.anchor,
                "error": r.error,
            }
            for r in results
            if r.outcome == "failed"
        ],
        "gated_reports": [
            {
                "report_name": r.sample.pdf_path.name,
                "report_date": r.sample.report_date,
                "anchor": r.sample.anchor,
            }
            for r in results
            if r.outcome == "gated"
        ],
    }


def _persisted_report_count(sqlite_db_path: Path, source_id: str) -> int:
    """Return the source-scoped document count in SQLite."""
    if not sqlite_db_path.exists():
        return 0
    conn = sqlite3.connect(str(sqlite_db_path))
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_report_document'",
        ).fetchone()
        if exists is None:
            return 0
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM psp_report_document WHERE rldc = ?",
                (source_id,),
            ).fetchone()[0]
        )
    finally:
        conn.close()
