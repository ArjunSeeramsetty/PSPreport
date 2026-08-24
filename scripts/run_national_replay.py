"""CLI script to run multi-date national ingestion replay across all 5 RLDCs."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.national_replay import run_national_replay


def main() -> None:
    """Run sequential multi-day national ingestion replay across all 5 RLDCs."""
    parser = argparse.ArgumentParser(
        description="Run multi-date national ingestion replay across all 5 Indian RLDCs."
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        required=True,
        help="Start date in YYYY-MM-DD format (inclusive).",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        required=True,
        help="End date in YYYY-MM-DD format (inclusive).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "sqlite" / "national_replay.sqlite",
        help="Path to target SQLite database.",
    )
    parser.add_argument(
        "--rldc",
        type=str,
        default="all",
        choices=["all", "srldc", "nrldc", "wrldc", "erldc", "nerldc"],
        help="Specific RLDC to replay, or 'all' for all 5 (default: all).",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=ROOT / "downloads",
        help="Directory to store downloaded artifacts.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "rldc_report_sources.yaml",
        help="Path to sources configuration YAML.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "national_replay_report.json",
        help="Path to write JSON replay report.",
    )
    args = parser.parse_args()

    target_rldcs = None if args.rldc == "all" else {args.rldc}

    print("=" * 70)
    print("RUNNING NATIONAL MULTI-RLDC INGESTION REPLAY")
    print("=" * 70)
    print(f"Date Range:    {args.start_date} to {args.end_date}")
    print(f"Target RLDCs:  {args.rldc.upper()}")
    print(f"Database:      {args.db}")
    print("-" * 70)

    report = run_national_replay(
        sqlite_db_path=args.db,
        start_date=args.start_date,
        end_date=args.end_date,
        target_rldcs=target_rldcs,
        download_root=args.download_dir,
        config_path=args.config,
        output_path=args.output,
    )

    print(f"Replay Completed!")
    print(f"Dates Processed:         {report['total_dates_processed']}")
    print(f"Reports Persisted:        {report['total_reports_persisted']}")
    print(f"Observations Exported:    {report['total_observations_exported']}")
    print(f"Report saved to:          {args.output}")


if __name__ == "__main__":
    main()
