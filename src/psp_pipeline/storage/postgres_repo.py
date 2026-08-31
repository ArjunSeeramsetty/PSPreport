from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from typing import Iterable, Optional

try:
    import psycopg
except ImportError:
    psycopg = None  # type: ignore[assignment]

from psp_pipeline.models.contracts import (
    FactObservation,
    LineageRecord,
    ObservationLineage,
    PipelineRun,
    ReconciliationResult,
)
from psp_pipeline.storage.observation_identity import build_series_key


@dataclass(frozen=True)
class CuratedSnapshotWriteResult:
    """Outcome of an authoritative curated-report snapshot replacement."""

    inserted: int
    retired_timeseries_uuids: tuple[str, ...]
    retired_at: datetime | None


class PostgresRepository:
    def __init__(self, dsn: str):
        if psycopg is None:
            raise RuntimeError(
                "The 'psycopg' package is required to use PostgresRepository. "
                "Install it with `pip install psycopg[binary]`."
            )
        self.dsn = dsn

    def insert_lineage(self, records: Iterable[LineageRecord]) -> None:
        """
        Non-atomic helper for one-off tooling.
        Production pipeline should prefer run_in_transaction().
        """
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                self._insert_lineage(cur, records)
            conn.commit()

    def upsert_fact_observations(self, records: Iterable[FactObservation]) -> int:
        """
        Non-atomic helper for one-off tooling.
        Production pipeline should prefer run_in_transaction().
        """
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                inserted = self._upsert_facts(cur, records)
            conn.commit()
        return inserted

    def run_in_transaction(
        self,
        lineage: Iterable[LineageRecord],
        facts: Iterable[FactObservation],
        reconciliation: Iterable[ReconciliationResult] | None = None,
        observation_lineage: Iterable[ObservationLineage] | None = None,
    ) -> int:
        """Insert ingest, fact, reconciliation, and cell lineage atomically."""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                self._insert_lineage(cur, lineage)
                inserted = self._upsert_facts(cur, facts)
                if observation_lineage is not None:
                    self._insert_observation_lineage(cur, observation_lineage)
                if reconciliation is not None:
                    self._upsert_reconciliation(cur, reconciliation)
            conn.commit()
        return inserted

    def upsert_curated_observations(
        self,
        facts: Iterable[FactObservation],
        observation_lineage: Iterable[ObservationLineage],
    ) -> int:
        """Persist exported curated facts and exact cell lineage atomically."""

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                inserted = self._upsert_facts(cur, facts)
                self._insert_observation_lineage(cur, observation_lineage)
            conn.commit()
        return inserted

    def replace_curated_observation_snapshots(
        self,
        facts: Iterable[FactObservation],
        observation_lineage: Iterable[ObservationLineage],
    ) -> CuratedSnapshotWriteResult:
        """Persist complete report snapshots and close current facts now absent.

        This API is intentionally separate from ordinary upserts. Callers may
        use it only when ``facts`` represents every exportable observation for
        each report artifact in the batch; partial loads must use
        :meth:`upsert_curated_observations` instead.
        """

        fact_rows = list(facts)
        lineage_rows = list(observation_lineage)
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                snapshot_groups = self._snapshot_groups(fact_rows)
                self._lock_snapshot_groups(cur, snapshot_groups)
                retired_at = self._transaction_timestamp(cur)
                inserted = self._upsert_facts(cur, fact_rows)
                retired = self._retire_absent_snapshot_facts(cur, snapshot_groups)
                self._insert_observation_lineage(cur, lineage_rows)
            conn.commit()
        return CuratedSnapshotWriteResult(
            inserted=inserted,
            retired_timeseries_uuids=tuple(retired),
            retired_at=retired_at if retired else None,
        )

    def upsert_pipeline_run(self, record: PipelineRun) -> None:
        """Persist an idempotent orchestration outcome for freshness and SLA checks."""

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_run (
                        run_id, dag_id, started_at, completed_at, status,
                        sources_requested, sources_completed, sources_failed,
                        observations_exported, observations_inserted,
                        observations_deduplicated
                    ) VALUES (
                        %(run_id)s, %(dag_id)s, %(started_at)s, %(completed_at)s,
                        %(status)s, %(sources_requested)s, %(sources_completed)s,
                        %(sources_failed)s, %(observations_exported)s,
                        %(observations_inserted)s, %(observations_deduplicated)s
                    )
                    ON CONFLICT (run_id) DO UPDATE SET
                        completed_at = EXCLUDED.completed_at,
                        status = EXCLUDED.status,
                        sources_requested = EXCLUDED.sources_requested,
                        sources_completed = EXCLUDED.sources_completed,
                        sources_failed = EXCLUDED.sources_failed,
                        observations_exported = EXCLUDED.observations_exported,
                        observations_inserted = EXCLUDED.observations_inserted,
                        observations_deduplicated = EXCLUDED.observations_deduplicated
                    """,
                    asdict(record),
                )
            conn.commit()

    def refresh_current_truth_views(self) -> bool:
        """Refresh valid-date current-truth views when their migration is present."""

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                refreshed = self._refresh_current_truth_views(cur)
            conn.commit()
        return refreshed

    def upsert_canonical_entities(
        self,
        entities: Iterable[dict[str, object]],
        aliases: Iterable[dict[str, object]],
        adjudications: Iterable[dict[str, object]],
    ) -> dict[str, int]:
        """Publish the canonical identity index as the Postgres system of record."""

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                counts = self._upsert_canonical_identity(cur, entities, aliases, adjudications)
            conn.commit()
        return counts

    def upsert_wide_facts(self, rows: Iterable[object]) -> int:
        """Persist destination-table grains as current Postgres-primary facts."""

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                inserted = self._upsert_wide_facts(cur, rows)
            conn.commit()
        return inserted

    def fetch_current_wide_facts(self) -> list[dict[str, object]]:
        """Return current wide-fact grains for mirror verification."""

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        fact.grain_key,
                        fact.wide_fact_key,
                        fact.destination_table,
                        fact.entity_key,
                        fact.canonical_entity_id,
                        fact.metrics
                    FROM fact_wide_daily AS fact
                    JOIN fact_wide_daily_current AS current_truth
                      ON current_truth.wide_fact_key = fact.wide_fact_key
                    """
                )
                rows = cur.fetchall()
        return [
            {
                "grain_key": str(grain_key),
                "wide_fact_key": str(wide_fact_key),
                "destination_table": str(destination_table),
                "entity_key": str(entity_key),
                "canonical_entity_id": str(canonical_id) if canonical_id else None,
                "metrics": dict(metrics or {}),
            }
            for grain_key, wide_fact_key, destination_table, entity_key, canonical_id, metrics in rows
        ]

    def fetch_existing_hash(self, source_id: str) -> Optional[str]:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT content_hash
                    FROM ingest_lineage
                    WHERE source_id = %s
                    ORDER BY fetched_at DESC
                    LIMIT 1
                    """,
                    (source_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None

    def content_hash_exists(self, source_id: str, content_hash: str) -> bool:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM ingest_lineage
                    WHERE source_id = %s AND content_hash = %s
                    LIMIT 1
                    """,
                    (source_id, content_hash),
                )
                return cur.fetchone() is not None

    @staticmethod
    def _insert_lineage(cur, records: Iterable[LineageRecord]) -> None:
        for item in records:
            payload = asdict(item)
            cur.execute(
                """
                INSERT INTO ingest_lineage (
                    run_id, source_id, source_url, content_hash, fetched_at,
                    parser_version, extraction_confidence, report_type, source_region,
                    valid_from, valid_to, version_no, raw_object_key
                ) VALUES (
                    %(run_id)s, %(source_id)s, %(source_url)s, %(content_hash)s, %(fetched_at)s,
                    %(parser_version)s, %(extraction_confidence)s, %(report_type)s, %(source_region)s,
                    %(valid_from)s, %(valid_to)s, %(version_no)s, %(raw_object_key)s
                )
                ON CONFLICT DO NOTHING
                """,
                payload,
            )

    @staticmethod
    def _upsert_facts(cur, records: Iterable[FactObservation]) -> int:
        """Insert idempotent observations and assign revisions per valid-time grain."""

        inserted = 0
        for item in records:
            payload = asdict(item)
            series_key = item.series_key or build_series_key(
                entity_key=item.entity_key,
                metric_name=item.metric_name,
                time_block=item.time_block,
                report_type=item.report_type,
                source_region=item.source_region,
                valid_from=item.valid_from.isoformat(),
                valid_to=item.valid_to.isoformat() if item.valid_to else None,
            )
            payload["series_key"] = series_key
            payload["content_hash"] = item.content_hash or f"legacy:{item.timeseries_uuid}"
            # Lock one logical observation grain so concurrent loaders cannot
            # assign the same correction version.
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (series_key,),
            )
            cur.execute(
                """
                INSERT INTO fact_observation_dedup (
                    timeseries_uuid, series_key, content_hash, entity_key, metric_name, metric_id, time_block,
                    report_type, source_region, valid_from, valid_to,
                    first_ingested_at, canonical_entity_id
                ) VALUES (
                    %(timeseries_uuid)s, %(series_key)s, %(content_hash)s,
                    %(entity_key)s, %(metric_name)s, %(metric_id)s,
                    %(time_block)s, %(report_type)s, %(source_region)s,
                    %(valid_from)s, %(valid_to)s, CURRENT_TIMESTAMP,
                    %(canonical_entity_id)s
                )
                ON CONFLICT (timeseries_uuid) DO NOTHING
                RETURNING timeseries_uuid
                """,
                payload,
            )
            if cur.fetchone() is None:
                continue
            cur.execute(
                """
                UPDATE fact_observation
                SET sys_to = CURRENT_TIMESTAMP
                WHERE series_key = %(series_key)s
                  AND sys_to = 'infinity'
                """,
                payload,
            )
            cur.execute(
                """
                SELECT COALESCE(MAX(version_no), 0) + 1
                FROM fact_observation
                WHERE entity_key = %(entity_key)s
                  AND metric_name = %(metric_name)s
                  AND time_block IS NOT DISTINCT FROM %(time_block)s
                  AND report_type = %(report_type)s
                  AND source_region = %(source_region)s
                  AND valid_from = %(valid_from)s
                  AND valid_to IS NOT DISTINCT FROM %(valid_to)s
                """,
                payload,
            )
            version_row = cur.fetchone()
            payload["version_no"] = int(version_row[0]) if version_row else 1
            cur.execute(
                """
                INSERT INTO fact_observation (
                    entity_key, metric_name, metric_id, time_block, operational_value, settlement_value,
                    variance_pct, report_type, source_region, valid_from, valid_to,
                    version_no, ingested_at, sys_to, series_key, content_hash,
                    report_document_id, timeseries_uuid, canonical_entity_id
                ) VALUES (
                    %(entity_key)s, %(metric_name)s, %(metric_id)s, %(time_block)s, %(operational_value)s, %(settlement_value)s,
                    %(variance_pct)s, %(report_type)s, %(source_region)s, %(valid_from)s, %(valid_to)s,
                    %(version_no)s, CURRENT_TIMESTAMP, 'infinity', %(series_key)s, %(content_hash)s,
                    %(report_document_id)s, %(timeseries_uuid)s, %(canonical_entity_id)s
                )
                """,
                payload,
            )
            cur.execute(
                """
                INSERT INTO fact_observation_current (
                    series_key, timeseries_uuid, system_from
                ) VALUES (
                    %(series_key)s, %(timeseries_uuid)s, CURRENT_TIMESTAMP
                )
                ON CONFLICT (series_key) DO UPDATE SET
                    timeseries_uuid = EXCLUDED.timeseries_uuid,
                    system_from = EXCLUDED.system_from
                """,
                payload,
            )
            inserted += 1
        return inserted

    @staticmethod
    def _snapshot_groups(
        records: Iterable[FactObservation],
    ) -> dict[tuple[object, ...], set[str]]:
        """Group complete snapshots by immutable artifact and valid-time scope."""

        groups: dict[tuple[object, ...], set[str]] = {}
        for item in records:
            series_key = item.series_key or build_series_key(
                entity_key=item.entity_key,
                metric_name=item.metric_name,
                time_block=item.time_block,
                report_type=item.report_type,
                source_region=item.source_region,
                valid_from=item.valid_from.isoformat(),
                valid_to=item.valid_to.isoformat() if item.valid_to else None,
            )
            content_hash = item.content_hash or f"legacy:{item.timeseries_uuid}"
            group_key = (
                content_hash,
                item.report_type,
                item.source_region,
                item.valid_from,
                item.valid_to,
            )
            groups.setdefault(group_key, set()).add(series_key)
        return groups

    @staticmethod
    def _lock_snapshot_groups(cur, groups: dict[tuple[object, ...], set[str]]) -> None:
        """Serialize replacements for each artifact snapshot before mutation."""

        for group_key in sorted(groups, key=repr):
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (repr(group_key),),
            )

    @staticmethod
    def _transaction_timestamp(cur) -> datetime:
        """Read the stable PostgreSQL transaction timestamp for cross-store closure."""

        cur.execute("SELECT CURRENT_TIMESTAMP")
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("PostgreSQL did not return a transaction timestamp")
        return row[0]

    @staticmethod
    def _retire_absent_snapshot_facts(
        cur,
        groups: dict[tuple[object, ...], set[str]],
    ) -> list[str]:
        """Close only current rows omitted from an authoritative report snapshot."""

        retired: list[str] = []
        for group_key, current_series_keys in groups.items():
            (
                content_hash,
                report_type,
                source_region,
                valid_from,
                valid_to,
            ) = group_key
            params = {
                "content_hash": content_hash,
                "report_type": report_type,
                "source_region": source_region,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "series_keys": sorted(current_series_keys),
            }
            cur.execute(
                """
                UPDATE fact_observation
                SET sys_to = CURRENT_TIMESTAMP
                WHERE content_hash = %(content_hash)s
                  AND report_type = %(report_type)s
                  AND source_region = %(source_region)s
                  AND valid_from = %(valid_from)s
                  AND valid_to IS NOT DISTINCT FROM %(valid_to)s
                  AND sys_to = 'infinity'
                  AND NOT (series_key = ANY(%(series_keys)s))
                RETURNING timeseries_uuid
                """,
                params,
            )
            retired.extend(str(row[0]) for row in cur.fetchall())

        if retired:
            cur.execute(
                """
                DELETE FROM fact_observation_current
                WHERE timeseries_uuid = ANY(%s)
                """,
                (retired,),
            )
        return retired

    @staticmethod
    def _insert_observation_lineage(
        cur,
        records: Iterable[ObservationLineage],
    ) -> None:
        """Insert immutable cell-to-observation bridge records idempotently."""

        for item in records:
            cur.execute(
                """
                INSERT INTO fact_observation_lineage (
                    lineage_key, timeseries_uuid, source_id, report_document_id,
                    content_hash, destination_table, destination_key,
                    destination_column, raw_kind, raw_item_id, page_no, table_no,
                    row_no, col_no, confidence, extraction_method
                ) VALUES (
                    %(lineage_key)s, %(timeseries_uuid)s, %(source_id)s,
                    %(report_document_id)s, %(content_hash)s,
                    %(destination_table)s, %(destination_key)s,
                    %(destination_column)s, %(raw_kind)s, %(raw_item_id)s,
                    %(page_no)s, %(table_no)s, %(row_no)s, %(col_no)s,
                    %(confidence)s, %(extraction_method)s
                )
                ON CONFLICT (lineage_key) DO NOTHING
                """,
                asdict(item),
            )

    @staticmethod
    def _refresh_current_truth_views(cur) -> bool:
        """Refresh the optional materialized projection without migration coupling."""

        cur.execute("SELECT to_regclass('public.daily_regional_current_summary')")
        if cur.fetchone()[0] is None:
            return False
        cur.execute("REFRESH MATERIALIZED VIEW daily_regional_current_summary")
        return True

    @staticmethod
    def _upsert_reconciliation(cur, records: Iterable[ReconciliationResult]) -> None:
        for item in records:
            payload = asdict(item)
            cur.execute(
                """
                INSERT INTO reconciliation_result (
                    run_id, entity_key, metric_name, time_block,
                    variance_pct, source_region, computed_at
                ) VALUES (
                    %(run_id)s, %(entity_key)s, %(metric_name)s, %(time_block)s,
                    %(variance_pct)s, %(source_region)s, %(computed_at)s
                )
                ON CONFLICT (run_id, entity_key, metric_name, time_block)
                DO UPDATE SET
                    variance_pct = EXCLUDED.variance_pct,
                    computed_at = EXCLUDED.computed_at
                """,
                payload,
            )


    @staticmethod
    def _upsert_canonical_identity(
        cur,
        entities: Iterable[dict[str, object]],
        aliases: Iterable[dict[str, object]],
        adjudications: Iterable[dict[str, object]],
    ) -> dict[str, int]:
        """Idempotently merge canonical entities, aliases, and open issues."""

        entity_count = 0
        for entity in entities:
            cur.execute(
                """
                INSERT INTO canonical_entity (
                    entity_id, entity_code, entity_type, canonical_name,
                    region_code, state_code
                ) VALUES (
                    %(entity_id)s, %(entity_code)s, %(entity_type)s, %(canonical_name)s,
                    %(region_code)s, %(state_code)s
                )
                ON CONFLICT (entity_id) DO UPDATE SET
                    canonical_name = EXCLUDED.canonical_name,
                    region_code = EXCLUDED.region_code,
                    state_code = EXCLUDED.state_code
                """,
                entity,
            )
            entity_count += 1
        alias_count = 0
        for alias in aliases:
            cur.execute(
                """
                INSERT INTO canonical_entity_alias (
                    entity_id, source_id, entity_type, raw_name, normalized_name,
                    observation_entity_key, match_method, match_confidence,
                    approval_status
                ) VALUES (
                    %(entity_id)s, %(source_id)s, %(entity_type)s, %(raw_name)s,
                    %(normalized_name)s, %(observation_entity_key)s, %(match_method)s,
                    %(match_confidence)s, %(approval_status)s
                )
                ON CONFLICT (source_id, entity_type, normalized_name) DO UPDATE SET
                    entity_id = EXCLUDED.entity_id,
                    raw_name = EXCLUDED.raw_name,
                    observation_entity_key = EXCLUDED.observation_entity_key,
                    match_method = EXCLUDED.match_method,
                    match_confidence = EXCLUDED.match_confidence
                WHERE canonical_entity_alias.approval_status IN ('approved', 'auto_exact')
                """,
                alias,
            )
            alias_count += 1
        issue_count = 0
        for issue in adjudications:
            cur.execute(
                """
                INSERT INTO canonical_entity_adjudication (
                    source_id, entity_type, raw_name, normalized_name,
                    candidate_entity_id, candidate_score, reason, status
                ) VALUES (
                    %(source_id)s, %(entity_type)s, %(raw_name)s, %(normalized_name)s,
                    %(candidate_entity_id)s, %(candidate_score)s, %(reason)s, %(status)s
                )
                ON CONFLICT (source_id, entity_type, normalized_name, reason) DO NOTHING
                """,
                issue,
            )
            issue_count += 1
        return {
            "entities": entity_count,
            "aliases": alias_count,
            "adjudications": issue_count,
        }

    @staticmethod
    def _upsert_wide_facts(cur, records: Iterable[object]) -> int:
        """Insert idempotent wide grains and advance current-truth pointers."""

        inserted = 0
        for item in records:
            payload = {
                "wide_fact_key": item.wide_fact_key,
                "grain_key": item.grain_key,
                "source_id": item.source_id,
                "destination_table": item.destination_table,
                "destination_key": item.destination_key,
                "report_document_id": item.report_document_id,
                "content_hash": item.content_hash,
                "valid_date": item.valid_date,
                "entity_key": item.entity_key,
                "canonical_entity_id": item.canonical_entity_id,
                "report_type": item.report_type,
                "source_region": item.source_region,
                "metrics": json.dumps(item.metrics, sort_keys=True),
            }
            cur.execute(
                """
                INSERT INTO fact_wide_daily (
                    wide_fact_key, grain_key, source_id, destination_table,
                    destination_key, report_document_id, content_hash, valid_date,
                    entity_key, canonical_entity_id, report_type, source_region,
                    metrics, ingested_at, sys_to
                ) VALUES (
                    %(wide_fact_key)s, %(grain_key)s, %(source_id)s, %(destination_table)s,
                    %(destination_key)s, %(report_document_id)s, %(content_hash)s,
                    %(valid_date)s, %(entity_key)s, %(canonical_entity_id)s,
                    %(report_type)s, %(source_region)s, %(metrics)s::jsonb,
                    CURRENT_TIMESTAMP, 'infinity'
                )
                ON CONFLICT (wide_fact_key) DO NOTHING
                RETURNING wide_fact_key
                """,
                payload,
            )
            if cur.fetchone() is None:
                continue
            cur.execute(
                """
                UPDATE fact_wide_daily
                SET sys_to = CURRENT_TIMESTAMP
                WHERE grain_key = %(grain_key)s
                  AND sys_to = 'infinity'
                  AND wide_fact_key <> %(wide_fact_key)s
                """,
                payload,
            )
            cur.execute(
                """
                INSERT INTO fact_wide_daily_current (
                    grain_key, wide_fact_key, canonical_entity_id, system_from
                ) VALUES (
                    %(grain_key)s, %(wide_fact_key)s, %(canonical_entity_id)s,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (grain_key) DO UPDATE SET
                    wide_fact_key = EXCLUDED.wide_fact_key,
                    canonical_entity_id = EXCLUDED.canonical_entity_id,
                    system_from = EXCLUDED.system_from
                """,
                payload,
            )
            inserted += 1
        return inserted

