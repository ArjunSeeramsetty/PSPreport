from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, Optional

try:
    import psycopg
except ImportError:
    psycopg = None  # type: ignore[assignment]

from psp_pipeline.models.contracts import FactObservation, LineageRecord, ReconciliationResult


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
    ) -> int:
        """Insert lineage and facts in a single atomic transaction."""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                self._insert_lineage(cur, lineage)
                inserted = self._upsert_facts(cur, facts)
                if reconciliation is not None:
                    self._upsert_reconciliation(cur, reconciliation)
            conn.commit()
        return inserted

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
            grain_key = "|".join(
                (
                    item.entity_key,
                    item.metric_name,
                    item.time_block or "",
                    item.report_type,
                    item.source_region,
                    item.valid_from.isoformat(),
                    item.valid_to.isoformat() if item.valid_to else "",
                )
            )
            # Lock one logical observation grain so concurrent loaders cannot
            # assign the same correction version.
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (grain_key,),
            )
            cur.execute(
                """
                INSERT INTO fact_observation_dedup (
                    timeseries_uuid, entity_key, metric_name, time_block,
                    report_type, source_region, valid_from, valid_to,
                    first_ingested_at
                ) VALUES (
                    %(timeseries_uuid)s, %(entity_key)s, %(metric_name)s,
                    %(time_block)s, %(report_type)s, %(source_region)s,
                    %(valid_from)s, %(valid_to)s, %(ingested_at)s
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
                    entity_key, metric_name, time_block, operational_value, settlement_value,
                    variance_pct, report_type, source_region, valid_from, valid_to,
                    version_no, ingested_at, timeseries_uuid
                ) VALUES (
                    %(entity_key)s, %(metric_name)s, %(time_block)s, %(operational_value)s, %(settlement_value)s,
                    %(variance_pct)s, %(report_type)s, %(source_region)s, %(valid_from)s, %(valid_to)s,
                    %(version_no)s, %(ingested_at)s, %(timeseries_uuid)s
                )
                """,
                payload,
            )
            inserted += 1
        return inserted

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
