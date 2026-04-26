from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, Optional

import psycopg

from psp_pipeline.models.contracts import FactObservation, LineageRecord, ReconciliationResult


class PostgresRepository:
    def __init__(self, dsn: str):
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

    def upsert_fact_observations(self, records: Iterable[FactObservation]) -> None:
        """
        Non-atomic helper for one-off tooling.
        Production pipeline should prefer run_in_transaction().
        """
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                self._upsert_facts(cur, records)
            conn.commit()

    def run_in_transaction(
        self,
        lineage: Iterable[LineageRecord],
        facts: Iterable[FactObservation],
        reconciliation: Iterable[ReconciliationResult] | None = None,
    ) -> None:
        """Insert lineage and facts in a single atomic transaction."""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                self._insert_lineage(cur, lineage)
                self._upsert_facts(cur, facts)
                if reconciliation is not None:
                    self._upsert_reconciliation(cur, reconciliation)
            conn.commit()

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
    def _upsert_facts(cur, records: Iterable[FactObservation]) -> None:
        for item in records:
            payload = asdict(item)
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
                ON CONFLICT (entity_key, metric_name, time_block, valid_from, version_no)
                DO UPDATE SET
                    operational_value = EXCLUDED.operational_value,
                    settlement_value = EXCLUDED.settlement_value,
                    variance_pct = EXCLUDED.variance_pct,
                    valid_to = EXCLUDED.valid_to,
                    ingested_at = EXCLUDED.ingested_at
                """,
                payload,
            )

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
