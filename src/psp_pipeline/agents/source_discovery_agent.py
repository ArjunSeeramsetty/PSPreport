from __future__ import annotations

from typing import List

from psp_pipeline.agents.base import BaseAgent
from psp_pipeline.models.contracts import SourceDefinition
from psp_pipeline.models.source_registry import filter_sources, load_default_sources


class SourceDiscoveryAgent(BaseAgent):
    def __init__(self):
        super().__init__("source_discovery_agent")

    def run(self, include_controlled: bool = False) -> List[SourceDefinition]:
        sources = load_default_sources()
        selected = filter_sources(sources, include_controlled=include_controlled)
        self.logger.info("Discovered %d source definitions", len(selected))
        return selected

