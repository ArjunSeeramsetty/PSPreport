"""Verify an exported curated observation set against Timescale current truth."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isclose
from typing import Iterable

try:
    import psycopg
except ImportError:
    psycopg = None  # type: ignore[assignment]

from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.storage.observation_identity import build_series_key


@dataclass(frozen=True)
class CurrentMirrorRow:
    """One current Timescale observation needed for mirror verification."""

    series_key: str
    timeseries_uuid: str
    metric_id: str | None
    operational_value: float | None
    settlement_value: float | None


@dataclass(frozen=True)
class TimescaleMirrorReconciliation:
    """Comparison result between one SQLite export and Timescale current truth."""

    exported_count: int
    current_count: int
    missing_series_keys: tuple[str, ...]
    unexpected_series_keys: tuple[str, ...]
    mismatched_series_keys: tuple[str, ...]

    @property
    def is_match(self) -> bool:
        """Return whether every exported observation has an identical current mirror."""

        return not (
            self.missing_series_keys
            or self.unexpected_series_keys
            or self.mismatched_series_keys
        )

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready mirror result for pilot diagnostics."""

        payload = asdict(self)
        payload["is_match"] = self.is_match
        return payload


def reconcile_timescale_current_mirror(
    observations: Iterable[FactObservation],
    current_rows: Iterable[CurrentMirrorRow],
) -> TimescaleMirrorReconciliation:
    """Compare an exact curated export with Timescale's current-version rows.

    The comparison uses the stable series key rather than row counts alone.
    This makes the pilot sensitive to missing records, wrong metric identities,
    wrong revision UUIDs, and numeric value drift.
    """

    expected = {_series_key(observation): observation for observation in observations}
    actual = {row.series_key: row for row in current_rows}
    expected_keys = set(expected)
    actual_keys = set(actual)

    mismatched = []
    for series_key in sorted(expected_keys & actual_keys):
        if not _matches(expected[series_key], actual[series_key]):
            mismatched.append(series_key)
    return TimescaleMirrorReconciliation(
        exported_count=len(expected),
        current_count=len(actual),
        missing_series_keys=tuple(sorted(expected_keys - actual_keys)),
        unexpected_series_keys=tuple(sorted(actual_keys - expected_keys)),
        mismatched_series_keys=tuple(mismatched),
    )


def fetch_current_timescale_rows(
    postgres_dsn: str,
    observations: Iterable[FactObservation],
) -> list[CurrentMirrorRow]:
    """Fetch Timescale current truth for exactly the supplied observation grains.

    Raises ``RuntimeError`` when the optional PostgreSQL driver is unavailable.
    It deliberately queries through ``fact_observation_current`` so retired
    revisions cannot satisfy a pilot reconciliation.
    """

    if psycopg is None:
        raise RuntimeError("The 'psycopg' package is required for mirror verification.")
    series_keys = sorted({_series_key(observation) for observation in observations})
    if not series_keys:
        return []
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT observation.series_key, observation.timeseries_uuid,
                       observation.metric_id, observation.operational_value,
                       observation.settlement_value
                FROM fact_observation_current AS current_truth
                JOIN fact_observation AS observation
                  ON observation.timeseries_uuid = current_truth.timeseries_uuid
                WHERE observation.series_key = ANY(%s)
                """,
                (series_keys,),
            )
            return [
                CurrentMirrorRow(
                    series_key=str(row[0]),
                    timeseries_uuid=str(row[1]),
                    metric_id=str(row[2]) if row[2] is not None else None,
                    operational_value=float(row[3]) if row[3] is not None else None,
                    settlement_value=float(row[4]) if row[4] is not None else None,
                )
                for row in cursor.fetchall()
            ]


def _series_key(observation: FactObservation) -> str:
    """Return the repository's stable logical-grain key for an observation."""

    if observation.series_key:
        return observation.series_key
    return build_series_key(
        entity_key=observation.entity_key,
        metric_name=observation.metric_name,
        time_block=observation.time_block,
        report_type=observation.report_type,
        source_region=observation.source_region,
        valid_from=observation.valid_from.isoformat(),
        valid_to=observation.valid_to.isoformat() if observation.valid_to else None,
    )


def _matches(expected: FactObservation, actual: CurrentMirrorRow) -> bool:
    """Compare identity and nullable numeric values without float-string drift."""

    return (
        actual.timeseries_uuid == expected.timeseries_uuid
        and actual.metric_id == expected.metric_id
        and _same_number(actual.operational_value, expected.operational_value)
        and _same_number(actual.settlement_value, expected.settlement_value)
    )


def _same_number(left: float | None, right: float | None) -> bool:
    """Compare nullable values using a strict engineering tolerance."""

    if left is None or right is None:
        return left is right
    return isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
