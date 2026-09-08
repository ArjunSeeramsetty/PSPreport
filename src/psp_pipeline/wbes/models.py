"""WBES schedule-matrix domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Mapping


class EntityArchetype(str, Enum):
    """Physical dispatch participant in a WBES matrix."""

    ISGS = "isgs"
    BENEFICIARY = "beneficiary"
    REGIONAL_TIE = "regional_tie"


class MatrixKind(str, Enum):
    """Top-level WBES report family."""

    ENTITLEMENT = "entitlement"
    REQUISITION = "requisition"
    NET_SCHEDULE = "net_schedule"


class ScheduleComponent(str, Enum):
    """Net-schedule slices published alongside the total."""

    INJECTION = "injection"
    DRAWAL = "drawal"
    BILATERAL = "bilateral"
    COLLECTIVE = "collective"


FINAL_REVISION_VERSION = 10_000


def parse_revision_label(label: str) -> tuple[str, int]:
    """Normalize ``R0`` / ``R_final`` labels to a sortable version number."""

    raw = label.strip()
    compact = raw.replace(" ", "").replace("_", "").lower()
    if compact in {"rfinal", "final"}:
        return "Rfinal", FINAL_REVISION_VERSION
    if compact.startswith("r") and compact[1:].isdigit():
        version_no = int(compact[1:])
        return f"R{version_no}", version_no
    if compact.isdigit():
        version_no = int(compact)
        return f"R{version_no}", version_no
    raise ValueError(f"Unsupported WBES revision label: {label}")


def entity_key(
    *,
    region: str,
    archetype: EntityArchetype,
    entity_id: str,
    counterparty_archetype: EntityArchetype | None = None,
    counterparty_id: str | None = None,
) -> str:
    """Return a stable dispatch identity, including pair grain when present."""

    key = f"WBES:{region}:{archetype.value}:{entity_id}"
    if counterparty_id:
        counterpart = counterparty_archetype or EntityArchetype.BENEFICIARY
        key = f"{key}:{counterpart.value}:{counterparty_id}"
    return key


def metric_name(kind: MatrixKind, component: ScheduleComponent | None) -> str:
    """Return the long-form metric stored with each block cell."""

    if kind is MatrixKind.NET_SCHEDULE and component is not None:
        return f"wbes.net_schedule.{component.value}.mw"
    return f"wbes.{kind.value}.mw"


@dataclass(frozen=True)
class WbesMatrixRow:
    """One entity (or entity-pair) across a full day of blocks."""

    entity_id: str
    entity_name: str
    archetype: EntityArchetype
    values_mw: tuple[float, ...]
    counterparty_id: str | None = None
    counterparty_name: str | None = None
    counterparty_archetype: EntityArchetype | None = None


@dataclass(frozen=True)
class WbesMatrix:
    """One named matrix inside a revision document."""

    kind: MatrixKind
    rows: tuple[WbesMatrixRow, ...]
    component: ScheduleComponent | None = None


@dataclass(frozen=True)
class WbesRevisionDocument:
    """One published revision of the day's schedule matrices."""

    schedule_date: date
    revision_label: str
    revision_no: int
    source_region: str
    source_id: str
    block_count: int
    block_minutes: int
    matrices: tuple[WbesMatrix, ...]
    published_at: datetime | None = None
    content_hash: str = ""
    source_url: str = ""
    raw_path: str = ""


@dataclass(frozen=True)
class WbesBlockFact:
    """One bitemporal MW cell at (entity, metric, block, revision)."""

    series_key: str
    revision_uuid: str
    entity_key: str
    archetype: str
    matrix_kind: str
    metric_name: str
    time_block: str
    block_no: int
    operational_value: float
    source_region: str
    source_id: str
    valid_from: datetime
    valid_to: datetime
    version_no: int
    revision_label: str
    ingested_at: datetime
    content_hash: str
    counterparty_key: str | None = None
    schedule_component: str | None = None


@dataclass(frozen=True)
class ProbeResult:
    """Classified outcome of one unauthenticated WBES HTTP probe."""

    url: str
    status_code: int | None
    classification: str
    content_type: str | None = None
    final_url: str | None = None
    byte_count: int = 0
    error: str | None = None
    json_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class WbesRunSummary:
    """Operator-facing outcome of one isolated WBES pipeline run."""

    status: str
    run_id: str
    schedule_dates: tuple[str, ...] = ()
    documents_parsed: int = 0
    facts_upserted: int = 0
    facts_deduplicated: int = 0
    drop_files: int = 0
    live_fetches: int = 0
    probes: tuple[ProbeResult, ...] = ()
    skipped_checkpoints: int = 0
    recon_imbalances: int = 0
    timescale_inserted: int = 0
    errors: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready payload for CLI and DAG XCom."""

        return {
            "status": self.status,
            "run_id": self.run_id,
            "schedule_dates": list(self.schedule_dates),
            "documents_parsed": self.documents_parsed,
            "facts_upserted": self.facts_upserted,
            "facts_deduplicated": self.facts_deduplicated,
            "drop_files": self.drop_files,
            "live_fetches": self.live_fetches,
            "probes": [
                {
                    "url": probe.url,
                    "status_code": probe.status_code,
                    "classification": probe.classification,
                    "content_type": probe.content_type,
                    "final_url": probe.final_url,
                    "byte_count": probe.byte_count,
                    "error": probe.error,
                    "json_keys": list(probe.json_keys),
                }
                for probe in self.probes
            ],
            "skipped_checkpoints": self.skipped_checkpoints,
            "recon_imbalances": self.recon_imbalances,
            "timescale_inserted": self.timescale_inserted,
            "errors": list(self.errors),
            "details": dict(self.details),
        }
