"""Tests for Postgres-primary wide fact collapse, upsert, and mirror."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL

from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.storage.postgres_repo import PostgresRepository
from psp_pipeline.storage.wide_facts import (
    WideFactMirrorMismatchError,
    WideFactRow,
    build_wide_grain_key,
    export_wide_facts,
    verify_exported_wide_fact_mirror,
)


def _observation(**overrides: object) -> FactObservation:
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    payload = {
        "entity_key": "SR:region:Southern Region",
        "metric_name": "srldc.FactSRLDCRegionalDaily.DayEnergyMetMU",
        "metric_id": "FactSRLDCRegionalDaily.DayEnergyMetMU",
        "time_block": None,
        "operational_value": 950.0,
        "settlement_value": None,
        "variance_pct": None,
        "report_type": "srldc_daily_psp",
        "source_region": "SR",
        "valid_from": now,
        "valid_to": None,
        "version_no": 1,
        "ingested_at": now,
        "timeseries_uuid": "00000000-0000-0000-0000-000000000001",
        "source_id": "srldc",
        "destination_table": "FactSRLDCRegionalDaily",
        "destination_key": "report=1;date=1;region=1",
        "destination_column": "DayEnergyMetMU",
        "content_hash": "artifact-hash",
        "report_document_id": 1,
        "canonical_entity_id": "11111111-1111-1111-1111-111111111111",
    }
    payload.update(overrides)
    return FactObservation(**payload)


def test_export_wide_facts_groups_metrics_on_destination_table_grain() -> None:
    """Long-form measures collapse into one JSONB grain per destination table."""

    energy = _observation()
    peak = _observation(
        metric_name="srldc.FactSRLDCRegionalDaily.EveningPeakDemandMetMW",
        metric_id="FactSRLDCRegionalDaily.EveningPeakDemandMetMW",
        destination_column="EveningPeakDemandMetMW",
        operational_value=45000.0,
        timeseries_uuid="00000000-0000-0000-0000-000000000002",
    )
    skipped = _observation(destination_table=None, operational_value=1.0)

    rows = export_wide_facts([energy, peak, skipped])

    assert len(rows) == 1
    row = rows[0]
    assert row.destination_table == "FactSRLDCRegionalDaily"
    assert row.metrics == {
        "DayEnergyMetMU": 950.0,
        "EveningPeakDemandMetMW": 45000.0,
    }
    assert row.canonical_entity_id == "11111111-1111-1111-1111-111111111111"
    expected_grain = build_wide_grain_key(
        source_id="srldc",
        destination_table="FactSRLDCRegionalDaily",
        entity_key="SR:region:Southern Region",
        valid_date=energy.valid_from.date(),
        destination_key="report=1;date=1;region=1",
    )
    assert row.grain_key == expected_grain
    assert row.wide_fact_key == str(
        uuid5(NAMESPACE_URL, f"{expected_grain}|artifact-hash")
    )


def test_postgres_wide_fact_upsert_is_idempotent_and_closes_prior_current() -> None:
    """A replay of the same key is a no-op; a new hash advances current truth."""

    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []
            self._insert_results = [
                ("key-1",),
                None,
                ("key-2",),
            ]

        def execute(self, query: str, params: object = None) -> None:
            self.calls.append((query, params))

        def fetchone(self) -> object:
            return self._insert_results.pop(0)

    first = _observation()
    row = export_wide_facts([first])[0]
    replay = row
    corrected = WideFactRow(
        grain_key=row.grain_key,
        wide_fact_key=str(uuid5(NAMESPACE_URL, f"{row.grain_key}|corrected-hash")),
        source_id=row.source_id,
        destination_table=row.destination_table,
        destination_key=row.destination_key,
        report_document_id=row.report_document_id,
        content_hash="corrected-hash",
        valid_date=row.valid_date,
        entity_key=row.entity_key,
        canonical_entity_id=row.canonical_entity_id,
        report_type=row.report_type,
        source_region=row.source_region,
        metrics={"DayEnergyMetMU": 951.0},
    )

    cursor = Cursor()
    inserted = PostgresRepository._upsert_wide_facts(cursor, [row, replay, corrected])
    queries = "\n".join(query for query, _ in cursor.calls)

    assert inserted == 2
    assert "INSERT INTO fact_wide_daily" in queries
    assert "ON CONFLICT (wide_fact_key) DO NOTHING" in queries
    assert "SET sys_to = CURRENT_TIMESTAMP" in queries
    assert "INSERT INTO fact_wide_daily_current" in queries
    assert "replace_complete_snapshots" not in queries
    assert "DELETE FROM fact_wide_daily" not in queries
    assert "%(metrics)s::jsonb" in queries
    assert cursor.calls[0][1]["metrics"] == '{"DayEnergyMetMU": 950.0}'


def test_wide_fact_mirror_compares_current_metrics_by_grain_key() -> None:
    """Current-truth verification is keyed by grain, not by historical UUID."""

    row = export_wide_facts([_observation()])[0]

    class Repository:
        def fetch_current_wide_facts(self) -> list[dict[str, object]]:
            return [
                {
                    "grain_key": row.grain_key,
                    "wide_fact_key": row.wide_fact_key,
                    "destination_table": row.destination_table,
                    "entity_key": row.entity_key,
                    "canonical_entity_id": row.canonical_entity_id,
                    "metrics": dict(row.metrics),
                }
            ]

    result = verify_exported_wide_fact_mirror([row], Repository())
    assert result["is_match"] is True
    assert result["exported_count"] == 1


def test_wide_fact_mirror_fails_closed_on_metric_divergence() -> None:
    """A successful insert is rejected when current metrics differ."""

    row = export_wide_facts([_observation()])[0]

    class Repository:
        def fetch_current_wide_facts(self) -> list[dict[str, object]]:
            return [
                {
                    "grain_key": row.grain_key,
                    "wide_fact_key": "other",
                    "destination_table": row.destination_table,
                    "entity_key": row.entity_key,
                    "canonical_entity_id": row.canonical_entity_id,
                    "metrics": {"DayEnergyMetMU": 1.0},
                }
            ]

    try:
        verify_exported_wide_fact_mirror([row], Repository())
    except WideFactMirrorMismatchError as exc:
        assert exc.result["is_match"] is False
        assert row.grain_key in exc.result["mismatched_grain_keys"]
    else:
        raise AssertionError("expected WideFactMirrorMismatchError")
