"""Local SQLite store for WBES block facts, checkpoints, and entities.

This database is separate from ``data/sqlite/all_rldc_daily.sqlite``.
"""

from __future__ import annotations

from datetime import datetime
import sqlite3
from pathlib import Path
from typing import Iterable

from psp_pipeline.wbes.models import WbesBlockFact, WbesRevisionDocument, entity_key

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wbes_checkpoint (
    source_id TEXT NOT NULL,
    schedule_date TEXT NOT NULL,
    revision_label TEXT NOT NULL,
    status TEXT NOT NULL,
    content_hash TEXT,
    raw_path TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source_id, schedule_date, revision_label)
);

CREATE TABLE IF NOT EXISTS dim_wbes_entity (
    entity_key TEXT PRIMARY KEY,
    archetype TEXT NOT NULL,
    region TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_wbes_block (
    revision_uuid TEXT PRIMARY KEY,
    series_key TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    counterparty_key TEXT,
    archetype TEXT NOT NULL,
    matrix_kind TEXT NOT NULL,
    schedule_component TEXT,
    metric_name TEXT NOT NULL,
    time_block TEXT NOT NULL,
    block_no INTEGER NOT NULL,
    operational_value REAL NOT NULL,
    source_region TEXT NOT NULL,
    source_id TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    revision_label TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    sys_to TEXT NOT NULL DEFAULT 'infinity',
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS fact_wbes_block_series_history_idx
    ON fact_wbes_block (series_key, ingested_at DESC);

CREATE TABLE IF NOT EXISTS fact_wbes_block_current (
    series_key TEXT PRIMARY KEY,
    revision_uuid TEXT NOT NULL,
    system_from TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wbes_recon_imbalance (
    schedule_date TEXT NOT NULL,
    revision_label TEXT NOT NULL,
    source_region TEXT NOT NULL,
    block_no INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    left_value REAL NOT NULL,
    right_value REAL NOT NULL,
    variance_mw REAL NOT NULL,
    PRIMARY KEY (schedule_date, revision_label, source_region, block_no, metric_name)
);
"""


class WbesSqliteStore:
    """Bitemporal SQLite persistence for isolated WBES ingest."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def checkpoint_status(
        self, source_id: str, schedule_date: str, revision_label: str
    ) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT status FROM wbes_checkpoint
                WHERE source_id = ? AND schedule_date = ? AND revision_label = ?
                """,
                (source_id, schedule_date, revision_label),
            ).fetchone()
        return None if row is None else str(row["status"])

    def mark_checkpoint(
        self,
        *,
        source_id: str,
        schedule_date: str,
        revision_label: str,
        status: str,
        content_hash: str | None = None,
        raw_path: str | None = None,
        updated_at: datetime,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO wbes_checkpoint(
                    source_id, schedule_date, revision_label, status,
                    content_hash, raw_path, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, schedule_date, revision_label) DO UPDATE SET
                    status = excluded.status,
                    content_hash = excluded.content_hash,
                    raw_path = excluded.raw_path,
                    updated_at = excluded.updated_at
                """,
                (
                    source_id,
                    schedule_date,
                    revision_label,
                    status,
                    content_hash,
                    raw_path,
                    updated_at.isoformat(),
                ),
            )
            conn.commit()

    def upsert_entities(self, document: WbesRevisionDocument) -> None:
        rows = []
        for matrix in document.matrices:
            for item in matrix.rows:
                key = entity_key(
                    region=document.source_region,
                    archetype=item.archetype,
                    entity_id=item.entity_id,
                )
                rows.append(
                    (
                        key,
                        item.archetype.value,
                        document.source_region,
                        item.entity_id,
                        item.entity_name,
                    )
                )
                if item.counterparty_id and item.counterparty_archetype is not None:
                    counterpart = entity_key(
                        region=document.source_region,
                        archetype=item.counterparty_archetype,
                        entity_id=item.counterparty_id,
                    )
                    rows.append(
                        (
                            counterpart,
                            item.counterparty_archetype.value,
                            document.source_region,
                            item.counterparty_id,
                            item.counterparty_name or item.counterparty_id,
                        )
                    )
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO dim_wbes_entity(
                    entity_key, archetype, region, entity_id, display_name
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(entity_key) DO UPDATE SET
                    display_name = excluded.display_name
                """,
                rows,
            )
            conn.commit()

    def upsert_facts(self, facts: Iterable[WbesBlockFact]) -> tuple[int, int]:
        """Insert new revisions and close prior current-truth rows.

        Returns:
            ``(inserted, deduplicated)`` counts.
        """

        inserted = 0
        deduplicated = 0
        with self.connect() as conn:
            for fact in facts:
                existing = conn.execute(
                    "SELECT 1 FROM fact_wbes_block WHERE revision_uuid = ?",
                    (fact.revision_uuid,),
                ).fetchone()
                if existing is not None:
                    deduplicated += 1
                    continue
                ingested = fact.ingested_at.isoformat()
                conn.execute(
                    """
                    UPDATE fact_wbes_block
                    SET sys_to = ?
                    WHERE series_key = ? AND sys_to = 'infinity'
                    """,
                    (ingested, fact.series_key),
                )
                conn.execute(
                    """
                    INSERT INTO fact_wbes_block(
                        revision_uuid, series_key, entity_key, counterparty_key,
                        archetype, matrix_kind, schedule_component, metric_name,
                        time_block, block_no, operational_value, source_region,
                        source_id, valid_from, valid_to, version_no, revision_label,
                        ingested_at, sys_to, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'infinity', ?)
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
                        fact.valid_from.isoformat(),
                        fact.valid_to.isoformat(),
                        fact.version_no,
                        fact.revision_label,
                        ingested,
                        fact.content_hash,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO fact_wbes_block_current(series_key, revision_uuid, system_from)
                    VALUES (?, ?, ?)
                    ON CONFLICT(series_key) DO UPDATE SET
                        revision_uuid = excluded.revision_uuid,
                        system_from = excluded.system_from
                    """,
                    (fact.series_key, fact.revision_uuid, ingested),
                )
                inserted += 1
            conn.commit()
        return inserted, deduplicated

    def current_value(self, series_key: str) -> float | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT fact.operational_value
                FROM fact_wbes_block_current AS current_truth
                JOIN fact_wbes_block AS fact
                  ON fact.revision_uuid = current_truth.revision_uuid
                WHERE current_truth.series_key = ?
                """,
                (series_key,),
            ).fetchone()
        return None if row is None else float(row["operational_value"])

    def record_imbalances(self, rows: Iterable[tuple[object, ...]]) -> int:
        payload = list(rows)
        if not payload:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO wbes_recon_imbalance(
                    schedule_date, revision_label, source_region, block_no,
                    metric_name, left_value, right_value, variance_mw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            conn.commit()
        return len(payload)
