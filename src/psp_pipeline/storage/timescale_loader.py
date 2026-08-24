"""Load portable curated observations into the versioned Timescale repository."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Callable, Iterable

from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.storage.postgres_repo import PostgresRepository
from psp_pipeline.storage.sqlite_curated_export import export_all_daily_observations


ObservationExporter = Callable[..., list[FactObservation]]
RepositoryFactory = Callable[[str], PostgresRepository]


def load_curated_observations_to_timescale(
    sqlite_path: Path,
    postgres_dsn: str,
    *,
    rldcs: Iterable[str] | None = None,
    report_document_id: int | None = None,
    ingested_at: datetime | None = None,
    observation_exporter: ObservationExporter = export_all_daily_observations,
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
    inserted = repository_factory(postgres_dsn).upsert_fact_observations(observations)
    return {
        "observations_exported": len(observations),
        "observations_inserted": inserted,
        "observations_deduplicated": len(observations) - inserted,
    }
