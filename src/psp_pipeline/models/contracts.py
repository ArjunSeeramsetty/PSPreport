from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    domain: str
    region: str
    report_family: str
    url: str
    fmt: str
    cadence: str
    access_mode: str = "public"
    notes: str = ""


@dataclass(frozen=True)
class FetchArtifact:
    source_id: str
    source_url: str
    content_hash: str
    fetched_at: datetime
    mime_type: str
    local_path: str
    status_code: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LineageRecord:
    run_id: str
    source_id: str
    source_url: str
    content_hash: str
    fetched_at: datetime
    parser_version: str
    extraction_confidence: float
    report_type: str
    source_region: str
    valid_from: datetime
    valid_to: Optional[datetime]
    version_no: int
    raw_object_key: str


@dataclass(frozen=True)
class FactObservation:
    entity_key: str
    metric_name: str
    time_block: Optional[str]
    operational_value: Optional[float]
    settlement_value: Optional[float]
    variance_pct: Optional[float]
    report_type: str
    source_region: str
    valid_from: datetime
    valid_to: Optional[datetime]
    version_no: int
    ingested_at: datetime
    timeseries_uuid: str

