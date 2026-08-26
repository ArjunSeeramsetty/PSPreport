"""Freshness checks for publicly available PSP report sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable


def check_source_freshness(
    conn,
    expected_source_ids: Iterable[str],
    *,
    max_staleness_hours: int = 36,
    now: datetime | None = None,
) -> list[str]:
    """Return expected public sources with no recent successful ingestion."""

    observed_at = now or datetime.now(timezone.utc)
    cutoff = observed_at - timedelta(hours=max_staleness_hours)
    source_ids = sorted({source_id for source_id in expected_source_ids})
    if not source_ids:
        return []
    placeholders = ", ".join("%s" for _ in source_ids)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT source_id, MAX(fetched_at)
            FROM ingest_lineage
            WHERE source_id IN ({placeholders})
            GROUP BY source_id
            """,
            source_ids,
        )
        latest_by_source = {str(source_id): fetched_at for source_id, fetched_at in cur.fetchall()}
    return [
        source_id
        for source_id in source_ids
        if latest_by_source.get(source_id) is None
        or latest_by_source[source_id] < cutoff
    ]
