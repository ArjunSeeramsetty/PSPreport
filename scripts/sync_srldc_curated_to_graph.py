"""Synchronize curated SRLDC daily observation topology to Neo4j."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from psp_pipeline.agents.graph_sync_agent import GraphSyncAgent
from psp_pipeline.core.settings import load_settings
from psp_pipeline.storage.neo4j_repo import Neo4jRepository
from psp_pipeline.storage.sqlite_curated_export import (
    export_nrldc_daily_observations,
    export_srldc_daily_observations,
)


def main() -> None:
    """Read curated SQLite facts and idempotently sync their graph topology."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Curated RLDC SQLite database")
    parser.add_argument("--rldc", choices=("srldc", "nrldc"), default="srldc")
    parser.add_argument("--report-id", type=int, help="Optional psp_report_document id")
    args = parser.parse_args()

    with sqlite3.connect(args.db) as conn:
        exporter = (
            export_nrldc_daily_observations if args.rldc == "nrldc"
            else export_srldc_daily_observations
        )
        facts = exporter(conn, args.report_id)
    if not facts:
        return
    settings = load_settings()
    repository = Neo4jRepository(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
    )
    try:
        GraphSyncAgent(repository).run(facts)
    finally:
        repository.close()


if __name__ == "__main__":
    main()
