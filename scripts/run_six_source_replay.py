"""Execute end-to-end 6-source daily PSP replay through SQLite, TimescaleDB, and Neo4j."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.core.settings import load_settings
from psp_pipeline.pipelines.rldc_daily_psp import (
    LocalReportInput,
    run_rldc_local_pdf_ingestion,
)
from psp_pipeline.reconciliation.all_india_balance import synthesize_all_india_daily_balance
from psp_pipeline.storage.sqlite_curated_export import export_all_daily_observations
from psp_pipeline.storage.timescale_loader import load_curated_observations_to_timescale

LOGGER = logging.getLogger(__name__)

APPROVED_2026_FILES = {
    "2026-01-01": {
        "erldc": ROOT / "downloads" / "ERLDC_PSP" / "Power Supply Position Report_01012026.pdf",
        "nerldc": ROOT / "downloads" / "NERLDC_PSP" / "NER-PSP-REPORT-DATED-01-01-2026.pdf",
        "nrldc": ROOT / "downloads" / "NRLDC_PSP" / "tu3jPAbbZo4XMsihlvNG-w-daily010126.pdf",
        "srldc": ROOT / "downloads" / "SRLDC_PSP" / "01-01-2026-psp.pdf",
        "wrldc": ROOT / "downloads" / "WRLDC_PSP" / "WRLDC_PSP_Report_01-01-2026.pdf",
        "grid_india_national": ROOT / "downloads" / "NLDC_PSP" / "01.01.26_NLDC_PSP_872.pdf",
    },
    "2026-01-31": {
        "erldc": ROOT / "downloads" / "ERLDC_PSP" / "Power Supply Position Report_31012026.pdf",
        "nerldc": ROOT / "downloads" / "NERLDC_PSP" / "NER-PSP-REPORT-DATED-31-01-2026.pdf",
        "nrldc": ROOT / "downloads" / "NRLDC_PSP" / "jeT4304Z6EQhgpmQM7GY-w-daily310126.pdf",
        "srldc": ROOT / "downloads" / "SRLDC_PSP" / "31-01-2026-psp.pdf",
        "wrldc": ROOT / "downloads" / "WRLDC_PSP" / "WRLDC_PSP_Report_31-01-2026.pdf",
        "grid_india_national": ROOT / "downloads" / "NLDC_PSP" / "31.01.26_NLDC_PSP_982.pdf",
    },
    "2026-02-01": {
        "erldc": ROOT / "downloads" / "ERLDC_PSP" / "Power Supply Position Report_01022026.pdf",
        "nerldc": ROOT / "downloads" / "NERLDC_PSP" / "NER-PSP-REPORT-DATED-01-02-2026.pdf",
        "nrldc": ROOT / "downloads" / "NRLDC_PSP" / "cXtskLqyLzHp757iRa7r-w-daily010226.pdf",
        "srldc": ROOT / "downloads" / "SRLDC_PSP" / "01-02-2026-psp.pdf",
        "wrldc": ROOT / "downloads" / "WRLDC_PSP" / "WRLDC_PSP_Report_01-02-2026.pdf",
        "grid_india_national": ROOT / "downloads" / "NLDC_PSP" / "01.02.26_NLDC_PSP_308.pdf",
    },
}


def run_replay_for_date(
    target_date_str: str,
    db_path: Path,
    summary_path: Path,
    *,
    load_timescale: bool = True,
    sync_neo4j: bool = True,
) -> dict:
    """Run full 6-source replay for a single date across SQLite, Timescale, and Neo4j."""
    if target_date_str not in APPROVED_2026_FILES:
        raise ValueError(f"Target date {target_date_str} not in approved 2026 files registry.")

    target_date = date.fromisoformat(target_date_str)
    file_map = APPROVED_2026_FILES[target_date_str]
    inputs = [
        LocalReportInput(rldc=rldc, local_path=path, report_date=target_date)
        for rldc, path in file_map.items()
    ]

    db_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    LOGGER.info("Starting 6-source local SQLite ingestion for %s", target_date_str)
    ingestion = run_rldc_local_pdf_ingestion(db_path, inputs)

    conn = sqlite3.connect(str(db_path))
    try:
        date_rows = conn.execute("SELECT DateID, ActualDate FROM DimDates WHERE ActualDate = ?", (target_date_str,)).fetchall()
        if not date_rows:
            raise RuntimeError(f"DimDates row missing for {target_date_str}")
        date_id = date_rows[0][0]

        balance = synthesize_all_india_daily_balance(conn, date_id)
        balance_dict = balance.as_dict()

        # Count facts and observations per source
        doc_rows = conn.execute("SELECT id, rldc, local_path, report_date FROM psp_report_document").fetchall()
        source_docs = {r[1]: r[0] for r in doc_rows}

        obs = export_all_daily_observations(conn)
        obs_by_source: dict[str, int] = {}
        for o in obs:
            obs_by_source[o.source_region] = obs_by_source.get(o.source_region, 0) + 1

        fact_table_counts: dict[str, int] = {}
        curated_tables = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Fact%'").fetchall()
        ]
        for tbl in curated_tables:
            fact_table_counts[tbl] = int(conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
    finally:
        conn.close()

    # Optional TimescaleDB load
    timescale_result = None
    settings = load_settings()
    if load_timescale:
        LOGGER.info("Loading %d observations into TimescaleDB (%s)", len(obs), settings.postgres_dsn)
        try:
            timescale_result = load_curated_observations_to_timescale(
                db_path,
                settings.postgres_dsn,
                ingested_at=datetime.now(timezone.utc),
                replace_complete_snapshots=True,
            )
            LOGGER.info("TimescaleDB load complete: %s", timescale_result)
        except Exception as exc:
            LOGGER.warning("TimescaleDB load encountered error: %s", exc)
            timescale_result = {"error": str(exc)}

    # Optional Neo4j topology sync
    neo4j_result = None
    if sync_neo4j:
        LOGGER.info("Syncing 6-source topology and observations into Neo4j (%s)", settings.neo4j_uri)
        try:
            from psp_pipeline.agents.graph_sync_agent import GraphSyncAgent
            from psp_pipeline.storage.neo4j_repo import Neo4jRepository
            from psp_pipeline.storage.sqlite_topology_export import export_curated_topology

            constraints_path = ROOT / "sql" / "neo4j_constraints.cypher"
            cypher_statements = [
                s.strip() for s in constraints_path.read_text().split(";") if s.strip()
            ]
            with sqlite3.connect(str(db_path)) as conn_topo:
                topology = export_curated_topology(conn_topo)

            repository = Neo4jRepository(
                settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
            )
            try:
                repository.ensure_constraints(cypher_statements)
                repository.merge_grid_topology(topology)
                agent = GraphSyncAgent(repository)
                agent.run(obs)
                retired_uuids = (
                    timescale_result.get("retired_timeseries_uuids", [])
                    if timescale_result
                    else []
                )
                retired_at = timescale_result.get("retired_at") if timescale_result else None
                if retired_uuids and retired_at:
                    repository.retire_observation_versions(
                        retired_uuids,
                        datetime.fromisoformat(str(retired_at)),
                    )
                neo4j_result = {
                    "topology_regions": len(topology.get("regions", [])),
                    "topology_states": len(topology.get("states", [])),
                    "topology_lines": len(topology.get("transmission_lines", [])),
                    "topology_generators": len(topology.get("generating_units", [])),
                    "observations_synced": len(obs),
                    "observations_retired": len(retired_uuids),
                }
                LOGGER.info("Neo4j sync complete: %s", neo4j_result)
            finally:
                repository.close()
        except Exception as exc:
            LOGGER.warning("Neo4j sync encountered error: %s", exc)
            neo4j_result = {"error": str(exc)}

    summary = {
        "target_date": target_date_str,
        "sqlite_db_path": str(db_path),
        "ingestion_counts": ingestion,
        "source_documents": {k: str(v) for k, v in file_map.items()},
        "fact_table_counts": fact_table_counts,
        "exported_observation_total": len(obs),
        "exported_observations_by_source": obs_by_source,
        "balance_reconciliation": balance_dict,
        "timescale_result": timescale_result,
        "neo4j_result": neo4j_result,
    }

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    LOGGER.info("Replay complete for %s -> %s", target_date_str, summary_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Six-source daily PSP replay runner.")
    parser.add_argument("--date", default="2026-01-01", help="Target replay date (YYYY-MM-DD)")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "sqlite" / "six_source_replay_2026_01_01.sqlite")
    parser.add_argument("--summary", type=Path, default=ROOT / "data" / "diagnostics" / "six_source_replay_2026_01_01.json")
    parser.add_argument("--no-timescale", action="store_true", help="Skip TimescaleDB load")
    parser.add_argument("--no-neo4j", action="store_true", help="Skip Neo4j sync")
    args = parser.parse_args()

    configure_logging("INFO")
    run_replay_for_date(
        args.date,
        args.db,
        args.summary,
        load_timescale=not args.no_timescale,
        sync_neo4j=not args.no_neo4j,
    )


if __name__ == "__main__":
    main()
