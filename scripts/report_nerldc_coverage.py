"""CLI script to generate and display the NERLDC curated fact coverage report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.nerldc_coverage_report import generate_nerldc_coverage_report


def main() -> None:
    """Generate NERLDC coverage diagnostic report from a curated SQLite database."""
    parser = argparse.ArgumentParser(
        description="Analyze curated fact coverage for NERLDC reports in SQLite."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "sqlite" / "nerldc_anchor_scan.sqlite",
        help="Path to curated SQLite database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "nerldc_coverage_report.json",
        help="Path to write JSON coverage report.",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Error: Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    report = generate_nerldc_coverage_report(args.db, output_path=args.output)

    print(f"NERLDC coverage report written to {args.output}")
    print(f"Total Raw Reports:     {report['total_raw_reports']}")
    print(
        f"Total Curated Reports: {report['total_curated_reports']} "
        f"({report['overall_promotion_rate_pct']}%)"
    )
    print(f"Total Lineage Records: {report['total_lineage_records']}")

    print("\nSection Breakdown:")
    for section in report["sections"]:
        print(
            f"  - {section['fact_table']:<35}: {section['total_rows']:>5} rows "
            f"({section['report_coverage_pct']}%)"
        )

    print("\nTemplate Breakdown:")
    for t in report["templates"]:
        print(
            f"  - {t['template_id']:<50}: {t['promoted_reports']}/{t['total_reports']} "
            f"({t['promotion_rate_pct']}%) [Gated: {t['gated_reports']}]"
        )


if __name__ == "__main__":
    main()
