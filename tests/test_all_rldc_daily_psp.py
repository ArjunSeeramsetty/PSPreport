"""Tests for fail-soft multi-RLDC daily PSP coordination."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from psp_pipeline.pipelines.all_rldc_daily_psp import (
    catch_up_missing_rldc_dates,
    missing_sources_for_date,
    run_all_rldc_daily_psp,
)
from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema


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


def test_missing_sources_for_date_excludes_persisted_reports(tmp_path: Path) -> None:
    """Catch-up only targets sources that never stored the requested valid date."""

    import sqlite3

    db_path = tmp_path / "catch_up.sqlite"
    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)
        conn.execute(
            """
            INSERT INTO psp_report_document(
                rldc, source_url, local_path, content_hash, fetched_at,
                ocr_score, ocr_used, ocr_reason, extracted_char_count, report_date
            ) VALUES ('srldc', 'u', 'p', 'h', '2026-01-02T00:00:00Z', 1, 0, 'n', 1, '2026-01-02')
            """
        )
        conn.commit()

    missing = missing_sources_for_date(db_path, date(2026, 1, 2))
    assert "srldc" not in missing
    assert "erldc" in missing


def test_catch_up_replays_only_missing_sources_in_the_lookback_window(
    tmp_path: Path,
) -> None:
    """Yesterday's missing sources are collected; complete dates are skipped."""

    import sqlite3

    db_path = tmp_path / "catch_up.sqlite"
    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)
        conn.execute(
            """
            INSERT INTO psp_report_document(
                rldc, source_url, local_path, content_hash, fetched_at,
                ocr_score, ocr_used, ocr_reason, extracted_char_count, report_date
            ) VALUES ('srldc', 'u', 'p', 'h1', '2026-01-01T00:00:00Z', 1, 0, 'n', 1, '2026-01-01'),
                     ('nrldc', 'u', 'p', 'h2', '2026-01-01T00:00:00Z', 1, 0, 'n', 1, '2026-01-01'),
                     ('wrldc', 'u', 'p', 'h3', '2026-01-01T00:00:00Z', 1, 0, 'n', 1, '2026-01-01'),
                     ('erldc', 'u', 'p', 'h4', '2026-01-01T00:00:00Z', 1, 0, 'n', 1, '2026-01-01'),
                     ('nerldc', 'u', 'p', 'h5', '2026-01-01T00:00:00Z', 1, 0, 'n', 1, '2026-01-01'),
                     ('grid_india_national', 'u', 'p', 'h6', '2026-01-01T00:00:00Z', 1, 0, 'n', 1, '2026-01-01')
            """
        )
        conn.commit()

    calls: list[tuple[str, str]] = []

    def runner(**kwargs: object) -> dict[str, int]:
        source_id = next(iter(kwargs["target_rldcs"]))
        calls.append((kwargs["target_date"].isoformat(), source_id))
        return {"reports_persisted": 1}

    result = catch_up_missing_rldc_dates(
        config_path=tmp_path / "sources.yaml",
        sqlite_db_path=db_path,
        download_root=tmp_path / "raw",
        target_date=date(2026, 1, 3),
        lookback_days=2,
        collection_runner=runner,
    )

    assert result["dates"][0]["target_date"] == "2026-01-01"
    assert result["dates"][0]["skipped"] is True
    assert result["dates"][1]["target_date"] == "2026-01-02"
    assert result["dates"][1]["skipped"] is False
    assert calls[0][0] == "2026-01-02"
    assert {source for _, source in calls} == {
        "srldc",
        "nrldc",
        "wrldc",
        "erldc",
        "nerldc",
        "grid_india_national",
    }
    assert all(day != "2026-01-03" for day, _source in calls)


def test_catch_up_does_not_recollect_the_anchor_date(tmp_path: Path) -> None:
    """Today's collect task owns the orchestration date; catch-up only looks back."""

    calls: list[str] = []

    def runner(**kwargs: object) -> dict[str, int]:
        calls.append(kwargs["target_date"].isoformat())
        return {"reports_persisted": 1}

    result = catch_up_missing_rldc_dates(
        config_path=tmp_path / "sources.yaml",
        sqlite_db_path=tmp_path / "missing.sqlite",
        download_root=tmp_path / "raw",
        target_date=date(2026, 1, 3),
        lookback_days=1,
        collection_runner=runner,
    )

    assert [item["target_date"] for item in result["dates"]] == ["2026-01-02"]
    assert set(calls) == {"2026-01-02"}
