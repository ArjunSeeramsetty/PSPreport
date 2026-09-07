"""Run a date-scoped SQLite → Timescale → Neo4j dual-write rehearsal."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.dual_write_rehearsal import run_dual_write_rehearsal


def main() -> int:
    """Summarize dual-write counts and OpenLineage coverage facets for a window."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Publish each date through Timescale and Neo4j using AppSettings DSNs",
    )
    args = parser.parse_args()
    timescale_sink = None
    graph_sink = None
    if args.live:
        timescale_sink, graph_sink = _live_sinks()
    run_dual_write_rehearsal(
        args.db,
        args.start_date,
        args.end_date,
        timescale_sink=timescale_sink,
        graph_sink=graph_sink,
        output_path=args.output,
    )
    return 0


def _live_sinks():
    """Bind date-scoped DAG stages to the configured Timescale and Neo4j DSNs."""

    from psp_pipeline.core.settings import load_settings
    from psp_pipeline.pipelines.stages import (
        export_all_curated_to_timescale,
        sync_all_curated_to_graph,
    )

    settings = load_settings()

    def timescale_sink(db_path, target_date, observations):
        inserted = export_all_curated_to_timescale(
            settings,
            db_path,
            target_date=target_date,
        )
        return {
            "target_date": target_date.isoformat(),
            "observations_exported": len(observations),
            "observations_inserted": inserted,
        }

    def graph_sink(db_path, target_date, topology, observations):
        synced = sync_all_curated_to_graph(
            settings,
            db_path,
            target_date=target_date,
        )
        return {
            "target_date": target_date.isoformat(),
            "topology_regions": len(topology.get("regions") or []),
            "observations_synced": synced,
        }

    return timescale_sink, graph_sink


if __name__ == "__main__":
    raise SystemExit(main())
