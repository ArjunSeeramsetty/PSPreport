"""Tests for portable observation loading and bitemporal SQL contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.storage.postgres_repo import PostgresRepository
from psp_pipeline.storage.timescale_loader import load_curated_observations_to_timescale


def _observation() -> FactObservation:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    return FactObservation(
        entity_key="SR:region:Southern Region",
        metric_name="srldc.FactSRLDCRegionalDaily.DayEnergyMetMU",
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


def test_timescale_loader_reports_export_insert_and_dedup_counts(tmp_path: Path) -> None:
    """The loader delegates UUID/version behavior to the repository."""

    sqlite_path = tmp_path / "curated.sqlite"
    sqlite3.connect(sqlite_path).close()

    class FakeRepository:
        def __init__(self, dsn: str) -> None:
            assert dsn == "postgresql://test"

        def upsert_fact_observations(self, records: list[FactObservation]) -> int:
            assert records == [_observation(), _observation()]
            return 1

    def exporter(*args: object, **kwargs: object) -> list[FactObservation]:
        assert kwargs["rldcs"] == ["srldc"]
        return [_observation(), _observation()]

    result = load_curated_observations_to_timescale(
        sqlite_path,
        "postgresql://test",
        rldcs=["srldc"],
        observation_exporter=exporter,
        repository_factory=FakeRepository,
    )

    assert result == {
        "observations_exported": 2,
        "observations_inserted": 1,
        "observations_deduplicated": 1,
    }


def test_timescale_loader_rejects_missing_sqlite_database(tmp_path: Path) -> None:
    """A missing local curated database is an explicit configuration error."""

    with pytest.raises(FileNotFoundError):
        load_curated_observations_to_timescale(tmp_path / "missing.sqlite", "postgresql://test")


def test_postgres_repository_uses_uuid_ledger_and_versioned_grain_lock() -> None:
    """The write contract deduplicates UUID replays before assigning versions."""

    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []
            self._responses = [("00000000-0000-0000-0000-000000000001",), (2,)]

        def execute(self, query: str, params: object = None) -> None:
            self.calls.append((query, params))

        def fetchone(self) -> object:
            return self._responses.pop(0)

    cursor = Cursor()
    inserted = PostgresRepository._upsert_facts(cursor, [_observation()])

    queries = "\n".join(query for query, _ in cursor.calls)
    assert inserted == 1
    assert "pg_advisory_xact_lock" in queries
    assert "INSERT INTO fact_observation_dedup" in queries
    assert "ON CONFLICT (timeseries_uuid) DO NOTHING" in queries
    assert "COALESCE(MAX(version_no), 0) + 1" in queries
    assert cursor.calls[-1][1]["version_no"] == 2
