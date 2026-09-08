"""Isolated WBES pipeline: drop ingest, checkpoints, no graph writes."""

from datetime import date
from pathlib import Path

import httpx

from psp_pipeline.wbes.client import WbesClient
from psp_pipeline.wbes.facts import expand_revision_facts
from psp_pipeline.wbes.pipeline import run_wbes_schedule, settings_with_overrides
from psp_pipeline.wbes.settings import load_wbes_settings
from psp_pipeline.wbes.sqlite_store import WbesSqliteStore
from wbes_support import synthetic_document, write_json


def _enabled_settings(tmp_path: Path, *, live: bool = False):
    root = Path(__file__).resolve().parents[1]
    return settings_with_overrides(
        load_wbes_settings(tmp_path),
        enabled=True,
        allow_live_network=live,
        write_timescale=False,
        project_root=tmp_path,
        catalog_path=root / "config" / "wbes_sources.yaml",
        raw_dir=tmp_path / "raw",
        drop_dir=tmp_path / "drop",
        sqlite_path=tmp_path / "wbes.sqlite",
    )


def test_disabled_pipeline_does_not_create_sqlite(tmp_path: Path) -> None:
    settings = settings_with_overrides(load_wbes_settings(tmp_path), enabled=False)
    summary = run_wbes_schedule(settings, start_date=date(2026, 9, 1))
    assert summary.status == "disabled"
    assert not (tmp_path / "wbes.sqlite").exists()


def test_drop_folder_ingests_r0_without_network(tmp_path: Path) -> None:
    settings = _enabled_settings(tmp_path)
    write_json(settings.drop_dir / "r0.json", synthetic_document())
    summary = run_wbes_schedule(settings, start_date=date(2026, 9, 1), end_date=date(2026, 9, 1))
    assert summary.status == "success"
    assert summary.documents_parsed == 1
    assert summary.live_fetches == 0
    assert summary.facts_upserted > 96
    store = WbesSqliteStore(settings.sqlite_path)
    with store.connect() as conn:
        archetypes = {
            row["archetype"]
            for row in conn.execute("SELECT DISTINCT archetype FROM dim_wbes_entity")
        }
        current_count = conn.execute("SELECT COUNT(*) AS n FROM fact_wbes_block_current").fetchone()["n"]
    assert archetypes == {"isgs", "beneficiary", "regional_tie"}
    assert current_count == summary.facts_upserted


def test_checkpoint_skips_already_persisted_revision(tmp_path: Path) -> None:
    settings = _enabled_settings(tmp_path)
    write_json(settings.drop_dir / "r0.json", synthetic_document())
    first = run_wbes_schedule(settings, start_date=date(2026, 9, 1))
    second = run_wbes_schedule(settings, start_date=date(2026, 9, 1))
    assert first.facts_upserted > 0
    assert second.skipped_checkpoints == 1
    assert second.facts_upserted == 0


def test_public_json_probe_is_copied_into_drop_and_parsed(tmp_path: Path) -> None:
    settings = _enabled_settings(tmp_path, live=True)
    payload = synthetic_document()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/schedule.json"):
            import json

            body = json.dumps(payload).encode("utf-8")
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "application/json"},
                content=body,
            )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            content=b"<html>Login</html>",
        )

    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        """
sources:
  - id: wbes_national
    region: ALL
    landing_url: https://example.test/schedule.json
    access_mode: controlled
    matrices: [entitlement, requisition, net_schedule]
    components: [injection, drawal, bilateral, collective]
    probe_urls:
      - https://example.test/schedule.json
""".strip()
        + "\n",
        encoding="utf-8",
    )
    settings = settings_with_overrides(settings, catalog_path=catalog_path)
    client = WbesClient(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )
    summary = run_wbes_schedule(
        settings,
        start_date=date(2026, 9, 1),
        client=client,
    )
    assert any(probe.classification == "public_json" for probe in summary.probes)
    assert summary.live_fetches >= 1
    assert summary.documents_parsed == 1
    assert summary.facts_upserted > 0


def test_expanded_facts_always_have_time_blocks() -> None:
    from psp_pipeline.wbes.parser import parse_wbes_payload

    document = parse_wbes_payload(
        synthetic_document(),
        source_id="wbes_national",
        source_region="WR",
        block_count=96,
        block_minutes=15,
        content_hash="synthetic",
    )
    facts = expand_revision_facts(document)
    assert facts
    assert all(fact.time_block for fact in facts)
    assert all(1 <= fact.block_no <= 96 for fact in facts)


def test_timescale_flag_uses_injected_store_not_fact_observation(tmp_path: Path) -> None:
    settings = settings_with_overrides(_enabled_settings(tmp_path), write_timescale=True)
    write_json(settings.drop_dir / "r0.json", synthetic_document())

    class FakeTimescale:
        def __init__(self) -> None:
            self.received = 0

        def upsert_facts(self, facts):
            rows = list(facts)
            self.received = len(rows)
            assert all(row.time_block for row in rows)
            return len(rows)

    fake = FakeTimescale()
    summary = run_wbes_schedule(
        settings,
        start_date=date(2026, 9, 1),
        timescale_store=fake,
    )
    assert summary.timescale_inserted == fake.received
    assert fake.received == summary.facts_upserted
