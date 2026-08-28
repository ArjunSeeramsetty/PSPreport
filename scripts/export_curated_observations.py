"""CLI script to export bitemporal FactObservation records from curated SQLite facts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.storage.sqlite_curated_export import (
    RLDC_EXPORTERS,
    export_all_daily_observations,
)


def main() -> None:
    """Export curated facts into portable time-series observations."""
    parser = argparse.ArgumentParser(
        description="Export curated SQLite daily power system facts as portable observations."
    )
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to curated SQLite database.",
    )
    parser.add_argument(
        "--rldc",
        type=str,
        default="all",
        choices=["all", "srldc", "nrldc", "wrldc", "erldc", "nerldc", "grid_india_national", "nldc"],
        help="Specific RLDC to export, or 'all' for all available (default: all).",
    )
    parser.add_argument(
        "--report-id",
        type=int,
        default=None,
        help="Optional specific ReportDocumentID filter.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write exported observations (.jsonl or .json).",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Error: Database not found at {args.db}", file=sys.stderr)
        sys.exit(1)

    rldcs_to_export = None if args.rldc == "all" else [args.rldc]

    conn = sqlite3.connect(args.db)
    try:
        recorded_at = datetime.now(timezone.utc)
        observations = export_all_daily_observations(
            conn,
            rldcs=rldcs_to_export,
            report_document_id=args.report_id,
            ingested_at=recorded_at,
        )
    finally:
        conn.close()

    print(f"Exported {len(observations)} observation records from {args.db}")

    # Metrics summary by source region
    by_region: dict[str, int] = {}
    by_metric_prefix: dict[str, int] = {}
    for obs in observations:
        by_region[obs.source_region] = by_region.get(obs.source_region, 0) + 1
        prefix = obs.metric_name.split(".")[0]
        by_metric_prefix[prefix] = by_metric_prefix.get(prefix, 0) + 1

    print("\nBreakdown by Source Region:")
    for region, count in sorted(by_region.items()):
        print(f"  - {region:<6}: {count:>6} observations")

    if args.output is not None:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        is_json = out_path.suffix.lower() == ".json"

        obs_dicts = [
            {
                "entity_key": obs.entity_key,
                "metric_name": obs.metric_name,
                "time_block": obs.time_block,
                "operational_value": obs.operational_value,
                "settlement_value": obs.settlement_value,
                "variance_pct": obs.variance_pct,
                "report_type": obs.report_type,
                "source_region": obs.source_region,
                "valid_from": obs.valid_from.isoformat() if obs.valid_from else None,
                "valid_to": obs.valid_to.isoformat() if obs.valid_to else None,
                "version_no": obs.version_no,
                "ingested_at": obs.ingested_at.isoformat() if obs.ingested_at else None,
                "timeseries_uuid": obs.timeseries_uuid,
            }
            for obs in observations
        ]

        if is_json:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(obs_dicts, f, indent=2)
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                for record in obs_dicts:
                    f.write(json.dumps(record) + "\n")
        print(f"\nWritten {len(obs_dicts)} records to {args.output}")


if __name__ == "__main__":
    main()
