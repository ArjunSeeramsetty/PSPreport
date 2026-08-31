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
    series_key: str | None = None
    content_hash: str | None = None
    report_document_id: int | None = None
    source_id: str | None = None
    destination_table: str | None = None
    destination_key: str | None = None
    destination_column: str | None = None
    metric_id: str | None = None


@dataclass(frozen=True)
class ObservationLineage:
    """Cell-level provenance for one exported time-series observation."""

    lineage_key: str
    timeseries_uuid: str
    source_id: str
    report_document_id: int
    content_hash: str
    destination_table: str
    destination_key: str
    destination_column: str
    raw_kind: str
    raw_item_id: int
    page_no: int | None
    table_no: int | None
    row_no: int | None
    col_no: int | None
    confidence: float
    extraction_method: str


@dataclass(frozen=True)
class PipelineRun:
    """Persisted operational outcome for one orchestration execution."""

    run_id: str
    dag_id: str
    started_at: datetime
    completed_at: datetime
    status: str
    sources_requested: int
    sources_completed: int
    sources_failed: int
    observations_exported: int
    observations_inserted: int
    observations_deduplicated: int


@dataclass(frozen=True)
class ReconciliationResult:
    run_id: str
    entity_key: str
    metric_name: str
    time_block: Optional[str]
    variance_pct: Optional[float]
    source_region: str
    computed_at: datetime
