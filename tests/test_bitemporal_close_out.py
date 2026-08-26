"""Tests for bitemporal revision identity and current-truth close-out."""

from __future__ import annotations

from datetime import datetime, timezone

from psp_pipeline.models.contracts import FactObservation, ObservationLineage
from psp_pipeline.storage.observation_identity import (
    build_revision_uuid,
    build_series_key,
)
from psp_pipeline.storage.postgres_repo import PostgresRepository


def _observation(content_hash: str) -> FactObservation:
    """Build one revision of a stable daily regional observation."""

    valid_from = datetime(2026, 5, 1, tzinfo=timezone.utc)
    series_key = build_series_key(
        entity_key="SR:region:Southern Region",
        metric_name="srldc.FactSRLDCRegionalDaily.DayEnergyMetMU",
        time_block=None,
        report_type="srldc_daily_psp",
        source_region="SR",
        valid_from=valid_from.isoformat(),
        valid_to=None,
    )
    return FactObservation(
        entity_key="SR:region:Southern Region",
        metric_name="srldc.FactSRLDCRegionalDaily.DayEnergyMetMU",
        time_block=None,
        operational_value=100.0,
        settlement_value=None,
        variance_pct=None,
        report_type="srldc_daily_psp",
        source_region="SR",
        valid_from=valid_from,
        valid_to=None,
        version_no=1,
        ingested_at=valid_from,
        timeseries_uuid=build_revision_uuid(series_key, content_hash),
        series_key=series_key,
        content_hash=content_hash,
        report_document_id=7,
    )


def test_source_hash_creates_a_new_revision_for_one_stable_series() -> None:
    """A corrected artifact changes revision identity but not logical series identity."""

    original = _observation("original-hash")
    corrected = _observation("corrected-hash")

    assert original.series_key == corrected.series_key
    assert original.timeseries_uuid != corrected.timeseries_uuid


def test_repository_closes_open_revision_before_writing_new_current_truth() -> None:
    """One transaction closes the prior version and advances the current ledger."""

    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []
            self.responses = [("new-uuid",), (2,)]

        def execute(self, query: str, params: object = None) -> None:
            self.calls.append((query, params))

        def fetchone(self) -> object:
            return self.responses.pop(0)

    cursor = Cursor()
    inserted = PostgresRepository._upsert_facts(cursor, [_observation("corrected-hash")])
    queries = [query for query, _ in cursor.calls]

    close_index = next(index for index, query in enumerate(queries) if "SET sys_to" in query)
    insert_index = next(index for index, query in enumerate(queries) if "INSERT INTO fact_observation (" in query)

    assert inserted == 1
    assert close_index < insert_index
    assert "fact_observation_current" in queries[-1]
    assert "CURRENT_TIMESTAMP" in queries[close_index]


def test_duplicate_revision_does_not_close_the_existing_current_truth() -> None:
    """UUID replay deduplication exits before any temporal close-out mutation."""

    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def execute(self, query: str, params: object = None) -> None:
            self.calls.append((query, params))

        def fetchone(self) -> None:
            return None

    cursor = Cursor()
    assert PostgresRepository._upsert_facts(cursor, [_observation("original-hash")]) == 0
    assert not any("SET sys_to" in query for query, _ in cursor.calls)


def test_repository_writes_cell_lineage_to_the_dedicated_bridge() -> None:
    """Cell provenance is idempotent and separate from the telemetry table."""

    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def execute(self, query: str, params: object = None) -> None:
            self.calls.append((query, params))

    observation = _observation("original-hash")
    record = ObservationLineage(
        lineage_key="00000000-0000-0000-0000-000000000003",
        timeseries_uuid=observation.timeseries_uuid,
        source_id="srldc",
        report_document_id=7,
        content_hash="original-hash",
        destination_table="FactSRLDCRegionalDaily",
        destination_key="report=7;date=1;region=1",
        destination_column="DayEnergyMetMU",
        raw_kind="cell",
        raw_item_id=33,
        page_no=1,
        table_no=1,
        row_no=3,
        col_no=4,
        confidence=1.0,
        extraction_method="pdfplumber",
    )
    cursor = Cursor()

    PostgresRepository._insert_observation_lineage(cursor, [record])

    query, payload = cursor.calls[0]
    assert "INSERT INTO fact_observation_lineage" in query
    assert "ON CONFLICT (lineage_key) DO NOTHING" in query
    assert payload["raw_item_id"] == 33


def test_current_truth_refresh_is_optional_until_migration_is_applied() -> None:
    """Older deployments skip the view refresh rather than failing ingestion."""

    class Cursor:
        def __init__(self, view_exists: bool) -> None:
            self.view_exists = view_exists
            self.calls: list[str] = []

        def execute(self, query: str, params: object = None) -> None:
            self.calls.append(query)

        def fetchone(self):
            return ("daily_regional_current_summary",) if self.view_exists else (None,)

    absent = Cursor(view_exists=False)
    assert PostgresRepository._refresh_current_truth_views(absent) is False
    assert len(absent.calls) == 1

    present = Cursor(view_exists=True)
    assert PostgresRepository._refresh_current_truth_views(present) is True
    assert "REFRESH MATERIALIZED VIEW" in present.calls[-1]
