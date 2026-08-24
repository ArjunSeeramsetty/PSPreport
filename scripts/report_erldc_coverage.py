"""CLI wrapper for running the ERLDC curated coverage report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.erldc_coverage_report import generate_erldc_coverage_report


def main() -> None:
    """Entrypoint for the ERLDC curated coverage diagnostic CLI."""

    parser = argparse.ArgumentParser(
        description="Generate curated coverage diagnostic for ERLDC PSP corpus."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/sqlite/erldc_anchor_scan.sqlite"),
        help="Path to SQLite database containing ingested and curated ERLDC reports.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/diagnostics/erldc_coverage_report.json"),
        help="Path to output JSON diagnostic file.",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Error: Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    report = generate_erldc_coverage_report(args.db)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"ERLDC coverage report written to {args.output}")
    print(f"Total Raw Reports:     {report['total_raw_reports']}")
    print(f"Total Curated Reports: {report['total_curated_reports']} ({report['overall_promotion_rate_pct']}%)")
    print(f"Total Lineage Records: {report['total_lineage_records']}")
    print("\nSection Breakdown:")
    for sec in report["sections"]:
        print(f"  - {sec['fact_table']:<35}: {sec['total_rows']:>5} rows ({sec['report_coverage_pct']}%)")
    print("\nTemplate Breakdown:")
    for tmpl in report["templates"]:
        print(f"  - {tmpl['template_id']:<50}: {tmpl['promoted_reports']}/{tmpl['total_reports']} ({tmpl['promotion_rate_pct']}%) [Gated: {tmpl['gated_reports']}]")


if __name__ == "__main__":
    main()
