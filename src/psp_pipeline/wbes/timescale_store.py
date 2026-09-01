"""Optional Timescale persistence for WBES block facts.

Applied only when ``WBES_WRITE_TIMESCALE=true``. The public greenfield schema
is not modified. Graph sync is intentionally absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from psp_pipeline.storage.timescale_bootstrap import split_sql_statements
from psp_pipeline.wbes.models import WbesBlockFact

try:
    import psycopg
except ImportError:  # pragma: no cover - optional extra
    psycopg = None  # type: ignore[assignment]


def default_wbes_schema_path() -> Path:
    """Return the isolated WBES Timescale DDL path."""

    return Path(__file__).resolve().parents[3] / "sql" / "wbes_schema.sql"


def apply_wbes_schema(postgres_dsn: str, *, schema_path: Path | None = None) -> int:
    """Create WBES hypertables if they do not already exist."""

    if psycopg is None:
        raise RuntimeError("psycopg is required to apply the WBES Timescale schema")
    path = schema_path or default_wbes_schema_path()
    statements = split_sql_statements(path.read_text(encoding="utf-8"))
    with psycopg.connect(postgres_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
    return len(statements)


class WbesTimescaleStore:
    """Bulk upsert WBES block revisions without touching ``fact_observation``."""

    def __init__(self, dsn: str, *, connect=None):
        self.dsn = dsn
        self._connect = connect or _connect

    def upsert_facts(self, facts: Iterable[WbesBlockFact]) -> int:
        rows = list(facts)
        if not rows:
            return 0
        inserted = 0
        with self._connect(self.dsn) as conn:
            with conn.cursor() as cur:
                for fact in rows:
                    cur.execute(
                        """
                        INSERT INTO fact_wbes_block_dedup (
                            revision_uuid, series_key, content_hash
                        ) VALUES (%s, %s, %s)
                        ON CONFLICT (revision_uuid) DO NOTHING
                        RETURNING revision_uuid
                        """,
                        (fact.revision_uuid, fact.series_key, fact.content_hash),
                    )
                    if cur.fetchone() is None:
                        continue
                    cur.execute(
                        """
                        UPDATE fact_wbes_block
                        SET sys_to = %s
                        WHERE series_key = %s AND sys_to = 'infinity'
                        """,
                        (fact.ingested_at, fact.series_key),
                    )
                    cur.execute(
                        """
                        INSERT INTO fact_wbes_block (
                            revision_uuid, series_key, entity_key, counterparty_key,
                            archetype, matrix_kind, schedule_component, metric_name,
                            time_block, block_no, operational_value, source_region,
                            source_id, valid_from, valid_to, version_no, revision_label,
                            ingested_at, sys_to, content_hash
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, 'infinity', %s
                        )
                        """,
                        (
                            fact.revision_uuid,
                            fact.series_key,
                            fact.entity_key,
                            fact.counterparty_key,
                            fact.archetype,
                            fact.matrix_kind,
                            fact.schedule_component,
                            fact.metric_name,
                            fact.time_block,
                            fact.block_no,
                            fact.operational_value,
                            fact.source_region,
                            fact.source_id,
                            fact.valid_from,
                            fact.valid_to,
                            fact.version_no,
                            fact.revision_label,
                            fact.ingested_at,
                            fact.content_hash,
                        ),
                    )
                    cur.execute(
                        """
                        INSERT INTO fact_wbes_block_current (
                            series_key, revision_uuid, system_from
                        ) VALUES (%s, %s, %s)
                        ON CONFLICT (series_key) DO UPDATE SET
                            revision_uuid = EXCLUDED.revision_uuid,
                            system_from = EXCLUDED.system_from
                        """,
                        (fact.series_key, fact.revision_uuid, fact.ingested_at),
                    )
                    inserted += 1
            conn.commit()
        return inserted


def _connect(dsn: str):
    if psycopg is None:
        raise RuntimeError("psycopg is required to write WBES facts to Timescale")
    return psycopg.connect(dsn)
