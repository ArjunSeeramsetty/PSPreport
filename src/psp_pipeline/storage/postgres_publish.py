"""Publish canonical identity and wide facts into the Postgres projection."""

from __future__ import annotations

import logging
import sqlite3
from typing import Iterable

from psp_pipeline.identity.canonical import (
    CanonicalCatalog,
    build_canonical_catalog,
    catalog_as_postgres_rows,
)
from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.storage.wide_facts import (
    attach_canonical_entity_ids,
    export_wide_facts,
    verify_exported_wide_fact_mirror,
)


LOGGER = logging.getLogger(__name__)


def dimension_catalog_available(conn: sqlite3.Connection) -> bool:
    """Return whether curated dimensions exist for identity publication."""

    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'DimRegions'"
    ).fetchone()
    return row is not None


def prepare_curated_postgres_publish(
    conn: sqlite3.Connection,
    observations: Iterable[FactObservation],
    repository: object,
) -> tuple[list[FactObservation], CanonicalCatalog | None, dict[str, object]]:
    """Attach canonical IDs and optionally publish the identity index.

    Fake repositories without ``upsert_canonical_entities`` keep working: the
    SQLite catalog is still built when dimensions exist, but Postgres identity
    rows are skipped.
    """

    observation_rows = list(observations)
    if not dimension_catalog_available(conn):
        return observation_rows, None, {"skipped": True}
    catalog = build_canonical_catalog(conn)
    annotated = attach_canonical_entity_ids(observation_rows, catalog)
    entities, aliases, issues = catalog_as_postgres_rows(catalog)
    identity_counts: dict[str, object] = {
        "entities": 0,
        "aliases": 0,
        "adjudications": 0,
        "skipped": True,
    }
    publisher = getattr(repository, "upsert_canonical_entities", None)
    if callable(publisher):
        identity_counts = dict(publisher(entities, aliases, issues))
        identity_counts["skipped"] = False
        LOGGER.info("canonical_identity_published counts=%s", identity_counts)
    conn.commit()
    return annotated, catalog, {
        "catalog_entities": len(catalog.entities),
        "catalog_aliases": len(catalog.aliases),
        "catalog_adjudications": len(catalog.adjudications),
        "postgres": identity_counts,
        "skipped": False,
    }


def publish_wide_facts_to_repository(
    observations: Iterable[FactObservation],
    catalog: CanonicalCatalog | None,
    repository: object,
    *,
    verify_current_mirror: bool = True,
) -> dict[str, object]:
    """Collapse long-form facts and upsert destination-table grains.

    Snapshot replacement is never used here. A replay with the same
    ``wide_fact_key`` is a no-op; a corrected payload inserts a new key and
    closes the previous ``sys_to``.
    """

    rows = export_wide_facts(observations, catalog)
    inserted = 0
    skipped = True
    publisher = getattr(repository, "upsert_wide_facts", None)
    if rows and callable(publisher):
        inserted = int(publisher(rows))
        skipped = False
        LOGGER.info(
            "wide_facts_published exported=%s inserted=%s",
            len(rows),
            inserted,
        )
    summary: dict[str, object] = {
        "wide_facts_exported": len(rows),
        "wide_facts_inserted": inserted,
        "wide_facts_deduplicated": len(rows) - inserted,
        "skipped": skipped or not rows,
    }
    if (
        verify_current_mirror
        and rows
        and not skipped
        and callable(getattr(repository, "fetch_current_wide_facts", None))
    ):
        summary["wide_mirror"] = verify_exported_wide_fact_mirror(rows, repository)
    return summary
