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
            self.repo.merge_entity(
                entity_key=fact.entity_key,
                entity_type=fact.report_type,
                timeseries_uuid=fact.timeseries_uuid,
            )

