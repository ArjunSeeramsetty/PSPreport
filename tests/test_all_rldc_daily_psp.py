"""Tests for fail-soft multi-RLDC daily PSP coordination."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from psp_pipeline.pipelines.all_rldc_daily_psp import run_all_rldc_daily_psp


def test_coordinator_continues_after_one_source_failure(tmp_path: Path) -> None:
    """A failed regional collector cannot prevent later regional runs."""

    calls: list[str] = []

    def runner(**kwargs: object) -> dict[str, int]:
        source_id = next(iter(kwargs["target_rldcs"]))
        calls.append(source_id)
        if source_id == "nrldc":
            raise RuntimeError("listing unavailable")
        return {
            "pdf_links_found": 1,
            "reports_downloaded": 1,
            "reports_persisted": 1,
            "ocr_recommended": 0,
            "report_family_rejected": 0,
        }

    result = run_all_rldc_daily_psp(
        config_path=tmp_path / "sources.yaml",
        sqlite_db_path=tmp_path / "consolidated.sqlite",
        download_root=tmp_path / "raw",
        target_date=date(2026, 5, 1),
        collection_runner=runner,
    )

    assert calls == [
        "srldc",
        "nrldc",
        "wrldc",
        "erldc",
        "nerldc",
        "grid_india_national",
    ]
    assert result["aggregate"]["sources_completed"] == 5
    assert result["aggregate"]["sources_failed"] == 1
    assert result["aggregate"]["reports_persisted"] == 5
    assert result["source_failures"]["nrldc"] == "RuntimeError: listing unavailable"


def test_coordinator_limits_execution_to_requested_sources(tmp_path: Path) -> None:
    """A selected source subset preserves canonical ordering and aggregation."""

    calls: list[str] = []

    def runner(**kwargs: object) -> dict[str, int]:
        source_id = next(iter(kwargs["target_rldcs"]))
        calls.append(source_id)
        return {"reports_persisted": 2}

    result = run_all_rldc_daily_psp(
        config_path=tmp_path / "sources.yaml",
        sqlite_db_path=tmp_path / "consolidated.sqlite",
        download_root=tmp_path / "raw",
        target_rldcs={"nerldc", "srldc"},
        collection_runner=runner,
    )

    assert calls == ["srldc", "nerldc"]
    assert result["aggregate"]["sources_requested"] == 2
    assert result["aggregate"]["reports_persisted"] == 4


def test_coordinator_rejects_unknown_sources(tmp_path: Path) -> None:
    """Invalid source ids fail before any collection attempt."""

    with pytest.raises(ValueError, match="Unknown RLDC source ids: invalid"):
        run_all_rldc_daily_psp(
            config_path=tmp_path / "sources.yaml",
            sqlite_db_path=tmp_path / "consolidated.sqlite",
            download_root=tmp_path / "raw",
            target_rldcs={"invalid"},
        )
