from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List
from uuid import uuid4

from psp_pipeline.agents.base import BaseAgent
from psp_pipeline.models.contracts import FactObservation, FetchArtifact, LineageRecord


class ParserAgent(BaseAgent):
    """
    Adapter layer:
    - Keeps existing parser modules untouched.
    - Emits normalized lineage + minimal fact observations for Bronze staging.
    """

    parser_version = "v1.0-public-bootstrap"

    def __init__(self):
        super().__init__("parser_agent")

    def run(self, run_id: str, artifacts: Iterable[FetchArtifact]) -> tuple[List[LineageRecord], List[FactObservation]]:
        lineage: List[LineageRecord] = []
        facts: List[FactObservation] = []
        now = datetime.now(timezone.utc)

        for artifact in artifacts:
            report_type = _infer_report_type(artifact.local_path)
            source_region = _infer_region_from_source(artifact.source_id)
            lineage.append(
                LineageRecord(
                    run_id=run_id,
                    source_id=artifact.source_id,
                    source_url=artifact.source_url,
                    content_hash=artifact.content_hash,
                    fetched_at=artifact.fetched_at,
                    parser_version=self.parser_version,
                    extraction_confidence=0.5,
                    report_type=report_type,
                    source_region=source_region,
                    valid_from=now,
                    valid_to=None,
                    version_no=1,
                    raw_object_key=f"{artifact.source_id}/{Path(artifact.local_path).name}",
                )
            )

            # Minimal placeholder fact enables end-to-end pipeline smoke tests.
            facts.append(
                FactObservation(
                    entity_key=f"{source_region}:{artifact.source_id}",
                    metric_name="raw_artifact_count",
                    time_block=None,
                    operational_value=1.0,
                    settlement_value=None,
                    variance_pct=None,
                    report_type=report_type,
                    source_region=source_region,
                    valid_from=now,
                    valid_to=None,
                    version_no=1,
                    ingested_at=now,
                    timeseries_uuid=str(uuid4()),
                )
            )

        return lineage, facts


def _infer_report_type(local_path: str) -> str:
    name = Path(local_path).name.lower()
    if "dsm" in name:
        return "dsm"
    if "rea" in name:
        return "rea"
    if "outage" in name or "trip" in name:
        return "outage"
    if "monthly" in name:
        return "monthly_psp"
    if "weekly" in name:
        return "weekly_psp"
    return "daily_psp"


def _infer_region_from_source(source_id: str) -> str:
    sid = source_id.lower()
    if "ner" in sid:
        return "NER"
    if "sr" in sid:
        return "SR"
    if "nr" in sid:
        return "NR"
    if "wr" in sid:
        return "WR"
    if "er" in sid:
        return "ER"
    return "NATIONAL"

