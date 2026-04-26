from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List

from psp_pipeline.agents.base import BaseAgent
from psp_pipeline.models.contracts import FetchArtifact


class SchemaDriftAgent(BaseAgent):
    def __init__(self):
        super().__init__("schema_drift_agent")

    def run(self, artifacts: Iterable[FetchArtifact]) -> Dict[str, List[str]]:
        """
        Very lightweight drift detector for bootstrap:
        groups by source and detects extension/mime changes.
        """
        signatures: Dict[str, set[str]] = defaultdict(set)
        for artifact in artifacts:
            signatures[artifact.source_id].add(f"{Path(artifact.local_path).suffix}|{artifact.mime_type}")

        drifted = {k: sorted(v) for k, v in signatures.items() if len(v) > 1}
        if drifted:
            self.logger.warning("Schema drift-like pattern detected for %d sources", len(drifted))
        return drifted

