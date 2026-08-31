"""Load portable curated observations into the versioned Timescale repository."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Callable, Iterable

from psp_pipeline.models.contracts import FactObservation, ObservationLineage
from psp_pipeline.quality.timescale_mirror_reconciliation import (
    CurrentRowFetcher,
    verify_exported_current_mirror,
)
from psp_pipeline.storage.postgres_repo import PostgresRepository
from psp_pipeline.storage.sqlite_curated_export import (
    export_all_daily_observations,
    export_observation_lineage,
)


ObservationExporter = Callable[..., list[FactObservation]]
ObservationLineageExporter = Callable[[sqlite3.Connection, Iterable[FactObservation]], list[ObservationLineage]]
RepositoryFactory = Callable[[str], PostgresRepository]


def load_curated_observations_to_timescale(
    sqlite_path: Path,
    postgres_dsn: str,
    *,
    rldcs: Iterable[str] | None = None,
    report_document_id: int | None = None,
    ingested_at: datetime | None = None,
    observation_exporter: ObservationExporter = export_all_daily_observations,
    observation_lineage_exporter: ObservationLineageExporter = export_observation_lineage,
    repository_factory: RepositoryFactory = PostgresRepository,
    replace_complete_snapshots: bool = False,
    verify_current_mirror: bool = True,
    current_row_fetcher: CurrentRowFetcher | None = None,
) -> dict[str, int | str | list[str] | dict[str, object]]:
    """Export curated SQLite facts and load idempotent Timescale versions.

    The database repository owns UUID replay deduplication and correction
    version assignment. ``replace_complete_snapshots`` is opt-in because it
    closes current facts omitted from a full report export; never enable it
    for a partial source, date, or table selection. Dual-write mirror
    verification is on by default so a successful load means current truth
    matches the exported SQLite grain set.
    """

    if not sqlite_path.exists():
        raise FileNotFoundError(f"Curated SQLite database not found at {sqlite_path}")
    with sqlite3.connect(sqlite_path) as connection:
        observations = observation_exporter(
            connection,
            rldcs=rldcs,
            report_document_id=report_document_id,
            ingested_at=ingested_at,
        )
        observation_lineage = observation_lineage_exporter(connection, observations)
    repository = repository_factory(postgres_dsn)
    retired_timeseries_uuids: tuple[str, ...] = ()
    retired_at: datetime | None = None
    if replace_complete_snapshots and hasattr(
        repository,
        "replace_curated_observation_snapshots",
    ):
        result = repository.replace_curated_observation_snapshots(
            observations,
            observation_lineage,
        )
        inserted = result.inserted
        retired_timeseries_uuids = result.retired_timeseries_uuids
        retired_at = result.retired_at
    elif hasattr(repository, "upsert_curated_observations"):
        inserted = repository.upsert_curated_observations(observations, observation_lineage)
    else:
        # Compatibility for constrained test doubles and legacy tooling.
        inserted = repository.upsert_fact_observations(observations)
    summary: dict[str, int | str | list[str] | dict[str, object]] = {
        "observations_exported": len(observations),
        "observations_inserted": inserted,
        "observations_deduplicated": len(observations) - inserted,
        "observation_lineage_exported": len(observation_lineage),
    }
    if replace_complete_snapshots:
        summary["observations_retired"] = len(retired_timeseries_uuids)
        summary["retired_timeseries_uuids"] = list(retired_timeseries_uuids)
        if retired_at is not None:
            summary["retired_at"] = retired_at.isoformat()
    if verify_current_mirror and observations:
        reconciliation = verify_exported_current_mirror(
            observations,
            postgres_dsn,
            current_row_fetcher=current_row_fetcher,
        )
        summary["mirror"] = reconciliation.as_dict()
    return summary
