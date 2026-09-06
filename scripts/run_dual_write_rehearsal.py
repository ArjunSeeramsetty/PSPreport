"""Run a date-scoped SQLite → Timescale → Neo4j dual-write rehearsal."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.dual_write_rehearsal import run_dual_write_rehearsal


def main() -> int:
    """Summarize dual-write counts and OpenLineage coverage facets for a window."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_dual_write_rehearsal(
        args.db,
        args.start_date,
        args.end_date,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
