"""Re-promote eligible SRLDC reports from persisted SQLite raw cells."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.storage.sqlite_curated_promoter import repromote_srldc_reports
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


def main() -> None:
    """Refresh curated facts and coverage for an existing SRLDC SQLite database."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    if not args.db.exists():
        parser.error(f"SQLite database does not exist: {args.db}")

    configure_logging()
    with sqlite3.connect(args.db) as conn:
        ensure_curated_sqlite_schema(conn)
        result = repromote_srldc_reports(conn)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
