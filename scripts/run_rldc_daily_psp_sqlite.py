from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.rldc_daily_psp import run_rldc_daily_psp_collection


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract RLDC daily PSP reports and persist parsed fields to SQLite.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "rldc_report_sources.yaml",
        help="Path to RLDC report source YAML.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "sqlite" / "rldc_daily_psp.db",
        help="Output SQLite database path.",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=ROOT / "data" / "raw" / "rldc_daily_psp",
        help="Directory where PDF files are stored.",
    )
    parser.add_argument(
        "--rldc",
        action="append",
        default=[],
        help="Run only for specific RLDC keys (repeatable), e.g. --rldc srldc --rldc nrlldc.",
    )
    parser.add_argument(
        "--max-reports",
        type=int,
        default=3,
        help="Max number of latest PDF links to process per RLDC per run.",
    )
    parser.add_argument(
        "--target-date",
        type=str,
        default=None,
        help="Target report date in YYYY-MM-DD. Defaults to current UTC date.",
    )
    return parser.parse_args()


def main() -> None:
    configure_logging("INFO")
    args = _parse_args()
    result = run_rldc_daily_psp_collection(
        config_path=args.config,
        sqlite_db_path=args.db,
        download_root=args.download_dir,
        target_rldcs=set(args.rldc) if args.rldc else None,
        max_reports_per_rldc=args.max_reports,
        target_date=date.fromisoformat(args.target_date) if args.target_date else None,
    )
    print(result)


if __name__ == "__main__":
    main()
