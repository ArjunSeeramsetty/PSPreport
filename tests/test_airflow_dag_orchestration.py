"""Tests for 5-RLDC stage orchestration functions."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.core.settings import AppSettings, load_settings
from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.pipelines.stages import (
    audit_national_curated_dimensions,
    collect_all_rldc_daily_psp,
    evaluate_curated_coverage_contract,
    export_all_curated_to_timescale,
    reconcile_national_daily_balance,
    sync_all_curated_to_graph,
)
from psp_pipeline.quality.timescale_mirror_reconciliation import CurrentMirrorRow
from psp_pipeline.storage.observation_identity import build_series_key


@pytest.fixture
def mock_settings(tmp_path: Path) -> AppSettings:
    settings = load_settings()
    return AppSettings(
        project_root=tmp_path,
        raw_bucket="test",
        postgres_dsn=settings.postgres_dsn,
        neo4j_uri=settings.neo4j_uri,
        neo4j_user=settings.neo4j_user,
        neo4j_password=settings.neo4j_password,
        minio_endpoint="localhost:9000",
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin",
        minio_secure=False,
        wbes_username="",
        wbes_password="",
        http_max_attempts=1,
        http_base_delay_seconds=0.0,
        http_max_delay_seconds=0.0,
        http_jitter_seconds=0.0,
    )


def test_collect_all_rldc_stage_fail_soft(mock_settings: AppSettings) -> None:
    result = collect_all_rldc_daily_psp(mock_settings, target_date=date(2025, 1, 1))
    assert "aggregate" in result
    assert "sources_failed" in result["aggregate"]
    assert "source_failures" in result


def test_reconcile_national_daily_balance_stage(tmp_path: Path) -> None:
    db_path = tmp_path / "all_rldc.sqlite"
    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)

    result = reconcile_national_daily_balance(db_path, date_id=1)
    assert isinstance(result, dict)


def test_reconcile_national_balance_resolves_the_requested_valid_date(tmp_path: Path) -> None:
    """The daily stage must not fall back to the first SQLite date row."""

    db_path = tmp_path / "dated_balance.sqlite"
    target_date = date(2025, 4, 15)
    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)
        conn.execute("INSERT INTO DimDates(DateID, ActualDate) VALUES (?, ?)", (77, target_date.isoformat()))

    result = reconcile_national_daily_balance(db_path, target_date=target_date)

    assert result["date_id"] == 77


def test_audit_national_curated_dimensions_stage(tmp_path: Path) -> None:
    non_existent = tmp_path / "non_existent.sqlite"
    assert audit_national_curated_dimensions(non_existent) == {}


def test_export_and_sync_curated_stages_non_existent(mock_settings: AppSettings, tmp_path: Path) -> None:
    non_existent = tmp_path / "non_existent.sqlite"
    assert export_all_curated_to_timescale(mock_settings, non_existent) == 0
    assert sync_all_curated_to_graph(mock_settings, non_existent) == 0


def test_daily_dag_wires_coverage_contract_and_timescale_mirror() -> None:
    """The public DAG evaluates corpus floors and dual-write verification in-process."""

    dag_source = Path(__file__).resolve().parents[1] / "dags" / "psp_daily_pipeline.py"
    text = dag_source.read_text(encoding="utf-8")
    assert "coverage_contract_task" in text
    assert "evaluate_curated_coverage_contract" in text
    assert "export_all_curated_to_timescale" in text


def test_graph_stage_applies_constraints_and_syncs_topology(
    mock_settings: AppSettings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The DAG graph stage initializes constraints before merging dimensions."""

    from psp_pipeline.pipelines import stages

    db_path = tmp_path / "topology.sqlite"
    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)

    events: list[str] = []

    class FakeRepository:
        def __init__(self, *_: object) -> None:
            pass

        def ensure_constraints(self, statements: list[str]) -> None:
            assert statements
            events.append("constraints")

        def merge_grid_topology(self, topology: dict[str, object]) -> None:
            assert "regions" in topology
            events.append("topology")

        def close(self) -> None:
            events.append("close")

    monkeypatch.setattr(stages, "Neo4jRepository", FakeRepository)

    assert sync_all_curated_to_graph(mock_settings, db_path, target_date=date(2025, 1, 1)) == 0
    assert events == ["constraints", "topology", "close"]


def test_timescale_stage_verifies_current_mirror_after_upsert(
    mock_settings: AppSettings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Daily Timescale publication fails closed when current truth diverges."""

    from psp_pipeline.pipelines import stages

    db_path = tmp_path / "mirror.sqlite"
    with sqlite3.connect(db_path) as conn:
        ensure_sqlite_schema(conn)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observation = FactObservation(
        entity_key="SR:region:Southern Region",
        metric_name="srldc.FactSRLDCRegionalDaily.DayEnergyMetMU",
        metric_id="FactSRLDCRegionalDaily.DayEnergyMetMU",
        time_block=None,
        operational_value=100.0,
        settlement_value=None,
        variance_pct=None,
        report_type="srldc_daily_psp",
        source_region="SR",
        valid_from=now,
        valid_to=None,
        version_no=1,
        ingested_at=now,
        timeseries_uuid="00000000-0000-0000-0000-000000000001",
    )
    events: list[str] = []

    class FakeRepository:
        def __init__(self, *_: object) -> None:
            pass

        def upsert_curated_observations(self, facts, observation_lineage) -> int:
            events.append("upsert")
            return len(facts)

        def refresh_current_truth_views(self) -> bool:
            events.append("refresh")
            return True

    monkeypatch.setattr(stages, "PostgresRepository", FakeRepository)
    monkeypatch.setattr(
        stages,
        "_export_curated_observations_for_date",
        lambda *_args, **_kwargs: [observation],
    )
    monkeypatch.setattr(stages, "export_observation_lineage", lambda *_args, **_kwargs: [])

    def fetcher(_dsn: str, observations):
        events.append("mirror")
        observation = observations[0]
        return [
            CurrentMirrorRow(
                series_key=observation.series_key
                or build_series_key(
                    entity_key=observation.entity_key,
                    metric_name=observation.metric_name,
                    time_block=observation.time_block,
                    report_type=observation.report_type,
                    source_region=observation.source_region,
                    valid_from=observation.valid_from.isoformat(),
                    valid_to=None,
                ),
                timeseries_uuid=observation.timeseries_uuid,
                metric_id=observation.metric_id,
                operational_value=observation.operational_value,
                settlement_value=observation.settlement_value,
            )
        ]

    inserted = export_all_curated_to_timescale(
        mock_settings,
        db_path,
        current_row_fetcher=fetcher,
    )
    assert inserted == 1
    assert events == ["upsert", "refresh", "mirror"]


def test_coverage_stage_skips_missing_daily_database(tmp_path: Path) -> None:
    """Coverage evaluation is a no-op until the curated SQLite replay exists."""

    payload = evaluate_curated_coverage_contract(tmp_path / "missing.sqlite")
    assert payload["skipped"] is True
    assert payload["passed"] is True
