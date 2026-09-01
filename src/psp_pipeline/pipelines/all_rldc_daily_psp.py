"""Fail-soft coordinator for daily public PSP ingestion across all RLDCs."""

from __future__ import annotations

from datetime import date, timedelta
import logging
from pathlib import Path
import sqlite3
from typing import Any, Callable

from psp_pipeline.pipelines.rldc_daily_psp import run_rldc_daily_psp_collection


LOGGER = logging.getLogger(__name__)
RLDC_SOURCE_IDS = (
    "srldc",
    "nrldc",
    "wrldc",
    "erldc",
    "nerldc",
    "grid_india_national",
)
CollectionRunner = Callable[..., dict[str, int]]


def run_all_rldc_daily_psp(
    config_path: Path,
    sqlite_db_path: Path,
    download_root: Path,
    target_date: date | None = None,
    max_reports_per_rldc: int = 3,
    target_rldcs: set[str] | None = None,
    collection_runner: CollectionRunner = run_rldc_daily_psp_collection,
) -> dict[str, Any]:
    """Run public PSP collection for each selected RLDC without cross-source aborts.

    Args:
        config_path: Public-source configuration shared by regional collectors.
        sqlite_db_path: Consolidated raw and curated SQLite destination.
        download_root: Local directory for downloaded source artifacts.
        target_date: Optional report date; defaults to the individual collector's
            current-date behavior.
        max_reports_per_rldc: Per-source discovery limit.
        target_rldcs: Optional subset of the regional sources and NLDC feed.
        collection_runner: Injectable collector used by tests and local runners.

    Returns:
        A source-indexed result with aggregated counters and isolated failures.
    """

    selected_sources = _selected_sources(target_rldcs)
    aggregate = {
        "sources_requested": len(selected_sources),
        "sources_completed": 0,
        "sources_failed": 0,
        "pdf_links_found": 0,
        "reports_downloaded": 0,
        "reports_persisted": 0,
        "ocr_recommended": 0,
        "report_family_rejected": 0,
    }
    source_results: dict[str, dict[str, int]] = {}
    source_failures: dict[str, str] = {}

    for source_id in selected_sources:
        try:
            result = collection_runner(
                config_path=config_path,
                sqlite_db_path=sqlite_db_path,
                download_root=download_root,
                target_rldcs={source_id},
                max_reports_per_rldc=max_reports_per_rldc,
                target_date=target_date,
            )
        except Exception as error:  # Source failures must not block other regions.
            LOGGER.exception("all_rldc_source_failed source=%s", source_id)
            source_failures[source_id] = f"{type(error).__name__}: {error}"
            aggregate["sources_failed"] += 1
            continue

        source_results[source_id] = result
        aggregate["sources_completed"] += 1
        for counter_name in (
            "pdf_links_found",
            "reports_downloaded",
            "reports_persisted",
            "ocr_recommended",
            "report_family_rejected",
        ):
            aggregate[counter_name] += int(result.get(counter_name, 0))

    return {
        "aggregate": aggregate,
        "sources": source_results,
        "source_failures": source_failures,
    }


def missing_sources_for_date(
    sqlite_db_path: Path | str,
    target_date: date,
    expected_sources: tuple[str, ...] | None = None,
) -> set[str]:
    """Return public sources with no persisted report for one valid date."""

    expected = expected_sources or RLDC_SOURCE_IDS
    path = Path(sqlite_db_path)
    if not path.exists():
        return set(expected)
    with sqlite3.connect(path) as conn:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("psp_report_document",),
        ).fetchone()
        if not has_table:
            return set(expected)
        present = {
            str(row[0])
            for row in conn.execute(
                "SELECT DISTINCT rldc FROM psp_report_document WHERE report_date = ?",
                (target_date.isoformat(),),
            )
        }
    return {source for source in expected if source not in present}


def catch_up_missing_rldc_dates(
    *,
    config_path: Path,
    sqlite_db_path: Path,
    download_root: Path,
    target_date: date,
    lookback_days: int = 2,
    max_reports_per_rldc: int = 1,
    collection_runner: CollectionRunner = run_rldc_daily_psp_collection,
) -> dict[str, Any]:
    """Re-collect recent dates that never persisted a report for a source.

    Today's orchestration date is owned by the primary collect task. This
    catch-up only walks the lookback window so a single outage does not leave
    a permanent hole in the curated SQLite replay.
    """

    lookback = max(int(lookback_days), 0)
    date_results: list[dict[str, Any]] = []
    for offset in range(lookback, 0, -1):
        catch_date = target_date - timedelta(days=offset)
        missing = missing_sources_for_date(sqlite_db_path, catch_date)
        if not missing:
            date_results.append(
                {
                    "target_date": catch_date.isoformat(),
                    "missing_sources": [],
                    "skipped": True,
                }
            )
            continue
        LOGGER.info(
            "rldc_catch_up date=%s missing=%s",
            catch_date.isoformat(),
            ",".join(sorted(missing)),
        )
        collection = run_all_rldc_daily_psp(
            config_path=config_path,
            sqlite_db_path=sqlite_db_path,
            download_root=download_root,
            target_date=catch_date,
            max_reports_per_rldc=max_reports_per_rldc,
            target_rldcs=missing,
            collection_runner=collection_runner,
        )
        date_results.append(
            {
                "target_date": catch_date.isoformat(),
                "missing_sources": sorted(missing),
                "skipped": False,
                "aggregate": collection.get("aggregate", {}),
                "source_failures": collection.get("source_failures", {}),
            }
        )
    return {
        "lookback_days": lookback,
        "anchor_date": target_date.isoformat(),
        "dates": date_results,
    }


def _selected_sources(target_rldcs: set[str] | None) -> tuple[str, ...]:
    """Validate an optional source subset while retaining a stable run order."""

    if target_rldcs is None:
        return RLDC_SOURCE_IDS
    normalized_sources = {source.lower() for source in target_rldcs}
    unknown_sources = normalized_sources.difference(RLDC_SOURCE_IDS)
    if unknown_sources:
        raise ValueError(f"Unknown RLDC source ids: {', '.join(sorted(unknown_sources))}")
    return tuple(source for source in RLDC_SOURCE_IDS if source in normalized_sources)
