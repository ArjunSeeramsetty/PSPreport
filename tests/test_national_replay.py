"""Unit tests for multi-date national replay and benchmark harness."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.quality.national_replay import run_national_replay


def test_run_national_replay_mocked(tmp_path: Path) -> None:
    db_path = tmp_path / "test_replay.sqlite"
    out_json = tmp_path / "replay_report.json"

    # Pre-populate database with a sample report and facts for 2025-01-01
    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)
        conn.executescript(
            """
            INSERT INTO psp_report_document(id, rldc, source_url, local_path, content_hash, fetched_at, ocr_score, ocr_used, ocr_reason, extracted_char_count, report_date)
            VALUES (1, 'srldc', 'http://example.com', 'srldc.pdf', 'hash1', '2025-01-01T00:00:00Z', 1.0, 0, 'none', 100, '2025-01-01');

            INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2025-01-01');

            INSERT INTO FactSRLDCStateDaily(ReportDocumentID, DateID, StateID, DemandMetMU)
            VALUES (1, 1, (SELECT StateID FROM DimStates WHERE StateName = 'Karnataka'), 250.0);
            """
        )
        conn.commit()

    def dummy_runner(**kwargs: object) -> dict[str, int]:
        return {
            "sources_completed": 1,
            "sources_failed": 0,
            "pdf_links_found": 1,
            "reports_downloaded": 1,
            "reports_persisted": 1,
            "ocr_recommended": 0,
            "report_family_rejected": 0,
        }

    report = run_national_replay(
        sqlite_db_path=db_path,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
        target_rldcs={"srldc"},
        output_path=out_json,
        collection_runner=dummy_runner,
    )

    assert report["total_dates_processed"] == 2
    assert len(report["date_results"]) == 2
    assert out_json.exists()
    assert report["date_results"][0]["target_date"] == "2025-01-01"
    assert report["date_results"][0]["observations_exported"] > 0
    assert "final_dimension_audit" in report


def test_run_national_replay_with_balance_synthesis(tmp_path: Path) -> None:
    db_path = tmp_path / "balance_replay.sqlite"

    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)
        conn.executescript(
            """
            INSERT INTO psp_report_document(id, rldc, source_url, local_path, content_hash, fetched_at, ocr_score, ocr_used, ocr_reason, extracted_char_count, report_date)
            VALUES (1, 'srldc', 'http://example.com/sr', 'srldc.pdf', 'hash1', '2025-01-01T00:00:00Z', 1.0, 0, 'none', 100, '2025-01-01'),
                   (2, 'nerldc', 'http://example.com/ner', 'nerldc.pdf', 'hash2', '2025-01-01T00:00:00Z', 1.0, 0, 'none', 100, '2025-01-01');

            INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2025-01-01');

            INSERT INTO FactSRLDCRegionalDaily(ReportDocumentID, DateID, RegionID, DayEnergyMetMU)
            VALUES (1, 1, (SELECT RegionID FROM DimRegions WHERE RegionName = 'Southern Region'), 950.0);

            INSERT INTO FactNERLDCRegionalDaily(ReportDocumentID, DateID, RegionID, DayEnergyMetMU)
            VALUES (2, 1, (SELECT RegionID FROM DimRegions WHERE RegionName = 'North Eastern Region'), 48.5);
            """
        )
        conn.commit()

    def dummy_runner(**kwargs: object) -> dict[str, int]:
        return {"sources_completed": 2, "reports_persisted": 2}

    report = run_national_replay(
        sqlite_db_path=db_path,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 1),
        target_rldcs={"srldc", "nerldc"},
        collection_runner=dummy_runner,
    )

    assert report["total_dates_processed"] == 1
    assert report["date_results"][0]["balance_synthesized"] is True
    assert "srldc" in report["date_results"][0]["sources_in_balance"]
    assert "nerldc" in report["date_results"][0]["sources_in_balance"]


def test_replay_observation_yields_are_scoped_to_each_date(tmp_path: Path) -> None:
    """A later date must not re-count observations from earlier replay dates."""

    db_path = tmp_path / "date_scoped_replay.sqlite"
    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)
        conn.executescript(
            """
            INSERT INTO psp_report_document(id, rldc, source_url, local_path, content_hash, fetched_at, ocr_score, ocr_used, ocr_reason, extracted_char_count, report_date)
            VALUES (1, 'srldc', 'http://example.com/one', 'one.pdf', 'hash-one', '2025-01-01T00:00:00Z', 1.0, 0, 'none', 100, '2025-01-01'),
                   (2, 'srldc', 'http://example.com/two', 'two.pdf', 'hash-two', '2025-01-02T00:00:00Z', 1.0, 0, 'none', 100, '2025-01-02');
            INSERT INTO DimDates(DateID, ActualDate) VALUES (1, '2025-01-01'), (2, '2025-01-02');
            INSERT INTO FactSRLDCStateDaily(ReportDocumentID, DateID, StateID, DemandMetMU)
            VALUES (1, 1, (SELECT StateID FROM DimStates WHERE StateName = 'Karnataka'), 10.0),
                   (2, 2, (SELECT StateID FROM DimStates WHERE StateName = 'Karnataka'), 20.0);
            """
        )

    report = run_national_replay(
        sqlite_db_path=db_path,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
        target_rldcs={"srldc"},
        collection_runner=lambda **_: {"sources_completed": 1, "reports_persisted": 0},
    )

    yields = [result["observations_exported"] for result in report["date_results"]]
    assert yields[0] == yields[1] == 1
