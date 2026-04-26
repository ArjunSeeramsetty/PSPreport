from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, TypeVar

from psp_pipeline.models.contracts import (
    FactObservation,
    FetchArtifact,
    LineageRecord,
    ReconciliationResult,
    SourceDefinition,
)

T = TypeVar("T")


def _encode_datetime(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _decode_datetime(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _serialize_dataclass(item: T) -> Dict[str, Any]:
    raw = asdict(item)
    return {k: _encode_datetime(v) for k, v in raw.items()}


def _deserialize_item(payload: Dict[str, Any], cls):
    return cls(**{k: _decode_datetime(v) for k, v in payload.items()})


def serialize_sources(items: Iterable[SourceDefinition]) -> List[Dict[str, Any]]:
    return [_serialize_dataclass(x) for x in items]


def deserialize_sources(items: Iterable[Dict[str, Any]]) -> List[SourceDefinition]:
    return [_deserialize_item(x, SourceDefinition) for x in items]


def serialize_artifacts(items: Iterable[FetchArtifact]) -> List[Dict[str, Any]]:
    return [_serialize_dataclass(x) for x in items]


def deserialize_artifacts(items: Iterable[Dict[str, Any]]) -> List[FetchArtifact]:
    return [_deserialize_item(x, FetchArtifact) for x in items]


def serialize_lineage(items: Iterable[LineageRecord]) -> List[Dict[str, Any]]:
    return [_serialize_dataclass(x) for x in items]


def deserialize_lineage(items: Iterable[Dict[str, Any]]) -> List[LineageRecord]:
    return [_deserialize_item(x, LineageRecord) for x in items]


def serialize_facts(items: Iterable[FactObservation]) -> List[Dict[str, Any]]:
    return [_serialize_dataclass(x) for x in items]


def deserialize_facts(items: Iterable[Dict[str, Any]]) -> List[FactObservation]:
    return [_deserialize_item(x, FactObservation) for x in items]


def serialize_reconciliation(items: Iterable[ReconciliationResult]) -> List[Dict[str, Any]]:
    return [_serialize_dataclass(x) for x in items]


def deserialize_reconciliation(items: Iterable[Dict[str, Any]]) -> List[ReconciliationResult]:
    return [_deserialize_item(x, ReconciliationResult) for x in items]

