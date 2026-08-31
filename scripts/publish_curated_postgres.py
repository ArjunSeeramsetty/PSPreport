"""Publish canonical identity and Postgres-primary wide facts from SQLite."""

from __future__ import annotations

import argparse
import json
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
    """Parse SQLite replay publication options."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--rldc", action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    """Load observations, canonical identities, and wide facts without DROP."""

    configure_logging("INFO")
    args = _parse_args()
    result = load_curated_observations_to_timescale(
        args.db,
        load_settings().postgres_dsn,
        rldcs=args.rldc or None,
        replace_complete_snapshots=False,
    )
    payload = json.dumps(result, indent=2, sort_keys=True, default=str)
    LOGGER.info("curated_postgres_publish_complete result=%s", result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
