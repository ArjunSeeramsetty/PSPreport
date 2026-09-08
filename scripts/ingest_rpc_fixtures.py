"""Ingest committed local RPC settlement fixtures into curated SQLite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.rpc_fixtures import (
    default_rpc_fixture_dir,
    ensure_canonical_rpc_fixtures,
    ingest_rpc_fixture_reports,
)


def main() -> int:
    """Write canonical RPC workbooks if needed, then persist and promote them."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "sqlite" / "rpc_fixtures.sqlite",
    )
    parser.add_argument("--fixture-dir", type=Path, default=default_rpc_fixture_dir())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    ensure_canonical_rpc_fixtures(args.fixture_dir)
    payload = ingest_rpc_fixture_reports(args.db, fixture_dir=args.fixture_dir)
    text = json.dumps(payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
