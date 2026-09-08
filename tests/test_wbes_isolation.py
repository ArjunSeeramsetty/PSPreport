"""WBES must not leak into public PSP ingestion, Timescale greenfield, or Neo4j."""

from pathlib import Path

from psp_pipeline.models.source_registry import filter_sources, load_default_sources
from psp_pipeline.storage.timescale_bootstrap import default_greenfield_schema_path
from psp_pipeline.wbes.timescale_store import default_wbes_schema_path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_public_source_filter_still_excludes_wbes() -> None:
    filtered = filter_sources(load_default_sources(), include_controlled=False)
    assert not any(source.source_id == "wbes_national" for source in filtered)


def test_public_ingestion_script_keeps_controlled_sources_off() -> None:
    text = _read(ROOT / "scripts" / "run_public_ingestion.py")
    assert "include_controlled=False" in text
    assert "psp_pipeline.wbes" not in text


def test_public_dag_does_not_import_or_trigger_wbes() -> None:
    dag_text = _read(ROOT / "dags" / "psp_daily_pipeline.py")
    assert "wbes_schedule" not in dag_text
    assert "psp_pipeline.wbes" not in dag_text
    assert "include_controlled=False" in dag_text


def test_wbes_dag_is_paused_and_isolated() -> None:
    dag_text = _read(ROOT / "dags" / "wbes_schedule_pipeline.py")
    assert "is_paused_upon_creation=True" in dag_text
    assert "dag_id=\"wbes_schedule_ingestion\"" in dag_text
    assert "psp_daily_public_ingestion" not in dag_text
    assert "sync_graph" not in dag_text
    assert "Neo4j" not in dag_text


def test_wbes_package_does_not_reference_neo4j() -> None:
    package = ROOT / "src" / "psp_pipeline" / "wbes"
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import neo4j" not in text
        assert "from neo4j" not in text
        assert "GraphSyncAgent" not in text
        assert "sync_graph" not in text


def test_greenfield_timescale_schema_does_not_include_wbes_tables() -> None:
    greenfield = _read(default_greenfield_schema_path())
    assert "fact_wbes_block" not in greenfield
    wbes_sql = _read(default_wbes_schema_path())
    assert "CREATE TABLE IF NOT EXISTS fact_wbes_block" in wbes_sql
    assert "create_hypertable('fact_wbes_block'" in wbes_sql


def test_graph_sync_agent_still_drops_block_level_facts() -> None:
    from datetime import datetime, timezone

    from psp_pipeline.agents.graph_sync_agent import GraphSyncAgent
    from psp_pipeline.models.contracts import FactObservation

    fact = FactObservation(
        entity_key="WBES:WR:isgs:SYNTH-ISGS-1",
        metric_name="wbes.entitlement.mw",
        time_block="00:15",
        operational_value=1.0,
        settlement_value=None,
        variance_pct=None,
        report_type="wbes_schedule",
        source_region="WR",
        valid_from=datetime(2026, 9, 1, tzinfo=timezone.utc),
        valid_to=None,
        version_no=0,
        ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        timeseries_uuid="wbes-test",
    )

    class FakeRepo:
        def __init__(self) -> None:
            self.calls = 0

        def merge_observation_topologies(self, payload):
            self.calls += 1

    repo = FakeRepo()
    GraphSyncAgent(repo).run([fact])
    assert repo.calls == 0
