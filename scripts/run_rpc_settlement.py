"""Collect public RPC weekly DSM and monthly REA settlement accounts."""

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
from psp_pipeline.pipelines.rpc_settlement import run_rpc_settlement_collection


LOGGER = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    """Parse bounded RPC settlement collection options."""

    parser = argparse.ArgumentParser(
        description="Collect public RPC DSM and REA accounts into curated SQLite."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "rpc_report_sources.yaml",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "sqlite" / "all_rldc_daily.sqlite",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=ROOT / "downloads" / "rpc",
    )
    parser.add_argument("--target-date", type=date.fromisoformat)
    parser.add_argument("--max-reports-per-rpc", type=int, default=4)
    parser.add_argument("--rpc", action="append", default=[])
    return parser.parse_args()


def main() -> None:
    """Run the RPC collector and emit its structured summary through logging."""

    configure_logging("INFO")
    args = _parse_args()
    result = run_rpc_settlement_collection(
        config_path=args.config,
        sqlite_db_path=args.db,
        download_root=args.download_dir,
        target_date=args.target_date,
        max_reports_per_rpc=args.max_reports_per_rpc,
        target_rpcs=set(args.rpc) if args.rpc else None,
    )
    LOGGER.info("rpc_settlement_complete result=%s", result)


if __name__ == "__main__":
    main()
