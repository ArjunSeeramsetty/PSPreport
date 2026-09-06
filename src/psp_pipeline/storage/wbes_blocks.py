"""Isolated WBES 96-block schedule matrix helpers.

Live WBES portals are never contacted from this module. Callers must gate
ingestion behind credentials and ``wbes-controlled-access`` rules. Schedules
belong in Timescale, not Neo4j.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Mapping, Sequence

WBES_BLOCKS_PER_DAY = 96
WBES_BLOCK_MINUTES = 15

CREATE_FACT_WBES_BLOCK_SQL = """
CREATE TABLE IF NOT EXISTS fact_wbes_block (
    grain_key TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    sys_from TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_to TIMESTAMPTZ NOT NULL DEFAULT 'infinity',
    version_no INTEGER NOT NULL,
    block_no INTEGER NOT NULL CHECK (block_no BETWEEN 1 AND 96),
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION NULL,
    content_hash TEXT NOT NULL,
    report_document_id BIGINT NULL,
    timeseries_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
    PRIMARY KEY (grain_key, valid_from, version_no, sys_from)
)
"""

CREATE_WBES_HYPERTABLE_SQL = """
SELECT create_hypertable(
    'fact_wbes_block',
    by_range('valid_from', INTERVAL '7 days'),
    if_not_exists => TRUE
)
"""

ADD_WBES_HASH_DIMENSION_SQL = """
SELECT add_dimension(
    'fact_wbes_block',
    by_hash('grain_key', 4),
    if_not_exists => TRUE
)
"""

BITEMPORAL_WBES_UPSERT_SQL = """
WITH incoming_data AS (
    SELECT * FROM staging_wbes_metrics
),
retire_old AS (
    UPDATE fact_wbes_block AS fact
    SET sys_to = CURRENT_TIMESTAMP
    FROM incoming_data AS incoming
    WHERE fact.grain_key = incoming.grain_key
      AND fact.valid_from = incoming.valid_from
      AND fact.sys_to = 'infinity'
    RETURNING fact.grain_key, fact.valid_from
)
INSERT INTO fact_wbes_block (
    grain_key, valid_from, valid_to, sys_from, version_no, block_no,
    metric_name, metric_value, content_hash, report_document_id
)
SELECT
    incoming.grain_key,
    incoming.valid_from,
    incoming.valid_to,
    CURRENT_TIMESTAMP,
    COALESCE(
        (
            SELECT MAX(existing.version_no) + 1
            FROM fact_wbes_block AS existing
            WHERE existing.grain_key = incoming.grain_key
              AND existing.valid_from = incoming.valid_from
        ),
        1
    ),
    incoming.block_no,
    incoming.metric_name,
    incoming.metric_value,
    incoming.content_hash,
    incoming.report_document_id
FROM incoming_data AS incoming
"""


@dataclass(frozen=True)
class WbesBlock:
    """One validated 15-minute WBES schedule assertion."""

    grain_key: str
    valid_from: datetime
    valid_to: datetime
    block_no: int
    metric_name: str
    metric_value: float | None
    content_hash: str
    report_document_id: int | None = None


class WbesBlockError(ValueError):
    """Raised when a WBES block violates the 96-block daily grain."""


def block_window(valid_date: datetime, block_no: int) -> tuple[datetime, datetime]:
    """Return the half-open ``[valid_from, valid_to)`` window for one block."""

    if block_no < 1 or block_no > WBES_BLOCKS_PER_DAY:
        raise WbesBlockError(f"block_no {block_no} is outside 1..96")
    start_date = valid_date.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    valid_from = start_date + timedelta(minutes=WBES_BLOCK_MINUTES * (block_no - 1))
    return valid_from, valid_from + timedelta(minutes=WBES_BLOCK_MINUTES)


def build_wbes_grain_key(
    *,
    station_or_beneficiary: str,
    metric_name: str,
    valid_date: str,
) -> str:
    """Return a stable grain identifier excluding the 15-minute block."""

    return json.dumps(
        {
            "entity": station_or_beneficiary,
            "metric_name": metric_name,
            "valid_date": valid_date,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def validate_daily_blocks(blocks: Sequence[Mapping[str, object]]) -> tuple[int, ...]:
    """Return sorted block numbers after rejecting duplicates and out-of-range ids."""

    seen: dict[int, None] = {}
    for block in blocks:
        block_no = int(block["block_no"])
        if block_no < 1 or block_no > WBES_BLOCKS_PER_DAY:
            raise WbesBlockError(f"block_no {block_no} is outside 1..96")
        if block_no in seen:
            raise WbesBlockError(f"duplicate block_no {block_no}")
        seen[block_no] = None
    return tuple(sorted(seen))


def content_hash_for_block(payload: Mapping[str, object]) -> str:
    """Return a deterministic checksum used by bitemporal idempotency."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def wbes_schema_statements() -> tuple[str, ...]:
    """Return the isolated DDL statements for the WBES hypertable."""

    return (
        CREATE_FACT_WBES_BLOCK_SQL.strip(),
        CREATE_WBES_HYPERTABLE_SQL.strip(),
        ADD_WBES_HASH_DIMENSION_SQL.strip(),
    )
