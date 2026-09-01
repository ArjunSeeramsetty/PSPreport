"""Bitemporal SQLite persistence for WBES revisions."""

from datetime import datetime, timezone
from pathlib import Path

from psp_pipeline.wbes.facts import expand_revision_facts
from psp_pipeline.wbes.parser import parse_wbes_payload
from psp_pipeline.wbes.sqlite_store import WbesSqliteStore
from wbes_support import synthetic_document


def _facts(revision_label: str, injection_base: float):
    payload = synthetic_document(
        revision_label=revision_label,
        injection_base=injection_base,
        requisition_split=(injection_base * 0.6, injection_base * 0.4),
    )
    document = parse_wbes_payload(
        payload,
        source_id="wbes_national",
        source_region="WR",
        block_count=96,
        block_minutes=15,
        content_hash=f"hash-{revision_label}-{injection_base}",
    )
    return document, expand_revision_facts(
        document, ingested_at=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    )


def test_r1_closes_r0_and_becomes_current_truth(tmp_path: Path) -> None:
    store = WbesSqliteStore(tmp_path / "wbes.sqlite")
    r0_doc, r0_facts = _facts("R0", 200.0)
    r1_doc, r1_facts = _facts("R1", 180.0)
    inserted, deduped = store.upsert_facts(r0_facts)
    assert inserted == len(r0_facts)
    assert deduped == 0
    store.upsert_facts(r1_facts)

    sample = r0_facts[0]
    current = store.current_value(sample.series_key)
    r1_match = next(fact for fact in r1_facts if fact.series_key == sample.series_key)
    assert current == r1_match.operational_value

    with store.connect() as conn:
        history = conn.execute(
            """
            SELECT revision_label, sys_to
            FROM fact_wbes_block
            WHERE series_key = ?
            ORDER BY version_no
            """,
            (sample.series_key,),
        ).fetchall()
    assert [row["revision_label"] for row in history] == ["R0", "R1"]
    assert history[0]["sys_to"] != "infinity"
    assert history[1]["sys_to"] == "infinity"


def test_duplicate_revision_is_idempotent(tmp_path: Path) -> None:
    store = WbesSqliteStore(tmp_path / "wbes.sqlite")
    _, facts = _facts("R0", 200.0)
    first, _ = store.upsert_facts(facts)
    second, deduped = store.upsert_facts(facts)
    assert first == len(facts)
    assert second == 0
    assert deduped == len(facts)
