"""CLI script to run the national 5-RLDC dimension quality audit and output diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.national_dimension_audit import audit_national_dimensions


def main() -> None:
    """Run comprehensive 5-RLDC national dimension quality audit."""
    parser = argparse.ArgumentParser(
        description="Audit dimension health across all 5 Indian RLDCs in a curated database."
    )
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to curated SQLite database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "national_dimension_audit.json",
        help="Path to write the national dimension audit JSON report.",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Error: Database not found at {args.db}", file=sys.stderr)
        sys.exit(1)

    try:
        report = audit_national_dimensions(args.db)
    except Exception as exc:
        print(f"Error during national dimension audit: {exc}", file=sys.stderr)
        sys.exit(1)

    summary = report["national_summary"]

    print("=" * 70)
    print("NATIONAL 5-RLDC DIMENSION QUALITY DASHBOARD")
    print("=" * 70)
    print(f"Audited Database:         {args.db}")
    print(f"Active RLDCs:             {', '.join(r.upper() for r in summary['active_rldcs'])}")
    print(f"Total Reports Inspected:  {summary['total_reports_found']}")
    print("-" * 70)
    print("DIMENSION INVENTORY:")
    print(f"  - States:                 {summary['total_states_count']}")
    print(f"  - Generating Entities:    {summary['total_grid_entities_count']}")
    print(f"  - Voltage Nodes:          {summary['total_voltage_nodes_count']}")
    print(f"  - Reservoirs:             {summary['total_reservoirs_count']}")
    print(f"  - Transmission Elements:  {summary['total_transmission_elements_count']}")
    print(f"  - International Countries:{summary['total_countries_count']}")
    print("-" * 70)
    print("QUALITY ANOMALIES & PENDING TOPOLOGY:")
    print(f"  - Unresolved Regions:     {summary['total_unresolved_regions_count']}")
    print(f"  - Unresolved States:      {summary['total_unresolved_states_count']}")
    print(f"  - Duplicate Entity Groups:{summary['total_duplicate_entity_groups']}")
    print(f"  - Topology Enrichment Due:{summary['total_topology_enrichment_pending_count']}")
    print("=" * 70)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Full diagnostic audit written to {args.output}")


if __name__ == "__main__":
    main()
