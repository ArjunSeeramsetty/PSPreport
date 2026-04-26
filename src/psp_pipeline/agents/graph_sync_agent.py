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
        for fact in facts:
            self.repo.merge_observation_topology(
                entity_key=fact.entity_key,
                report_type=fact.report_type,
                metric_name=fact.metric_name,
                source_region=fact.source_region,
                timeseries_uuid=fact.timeseries_uuid,
                time_block=fact.time_block,
            )
