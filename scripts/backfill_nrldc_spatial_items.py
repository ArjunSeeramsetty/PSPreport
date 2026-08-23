"""Enrich persisted NRLDC continuation pages with LiteParse coordinates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.pipelines.rldc_daily_psp import (
    backfill_nrldc_continuation_spatial_items,
)


def main() -> None:
    """Run the idempotent local NRLDC continuation-coordinate backfill."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    if not args.db.exists():
        parser.error(f"SQLite database does not exist: {args.db}")

    configure_logging()
    result = backfill_nrldc_continuation_spatial_items(args.db)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
