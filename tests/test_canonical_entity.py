"""Tests for cross-source canonical entity identity and fuzzy adjudication."""

from __future__ import annotations

import sqlite3

from psp_pipeline.identity.canonical import (
    CanonicalAdjudication,
    CanonicalAlias,
    build_canonical_catalog,
    build_entity_id,
    name_similarity,
    propose_source_label,
)
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


def test_entity_id_is_stable_uuid5_of_entity_code() -> None:
    """Canonical UUIDs are deterministic and do not depend on insert order."""

    first = build_entity_id("state:IN-KA")
    second = build_entity_id("state:IN-KA")
    assert first == second
    assert first != build_entity_id("state:IN-TN")
    assert len(first) == 36


def test_exact_ka_alias_auto_approves_karnataka() -> None:
    """Approved SRLDC alias KA resolves to the Karnataka canonical entity."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    catalog = build_canonical_catalog(conn)

    result = propose_source_label(
        catalog,
        source_id="srldc",
        entity_type="state",
        raw_name="KA",
    )

    assert isinstance(result, CanonicalAlias)
    assert result.approval_status in {"approved", "auto_exact"}
    entity = catalog.entity_by_id(result.entity_id)
    assert entity is not None
    assert entity.canonical_name == "Karnataka"
    assert entity.entity_code == "state:IN-KA"
    assert entity.entity_id == build_entity_id("state:IN-KA")


def test_fuzzy_near_match_is_queued_and_never_auto_merged() -> None:
    """A misspelling above the fuzzy floor stays pending instead of merging."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    catalog = build_canonical_catalog(conn)
    karnataka_id = build_entity_id("state:IN-KA")
    assert name_similarity("Karnatka", "Karnataka") >= 0.88

    result = propose_source_label(
        catalog,
        source_id="srldc",
        entity_type="state",
        raw_name="Karnatka",
    )

    assert isinstance(result, CanonicalAdjudication)
    assert result.status == "pending"
    assert result.reason == "fuzzy_candidate"
    assert result.candidate_entity_id == karnataka_id
    assert result.candidate_score is not None and result.candidate_score >= 0.88
    assert not any(
        alias.raw_name == "Karnatka"
        and alias.approval_status in {"approved", "auto_exact"}
        for alias in catalog.aliases
    )


def test_catalog_persists_identity_tables_and_region_observation_keys() -> None:
    """SQLite is the local identity index before Postgres publication."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    catalog = build_canonical_catalog(conn)

    entity_count = conn.execute("SELECT COUNT(*) FROM canonical_entity").fetchone()[0]
    alias_count = conn.execute(
        "SELECT COUNT(*) FROM canonical_entity_alias"
    ).fetchone()[0]
    assert entity_count == len(catalog.entities)
    assert alias_count >= 1
    southern = conn.execute(
        """
        SELECT EntityID FROM canonical_entity_alias
        WHERE ObservationEntityKey = 'SR:region:Southern Region'
          AND ApprovalStatus IN ('approved', 'auto_exact')
        """
    ).fetchone()
    assert southern is not None
    assert southern[0] == build_entity_id("region:SR")
