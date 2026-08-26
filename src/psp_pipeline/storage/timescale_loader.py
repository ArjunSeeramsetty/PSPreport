"""Load portable curated observations into the versioned Timescale repository."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Callable, Iterable

from psp_pipeline.models.contracts import FactObservation, ObservationLineage
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
) -> dict[str, int]:
    """Export curated SQLite facts and load idempotent Timescale versions.

    The database repository owns UUID replay deduplication and correction
    version assignment. This function intentionally does not transform facts.
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
    if hasattr(repository, "upsert_curated_observations"):
        inserted = repository.upsert_curated_observations(observations, observation_lineage)
    else:
        # Compatibility for constrained test doubles and legacy tooling.
        inserted = repository.upsert_fact_observations(observations)
    return {
        "observations_exported": len(observations),
        "observations_inserted": inserted,
        "observations_deduplicated": len(observations) - inserted,
        "observation_lineage_exported": len(observation_lineage),
    }
