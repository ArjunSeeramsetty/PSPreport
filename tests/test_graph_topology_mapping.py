from datetime import datetime, timezone

from psp_pipeline.agents.graph_sync_agent import GraphSyncAgent
from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.storage.neo4j_repo import _split_entity_key


def test_split_entity_key_region_and_entity():
    region, entity = _split_entity_key("SR:srldc_daily_reports")
    assert region == "SR"
    assert entity == "srldc_daily_reports"


def test_split_entity_key_fallbacks():
    region, entity = _split_entity_key("entity_without_region")
    assert region == "NATIONAL"
    assert entity == "entity_without_region"


def test_graph_sync_agent_calls_topology_merge():
    now = datetime.now(timezone.utc)
    fact = FactObservation(
        entity_key="SR:srldc_daily_reports",
        metric_name="raw_artifact_count",
        time_block=None,
        operational_value=1.0,
        settlement_value=None,
        variance_pct=None,
        report_type="daily_psp",
        source_region="SR",
        valid_from=now,
        valid_to=None,
        version_no=1,
        ingested_at=now,
        timeseries_uuid="uuid-1",
    )

    class FakeRepo:
        def __init__(self):
            self.calls = 0

        def merge_observation_topology(self, **kwargs):
            self.calls += 1
            assert kwargs["entity_key"] == "SR:srldc_daily_reports"

    repo = FakeRepo()
    GraphSyncAgent(repo).run([fact])
    assert repo.calls == 1

