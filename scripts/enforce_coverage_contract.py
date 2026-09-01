"""Enforce a named raw-cell coverage profile against a curated SQLite replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.coverage_contract import (
    default_coverage_manifest_path,
    enforce_coverage_manifest,
)


def main() -> int:
    """Fail when the selected coverage profile regresses below its floor."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=default_coverage_manifest_path())
    parser.add_argument("--profile", default="synthetic")
    parser.add_argument("--require-source", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    results = enforce_coverage_manifest(
        args.db,
        args.manifest,
        profile_name=args.profile,
        require_sources=args.require_source or None,
    )
    payload = {
        name: result.as_dict() for name, result in results.items()
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
