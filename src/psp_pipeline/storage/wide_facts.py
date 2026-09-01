"""Export wide curated facts and treat Postgres as the query-primary store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from psp_pipeline.identity.canonical import CanonicalCatalog, resolve_observation_entity_id
from psp_pipeline.models.contracts import FactObservation


@dataclass(frozen=True)
class WideFactRow:
    """One destination-table grain with all numeric measures packed as JSON."""

    grain_key: str
    wide_fact_key: str
    source_id: str
    destination_table: str
    destination_key: str | None
    report_document_id: int | None
    content_hash: str
    valid_date: date
    entity_key: str
    canonical_entity_id: str | None
    report_type: str
    source_region: str
    metrics: dict[str, float]


def build_wide_grain_key(
    *,
    source_id: str,
    destination_table: str,
    entity_key: str,
    valid_date: date,
    destination_key: str | None,
) -> str:
    """Return a stable grain identifier for one wide fact row."""

    return json.dumps(
        {
            "destination_key": destination_key,
            "destination_table": destination_table,
            "entity_key": entity_key,
            "source_id": source_id,
            "valid_date": valid_date.isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def export_wide_facts(
    observations: Iterable[FactObservation],
    catalog: CanonicalCatalog | None = None,
) -> list[WideFactRow]:
    """Collapse long-form observations into destination-table grains.

    Rows without a curated destination table are skipped. Metrics use the
    destination column name when present so Postgres stays aligned with SQLite
    wide tables.
    """

    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    for observation in observations:
        if not observation.destination_table or not observation.source_id:
            continue
        valid_date = observation.valid_from.date()
        grain = (
            observation.source_id,
            observation.destination_table,
            observation.entity_key,
            valid_date.isoformat(),
            observation.destination_key,
            observation.report_document_id,
            observation.content_hash,
            observation.report_type,
            observation.source_region,
        )
        bucket = grouped.setdefault(
            grain,
            {"metrics": {}, "observation": observation},
        )
        metric_name = observation.destination_column or observation.metric_id
        measured = (
            observation.operational_value
            if observation.operational_value is not None
            else observation.settlement_value
        )
        if not metric_name or measured is None:
            continue
        metrics = bucket["metrics"]
        assert isinstance(metrics, dict)
        metrics[str(metric_name)] = float(measured)

    rows: list[WideFactRow] = []
    for grain, payload in grouped.items():
        metrics = payload["metrics"]
        assert isinstance(metrics, dict)
        if not metrics:
            continue
        source_id, destination_table, entity_key, valid_date_text, destination_key, report_id, content_hash, report_type, source_region = grain
        valid_date = date.fromisoformat(str(valid_date_text))
        grain_key = build_wide_grain_key(
            source_id=str(source_id),
            destination_table=str(destination_table),
            entity_key=str(entity_key),
            valid_date=valid_date,
            destination_key=str(destination_key) if destination_key else None,
        )
        content = str(content_hash or "")
        source_observation = payload["observation"]
        assert isinstance(source_observation, FactObservation)
        canonical_id = source_observation.canonical_entity_id
        if catalog is not None:
            canonical_id = (
                resolve_observation_entity_id(catalog, str(entity_key)) or canonical_id
            )
        rows.append(
            WideFactRow(
                grain_key=grain_key,
                wide_fact_key=str(uuid5(NAMESPACE_URL, f"{grain_key}|{content}")),
                source_id=str(source_id),
                destination_table=str(destination_table),
                destination_key=str(destination_key) if destination_key else None,
                report_document_id=int(report_id) if report_id is not None else None,
                content_hash=content,
                valid_date=valid_date,
                entity_key=str(entity_key),
                canonical_entity_id=canonical_id,
                report_type=str(report_type),
                source_region=str(source_region),
                metrics={key: float(value) for key, value in sorted(metrics.items())},
            )
        )
    return rows


def attach_canonical_entity_ids(
    observations: Iterable[FactObservation],
    catalog: CanonicalCatalog,
) -> list[FactObservation]:
    """Return observations with canonical_entity_id filled when the key is known."""

    annotated: list[FactObservation] = []
    for observation in observations:
        entity_id = resolve_observation_entity_id(catalog, observation.entity_key)
        if entity_id is None or observation.canonical_entity_id == entity_id:
            annotated.append(observation)
            continue
        annotated.append(
            FactObservation(
                **{
                    **observation.__dict__,
                    "canonical_entity_id": entity_id,
                }
            )
        )
    return annotated


class WideFactMirrorMismatchError(AssertionError):
    """Raised when published wide grains do not match Postgres current truth."""

    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        super().__init__(
            "Wide-fact current-truth mirror mismatch: "
            + json.dumps(result, sort_keys=True)
        )


def verify_exported_wide_fact_mirror(
    rows: Iterable[WideFactRow],
    repository: object,
) -> dict[str, object]:
    """Compare exported wide grains against the Postgres current-mirror query.

    The comparison is keyed by ``grain_key`` so a later correction with a new
    ``wide_fact_key`` is expected to replace the previous current metrics.
    """

    expected_rows = list(rows)
    fetcher = getattr(repository, "fetch_current_wide_facts", None)
    if not callable(fetcher):
        return {
            "exported_count": len(expected_rows),
            "current_count": 0,
            "skipped": True,
            "is_match": True,
        }
    actual_rows = list(fetcher())
    expected_by_key = {row.grain_key: row for row in expected_rows}
    actual_by_key = {str(row["grain_key"]): row for row in actual_rows}
    missing = tuple(sorted(set(expected_by_key) - set(actual_by_key)))
    unexpected = tuple(sorted(set(actual_by_key) - set(expected_by_key)))
    mismatched: list[str] = []
    for grain_key, expected in expected_by_key.items():
        actual = actual_by_key.get(grain_key)
        if actual is None:
            continue
        actual_metrics = {
            str(name): float(value)
            for name, value in dict(actual.get("metrics") or {}).items()
        }
        actual_entity = actual.get("canonical_entity_id") or None
        if actual_metrics != expected.metrics or actual_entity != expected.canonical_entity_id:
            mismatched.append(grain_key)
    result = {
        "exported_count": len(expected_rows),
        "current_count": len(actual_rows),
        "missing_grain_keys": missing,
        "unexpected_grain_keys": unexpected,
        "mismatched_grain_keys": tuple(sorted(set(mismatched))),
        "is_match": not missing and not unexpected and not mismatched,
        "skipped": False,
    }
    if not result["is_match"]:
        raise WideFactMirrorMismatchError(result)
    return result
