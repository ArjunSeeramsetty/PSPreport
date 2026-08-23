"""Write a JSON quality audit for WRLDC-referenced SQLite dimensions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from psp_pipeline.quality.wrldc_dimension_audit import audit_wrldc_dimensions


def main() -> None:
    """Parse CLI arguments and write the read-only WRLDC audit result."""

    parser = argparse.ArgumentParser(description="Audit WRLDC dimensions from SQLite.")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/sqlite/wrldc_anchor_scan.sqlite"),
        help="Path to the WRLDC anchor SQLite database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/diagnostics/wrldc_dimension_audit.json"),
        help="Destination path for JSON diagnostic output.",
    )
    args = parser.parse_args()

    result = audit_wrldc_dimensions(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Dimension audit written to {args.output}")


if __name__ == "__main__":
    main()
