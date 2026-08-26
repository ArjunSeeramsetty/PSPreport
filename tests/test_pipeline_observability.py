"""Tests for persisted run outcomes and source freshness checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from psp_pipeline.pipelines import stages
from psp_pipeline.quality.sla_monitor import check_source_freshness


def test_record_pipeline_run_persists_partial_source_outcome(monkeypatch) -> None:
    """One failed public source is visible without failing the orchestration."""

    persisted = []

    class FakeRepository:
        def __init__(self, _: str) -> None:
            pass

        def upsert_pipeline_run(self, record) -> None:
            persisted.append(record)

    monkeypatch.setattr(stages, "PostgresRepository", FakeRepository)
    result = stages.record_pipeline_run(
        SimpleNamespace(postgres_dsn="postgresql://test"),
        run_id="run-1",
        started_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        collection={
            "aggregate": {
                "sources_requested": 5,
                "sources_completed": 4,
                "sources_failed": 1,
            }
        },
        observations_inserted=9,
        graph_observations=10,
    )

    assert result == {"run_id": "run-1", "status": "partial"}
    assert persisted[0].observations_deduplicated == 1


def test_source_freshness_identifies_missing_and_stale_sources() -> None:
    """Freshness reports both sources absent from lineage and stale sources."""

    now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, query, params) -> None:
            assert "MAX(fetched_at)" in query
            assert params == ["erldc", "nrldc", "srldc"]

        def fetchall(self):
            return [
                ("srldc", now - timedelta(hours=2)),
                ("nrldc", now - timedelta(hours=40)),
            ]

    class Connection:
        def cursor(self):
            return Cursor()

    assert check_source_freshness(
        Connection(),
        ["srldc", "nrldc", "erldc"],
        now=now,
    ) == ["erldc", "nrldc"]
