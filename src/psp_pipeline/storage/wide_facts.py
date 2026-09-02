"""Export wide curated facts and treat Postgres as the query-primary store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import inspect
import json
import logging
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from psp_pipeline.identity.canonical import CanonicalCatalog, resolve_observation_entity_id
from psp_pipeline.models.contracts import FactObservation


LOGGER = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class _VersionBucket:
    """Metrics collected from one report document/version of a grain."""

    observation: FactObservation
    metrics: dict[str, float]


class WideFactGrainConflictError(ValueError):
    """Raised when one grain has same-rank versions with conflicting metrics."""

    def __init__(self, grain_key: str, detail: str) -> None:
        self.grain_key = grain_key
        super().__init__(f"Wide-fact grain conflict for {grain_key}: {detail}")


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
    wide tables. When several report versions share a grain, the highest
    ``report_document_id`` wins, then the latest ``ingested_at``, then the
    highest ``version_no``. Same-rank versions with different metrics fail
    closed rather than last-iterable-wins.
    """

    grouped: dict[tuple[object, ...], _VersionBucket] = {}
    for observation in observations:
        if not observation.destination_table or not observation.source_id:
            continue
        valid_date = observation.valid_from.date()
        version_key = (
            observation.source_id,
            observation.destination_table,
            observation.entity_key,
            valid_date.isoformat(),
            observation.destination_key,
            observation.report_type,
            observation.source_region,
            observation.report_document_id,
            observation.content_hash,
        )
        metric_name = observation.destination_column or observation.metric_id
        measured = (
            observation.operational_value
            if observation.operational_value is not None
            else observation.settlement_value
        )
        if not metric_name or measured is None:
            continue
        metric_value = float(measured)
        bucket = grouped.get(version_key)
        if bucket is None:
            grouped[version_key] = _VersionBucket(
                observation=observation,
                metrics={str(metric_name): metric_value},
            )
            continue
        existing = bucket.metrics.get(str(metric_name))
        if existing is not None and existing != metric_value:
            grain_key = build_wide_grain_key(
                source_id=str(observation.source_id),
                destination_table=str(observation.destination_table),
                entity_key=str(observation.entity_key),
                valid_date=valid_date,
                destination_key=(
                    str(observation.destination_key) if observation.destination_key else None
                ),
            )
            raise WideFactGrainConflictError(
                grain_key,
                f"metric {metric_name!r} has {existing} and {metric_value} "
                "in the same document version",
            )
        bucket.metrics[str(metric_name)] = metric_value
        if _version_rank(observation) > _version_rank(bucket.observation):
            grouped[version_key] = _VersionBucket(
                observation=observation,
                metrics=bucket.metrics,
            )

    by_grain: dict[str, list[_VersionBucket]] = {}
    for version_key, bucket in grouped.items():
        if not bucket.metrics:
            continue
        source_id, destination_table, entity_key, valid_date_text, destination_key, _report_type, _region, _report_id, _hash = version_key
        grain_key = build_wide_grain_key(
            source_id=str(source_id),
            destination_table=str(destination_table),
            entity_key=str(entity_key),
            valid_date=date.fromisoformat(str(valid_date_text)),
            destination_key=str(destination_key) if destination_key else None,
        )
        by_grain.setdefault(grain_key, []).append(bucket)

    rows: list[WideFactRow] = []
    for grain_key, versions in sorted(by_grain.items()):
        selected = _select_authoritative_version(grain_key, versions)
        source_observation = selected.observation
        valid_date = source_observation.valid_from.date()
        content = str(source_observation.content_hash or "")
        canonical_id = source_observation.canonical_entity_id
        if catalog is not None:
            canonical_id = (
                resolve_observation_entity_id(catalog, source_observation.entity_key)
                or canonical_id
            )
        rows.append(
            WideFactRow(
                grain_key=grain_key,
                wide_fact_key=str(uuid5(NAMESPACE_URL, f"{grain_key}|{content}")),
                source_id=str(source_observation.source_id),
                destination_table=str(source_observation.destination_table),
                destination_key=(
                    str(source_observation.destination_key)
                    if source_observation.destination_key
                    else None
                ),
                report_document_id=(
                    int(source_observation.report_document_id)
                    if source_observation.report_document_id is not None
                    else None
                ),
                content_hash=content,
                valid_date=valid_date,
                entity_key=str(source_observation.entity_key),
                canonical_entity_id=canonical_id,
                report_type=str(source_observation.report_type),
                source_region=str(source_observation.source_region),
                metrics={key: float(value) for key, value in sorted(selected.metrics.items())},
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
    Only exported grains are compared: other dates already current in Postgres
    are outside this publish slice and are not treated as unexpected extras.
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
    expected_by_key = {row.grain_key: row for row in expected_rows}
    grain_keys = list(expected_by_key)
    actual_rows = _fetch_current_wide_facts(fetcher, grain_keys)
    actual_by_key = {
        str(row["grain_key"]): row
        for row in actual_rows
        if str(row.get("grain_key") or "") in expected_by_key
    }
    missing = tuple(sorted(set(expected_by_key) - set(actual_by_key)))
    unexpected = tuple(
        sorted(
            str(row["grain_key"])
            for row in actual_rows
            if str(row.get("grain_key") or "") not in expected_by_key
        )
    )
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
        "current_count": len(actual_by_key),
        "missing_grain_keys": missing,
        "unexpected_grain_keys": unexpected,
        "mismatched_grain_keys": tuple(sorted(set(mismatched))),
        "is_match": not missing and not mismatched,
        "skipped": False,
    }
    if not result["is_match"]:
        raise WideFactMirrorMismatchError(result)
    return result


def _fetch_current_wide_facts(
    fetcher: object,
    grain_keys: list[str],
) -> list[dict[str, object]]:
    """Call ``fetch_current_wide_facts``, scoping to exported keys when supported."""

    kwargs: dict[str, object] = {}
    try:
        signature = inspect.signature(fetcher)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        signature = None
    if signature is not None:
        parameters = signature.parameters
        if "grain_keys" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            kwargs["grain_keys"] = grain_keys
    try:
        return list(fetcher(**kwargs))  # type: ignore[misc, operator]
    except TypeError:
        return list(fetcher())  # type: ignore[operator]


def _select_authoritative_version(
    grain_key: str,
    versions: list[_VersionBucket],
) -> _VersionBucket:
    """Return the latest report/version for one grain, failing on same-rank conflicts."""

    ranked = sorted(versions, key=lambda bucket: _version_rank(bucket.observation), reverse=True)
    selected = ranked[0]
    for other in ranked[1:]:
        if other.metrics == selected.metrics:
            continue
        if _version_rank(other.observation) == _version_rank(selected.observation):
            raise WideFactGrainConflictError(
                grain_key,
                "same-rank report versions disagree on metrics",
            )
        LOGGER.warning(
            "wide_fact_correction grain=%s selected_report=%s discarded_report=%s",
            grain_key,
            selected.observation.report_document_id,
            other.observation.report_document_id,
        )
    return selected


def _version_rank(observation: FactObservation) -> tuple[int, datetime, int]:
    """Sort key for choosing one authoritative document/version per grain."""

    report_id = observation.report_document_id
    return (
        -1 if report_id is None else int(report_id),
        observation.ingested_at,
        int(observation.version_no),
    )
