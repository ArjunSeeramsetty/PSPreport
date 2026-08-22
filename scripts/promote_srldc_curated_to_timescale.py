"""Promote curated SRLDC daily SQLite facts into TimescaleDB observations."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from psp_pipeline.core.settings import load_settings
from psp_pipeline.storage.postgres_repo import PostgresRepository
from psp_pipeline.storage.sqlite_curated_export import export_srldc_daily_observations


def main() -> None:
    """Export local curated facts and append them to the configured TimescaleDB."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Curated SRLDC SQLite database")
    parser.add_argument("--report-id", type=int, help="Optional psp_report_document id")
    args = parser.parse_args()

    with sqlite3.connect(args.db) as conn:
        facts = export_srldc_daily_observations(conn, args.report_id)
    if not facts:
        return
    settings = load_settings()
    PostgresRepository(settings.postgres_dsn).upsert_fact_observations(facts)


if __name__ == "__main__":
    main()
