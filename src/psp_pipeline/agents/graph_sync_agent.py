from __future__ import annotations

from typing import Iterable

from psp_pipeline.agents.base import BaseAgent
from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.storage.neo4j_repo import Neo4jRepository


class GraphSyncAgent(BaseAgent):
    def __init__(self, repo: Neo4jRepository):
        super().__init__("graph_sync_agent")
        self.repo = repo

    def run(self, facts: Iterable[FactObservation]) -> None:
        payload = [
            {
                "entity_key": fact.entity_key,
                "report_type": fact.report_type,
                "metric_name": fact.metric_name,
                "source_region": fact.source_region,
                "timeseries_uuid": fact.timeseries_uuid,
                "time_block": fact.time_block,
            }
            for fact in facts
        ]
        if not payload:
            return
        merge_batch = getattr(self.repo, "merge_observation_topologies", None)
        if callable(merge_batch):
            merge_batch(payload)
            return
        for item in payload:
            self.repo.merge_observation_topology(**item)
