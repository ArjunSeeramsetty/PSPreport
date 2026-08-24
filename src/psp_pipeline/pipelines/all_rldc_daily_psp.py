"""Fail-soft coordinator for daily public PSP ingestion across all RLDCs."""

from __future__ import annotations

from datetime import date
import logging
from pathlib import Path
from typing import Any, Callable

from psp_pipeline.pipelines.rldc_daily_psp import run_rldc_daily_psp_collection


LOGGER = logging.getLogger(__name__)
RLDC_SOURCE_IDS = ("srldc", "nrldc", "wrldc", "erldc", "nerldc")
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
        target_rldcs: Optional subset of the five canonical regional sources.
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


def _selected_sources(target_rldcs: set[str] | None) -> tuple[str, ...]:
    """Validate an optional source subset while retaining a stable run order."""

    if target_rldcs is None:
        return RLDC_SOURCE_IDS
    normalized_sources = {source.lower() for source in target_rldcs}
    unknown_sources = normalized_sources.difference(RLDC_SOURCE_IDS)
    if unknown_sources:
        raise ValueError(f"Unknown RLDC source ids: {', '.join(sorted(unknown_sources))}")
    return tuple(source for source in RLDC_SOURCE_IDS if source in normalized_sources)
