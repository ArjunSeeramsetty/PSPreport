"""Tests for 5-RLDC stage orchestration functions."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.core.settings import AppSettings, load_settings
from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.pipelines.stages import (
    audit_national_curated_dimensions,
    collect_all_rldc_daily_psp,
    export_all_curated_to_timescale,
    reconcile_national_daily_balance,
    sync_all_curated_to_graph,
)


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
