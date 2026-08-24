"""Thin CLI wrapper for auditing ERLDC-referenced dimension quality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.erldc_dimension_audit import audit_erldc_dimensions


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit ERLDC dimensions from SQLite.")
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "sqlite" / "erldc_anchor_scan.sqlite",
        help="Path to ERLDC anchor SQLite database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "erldc_dimension_audit.json",
        help="Destination path for JSON diagnostic output.",
    )
    args = parser.parse_args()

    result = audit_erldc_dimensions(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"ERLDC dimension audit written to {args.output}")


if __name__ == "__main__":
    main()
