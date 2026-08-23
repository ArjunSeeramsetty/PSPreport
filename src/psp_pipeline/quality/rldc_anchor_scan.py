"""Replayable monthly-anchor ingestion scans for public RLDC PSP archives."""

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
SUPPORTED_RLDCS = frozenset({"wrldc"})
DEFAULT_ANCHOR_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class AnchorScanResult:
    """Outcome recorded for one monthly anchor document."""

    sample: MonthlyAnchorSample
    outcome: str
    error: str | None = None


def scan_rldc_monthly_anchors(
    input_dir: Path,
    sqlite_db_path: Path,
    *,
    rldc: str,
    timeout_seconds: int = DEFAULT_ANCHOR_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Ingest local monthly anchors with source-scoped resume and fail-soft rules.

    Only WRLDC is supported currently. Existing source documents are completed
    checkpoints; a failure for one local PDF does not stop later anchors.
    """

    source_id = rldc.lower()
    if source_id not in SUPPORTED_RLDCS:
        raise ValueError(f"Unsupported RLDC anchor scan source: {rldc}")

    samples = _unique_samples(
        _select_monthly_anchor_paths(
            sorted(input_dir.glob("*.pdf")), source_id=source_id
        )
    )
    completed_paths = _load_completed_paths(sqlite_db_path, source_id)
    results: list[AnchorScanResult] = []
    for index, sample in enumerate(samples, start=1):
        logger.info(
            "rldc_anchor_scan_progress source=%s index=%s total=%s date=%s anchor=%s",
            source_id, index, len(samples), sample.report_date, sample.anchor,
        )
        if str(sample.pdf_path) in completed_paths:
            results.append(AnchorScanResult(sample, "already_persisted"))
            continue
        ingestion, error = _ingest_anchor_with_timeout(
            sqlite_db_path,
            sample,
            source_id,
            timeout_seconds,
        )
        if error is not None:
            logger.warning(
                "rldc_anchor_scan_failed source=%s path=%s error=%s",
                source_id, sample.pdf_path, error,
            )
            results.append(AnchorScanResult(sample, "failed", error))
            continue

        outcome = "skipped"
        if ingestion["report_family_rejected"]:
            outcome = "family_rejected"
        elif ingestion["reports_persisted"]:
            outcome = "persisted"
        results.append(AnchorScanResult(sample, outcome))
    return _build_summary(sqlite_db_path, source_id, results)


def scan_wrldc_monthly_anchors(
    input_dir: Path,
    sqlite_db_path: Path,
    *,
    timeout_seconds: int = DEFAULT_ANCHOR_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Scan local WRLDC PSP monthly anchors into ``sqlite_db_path``."""

    return scan_rldc_monthly_anchors(
        input_dir,
        sqlite_db_path,
        rldc="wrldc",
        timeout_seconds=timeout_seconds,
    )


def _select_monthly_anchor_paths(
    pdf_paths: list[Path], source_id: str
) -> list[MonthlyAnchorSample]:
    """Load the existing source-aware monthly anchor selector when needed."""

    from psp_pipeline.schema_design.service import select_monthly_anchor_paths

    return select_monthly_anchor_paths(pdf_paths, source_id=source_id)


def _unique_samples(samples: list[MonthlyAnchorSample]) -> list[MonthlyAnchorSample]:
    """Preserve anchor order while avoiding duplicate first/last files in sparse months."""

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
    connection = sqlite3.connect(sqlite_db_path)
    try:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("psp_report_document",),
        ).fetchone()
        if table_exists is None:
            return set()
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT local_path FROM psp_report_document WHERE rldc = ?",
                (source_id,),
            )
        }
    finally:
        connection.close()


def _ingest_anchor_with_timeout(
    sqlite_db_path: Path,
    sample: MonthlyAnchorSample,
    source_id: str,
    timeout_seconds: int,
) -> tuple[dict[str, int] | None, str | None]:
    """Run one local ingestion in an isolated worker with a hard time limit."""

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
    """Run local PDF ingestion in a child process and return a compact result."""

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
    sqlite_db_path: Path, source_id: str, results: list[AnchorScanResult]
) -> dict[str, Any]:
    """Return stable JSON-ready scan diagnostics and replay outcomes."""

    outcomes = Counter(result.outcome for result in results)
    persisted_count = _persisted_report_count(sqlite_db_path, source_id)
    return {
        "rldc": source_id,
        "sqlite_db_path": str(sqlite_db_path),
        "anchor_count": len(results),
        "persisted_report_count": persisted_count,
        "outcome_counts": dict(sorted(outcomes.items())),
        "failed_reports": [
            {
                "report_name": result.sample.pdf_path.name,
                "report_date": result.sample.report_date,
                "anchor": result.sample.anchor,
                "error": result.error,
            }
            for result in results
            if result.outcome == "failed"
        ],
    }


def _persisted_report_count(sqlite_db_path: Path, source_id: str) -> int:
    """Return the source-scoped document count after a scan attempt."""

    if not sqlite_db_path.exists():
        return 0
    connection = sqlite3.connect(sqlite_db_path)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("psp_report_document",),
        ).fetchone()
        if exists is None:
            return 0
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM psp_report_document WHERE rldc = ?",
                (source_id,),
            ).fetchone()[0]
        )
    finally:
        connection.close()
