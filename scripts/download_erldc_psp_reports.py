"""CLI wrapper for ERLDC daily PSP API downloads."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.acquisition.downloaders.erldc import download_erldc_range
from psp_pipeline.core.logging import configure_logging


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2023, 4, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output-dir", type=Path, default=ROOT / "downloads" / "ERLDC_PSP")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--delay-seconds", type=float, default=0.75)
    return parser.parse_args()


def main() -> None:
    """Run the ERLDC PSP downloader."""

    configure_logging("WARNING")
    args = parse_args()
    result = download_erldc_range(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        max_attempts=args.max_attempts,
        delay_seconds=args.delay_seconds,
    )
    print(result)


if __name__ == "__main__":
    main()
