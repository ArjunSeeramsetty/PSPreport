"""Unit tests for ERLDC monthly-anchor scanning."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from psp_pipeline.quality.rldc_anchor_scan import (
    scan_erldc_monthly_anchors,
    scan_rldc_monthly_anchors,
)
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


def test_scan_erldc_monthly_anchors_empty_dir(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    db_path = tmp_path / "erldc_test.sqlite"

    result = scan_erldc_monthly_anchors(empty_dir, db_path)
    assert result["rldc"] == "erldc"
    assert result["anchor_count"] == 0
    assert result["persisted_report_count"] == 0
    assert result["failed_reports"] == []


def test_scan_erldc_monthly_anchors_skips_persisted(tmp_path: Path) -> None:
    input_dir = tmp_path / "reports"
    input_dir.mkdir()
    sample_pdf = input_dir / "Power Supply Position Report_15042025.pdf"
    sample_pdf.write_bytes(b"%PDF-1.4 dummy")

    db_path = tmp_path / "erldc_test.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_curated_sqlite_schema(conn)
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rldc TEXT NOT NULL,
            report_date TEXT NOT NULL,
            filename TEXT NOT NULL,
            local_path TEXT NOT NULL
        );
        INSERT INTO psp_report_document(rldc, report_date, filename, local_path)
        VALUES ('erldc', '2025-04-15', '{sample_pdf.name}', '{sample_pdf.resolve()}');
        """
    )
    conn.close()

    result = scan_rldc_monthly_anchors(input_dir, db_path, rldc="erldc")
    assert result["anchor_count"] == 1
    assert result["outcome_counts"]["already_persisted"] == 1
    assert result["failed_reports"] == []
