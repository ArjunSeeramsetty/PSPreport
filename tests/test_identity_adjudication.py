"""Tests for human approve/reject of pending canonical identity issues."""

from __future__ import annotations

from inspect import getsource
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.identity.adjudication import (
    AdjudicationError,
    apply_adjudication,
    identity_adjudication_summary,
    list_identity_adjudications,
    queue_source_label,
    republish_identity_after_adjudication,
)
from psp_pipeline.identity.canonical import (
    CanonicalAdjudication,
    CanonicalAlias,
    annotate_topology_with_canonical_ids,
    build_canonical_catalog,
    build_entity_id,
    propose_source_label,
)
from psp_pipeline.pipelines.stages import (
    apply_canonical_identity_adjudication,
    audit_pending_identity_adjudications,
)
from psp_pipeline.storage.postgres_repo import PostgresRepository
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema
from psp_pipeline.storage.sqlite_topology_export import export_curated_topology
from psp_pipeline.storage.timescale_bootstrap import default_greenfield_schema_path


def _queue_karnatka(conn: sqlite3.Connection) -> int:
    result = queue_source_label(
        conn,
        source_id="srldc",
        entity_type="state",
        raw_name="Karnatka",
    )
    assert isinstance(result, CanonicalAdjudication)
    issues = [
        issue
        for issue in list_identity_adjudications(conn, status="pending")
        if issue["raw_name"] == "Karnatka"
    ]
    assert issues
    return int(issues[0]["issue_id"])


def test_approve_karnatka_writes_alias_and_resolves_on_rebuild() -> None:
    """Approving a fuzzy misspelling creates a human alias that survives rebuild."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    issue_id = _queue_karnatka(conn)
    karnataka_id = build_entity_id("state:IN-KA")

    applied = apply_adjudication(conn, issue_id=issue_id, decision="approved")

    assert applied.decision == "approved"
    assert applied.entity_id == karnataka_id
    assert applied.aliases_written >= 1
    alias = conn.execute(
        """
        SELECT EntityID, MatchMethod, ApprovalStatus
        FROM canonical_entity_alias
        WHERE RawName = 'Karnatka' AND MatchMethod = 'human_adjudication'
        """
    ).fetchone()
    assert alias is not None
    assert alias[0] == karnataka_id
    assert alias[2] == "approved"

    rebuilt = build_canonical_catalog(conn)
    resolved = propose_source_label(
        rebuilt,
        source_id="srldc",
        entity_type="state",
        raw_name="Karnatka",
    )
    assert isinstance(resolved, CanonicalAlias)
    assert resolved.entity_id == karnataka_id
    assert any(
        item.raw_name == "Karnatka" and item.match_method == "human_adjudication"
        for item in rebuilt.aliases
    )


def test_reject_karnatka_records_decision_without_alias() -> None:
    """Rejection closes the issue and never auto-merges a fuzzy label."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    issue_id = _queue_karnatka(conn)

    applied = apply_adjudication(conn, issue_id=issue_id, decision="rejected")

    assert applied.decision == "rejected"
    assert applied.aliases_written == 0
    assert conn.execute(
        """
        SELECT COUNT(*) FROM canonical_entity_alias
        WHERE RawName = 'Karnatka'
        """
    ).fetchone()[0] == 0
    status = conn.execute(
        "SELECT Status FROM canonical_entity_adjudication WHERE IssueID = ?",
        (issue_id,),
    ).fetchone()[0]
    assert status == "rejected"


def test_cannot_approve_unmatched_label_without_entity_id() -> None:
    """An unmatched label stays pending until an operator supplies an entity."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    queued = queue_source_label(
        conn,
        source_id="srldc",
        entity_type="state",
        raw_name="Zzzyxland",
    )
    assert isinstance(queued, CanonicalAdjudication)
    assert queued.reason == "unmatched_label"
    assert queued.candidate_entity_id is None
    issue_id = list_identity_adjudications(conn)[0]["issue_id"]

    with pytest.raises(AdjudicationError, match="entity_id"):
        apply_adjudication(conn, issue_id=int(issue_id), decision="approved")


def test_cannot_apply_the_same_issue_twice() -> None:
    """A decided issue cannot be approved or rejected again."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    issue_id = _queue_karnatka(conn)
    apply_adjudication(conn, issue_id=issue_id, decision="approved")

    with pytest.raises(AdjudicationError, match="not pending"):
        apply_adjudication(conn, issue_id=issue_id, decision="approved")


def test_catalog_rebuild_publishes_queued_adjudications() -> None:
    """Source-label queues are reloaded so Postgres publish keeps pending issues."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _queue_karnatka(conn)

    catalog = build_canonical_catalog(conn)

    assert any(
        issue.raw_name == "Karnatka" and issue.status == "pending"
        for issue in catalog.adjudications
    )


def test_republish_backfills_observation_keys_on_fake_repository() -> None:
    """Approval republishes identity and stamps current facts by entity_key."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    issue_id = _queue_karnatka(conn)
    applied = apply_adjudication(conn, issue_id=issue_id, decision="approved")
    events: list[str] = []

    class Repository:
        def upsert_canonical_entities(self, entities, aliases, adjudications) -> dict[str, int]:
            events.append("identity")
            return {
                "entities": len(list(entities)),
                "aliases": len(list(aliases)),
                "adjudications": len(list(adjudications)),
            }

        def apply_canonical_adjudication(self, payload: dict[str, object]) -> dict[str, int]:
            events.append("decision")
            assert payload["decision"] == "approved"
            assert payload["decided_by"] == "operator"
            return {"issues_updated": 1, "aliases_upserted": 1}

        def backfill_canonical_entity_ids(self, entity_id, keys) -> dict[str, int]:
            events.append("backfill")
            assert entity_id == applied.entity_id
            assert keys
            return {"observations_updated": 1, "wide_facts_updated": 1}

    published = republish_identity_after_adjudication(conn, Repository(), applied)

    assert events == ["identity", "decision", "backfill"]
    assert published["backfill"]["skipped"] is False
    assert published["postgres"]["skipped"] is False


def test_topology_stations_units_countries_and_lines_bind_canonical_ids() -> None:
    """Station/unit codes and observation keys stamp topology canonical UUIDs."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    southern = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Southern Region'"
    ).fetchone()[0]
    karnataka = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Karnataka'"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO DimPowerStations(
            StationCode, CanonicalStationName, StateID, RegionID, InstalledCapacityMW
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("KA-RTPS", "Raichur TPS", karnataka, southern, 1720.0),
    )
    station_id = conn.execute("SELECT StationID FROM DimPowerStations").fetchone()[0]
    conn.execute(
        """
        INSERT INTO DimGeneratingUnits(
            UnitCode, StationID, CanonicalUnitName, UnitNumber, CapacityMW
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("KA-RTPS-U1", station_id, "Raichur TPS Unit 1", "1", 210.0),
    )
    conn.execute(
        """
        INSERT INTO DimVoltageNodes(NodeName, NominalVoltageKV, StateID, RegionID)
        VALUES (?, ?, ?, ?)
        """,
        ("Raichur 400kV", 400.0, karnataka, southern),
    )
    conn.execute(
        """
        INSERT INTO DimTransmissionElements(
            ElementName, ElementType, NominalVoltageKV, FromRegionID, FromStateID
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("400KV-RTPS-HOODY", "line", 400.0, southern, karnataka),
    )
    catalog = build_canonical_catalog(conn)
    topology = annotate_topology_with_canonical_ids(export_curated_topology(conn), catalog)

    station = topology["stations"][0]
    unit = topology["units"][0]
    country = next(row for row in topology["countries"] if row["name"] == "Bhutan")
    voltage = topology["voltage_nodes"][0]
    line = topology["transmission_lines"][0]
    assert station["station_code"] == "KA-RTPS"
    assert station["canonical_entity_id"] == build_entity_id("station:KA-RTPS")
    assert unit["unit_code"] == "KA-RTPS-U1"
    assert unit["canonical_entity_id"] == build_entity_id("unit:KA-RTPS-U1")
    assert country["canonical_entity_id"] == build_entity_id("country:bhutan")
    assert voltage["canonical_entity_id"] == build_entity_id("voltage:raichur400kv:SR")
    assert line["canonical_entity_id"] == build_entity_id("line:400kvrtpshoody")


def test_gold_views_are_in_greenfield_schema_and_lazy_applied() -> None:
    """Gold current-truth views are ordinary views keyed by canonical_entity_id."""

    script = default_greenfield_schema_path().read_text(encoding="utf-8")
    assert "CREATE OR REPLACE VIEW gold_wide_fact_current AS" in script
    assert "CREATE OR REPLACE VIEW gold_canonical_daily_current AS" in script
    assert "CREATE MATERIALIZED VIEW gold_" not in script
    assert "energy_met_mu" in script
    assert "evening_peak_demand_met_mw" in script

    class Cursor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def execute(self, query: str, params: object = None) -> None:
            self.calls.append(query)

    cursor = Cursor()
    PostgresRepository._ensure_gold_query_views(cursor)
    joined = "\n".join(cursor.calls)
    assert "gold_wide_fact_current" in joined
    assert "gold_canonical_daily_current" in joined
    assert all(call.upper().startswith("CREATE OR REPLACE VIEW GOLD_") for call in cursor.calls)

    fetch_sql = getsource(PostgresRepository.fetch_gold_canonical_daily_current)
    assert "FROM gold_canonical_daily_current" in fetch_sql
    assert "energy_met_mu" in fetch_sql
    assert "evening_peak_demand_met_mw" in fetch_sql


def test_postgres_backfill_updates_current_observation_and_wide_facts() -> None:
    """Backfill stamps current rows by entity_key without snapshot replacement."""

    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []
            self.rowcount = 2

        def execute(self, query: str, params: object = None) -> None:
            self.calls.append((query, params))

    cursor = Cursor()
    counts = PostgresRepository._backfill_canonical_entity_ids(
        cursor,
        "11111111-1111-1111-1111-111111111111",
        ["SR:state:Karnatka", "SR:state:Karnataka"],
    )
    queries = "\n".join(query for query, _ in cursor.calls)

    assert counts["observations_updated"] == 2
    assert counts["wide_facts_updated"] == 2
    assert "UPDATE fact_observation" in queries
    assert "UPDATE fact_wide_daily AS fact" in queries
    assert "UPDATE fact_wide_daily_current AS current_truth" in queries
    assert "entity_key = ANY(%(entity_keys)s)" in queries
    assert "sys_to = 'infinity'" in queries
    assert "DELETE FROM fact_observation" not in queries
    assert "replace_complete_snapshots" not in queries


def test_audit_pending_identity_stage_is_fail_soft(tmp_path: Path) -> None:
    """Missing databases and pending issues do not fail daily orchestration."""

    missing = audit_pending_identity_adjudications(tmp_path / "missing.sqlite")
    assert missing["skipped"] is True
    assert missing["passed"] is True
    assert missing["pending"] == 0

    db_path = tmp_path / "identity.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_curated_sqlite_schema(conn)
    _queue_karnatka(conn)
    conn.close()

    payload = audit_pending_identity_adjudications(db_path)
    assert payload["skipped"] is False
    assert payload["passed"] is True
    assert payload["pending"] == 1
    assert payload["issues"][0]["raw_name"] == "Karnatka"


def test_apply_stage_skips_postgres_when_no_repository(tmp_path: Path) -> None:
    """CLI apply can persist SQLite without requiring a live Timescale DSN."""

    db_path = tmp_path / "apply.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_curated_sqlite_schema(conn)
    issue_id = _queue_karnatka(conn)
    conn.close()

    payload = apply_canonical_identity_adjudication(
        db_path,
        issue_id=issue_id,
        decision="approved",
    )
    assert payload["apply"]["decision"] == "approved"
    assert payload["postgres"]["skipped"] is True
    with sqlite3.connect(db_path) as conn:
        summary = identity_adjudication_summary(conn)
    assert summary["approved"] == 1


def test_adjudication_cli_is_a_thin_wrapper() -> None:
    """The operator script delegates to stage helpers instead of duplicating logic."""

    text = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "adjudicate_canonical_identity.py"
    ).read_text(encoding="utf-8")
    assert "apply_canonical_identity_adjudication" in text
    assert "audit_pending_identity_adjudications" in text
    assert "list-pending" in text
    assert "--publish-postgres" in text
