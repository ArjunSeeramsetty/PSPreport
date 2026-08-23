"""Thin CLI wrapper for auditing NRLDC-referenced dimension quality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from psp_pipeline.quality.nrldc_dimension_audit import audit_nrldc_dimensions


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit NRLDC dimensions from SQLite.")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/sqlite/nrldc_anchor_scan.sqlite"),
        help="Path to NRLDC anchor SQLite database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/diagnostics/nrldc_dimension_audit.json"),
        help="Destination path for JSON diagnostic output.",
    )
    args = parser.parse_args()

    result = audit_nrldc_dimensions(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Dimension audit written to {args.output}")


if __name__ == "__main__":
    main()
