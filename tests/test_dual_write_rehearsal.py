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
from psp_pipeline.quality.rpc_fixtures import ingest_rpc_fixture_reports, write_canonical_rpc_fixtures


def _seed_srldc_energy(db_path: Path, report_id: int, report_date: str, energy_mu: float) -> None:
    """Insert one Southern-region daily energy fact for a replay date."""

    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)
        conn.execute(
            """
            INSERT INTO psp_report_document(
                id, rldc, source_url, local_path, content_hash, fetched_at,
                ocr_score, ocr_used, ocr_reason, extracted_char_count, report_date
            ) VALUES (?, 'srldc', 'http://example.com', ?, ?, '2026-09-01T00:00:00Z',
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
    fixture_dir = tmp_path / "rpc"
    write_canonical_rpc_fixtures(fixture_dir)
    ingest_rpc_fixture_reports(db_path, fixture_dir=fixture_dir)
    _seed_srldc_energy(db_path, 10, "2026-08-30", 950.0)
    _seed_srldc_energy(db_path, 11, "2026-09-06", 980.0)

    timescale_store: list[dict] = []
    graph_store: list[dict] = []
    summary = run_dual_write_rehearsal(
        db_path,
        date(2026, 8, 30),
        date(2026, 9, 6),
        timescale_sink=recording_timescale_sink(timescale_store),
        graph_sink=recording_graph_sink(graph_store),
        output_path=tmp_path / "dual_write.json",
    )

    dated = [item for item in summary["date_results"] if item["sqlite_observations"]]
    assert [item["target_date"] for item in dated] == ["2026-08-30", "2026-09-06"]
    first_keys = set(dated[0]["timescale"]["entity_keys"])
    second_keys = set(dated[1]["timescale"]["entity_keys"])
    assert first_keys
    assert second_keys
    assert first_keys != second_keys
    assert timescale_store[0]["target_date"] == "2026-08-30"
    assert graph_store[-1]["target_date"] == "2026-09-06"
    assert "SR" in dated[0]["timescale"]["source_regions"] or "ER" in dated[0]["timescale"]["source_regions"]

    facets = summary["openlineage"]["outputs"][0]["facets"]
    assert facets["coverageCompleteness"]["rpc_status"] == "floor_pass"
    assert facets["coverageCompleteness"]["rpc_fact_row_count"] >= 3
    assert facets["coverageCompleteness"]["full_psp_and_rpc_coverage"] is False
    rpc_assertion = next(
        item
        for item in facets["dataQualityAssertions"]["assertions"]
        if item["assertion"] == "rpc_status"
    )
    assert rpc_assertion["actual"] == "floor_pass"
    assert rpc_assertion["success"] is False
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
