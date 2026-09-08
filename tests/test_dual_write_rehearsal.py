"""Multi-date SQLite → Timescale → Neo4j dual-write rehearsal."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.quality.dual_write_rehearsal import (
    recording_graph_sink,
    recording_timescale_sink,
    run_dual_write_rehearsal,
)
from psp_pipeline.quality.national_replay import run_national_replay


def _seed_srldc_energy(db_path: Path, report_id: int, report_date: str, energy_mu: float) -> None:
    """Insert one Southern-region daily energy fact for a replay date."""

    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)
        conn.execute(
            """
            INSERT INTO psp_report_document(
                id, rldc, source_url, local_path, content_hash, fetched_at,
                ocr_score, ocr_used, ocr_reason, extracted_char_count, report_date
            ) VALUES (?, 'srldc', 'http://example.com', ?, ?, '2026-01-02T00:00:00Z',
                      1.0, 0, 'none', 100, ?)
            """,
            (report_id, f"srldc-{report_date}.pdf", f"hash-{report_id}", report_date),
        )
        conn.execute(
            "INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (?, ?)",
            (report_id, report_date),
        )
        conn.execute(
            """
            INSERT INTO FactSRLDCRegionalDaily(ReportDocumentID, DateID, RegionID, DayEnergyMetMU)
            VALUES (?, ?, (SELECT RegionID FROM DimRegions WHERE RegionName = 'Southern Region'), ?)
            """,
            (report_id, report_id, energy_mu),
        )
        conn.commit()


def test_dual_write_rehearsal_scopes_timescale_and_graph_to_each_date(
    tmp_path: Path,
) -> None:
    """Each valid date publishes only that day's SQLite observations to both sinks."""

    db_path = tmp_path / "dual.sqlite"
    _seed_srldc_energy(db_path, 1, "2026-01-01", 950.0)
    _seed_srldc_energy(db_path, 2, "2026-01-02", 980.0)

    timescale_store: list[dict] = []
    graph_store: list[dict] = []
    summary = run_dual_write_rehearsal(
        db_path,
        date(2026, 1, 1),
        date(2026, 1, 2),
        timescale_sink=recording_timescale_sink(timescale_store),
        graph_sink=recording_graph_sink(graph_store),
        output_path=tmp_path / "dual_write.json",
    )

    assert [item["target_date"] for item in summary["date_results"]] == [
        "2026-01-01",
        "2026-01-02",
    ]
    first, second = summary["date_results"]
    assert first["sqlite_report_ids"] == [1]
    assert second["sqlite_report_ids"] == [2]
    assert first["sqlite_observations"] == second["sqlite_observations"] == 1
    assert first["timescale"]["observations_exported"] == 1
    assert second["timescale"]["observations_exported"] == 1
    assert first["neo4j"]["observations_synced"] == 1
    assert second["neo4j"]["observations_synced"] == 1
    assert timescale_store[0]["target_date"] == "2026-01-01"
    assert graph_store[1]["target_date"] == "2026-01-02"
    assert "SR" in first["timescale"]["source_regions"]

    facets = summary["openlineage"]["outputs"][0]["facets"]
    assert "coverageCompleteness" in facets
    assert "dataQualityAssertions" in facets
    assert facets["coverageCompleteness"]["rpc_status"] == "not_demonstrated"
    assert facets["coverageCompleteness"]["full_psp_and_rpc_coverage"] is False
    assert (tmp_path / "dual_write.json").exists()


def test_national_replay_attaches_dual_write_when_sinks_are_provided(
    tmp_path: Path,
) -> None:
    """The multi-date harness can rehearse dual-write without live databases."""

    db_path = tmp_path / "national.sqlite"
    _seed_srldc_energy(db_path, 1, "2025-01-01", 250.0)
    _seed_srldc_energy(db_path, 2, "2025-01-02", 260.0)

    timescale_store: list[dict] = []
    report = run_national_replay(
        sqlite_db_path=db_path,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
        target_rldcs={"srldc"},
        collection_runner=lambda **_: {"sources_completed": 1, "reports_persisted": 0},
        timescale_sink=recording_timescale_sink(timescale_store),
    )

    assert "dual_write" in report
    assert report["dual_write"]["dates_processed"] == 2
    assert [item["target_date"] for item in timescale_store] == ["2025-01-01", "2025-01-02"]
    assert report["dual_write"]["openlineage"]["outputs"][0]["facets"]["coverageCompleteness"][
        "full_psp_and_rpc_coverage"
    ] is False


def test_dual_write_rehearsal_publishes_rpc_fixture_settlement(tmp_path: Path) -> None:
    """Canonical RPC fixtures dual-write settlement observations at full RPC cell coverage."""

    db_path = tmp_path / "rpc-dual.sqlite"
    timescale_store: list[dict] = []
    graph_store: list[dict] = []
    summary = run_dual_write_rehearsal(
        db_path,
        date(2026, 8, 1),
        date(2026, 8, 30),
        timescale_sink=recording_timescale_sink(timescale_store),
        graph_sink=recording_graph_sink(graph_store),
        ingest_rpc_fixtures=True,
        skip_empty_dates=True,
        rpc_fixture_dir=tmp_path / "rpc",
        output_path=tmp_path / "rpc_dual_write.json",
    )

    dates = [item["target_date"] for item in summary["date_results"]]
    assert dates == ["2026-08-01", "2026-08-30"]
    rea, dsm = summary["date_results"]
    assert rea["sqlite_observations"] >= 1
    assert dsm["sqlite_observations"] >= 5
    regions = set(dsm["timescale"]["source_regions"])
    assert {"ER", "NR", "SR", "WR", "NER"} <= regions
    completeness = summary["coverage_completeness"]
    assert completeness["rpc_status"] == "full"
    assert completeness["rpc_fact_row_count"] >= 8
    assert completeness["full_psp_and_rpc_coverage"] is False
    assert set(completeness["accounted_cell_pct_by_source"]) >= {
        "erpc",
        "nrpc",
        "srpc",
        "wrpc",
        "nerpc",
    }
    assert summary["rpc_fixtures"]["reports_persisted"] == 6
    assert (tmp_path / "rpc_dual_write.json").exists()
