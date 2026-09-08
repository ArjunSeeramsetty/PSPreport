from __future__ import annotations

import argparse
from datetime import date
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.wbes.pipeline import probe_wbes_public, run_wbes_schedule
from psp_pipeline.wbes.settings import load_wbes_settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Isolated WBES 96-block schedule ingest. Disabled unless WBES_ENABLED=true."
    )
    parser.add_argument("--date", help="Single IST operating date YYYY-MM-DD")
    parser.add_argument("--start-date", help="Inclusive start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="Inclusive end date YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Re-ingest dates already checkpointed")
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Unauthenticated catalog probe; do not parse or persist matrices",
    )
    args = parser.parse_args()
    configure_logging("INFO")
    settings = load_wbes_settings(ROOT)
    if args.probe_only:
        summary = probe_wbes_public(settings)
    else:
        start = _parse_date(args.date or args.start_date)
        end = _parse_date(args.date or args.end_date)
        summary = run_wbes_schedule(
            settings,
            start_date=start,
            end_date=end,
            force=args.force,
        )
    print(json.dumps(summary.as_dict(), indent=2, default=str))
    if summary.status in {"failed"}:
        return 1
    return 0


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
