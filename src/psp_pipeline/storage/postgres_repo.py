from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

import psycopg

from psp_pipeline.models.contracts import FactObservation, LineageRecord


class PostgresRepository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def insert_lineage(self, records: Iterable[LineageRecord]) -> None:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                self._insert_lineage(cur, records)
            conn.commit()

    def upsert_fact_observations(self, records: Iterable[FactObservation]) -> None:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                self._upsert_facts(cur, records)
            conn.commit()

    def run_in_transaction(
        self,
        lineage: Iterable[LineageRecord],
        facts: Iterable[FactObservation],
    ) -> None:
        """Insert lineage and facts in a single atomic transaction."""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                self._insert_lineage(cur, lineage)
                self._upsert_facts(cur, facts)
            conn.commit()

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

