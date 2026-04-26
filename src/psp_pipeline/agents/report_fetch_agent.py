from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from psp_pipeline.agents.base import BaseAgent
from psp_pipeline.connectors.http_client import HttpFetcher
from psp_pipeline.models.contracts import FetchArtifact, SourceDefinition


class ReportFetchAgent(BaseAgent):
    def __init__(
        self,
        raw_dir: Path,
        *,
        max_attempts: int = 3,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 12.0,
        jitter_seconds: float = 0.5,
    ):
        super().__init__("report_fetch_agent")
        self.raw_dir = raw_dir
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.jitter_seconds = jitter_seconds

    def run(self, sources: Iterable[SourceDefinition]) -> List[FetchArtifact]:
        artifacts: List[FetchArtifact] = []
        with HttpFetcher(
            max_attempts=self.max_attempts,
            base_delay_seconds=self.base_delay_seconds,
            max_delay_seconds=self.max_delay_seconds,
            jitter_seconds=self.jitter_seconds,
        ) as fetcher:
            for source in sources:
                try:
                    artifact = fetcher.fetch(source, self.raw_dir / source.source_id)
                    if artifact:
                        artifacts.append(artifact)
                        self.logger.info("Fetched %s", artifact.source_url)
                    else:
                        self.logger.warning("Fetch failed: %s", source.url)
                except Exception as exc:  # pragma: no cover - runtime behavior
                    self.logger.exception("Fetch error for %s: %s", source.url, exc)
        return artifacts
