"""Rehearse date-scoped dual-write from SQLite into TimescaleDB and Neo4j.

The rehearsal does not invent coverage. It exports each replay date's curated
observations, publishes them through injectable Timescale and graph sinks, and
stamps the OpenLineage coverage-completeness facets onto the summary so a
floor pass cannot be mistaken for full PSP/RPC coverage.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable

from psp_pipeline.lineage.openlineage import build_column_lineage_event
from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.quality.coverage_completeness import assess_coverage_completeness
from psp_pipeline.quality.coverage_contract import (
    default_coverage_manifest_path,
    evaluate_coverage_manifest,
)
from psp_pipeline.storage.sqlite_curated_export import export_all_daily_observations
from psp_pipeline.storage.sqlite_topology_export import export_curated_topology


LOGGER = logging.getLogger(__name__)

TimescaleSink = Callable[[Path, date, list[FactObservation]], dict[str, Any]]
GraphSink = Callable[[Path, date, dict[str, Any], list[FactObservation]], dict[str, Any]]


def run_dual_write_rehearsal(
    sqlite_db_path: Path | str,
    start_date: date,
    end_date: date,
    *,
    timescale_sink: TimescaleSink | None = None,
    graph_sink: GraphSink | None = None,
    output_path: Path | str | None = None,
    ingest_rpc_fixtures: bool = False,
    skip_empty_dates: bool = False,
    rpc_fixture_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Walk each date in the window and dual-write that slice off SQLite.

    Injected sinks keep the rehearsal runnable without live Timescale or Neo4j.
    Production callers pass wrappers around ``load_curated_observations_to_timescale``
    and ``GraphSyncAgent``. ``ingest_rpc_fixtures`` promotes canonical DSM/REA
    workbooks first so ``FactRPC*`` counts can leave ``not_demonstrated``.
    """

    db_path = Path(sqlite_db_path)
    rpc_ingest: dict[str, Any] | None = None
    if ingest_rpc_fixtures:
        from psp_pipeline.quality.rpc_fixtures import ingest_rpc_fixture_reports

        rpc_ingest = ingest_rpc_fixture_reports(db_path, fixture_dir=rpc_fixture_dir)
    if not db_path.exists():
        raise FileNotFoundError(f"Curated SQLite database not found at {db_path}")
    date_results: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        result = _rehearse_one_date(db_path, current, timescale_sink, graph_sink)
        if skip_empty_dates and not result["sqlite_report_ids"]:
            current += timedelta(days=1)
            continue
        date_results.append(result)
        current += timedelta(days=1)

    coverage = evaluate_coverage_manifest(
        db_path,
        default_coverage_manifest_path(),
        profile_name="corpus",
    )
    completeness = assess_coverage_completeness(coverage["corpus"], db_path=str(db_path))
    lineage = build_column_lineage_event(
        db_path,
        run_id=f"dual-write:{start_date.isoformat()}:{end_date.isoformat()}",
        job_name="psp.dual_write_rehearsal",
        completeness=completeness,
        event_time=datetime.now(timezone.utc),
    )
    summary = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "dates_processed": len(date_results),
        "sqlite_observation_total": sum(
            int(item["sqlite_observations"]) for item in date_results
        ),
        "date_results": date_results,
        "coverage": {name: result.as_dict() for name, result in coverage.items()},
        "coverage_completeness": completeness.as_dict(),
        "full_psp_and_rpc_coverage": completeness.full_psp_and_rpc_coverage,
        "openlineage": lineage,
        "rpc_fixtures": rpc_ingest,
    }
    if output_path is not None:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def recording_timescale_sink(store: list[dict[str, Any]]) -> TimescaleSink:
    """Return a Timescale sink that records each date's exported observations."""

    def _sink(
        _db_path: Path,
        target_date: date,
        observations: list[FactObservation],
    ) -> dict[str, Any]:
        payload = {
            "target_date": target_date.isoformat(),
            "observations_exported": len(observations),
            "entity_keys": [item.entity_key for item in observations],
            "source_regions": sorted({item.source_region for item in observations}),
        }
        store.append(payload)
        return payload

    return _sink


def recording_graph_sink(store: list[dict[str, Any]]) -> GraphSink:
    """Return a Neo4j sink that records topology plus observation entity keys."""

    def _sink(
        _db_path: Path,
        target_date: date,
        topology: dict[str, Any],
        observations: list[FactObservation],
    ) -> dict[str, Any]:
        payload = {
            "target_date": target_date.isoformat(),
            "topology_regions": len(topology.get("regions") or []),
            "observations_synced": len(observations),
            "entity_keys": [item.entity_key for item in observations],
        }
        store.append(payload)
        return payload

    return _sink


def _rehearse_one_date(
    db_path: Path,
    target_date: date,
    timescale_sink: TimescaleSink | None,
    graph_sink: GraphSink | None,
) -> dict[str, Any]:
    """Export one valid date from SQLite and push it to both sinks."""

    with sqlite3.connect(db_path) as conn:
        report_ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM psp_report_document WHERE report_date = ?",
                (target_date.isoformat(),),
            )
        ]
        observations = _observations_for_reports(conn, report_ids)
        topology = export_curated_topology(conn)
    timescale = (
        timescale_sink(db_path, target_date, observations)
        if timescale_sink is not None
        else {"skipped": True}
    )
    neo4j = (
        graph_sink(db_path, target_date, topology, observations)
        if graph_sink is not None
        else {"skipped": True}
    )
    LOGGER.info(
        "dual_write_date date=%s sqlite_obs=%s timescale=%s neo4j=%s",
        target_date.isoformat(),
        len(observations),
        timescale,
        neo4j,
    )
    return {
        "target_date": target_date.isoformat(),
        "sqlite_observations": len(observations),
        "sqlite_report_ids": report_ids,
        "timescale": timescale,
        "neo4j": neo4j,
    }


def _observations_for_reports(
    conn: sqlite3.Connection,
    report_ids: Iterable[int],
) -> list[FactObservation]:
    """Export curated observations for an explicit report-id set."""

    observations: list[FactObservation] = []
    for report_id in report_ids:
        observations.extend(
            export_all_daily_observations(conn, report_document_id=int(report_id))
        )
    return observations
