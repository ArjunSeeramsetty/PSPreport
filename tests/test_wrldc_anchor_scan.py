"""Regression tests for the resumable WRLDC anchor scan."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from unittest.mock import patch

from psp_pipeline.quality.rldc_anchor_scan import scan_rldc_monthly_anchors
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


def test_wrldc_anchor_scan_resumes_completed_local_path(tmp_path: Path) -> None:
    """A source-scoped persisted path is skipped without invoking a worker."""

    input_dir = tmp_path / "corpus"
    input_dir.mkdir()
    path = input_dir / "WRLDC_PSP_Report_01-01-2024.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    database = tmp_path / "scan.sqlite"
    connection = sqlite3.connect(database)
    ensure_curated_sqlite_schema(connection)
    connection.executescript(
        f"""
        CREATE TABLE psp_report_document (
            id INTEGER PRIMARY KEY, rldc TEXT NOT NULL, local_path TEXT NOT NULL,
            report_date TEXT NOT NULL, template_id TEXT, semantic_pass_required INTEGER
        );
        INSERT INTO psp_report_document VALUES
            (1, 'wrldc', '{path}', '2024-01-01', NULL, 0);
        """
    )
    connection.close()

    with patch("psp_pipeline.quality.rldc_anchor_scan._ingest_anchor_with_timeout") as worker:
        summary = scan_rldc_monthly_anchors(input_dir, database, rldc="wrldc")

    assert summary["outcome_counts"] == {"already_persisted": 1}
    assert summary["persisted_report_count"] == 1
    worker.assert_not_called()


def test_wrldc_anchor_scan_isolates_one_failed_worker(tmp_path: Path) -> None:
    """One parser failure is reported while later anchors remain eligible."""

    input_dir = tmp_path / "corpus"
    input_dir.mkdir()
    for day in (1, 15):
        (input_dir / f"WRLDC_PSP_Report_{day:02d}-01-2024.pdf").write_bytes(b"%PDF-1.4\n")
    database = tmp_path / "scan.sqlite"

    with patch(
        "psp_pipeline.quality.rldc_anchor_scan._ingest_anchor_with_timeout",
        side_effect=[(None, "timed out after 10 seconds"), ({"reports_persisted": 1, "report_family_rejected": 0}, None)],
    ):
        summary = scan_rldc_monthly_anchors(input_dir, database, rldc="wrldc", timeout_seconds=10)

    assert summary["outcome_counts"] == {"failed": 1, "persisted": 1}
    assert summary["failed_reports"][0]["error"] == "timed out after 10 seconds"
