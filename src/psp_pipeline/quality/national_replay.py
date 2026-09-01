"""Multi-date rolling ingestion replay and benchmark harness across all 5 RLDCs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

from psp_pipeline.pipelines.all_rldc_daily_psp import run_all_rldc_daily_psp
from psp_pipeline.quality.coverage_contract import (
    default_coverage_manifest_path,
    evaluate_coverage_manifest,
)
from psp_pipeline.quality.national_dimension_audit import audit_national_dimensions
from psp_pipeline.reconciliation.all_india_balance import synthesize_all_india_daily_balance
from psp_pipeline.storage.sqlite_curated_export import export_all_daily_observations
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DateReplayResult:
    """Outcome for a single replay date across selected RLDCs."""

    target_date: str
    sources_completed: int
    sources_failed: int
    reports_persisted: int
    observations_exported: int
    balance_synthesized: bool
    sources_in_balance: list[str]


@dataclass(frozen=True)
class NationalReplayReport:
    """Consolidated replay report across a date window."""

    started_at: str
    completed_at: str
    start_date: str
    end_date: str
    total_dates_processed: int
    total_reports_persisted: int
    total_observations_exported: int
    date_results: list[DateReplayResult]
    final_dimension_audit: dict[str, Any]


def run_national_replay(
    sqlite_db_path: Path | str,
    start_date: date,
    end_date: date,
    target_rldcs: set[str] | None = None,
    download_root: Path | str | None = None,
    config_path: Path | str | None = None,
    output_path: Path | str | None = None,
    collection_runner: Any = None,
) -> dict[str, Any]:
    """Execute a sequential multi-day replay across all 5 Indian RLDCs.

    Args:
        sqlite_db_path: Path to target SQLite database.
        start_date: Start date (inclusive).
        end_date: End date (inclusive).
        target_rldcs: Optional subset of RLDCs (default: all 5).
        download_root: Directory for local downloads.
        config_path: Sources configuration YAML.
        output_path: Optional path to write JSON replay report.

    Returns:
        Structured dictionary representation of `NationalReplayReport`.
    """
    db_path = Path(sqlite_db_path)
    dl_root = Path(download_root) if download_root else db_path.parent / "downloads"
    cfg_path = Path(config_path) if config_path else Path("config/rldc_report_sources.yaml")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        ensure_curated_sqlite_schema(conn)

    started_at = datetime.now(timezone.utc).isoformat()
    current_date = start_date
    date_results: list[DateReplayResult] = []
    total_persisted = 0
    total_exported = 0

    while current_date <= end_date:
        date_str = current_date.isoformat()
        LOGGER.info("Starting national replay for date=%s", date_str)

        # Run multi-RLDC daily collection and promotion
        call_kwargs: dict[str, Any] = {
            "config_path": cfg_path,
            "sqlite_db_path": db_path,
            "download_root": dl_root,
            "target_date": current_date,
            "max_reports_per_rldc": 1,
            "target_rldcs": target_rldcs,
        }
        if collection_runner is not None:
            call_kwargs["collection_runner"] = collection_runner
        collection = run_all_rldc_daily_psp(**call_kwargs)

        persisted = collection.get("aggregate", {}).get("reports_persisted", 0)
        total_persisted += persisted

        # Check export yield and all-India balance for this date
        with sqlite3.connect(db_path) as conn:
            date_row = conn.execute(
                "SELECT DateID FROM DimDates WHERE ActualDate = ?", (date_str,)
            ).fetchone()
            date_id = date_row[0] if date_row else None

            balance_ok = False
            sources_present: list[str] = []
            if date_id is not None:
                try:
                    balance = synthesize_all_india_daily_balance(conn, date_id=date_id)
                    balance_ok = bool(balance.sources_present)
                    sources_present = list(balance.sources_present)
                except Exception as exc:
                    LOGGER.warning("Balance synthesis skipped for %s: %s", date_str, exc)

            obs_count = 0
            if date_id is not None:
                try:
                    report_ids = [
                        int(row[0])
                        for row in conn.execute(
                            "SELECT id FROM psp_report_document WHERE report_date = ?",
                            (date_str,),
                        )
                    ]
                    obs = [
                        observation
                        for report_id in report_ids
                        for observation in export_all_daily_observations(
                            conn,
                            rldcs=target_rldcs,
                            report_document_id=report_id,
                        )
                    ]
                    obs_count = len(obs)
                    total_exported += obs_count
                except Exception as exc:
                    LOGGER.warning("Observation export skipped for %s: %s", date_str, exc)

        date_results.append(
            DateReplayResult(
                target_date=date_str,
                sources_completed=collection.get("aggregate", {}).get("sources_completed", 0),
                sources_failed=collection.get("aggregate", {}).get("sources_failed", 0),
                reports_persisted=persisted,
                observations_exported=obs_count,
                balance_synthesized=balance_ok,
                sources_in_balance=sources_present,
            )
        )
        current_date += timedelta(days=1)

    completed_at = datetime.now(timezone.utc).isoformat()

    # Final dimension quality audit and coverage-contract evaluation.
    try:
        final_audit = audit_national_dimensions(db_path)
    except Exception as exc:
        final_audit = {"error": str(exc)}

    try:
        coverage_results = evaluate_coverage_manifest(
            db_path,
            default_coverage_manifest_path(),
            profile_name="corpus",
            require_sources=target_rldcs,
        )
        final_coverage = {
            name: result.as_dict() for name, result in coverage_results.items()
        }
    except Exception as exc:
        final_coverage = {"error": str(exc)}

    report = NationalReplayReport(
        started_at=started_at,
        completed_at=completed_at,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        total_dates_processed=len(date_results),
        total_reports_persisted=total_persisted,
        total_observations_exported=total_exported,
        date_results=date_results,
        final_dimension_audit=final_audit,
    )
    report_dict = asdict(report)
    report_dict["coverage"] = final_coverage

    if output_path is not None:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2)

    return report_dict
