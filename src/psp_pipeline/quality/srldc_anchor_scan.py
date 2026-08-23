"""Corpus-level validation for monthly SRLDC PSP report anchors."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
import logging
import multiprocessing
from pathlib import Path
from queue import Empty
import sqlite3
from typing import Any

from psp_pipeline.pipelines.rldc_daily_psp import (
    LocalReportInput,
    run_rldc_local_pdf_ingestion,
)
from psp_pipeline.schema_design.service import (
    MonthlyAnchorSample,
    select_monthly_anchor_paths,
)

logger = logging.getLogger(__name__)

DEFAULT_ANCHOR_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class AnchorScanResult:
    """One anchor's ingestion and promotion outcome."""

    sample: MonthlyAnchorSample
    outcome: str
    error: str | None = None


def scan_srldc_monthly_anchors(
    input_dir: Path,
    sqlite_db_path: Path,
    timeout_seconds: int = DEFAULT_ANCHOR_TIMEOUT_SECONDS,
    rldc: str = "srldc",
) -> dict[str, Any]:
    """Ingest local first/fifteenth/last RLDC anchors into an isolated database.

    The scan is fail-soft: a malformed or stalled report is recorded in the
    returned diagnostics while later anchor reports continue to be processed.
    """

    source_id = rldc.lower()
    samples = select_monthly_anchor_paths(
        sorted(input_dir.glob("*.pdf")),
        source_id=source_id,
    )
    completed_paths = _load_completed_paths(sqlite_db_path, source_id)
    results: list[AnchorScanResult] = []
    for index, sample in enumerate(samples, start=1):
        logger.info(
            "rldc_anchor_scan_progress source=%s index=%s total=%s date=%s anchor=%s",
            source_id,
            index,
            len(samples),
            sample.report_date,
            sample.anchor,
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
                source_id,
                sample.pdf_path,
                error,
            )
            results.append(AnchorScanResult(sample, "failed", error))
            continue

        if ingestion["report_family_rejected"]:
            results.append(AnchorScanResult(sample, "family_rejected"))
        elif ingestion["reports_persisted"]:
            results.append(AnchorScanResult(sample, "persisted"))
        else:
            results.append(AnchorScanResult(sample, "skipped"))

    return _build_summary(sqlite_db_path, source_id, results)


def scan_nrldc_monthly_anchors(
    input_dir: Path,
    sqlite_db_path: Path,
    timeout_seconds: int = DEFAULT_ANCHOR_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Scan local NRLDC monthly anchors into an isolated SQLite database."""
    return scan_srldc_monthly_anchors(
        input_dir,
        sqlite_db_path,
        timeout_seconds=timeout_seconds,
        rldc="nrldc",
    )


def _load_completed_paths(sqlite_db_path: Path, source_id: str) -> set[str]:
    """Return local PDF paths already persisted by an interrupted anchor scan."""

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
    """Execute one ingestion in a child process and return its compact result."""

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
    except Exception as exc:
        result_queue.put(("error", repr(exc)))
        return
    result_queue.put(("ok", ingestion))


def _build_summary(
    sqlite_db_path: Path,
    source_id: str,
    results: list[AnchorScanResult],
) -> dict[str, Any]:
    """Build JSON-serializable template, reconciliation, and ambiguity metrics."""

    connection = sqlite3.connect(sqlite_db_path)
    try:
        has_documents = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("psp_report_document",),
        ).fetchone()
        if has_documents is None:
            return _empty_summary(source_id, results)
        template_counts = Counter(
            template_id or "unmatched"
            for (template_id,) in connection.execute(
                """
                SELECT template_id FROM psp_report_document
                WHERE rldc = ? ORDER BY id
                """,
                (source_id,),
            )
        )
        semantic_required = int(connection.execute(
            """
            SELECT COUNT(*) FROM psp_report_document
            WHERE rldc = ? AND semantic_pass_required = 1
            """,
            (source_id,),
        ).fetchone()[0])
        persisted_reports = int(connection.execute(
            "SELECT COUNT(*) FROM psp_report_document WHERE rldc = ?",
            (source_id,),
        ).fetchone()[0])
        coverage_rows = connection.execute(
            """
            SELECT coverage.Status, coverage.ValidationFailureCount
            FROM schema_coverage_run AS coverage
            JOIN psp_report_document AS document
              ON document.id = coverage.ReportDocumentID
            WHERE document.rldc = ?
            """,
            (source_id,),
        ).fetchall()
        status_counts = Counter(str(status) for status, _ in coverage_rows)
        direct_promotions = status_counts["passed"]
        reconciliation_failures = sum(int(value) for _, value in coverage_rows)
        ambiguity_rows = connection.execute(
            """
            SELECT
                coverage.TemplateID,
                raw.page_no,
                raw.table_no,
                raw.col_no,
                COUNT(*) AS occurrence_count,
                MIN(raw.cell_text) AS example_value
            FROM schema_coverage_item AS item
            JOIN schema_coverage_run AS coverage
              ON coverage.CoverageRunID = item.CoverageRunID
            JOIN psp_raw_cell AS raw ON raw.id = item.RawCellID
            JOIN psp_report_document AS document
              ON document.id = coverage.ReportDocumentID
            WHERE item.Disposition = 'ambiguous' AND document.rldc = ?
            GROUP BY coverage.TemplateID, raw.page_no, raw.table_no, raw.col_no
            ORDER BY occurrence_count DESC, coverage.TemplateID, raw.page_no,
                     raw.table_no, raw.col_no
            LIMIT 100
            """,
            (source_id,),
        ).fetchall()
    finally:
        connection.close()

    outcomes = Counter(result.outcome for result in results)
    failed_reports = [
        {
            "report_name": result.sample.pdf_path.name,
            "report_date": result.sample.report_date,
            "anchor": result.sample.anchor,
            "error": result.error,
        }
        for result in results
        if result.outcome == "failed"
    ]
    return {
        "rldc": source_id,
        "anchor_count": len(results),
        "outcome_counts": dict(sorted(outcomes.items())),
        "template_counts": dict(sorted(template_counts.items())),
        "persisted_report_count": persisted_reports,
        "direct_promotion_count": direct_promotions,
        "semantic_pass_required_count": semantic_required,
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "reconciliation_failure_count": reconciliation_failures,
        "failed_reports": failed_reports,
        "high_frequency_ambiguities": [
            {
                "template_id": template_id,
                "page_no": page_no,
                "table_no": table_no,
                "col_no": col_no,
                "occurrence_count": occurrence_count,
                "example_value": example_value,
            }
            for template_id, page_no, table_no, col_no, occurrence_count, example_value
            in ambiguity_rows
        ],
    }


def _empty_summary(
    source_id: str,
    results: list[AnchorScanResult],
) -> dict[str, Any]:
    """Return a stable diagnostic when no worker created raw ingestion tables."""

    outcomes = Counter(result.outcome for result in results)
    return {
        "rldc": source_id,
        "anchor_count": len(results),
        "outcome_counts": dict(sorted(outcomes.items())),
        "template_counts": {},
        "persisted_report_count": 0,
        "direct_promotion_count": 0,
        "semantic_pass_required_count": 0,
        "coverage_status_counts": {},
        "reconciliation_failure_count": 0,
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
        "high_frequency_ambiguities": [],
    }
