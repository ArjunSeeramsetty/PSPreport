"""Stable identity helpers for bitemporal fact observations."""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5


def build_series_key(
    *,
    entity_key: str,
    metric_name: str,
    time_block: str | None,
    report_type: str,
    source_region: str,
    valid_from: str,
    valid_to: str | None,
) -> str:
    """Return a collision-safe stable identifier for one logical observation grain."""

    return json.dumps(
        {
            "entity_key": entity_key,
            "metric_name": metric_name,
            "report_type": report_type,
            "source_region": source_region,
            "time_block": time_block,
            "valid_from": valid_from,
            "valid_to": valid_to,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def build_revision_uuid(series_key: str, content_hash: str) -> str:
    """Return an immutable revision UUID for a series and source artifact hash."""

    return str(uuid5(NAMESPACE_URL, f"{series_key}|{content_hash}"))
