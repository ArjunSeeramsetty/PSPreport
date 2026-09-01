"""Tests for greenfield Timescale recreate and SQLite backfill."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.quality.timescale_mirror_reconciliation import CurrentMirrorRow
from psp_pipeline.storage.observation_identity import build_series_key
from psp_pipeline.storage.timescale_bootstrap import (
    TimescaleSchemaStaleError,
    apply_greenfield_schema,
    bootstrap_timescale_from_sqlite,
    default_greenfield_schema_path,
    schema_status_from_inventory,
    split_sql_statements,
)
from psp_pipeline.storage.timescale_loader import load_curated_observations_to_timescale


READY_TABLES = (
    "fact_observation",
    "fact_observation_dedup",
    "fact_observation_current",
    "fact_observation_lineage",
    "pipeline_run",
    "ingest_lineage",
    "reconciliation_result",
    "canonical_entity",
    "canonical_entity_alias",
    "canonical_entity_adjudication",
    "fact_wide_daily",
    "fact_wide_daily_current",
)
READY_FACT_COLUMNS = (
    "sys_to",
    "series_key",
    "content_hash",
    "metric_id",
    "report_document_id",
    "timeseries_uuid",
    "canonical_entity_id",
)


def _observation() -> FactObservation:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    return FactObservation(
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


def _matching_fetcher(_dsn: str, observations):
    rows = []
    for observation in observations:
        series_key = observation.series_key or build_series_key(
            entity_key=observation.entity_key,
            metric_name=observation.metric_name,
            time_block=observation.time_block,
            report_type=observation.report_type,
            source_region=observation.source_region,
            valid_from=observation.valid_from.isoformat(),
            valid_to=observation.valid_to.isoformat() if observation.valid_to else None,
        )
        rows.append(
            CurrentMirrorRow(
                series_key=series_key,
                timeseries_uuid=observation.timeseries_uuid,
                metric_id=observation.metric_id,
                operational_value=observation.operational_value,
                settlement_value=observation.settlement_value,
            )
        )
    return rows


def test_greenfield_schema_file_is_the_current_dual_write_contract() -> None:
    """Fresh Timescale init must include bitemporal and metric-identity columns."""

    path = default_greenfield_schema_path()
    script = path.read_text(encoding="utf-8")
    assert path.name == "timescale_schema.sql"
    assert "sys_to" in script
    assert "series_key" in script
    assert "metric_id" in script
    assert "fact_observation_current" in script
    assert "fact_observation_lineage" in script
    assert "pipeline_run" in script
    assert "canonical_entity" in script
    assert "canonical_entity_alias" in script
    assert "canonical_entity_adjudication" in script
    assert "fact_wide_daily" in script
    assert "fact_wide_daily_current" in script
    assert "canonical_entity_id" in script
    assert "CREATE OR REPLACE VIEW gold_wide_fact_current AS" in script
    assert "CREATE OR REPLACE VIEW gold_canonical_daily_current AS" in script
    assert "decided_at" in script
    assert "decided_by" in script
    assert "create_hypertable('fact_observation'" in script
    assert "SET sys_to = ordered_versions.next_system_from" not in script


def test_split_sql_statements_drops_comment_only_chunks() -> None:
    """Bootstrap executes DDL, not SQL comments."""

    statements = split_sql_statements(
        "-- heading\nCREATE TABLE a (id INT);\n-- note\nCREATE INDEX b ON a (id);"
    )
    assert statements == (
        "CREATE TABLE a (id INT)",
        "CREATE INDEX b ON a (id)",
    )


def test_schema_status_marks_missing_table_as_not_stale() -> None:
    """An empty database can receive CREATE TABLE IF NOT EXISTS without a drop."""

    status = schema_status_from_inventory(
        present_tables=(),
        fact_columns=None,
        hypertable_present=False,
    )
    assert status.ready is False
    assert status.stale is False
    assert status.fact_table_present is False


def test_schema_status_marks_pre_bitemporal_table_as_stale() -> None:
    """Existing fact_observation without sys_to cannot be patched by greenfield SQL."""

    status = schema_status_from_inventory(
        present_tables=("fact_observation", "pipeline_run"),
        fact_columns=("entity_key", "metric_name", "ingested_at"),
        hypertable_present=True,
    )
    assert status.stale is True
    assert status.ready is False
    assert "sys_to" in status.missing_columns
    assert "metric_id" in status.missing_columns
    assert "canonical_entity_id" in status.missing_columns


def test_schema_status_requires_identity_and_wide_fact_tables() -> None:
    """Greenfield readiness includes canonical identity and wide-fact tables."""

    status = schema_status_from_inventory(
        present_tables=(
            "fact_observation",
            "fact_observation_dedup",
            "fact_observation_current",
            "fact_observation_lineage",
            "pipeline_run",
            "ingest_lineage",
            "reconciliation_result",
        ),
        fact_columns=READY_FACT_COLUMNS,
        hypertable_present=True,
    )
    assert status.ready is False
    assert "canonical_entity" in status.missing_tables
    assert "fact_wide_daily" in status.missing_tables


def test_apply_greenfield_schema_rejects_incremental_migration_files(
    tmp_path: Path,
) -> None:
    """Option 1 never executes sql/migrations/*.sql."""

    migration = tmp_path / "001_bitemporal_sys_to.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="timescale_schema.sql"):
        apply_greenfield_schema("postgresql://test", schema_path=migration)


def test_bootstrap_refuses_stale_schema_without_recreate(tmp_path, monkeypatch) -> None:
    """Operators must opt into DROP SCHEMA rather than running 001-005."""

    sqlite_path = tmp_path / "curated.sqlite"
    sqlite3.connect(sqlite_path).close()
    monkeypatch.setattr(
        "psp_pipeline.storage.timescale_bootstrap.inspect_greenfield_schema",
        lambda *_args, **_kwargs: schema_status_from_inventory(
            present_tables=("fact_observation",),
            fact_columns=("entity_key", "metric_name"),
            hypertable_present=True,
        ),
    )

    with pytest.raises(TimescaleSchemaStaleError, match="sql/migrations"):
        bootstrap_timescale_from_sqlite(sqlite_path, "postgresql://test")


def test_bootstrap_recreates_schema_then_backfills(tmp_path, monkeypatch) -> None:
    """Recreate applies the greenfield file, then upserts current SQLite facts."""

    sqlite_path = tmp_path / "curated.sqlite"
    sqlite3.connect(sqlite_path).close()
    observation = _observation()
    events: list[str] = []
    ready = schema_status_from_inventory(
        present_tables=READY_TABLES,
        fact_columns=READY_FACT_COLUMNS,
        hypertable_present=True,
    )
    inspections = [ready]

    def inspect(*_args, **_kwargs):
        events.append("inspect")
        return inspections[0]

    def apply(*_args, **kwargs):
        assert kwargs["recreate"] is True
        events.append("apply")
        return {"recreated": True, "statements_applied": 3}

    class FakeRepository:
        def __init__(self, dsn: str) -> None:
            assert dsn == "postgresql://test"

        def upsert_curated_observations(self, facts, observation_lineage) -> int:
            events.append("load")
            assert facts == [observation]
            return 1

        def refresh_current_truth_views(self) -> bool:
            events.append("refresh")
            return True

    monkeypatch.setattr(
        "psp_pipeline.storage.timescale_bootstrap.inspect_greenfield_schema",
        inspect,
    )
    monkeypatch.setattr(
        "psp_pipeline.storage.timescale_bootstrap.apply_greenfield_schema",
        apply,
    )

    result = bootstrap_timescale_from_sqlite(
        sqlite_path,
        "postgresql://test",
        recreate_schema=True,
        observation_exporter=lambda *args, **kwargs: [observation],
        observation_lineage_exporter=lambda *args, **kwargs: [],
        repository_factory=FakeRepository,
        current_row_fetcher=_matching_fetcher,
    )

    assert events == ["inspect", "apply", "inspect", "load", "refresh"]
    assert result["schema"]["ready"] is True
    assert result["schema_apply"]["recreated"] is True
    assert result["views_refreshed"] is True
    assert result["load"]["observations_inserted"] == 1
    assert result["load"]["mirror"]["is_match"] is True


def test_bootstrap_applies_schema_without_drop_when_database_is_empty(
    tmp_path, monkeypatch
) -> None:
    """A brand-new database can receive the greenfield file in place."""

    sqlite_path = tmp_path / "curated.sqlite"
    sqlite3.connect(sqlite_path).close()
    empty = schema_status_from_inventory(
        present_tables=(),
        fact_columns=None,
        hypertable_present=False,
    )
    ready = schema_status_from_inventory(
        present_tables=READY_TABLES,
        fact_columns=READY_FACT_COLUMNS,
        hypertable_present=True,
    )
    states = iter([empty, ready])
    applied: list[bool] = []

    monkeypatch.setattr(
        "psp_pipeline.storage.timescale_bootstrap.inspect_greenfield_schema",
        lambda *_args, **_kwargs: next(states),
    )

    def apply(*_args, **kwargs):
        applied.append(kwargs["recreate"])
        return {"recreated": False, "statements_applied": 3}

    class FakeRepository:
        def __init__(self, dsn: str) -> None:
            pass

        def upsert_curated_observations(self, facts, observation_lineage) -> int:
            return 0

        def refresh_current_truth_views(self) -> bool:
            return True

    monkeypatch.setattr(
        "psp_pipeline.storage.timescale_bootstrap.apply_greenfield_schema",
        apply,
    )
    result = bootstrap_timescale_from_sqlite(
        sqlite_path,
        "postgresql://test",
        observation_exporter=lambda *args, **kwargs: [],
        observation_lineage_exporter=lambda *args, **kwargs: [],
        repository_factory=FakeRepository,
        verify_current_mirror=False,
    )
    assert applied == [False]
    assert result["schema"]["ready"] is True
    assert result["load"]["observations_exported"] == 0


def test_bootstrap_requires_existing_sqlite_before_dropping_schema(
    tmp_path: Path,
) -> None:
    """A missing replay must not recreate Timescale."""

    with pytest.raises(FileNotFoundError):
        bootstrap_timescale_from_sqlite(tmp_path / "missing.sqlite", "postgresql://test")


def test_loader_backfill_keeps_snapshot_replace_off(tmp_path, monkeypatch) -> None:
    """Option B backfill uses idempotent upserts, not snapshot retirement."""

    sqlite_path = tmp_path / "curated.sqlite"
    sqlite3.connect(sqlite_path).close()
    seen: dict[str, object] = {}

    class FakeRepository:
        def __init__(self, dsn: str) -> None:
            pass

        def upsert_curated_observations(self, facts, observation_lineage) -> int:
            seen["facts"] = facts
            return len(facts)

        def replace_curated_observation_snapshots(self, facts, observation_lineage):
            raise AssertionError("snapshot replace must stay off for backfill")

    result = load_curated_observations_to_timescale(
        sqlite_path,
        "postgresql://test",
        observation_exporter=lambda *args, **kwargs: [_observation()],
        observation_lineage_exporter=lambda *args, **kwargs: [],
        repository_factory=FakeRepository,
        replace_complete_snapshots=False,
        current_row_fetcher=_matching_fetcher,
    )
    assert "observations_retired" not in result
    assert result["observations_inserted"] == 1


@pytest.mark.skipif(
    os.getenv("PSP_TIMESCALE_BOOTSTRAP_TEST") != "1",
    reason="Live Timescale recreate is opt-in via PSP_TIMESCALE_BOOTSTRAP_TEST=1",
)
def test_live_recreate_greenfield_schema_and_backfill_curated_sqlite(
    tmp_path: Path,
) -> None:
    """Drop public, apply timescale_schema.sql, and mirror a real SQLite export."""

    import psycopg

    from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema

    dsn = os.getenv(
        "POSTGRES_DSN",
        "postgresql://postgres:postgres@127.0.0.1:5432/power_kg",
    )
    sqlite_path = tmp_path / "all_rldc_daily.sqlite"
    conn = sqlite3.connect(sqlite_path)
    ensure_curated_sqlite_schema(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY,
            rldc TEXT NOT NULL,
            report_date TEXT
        );
        INSERT INTO psp_report_document(id, rldc, report_date)
        VALUES (1, 'srldc', '2025-01-01'), (2, 'nerldc', '2025-01-01');
        INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2025-01-01');
        INSERT INTO FactSRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, DayEnergyMetMU
        ) VALUES (
            1, 1,
            (SELECT RegionID FROM DimRegions WHERE RegionName = 'Southern Region'),
            45000.0, 950.0
        );
        INSERT INTO FactNERLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, DayEnergyMetMU
        ) VALUES (
            2, 1,
            (SELECT RegionID FROM DimRegions WHERE RegionName = 'North Eastern Region'),
            2561.0, 48.5
        );
        """
    )
    conn.commit()
    conn.close()

    result = bootstrap_timescale_from_sqlite(
        sqlite_path,
        dsn,
        recreate_schema=True,
    )
    assert result["schema"]["ready"] is True
    assert result["schema_apply"]["recreated"] is True
    assert result["load"]["observations_exported"] >= 4
    assert result["load"]["observations_inserted"] == result["load"]["observations_exported"]
    assert result["load"]["mirror"]["is_match"] is True

    replay = bootstrap_timescale_from_sqlite(sqlite_path, dsn, recreate_schema=False)
    assert replay["schema_apply"] is None
    assert replay["load"]["observations_inserted"] == 0
    assert replay["load"]["observations_deduplicated"] == replay["load"]["observations_exported"]
    assert replay["load"]["mirror"]["is_match"] is True

    with psycopg.connect(dsn) as pg:
        current_count = pg.execute(
            "SELECT COUNT(*) FROM fact_observation_current"
        ).fetchone()[0]
        metric_ids = pg.execute(
            """
            SELECT COUNT(*) FROM fact_observation
            WHERE metric_id IS NOT NULL AND sys_to = 'infinity'
            """
        ).fetchone()[0]
        entity_count = pg.execute("SELECT COUNT(*) FROM canonical_entity").fetchone()[0]
        wide_current = pg.execute(
            "SELECT COUNT(*) FROM fact_wide_daily_current"
        ).fetchone()[0]
        identity_column = pg.execute(
            """
            SELECT COUNT(*) FROM fact_observation
            WHERE canonical_entity_id IS NOT NULL AND sys_to = 'infinity'
            """
        ).fetchone()[0]
    assert current_count == result["load"]["observations_exported"]
    assert metric_ids == result["load"]["observations_exported"]
    assert entity_count >= 6
    assert wide_current >= 1
    assert identity_column >= 1
    assert result["load"]["identity"]["catalog_entities"] == entity_count
    assert result["load"]["wide"]["wide_mirror"]["is_match"] is True
    assert replay["load"]["wide"]["wide_facts_inserted"] == 0

    from psp_pipeline.identity.adjudication import (
        apply_adjudication,
        list_identity_adjudications,
        queue_source_label,
        republish_identity_after_adjudication,
    )
    from psp_pipeline.storage.postgres_repo import PostgresRepository

    repository = PostgresRepository(dsn)
    gold_rows = repository.fetch_gold_canonical_daily_current(region_code="SR")
    southern = next(
        row for row in gold_rows if row["entity_key"] == "SR:region:Southern Region"
    )
    assert southern["energy_met_mu"] == 950.0
    assert southern["evening_peak_demand_met_mw"] == 45000.0
    assert southern["canonical_entity_id"]
    assert southern["entity_code"] == "region:SR"

    with sqlite3.connect(sqlite_path) as conn:
        queue_source_label(
            conn,
            source_id="srldc",
            entity_type="state",
            raw_name="Karnatka",
        )
        issue_id = next(
            int(issue["issue_id"])
            for issue in list_identity_adjudications(conn)
            if issue["raw_name"] == "Karnatka" and issue["status"] == "pending"
        )
        applied = apply_adjudication(conn, issue_id=issue_id, decision="approved")
        published = republish_identity_after_adjudication(conn, repository, applied)
    assert published["apply"]["decision"] == "approved"
    assert published["backfill"]["skipped"] is False

    with psycopg.connect(dsn) as pg:
        alias = pg.execute(
            """
            SELECT match_method, approval_status, entity_id
            FROM canonical_entity_alias
            WHERE raw_name = 'Karnatka' AND match_method = 'human_adjudication'
            """
        ).fetchone()
        gold_view = pg.execute(
            """
            SELECT to_regclass('public.gold_canonical_daily_current'),
                   to_regclass('public.gold_wide_fact_current')
            """
        ).fetchone()
    assert alias is not None
    assert alias[1] == "approved"
    assert str(alias[2]) == applied.entity_id
    assert gold_view == (
        "gold_canonical_daily_current",
        "gold_wide_fact_current",
    )
