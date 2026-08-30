"""Write a conservative raw-cell coverage diagnostic for curated PSP data."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.raw_cell_coverage import generate_raw_cell_coverage_report


def main() -> None:
    """Generate and summarize the raw-cell coverage gate diagnostic."""

    parser = argparse.ArgumentParser(
        description="Audit raw PSP cells against curated lineage and approved exclusions."
    )
    parser.add_argument("--db", type=Path, required=True, help="Curated SQLite database path.")
    parser.add_argument("--rldc", help="Optional source scope, for example erldc.")
    parser.add_argument("--report-id", type=int, help="Optional raw report identifier.")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="JSON diagnostic output path.",
    )
    args = parser.parse_args()
    report = generate_raw_cell_coverage_report(
        args.db,
        rldc=args.rldc,
        report_id=args.report_id,
        output_path=args.output,
    )
    print(f"Raw non-empty cells: {report['raw_nonempty_cell_count']}")
    print(f"Mapped cells: {report['mapped_cell_count']}")
    print(f"Approved exclusions: {report['approved_exclusion_count']}")
    print(f"Unresolved cells: {report['unresolved_cell_count']}")
    print(f"Accounted coverage: {report['accounted_cell_pct']}%")


if __name__ == "__main__":
    main()
