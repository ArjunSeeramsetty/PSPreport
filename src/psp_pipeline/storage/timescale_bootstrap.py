"""Recreate Timescale from the greenfield schema, then backfill curated SQLite.

This is the disposable-volume path: apply ``sql/timescale_schema.sql`` and load
current curated facts. Incremental files under ``sql/migrations/`` are not used
here because ``001_bitemporal_sys_to.sql`` rewrites ``sys_to`` for every row.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Callable, Iterable

try:
    import psycopg
except ImportError:
    psycopg = None  # type: ignore[assignment]

from psp_pipeline.quality.timescale_mirror_reconciliation import CurrentRowFetcher
from psp_pipeline.storage.postgres_repo import PostgresRepository
from psp_pipeline.storage.timescale_loader import (
    ObservationExporter,
    ObservationLineageExporter,
    RepositoryFactory,
    load_curated_observations_to_timescale,
)


LOGGER = logging.getLogger(__name__)

REQUIRED_FACT_COLUMNS = (
    "sys_to",
    "series_key",
    "content_hash",
    "metric_id",
    "report_document_id",
    "timeseries_uuid",
    "canonical_entity_id",
)
REQUIRED_TABLES = (
    "fact_observation",
    "fact_observation_dedup",
    "fact_observation_current",
    "fact_observation_lineage",
    "pipeline_run",
    "ingest_lineage",
    "reconciliation_result",
    "canonical_entity",
    "canonical_entity_alias",
    "canonical_entity_adjudication",
    "fact_wide_daily",
    "fact_wide_daily_current",
)
Connect = Callable[..., object]


class TimescaleSchemaStaleError(RuntimeError):
    """Raised when an existing Timescale database cannot be upgraded in place.

    The greenfield file uses ``CREATE TABLE IF NOT EXISTS``, so missing columns
    are not added. Recreate the schema instead of applying ``sql/migrations/``.
    """


class TimescaleSchemaNotReadyError(RuntimeError):
    """Raised when the greenfield contract is still incomplete after apply."""


@dataclass(frozen=True)
class GreenfieldSchemaStatus:
    """Inventory of the Timescale objects required by curated dual-write."""

    fact_table_present: bool
    missing_tables: tuple[str, ...]
    missing_columns: tuple[str, ...]
    hypertable_present: bool
    ready: bool
    stale: bool

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready schema inspection payload."""

        return {
            "fact_table_present": self.fact_table_present,
            "missing_tables": list(self.missing_tables),
            "missing_columns": list(self.missing_columns),
            "hypertable_present": self.hypertable_present,
            "ready": self.ready,
            "stale": self.stale,
        }


def default_greenfield_schema_path() -> Path:
    """Return the repository-owned Timescale bootstrap SQL path."""

    return Path(__file__).resolve().parents[3] / "sql" / "timescale_schema.sql"


def split_sql_statements(script: str) -> tuple[str, ...]:
    """Split a comment-tolerant DDL script into executable statements."""

    statements: list[str] = []
    for raw in script.split(";"):
        lines = [
            line
            for line in raw.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        statement = "\n".join(lines).strip()
        if statement:
            statements.append(statement)
    return tuple(statements)


def schema_status_from_inventory(
    *,
    present_tables: Iterable[str],
    fact_columns: Iterable[str] | None,
    hypertable_present: bool,
) -> GreenfieldSchemaStatus:
    """Derive readiness from table, column, and hypertable inventory."""

    tables = {name.lower() for name in present_tables}
    missing_tables = tuple(
        name for name in REQUIRED_TABLES if name not in tables
    )
    fact_present = "fact_observation" in tables
    if fact_columns is None:
        missing_columns = REQUIRED_FACT_COLUMNS
        stale = False
        ready = False
    else:
        columns = {name.lower() for name in fact_columns}
        missing_columns = tuple(
            name for name in REQUIRED_FACT_COLUMNS if name not in columns
        )
        stale = bool(missing_columns) or (fact_present and not hypertable_present)
        ready = not missing_tables and not missing_columns and hypertable_present
    return GreenfieldSchemaStatus(
        fact_table_present=fact_present,
        missing_tables=missing_tables,
        missing_columns=missing_columns,
        hypertable_present=hypertable_present,
        ready=ready,
        stale=stale,
    )


def inspect_greenfield_schema(
    postgres_dsn: str,
    *,
    connect: Connect | None = None,
) -> GreenfieldSchemaStatus:
    """Inspect whether Timescale already matches the greenfield contract."""

    connector = connect or _connect
    with connector(postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """
            )
            present_tables = [str(row[0]) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'fact_observation'
                """
            )
            column_rows = cur.fetchall()
            fact_columns = [str(row[0]) for row in column_rows] if column_rows else None
            hypertable_present = False
            cur.execute("SELECT to_regclass('timescaledb_information.hypertables')")
            if cur.fetchone()[0] is not None:
                cur.execute(
                    """
                    SELECT 1
                    FROM timescaledb_information.hypertables
                    WHERE hypertable_name = 'fact_observation'
                    LIMIT 1
                    """
                )
                hypertable_present = cur.fetchone() is not None
    return schema_status_from_inventory(
        present_tables=present_tables,
        fact_columns=fact_columns,
        hypertable_present=hypertable_present,
    )


def apply_greenfield_schema(
    postgres_dsn: str,
    *,
    recreate: bool = False,
    schema_path: Path | str | None = None,
    connect: Connect | None = None,
) -> dict[str, object]:
    """Apply ``sql/timescale_schema.sql``, optionally after dropping ``public``.

    Returns:
        Counts of executed statements and whether the schema was recreated.

    Raises:
        FileNotFoundError: If the greenfield SQL file is missing.
        RuntimeError: If psycopg is not installed.
    """

    path = Path(schema_path) if schema_path else default_greenfield_schema_path()
    if path.name != "timescale_schema.sql":
        raise ValueError("Greenfield bootstrap only applies sql/timescale_schema.sql")
    script = path.read_text(encoding="utf-8")
    statements = split_sql_statements(script)
    connector = connect or _connect
    with connector(postgres_dsn) as conn:
        with conn.cursor() as cur:
            if recreate:
                LOGGER.warning("timescale_greenfield_recreate dropping public schema")
                cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
                cur.execute("CREATE SCHEMA public")
                cur.execute("GRANT ALL ON SCHEMA public TO public")
            for statement in statements:
                cur.execute(statement)
    return {
        "schema_path": str(path),
        "recreated": recreate,
        "statements_applied": len(statements),
    }


def bootstrap_timescale_from_sqlite(
    sqlite_path: Path | str,
    postgres_dsn: str,
    *,
    recreate_schema: bool = False,
    rldcs: Iterable[str] | None = None,
    verify_current_mirror: bool = True,
    current_row_fetcher: CurrentRowFetcher | None = None,
    observation_exporter: ObservationExporter | None = None,
    observation_lineage_exporter: ObservationLineageExporter | None = None,
    repository_factory: RepositoryFactory = PostgresRepository,
    connect: Connect | None = None,
    schema_path: Path | str | None = None,
) -> dict[str, object]:
    """Recreate or verify the greenfield schema, then backfill curated facts.

    ``replace_complete_snapshots`` is intentionally not exposed. A full SQLite
    replay uses idempotent upserts so UUID history is preserved across reloads.

    Raises:
        FileNotFoundError: If the curated SQLite replay is absent.
        TimescaleSchemaStaleError: If the live database is missing columns and
            ``recreate_schema`` was not requested.
        TimescaleSchemaNotReadyError: If apply did not produce the contract.
    """

    db_path = Path(sqlite_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Curated SQLite database not found at {db_path}")

    schema_result: dict[str, object] | None = None
    status = inspect_greenfield_schema(postgres_dsn, connect=connect)
    if recreate_schema:
        schema_result = apply_greenfield_schema(
            postgres_dsn,
            recreate=True,
            schema_path=schema_path,
            connect=connect,
        )
        status = inspect_greenfield_schema(postgres_dsn, connect=connect)
    elif status.stale:
        raise TimescaleSchemaStaleError(
            "Timescale schema is missing required columns or hypertable "
            "partitioning. Recreate from sql/timescale_schema.sql; do not apply "
            f"sql/migrations/. missing_columns={list(status.missing_columns)}"
        )
    elif not status.ready:
        schema_result = apply_greenfield_schema(
            postgres_dsn,
            recreate=False,
            schema_path=schema_path,
            connect=connect,
        )
        status = inspect_greenfield_schema(postgres_dsn, connect=connect)

    if not status.ready:
        raise TimescaleSchemaNotReadyError(
            "Greenfield Timescale schema is not ready after apply: "
            + str(status.as_dict())
        )

    load_kwargs: dict[str, object] = {
        "rldcs": rldcs,
        "verify_current_mirror": verify_current_mirror,
        "current_row_fetcher": current_row_fetcher,
        "repository_factory": repository_factory,
        "replace_complete_snapshots": False,
    }
    if observation_exporter is not None:
        load_kwargs["observation_exporter"] = observation_exporter
    if observation_lineage_exporter is not None:
        load_kwargs["observation_lineage_exporter"] = observation_lineage_exporter
    load_result = load_curated_observations_to_timescale(
        db_path,
        postgres_dsn,
        **load_kwargs,
    )
    views_refreshed = False
    repository = repository_factory(postgres_dsn)
    if hasattr(repository, "refresh_current_truth_views"):
        views_refreshed = bool(repository.refresh_current_truth_views())
    return {
        "schema": status.as_dict(),
        "schema_apply": schema_result,
        "views_refreshed": views_refreshed,
        "load": load_result,
    }


def _connect(dsn: str):
    """Open an autocommit connection so Timescale DDL is not wrapped."""

    if psycopg is None:
        raise RuntimeError(
            "The 'psycopg' package is required to bootstrap TimescaleDB. "
            "Install it with `pip install psycopg[binary]`."
        )
    return psycopg.connect(dsn, autocommit=True)
