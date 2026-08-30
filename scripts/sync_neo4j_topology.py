"""Synchronize curated five-RLDC dimensions and observations to Neo4j."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.agents.graph_sync_agent import GraphSyncAgent
from psp_pipeline.core.logging import configure_logging
from psp_pipeline.core.settings import load_settings
from psp_pipeline.storage.neo4j_repo import Neo4jRepository
from psp_pipeline.storage.sqlite_curated_export import export_all_daily_observations
from psp_pipeline.storage.sqlite_topology_export import export_curated_topology


LOGGER = logging.getLogger(__name__)
CONSTRAINTS_PATH = ROOT / "sql" / "neo4j_constraints.cypher"


def _load_cypher_statements(path: Path) -> list[str]:
    """Load complete semicolon-terminated Cypher statements from a local file."""

    return [statement.strip() for statement in path.read_text().split(";") if statement.strip()]


def main() -> None:
    """Synchronize dimension topology before its time-series observation links."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--rldc", action="append", default=[])
    parser.add_argument("--report-id", type=int)
    args = parser.parse_args()
    configure_logging("INFO")
    settings = load_settings()
    with sqlite3.connect(args.db) as connection:
        topology = export_curated_topology(connection)
        observations = export_all_daily_observations(
            connection,
            rldcs=args.rldc or None,
            report_document_id=args.report_id,
        )
    repository = Neo4jRepository(
        settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
    )
    try:
        repository.ensure_constraints(_load_cypher_statements(CONSTRAINTS_PATH))
        repository.merge_grid_topology(topology)
        GraphSyncAgent(repository).run(observations)
    finally:
        repository.close()
    LOGGER.info(
        "neo4j_topology_sync_complete topology_nodes=%s observations=%s",
        sum(len(rows) for rows in topology.values()),
        len(observations),
    )


if __name__ == "__main__":
    main()
