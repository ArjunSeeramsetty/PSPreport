"""Thin CLI wrapper for auditing NERLDC-referenced dimension quality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.nerldc_dimension_audit import audit_nerldc_dimensions


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit NERLDC dimensions from SQLite.")
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "sqlite" / "nerldc_anchor_scan.sqlite",
        help="Path to NERLDC anchor SQLite database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "nerldc_dimension_audit.json",
        help="Path to write the JSON audit report.",
    )
    args = parser.parse_args()

    audit = audit_nerldc_dimensions(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(f"NERLDC dimension audit written to {args.output}")


if __name__ == "__main__":
    main()
