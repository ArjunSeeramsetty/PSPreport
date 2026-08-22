"""Run the isolated SRLDC monthly-anchor integration scan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.quality.srldc_anchor_scan import scan_srldc_monthly_anchors
from psp_pipeline.core.logging import configure_logging


def main() -> None:
    """Run the scan and save an inspectable JSON diagnostic summary."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "downloads" / "SRLDC_PSP",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "sqlite" / "srldc_anchor_scan.sqlite",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "srldc_anchor_scan.json",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="Maximum parser runtime allowed for one historical PDF.",
    )
    args = parser.parse_args()
    configure_logging()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    summary = scan_srldc_monthly_anchors(
        args.input_dir,
        args.db,
        timeout_seconds=args.timeout_seconds,
    )
    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
