"""Load exported five-RLDC curated observations into TimescaleDB."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.core.settings import load_settings
from psp_pipeline.storage.timescale_loader import load_curated_observations_to_timescale


LOGGER = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    """Parse bounded Timescale load options."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--rldc", action="append", default=[])
    parser.add_argument("--report-id", type=int)
    parser.add_argument(
        "--replace-complete-snapshots",
        action="store_true",
        help="Close current facts absent from a complete report export.",
    )
    return parser.parse_args()


def main() -> None:
    """Load selected curated records using the configured PostgreSQL DSN."""

    configure_logging("INFO")
    args = _parse_args()
    result = load_curated_observations_to_timescale(
        args.db,
        load_settings().postgres_dsn,
        rldcs=args.rldc or None,
        report_document_id=args.report_id,
        replace_complete_snapshots=args.replace_complete_snapshots,
    )
    LOGGER.info("timescale_observation_load_complete result=%s", result)


if __name__ == "__main__":
    main()
