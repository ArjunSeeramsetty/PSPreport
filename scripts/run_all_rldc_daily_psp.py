"""Run fail-soft daily public PSP ingestion for all configured RLDCs."""

from __future__ import annotations

import argparse
from datetime import date
import logging
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.pipelines.all_rldc_daily_psp import run_all_rldc_daily_psp


LOGGER = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    """Parse bounded daily collection options."""

    parser = argparse.ArgumentParser(
        description="Collect daily public PSP reports into a consolidated SQLite database."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "rldc_report_sources.yaml",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "sqlite" / "all_rldc_daily_psp.sqlite",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=ROOT / "data" / "raw" / "all_rldc_daily_psp",
    )
    parser.add_argument("--target-date", type=date.fromisoformat)
    parser.add_argument("--max-reports-per-rldc", type=int, default=3)
    parser.add_argument("--rldc", action="append", default=[])
    return parser.parse_args()


def main() -> None:
    """Run the coordinator and emit its structured summary through logging."""

    configure_logging("INFO")
    args = _parse_args()
    result = run_all_rldc_daily_psp(
        config_path=args.config,
        sqlite_db_path=args.db,
        download_root=args.download_dir,
        target_date=args.target_date,
        max_reports_per_rldc=args.max_reports_per_rldc,
        target_rldcs=set(args.rldc) if args.rldc else None,
    )
    LOGGER.info("all_rldc_daily_psp_complete result=%s", result)


if __name__ == "__main__":
    main()
