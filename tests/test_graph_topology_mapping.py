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


def test_graph_sync_agent_prefers_batch_topology_merge():
    """Use the lock-safe repository batch API when it is available."""

    now = datetime.now(timezone.utc)
    fact = FactObservation(
        entity_key="SR:state:IN-AP",
        metric_name="state_demand_met_mw",
        time_block=None,
        operational_value=1.0,
        settlement_value=None,
        variance_pct=None,
        report_type="srldc_daily_psp",
        source_region="SR",
        valid_from=now,
        valid_to=None,
        version_no=1,
        ingested_at=now,
        timeseries_uuid="uuid-1",
    )

    class FakeRepo:
        def __init__(self):
            self.payload = []
            self.value_payload = []

        def merge_observation_topologies(self, payload):
            self.payload = payload

        def merge_daily_observation_values(self, payload):
            self.value_payload = payload

    repo = FakeRepo()
    GraphSyncAgent(repo).run([fact])

    assert repo.payload[0]["entity_key"] == "SR:state:IN-AP"
    assert repo.payload[0]["timeseries_uuid"] == "uuid-1"
    assert repo.payload[0]["metric_id"] is None
    assert repo.payload[0]["operational_value"] == 1.0
    assert repo.payload[0]["valid_from"] == now
    assert repo.value_payload == repo.payload


def test_graph_sync_agent_keeps_subdaily_telemetry_out_of_neo4j() -> None:
    """High-volume quarter-hour facts remain in Timescale rather than Neo4j."""

    now = datetime.now(timezone.utc)
    snapshot = FactObservation(
        entity_key="NLDC:all-india-grid",
        metric_name="nldc.FactNLDC15MinuteGridSnapshot.DemandMetMW",
        time_block="00:15",
        operational_value=225158.0,
        settlement_value=None,
        variance_pct=None,
        report_type="nldc_daily_psp",
        source_region="ALL",
        valid_from=now,
        valid_to=now,
        version_no=1,
        ingested_at=now,
        timeseries_uuid="snapshot-uuid",
    )

    class FakeRepo:
        def __init__(self):
            self.calls = 0

        def merge_observation_topologies(self, payload):
            self.calls += 1

    repo = FakeRepo()
    GraphSyncAgent(repo).run([snapshot])

    assert repo.calls == 0


def test_observation_version_query_preserves_revision_history() -> None:
    """Graph value nodes are UUID-scoped and only close older open versions."""

    from psp_pipeline.storage.neo4j_repo import _OBSERVATION_VERSION_QUERY

    assert "ObservationVersion {timeseries_uuid: row.timeseries_uuid}" in _OBSERVATION_VERSION_QUERY
    assert "previous.sys_to = 'infinity'" in _OBSERVATION_VERSION_QUERY
    assert "previous.ingested_at < datetime(row.ingested_at)" in _OBSERVATION_VERSION_QUERY
    assert "MERGE (ts)-[:HAS_VERSION]->(version)" in _OBSERVATION_VERSION_QUERY


def test_graph_retirement_query_closes_only_open_measurement_versions() -> None:
    """Timescale snapshot retirement is reflected without deleting graph history."""

    from psp_pipeline.storage.neo4j_repo import _RETIRE_OBSERVATION_VERSION_QUERY

    assert "MATCH (version:ObservationVersion" in _RETIRE_OBSERVATION_VERSION_QUERY
    assert "WHERE version.sys_to = 'infinity'" in _RETIRE_OBSERVATION_VERSION_QUERY
    assert "SET version.sys_to = datetime(row.retired_at)" in _RETIRE_OBSERVATION_VERSION_QUERY
