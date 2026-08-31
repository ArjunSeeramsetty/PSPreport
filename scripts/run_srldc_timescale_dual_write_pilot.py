"""Load one complete SRLDC curated report into Timescale and verify its mirror."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.core.settings import load_settings
from psp_pipeline.storage.sqlite_curated_export import export_all_daily_observations
from psp_pipeline.storage.timescale_loader import load_curated_observations_to_timescale


LOGGER = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    """Parse the deliberately narrow, report-scoped dual-write pilot options."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--replace-complete-snapshot",
        action="store_true",
        help="Retire absent current facts only after verifying this is a complete report export.",
    )
    return parser.parse_args()


def main() -> None:
    """Execute an opt-in SRLDC SQLite-to-Timescale mirror acceptance check."""

    configure_logging("INFO")
    args = _parse_args()
    if not args.db.exists():
        raise SystemExit(f"Curated SQLite database not found: {args.db}")

    settings = load_settings()
    with sqlite3.connect(args.db) as connection:
        observations = export_all_daily_observations(
            connection,
            rldcs=["srldc"],
            report_document_id=args.report_id,
        )
    if not observations:
        raise SystemExit(
            "No SRLDC observations were exported for the requested report; "
            "the dual-write gate refuses an empty acceptance result."
        )

    result = load_curated_observations_to_timescale(
        args.db,
        settings.postgres_dsn,
        rldcs=["srldc"],
        report_document_id=args.report_id,
        replace_complete_snapshots=args.replace_complete_snapshot,
        verify_current_mirror=True,
    )
    LOGGER.info("srldc_timescale_dual_write_pilot result=%s", result)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    mirror = result.get("mirror")
    if not isinstance(mirror, dict) or not mirror.get("is_match"):
        raise SystemExit("SRLDC Timescale mirror reconciliation failed.")


if __name__ == "__main__":
    main()
