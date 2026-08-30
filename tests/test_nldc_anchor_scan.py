"""Regression tests for the resumable Grid-India NLDC anchor scan."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from unittest.mock import patch

from psp_pipeline.quality.nldc_anchor_scan import scan_nldc_monthly_anchors
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


def test_nldc_anchor_scan_resumes_completed_local_path(tmp_path: Path) -> None:
    """A source-scoped persisted path is skipped without invoking a worker."""
    input_dir = tmp_path / "corpus"
    input_dir.mkdir()
    path = input_dir / "01-08-2026-nldc-psp.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    database = tmp_path / "scan.sqlite"
    connection = sqlite3.connect(str(database))
    ensure_curated_sqlite_schema(connection)
    connection.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY, rldc TEXT NOT NULL, local_path TEXT NOT NULL,
            report_date TEXT NOT NULL, template_id TEXT, semantic_pass_required INTEGER
        );
        INSERT INTO psp_report_document VALUES
            (1, 'grid_india_national', '{path}', '2026-08-01', NULL, 0);
        """
    )
    connection.close()

    with patch("psp_pipeline.quality.nldc_anchor_scan._ingest_anchor_with_timeout") as worker:
        summary = scan_nldc_monthly_anchors(input_dir, database)

    assert summary["outcome_counts"] == {"already_persisted": 1}
    assert summary["persisted_report_count"] == 1
    worker.assert_not_called()


def test_nldc_anchor_scan_isolates_one_failed_worker(tmp_path: Path) -> None:
    """One parser failure is reported while later anchors remain eligible."""
    input_dir = tmp_path / "corpus"
    input_dir.mkdir()
    for day in (1, 15):
        (input_dir / f"{day:02d}-08-2026-nldc-psp.pdf").write_bytes(b"%PDF-1.4\n")
    database = tmp_path / "scan.sqlite"

    with patch(
        "psp_pipeline.quality.nldc_anchor_scan._ingest_anchor_with_timeout",
        side_effect=[
            (None, "timed out after 10 seconds"),
            ({"reports_persisted": 1, "report_family_rejected": 0}, None),
        ],
    ):
        summary = scan_nldc_monthly_anchors(input_dir, database, timeout_seconds=10)

    assert summary["outcome_counts"] == {"failed": 1, "persisted": 1}
    assert summary["failed_reports"][0]["error"] == "timed out after 10 seconds"


def test_nldc_anchor_scan_gates_unverified_template(tmp_path: Path) -> None:
    """Reports rejected by family validation are recorded as gated, not promoted."""
    input_dir = tmp_path / "corpus"
    input_dir.mkdir()
    (input_dir / "01-08-2026-nldc-psp.pdf").write_bytes(b"%PDF-1.4\n")
    database = tmp_path / "scan.sqlite"

    with patch(
        "psp_pipeline.quality.nldc_anchor_scan._ingest_anchor_with_timeout",
        return_value=({"reports_persisted": 0, "report_family_rejected": 1}, None),
    ):
        summary = scan_nldc_monthly_anchors(input_dir, database)

    assert summary["outcome_counts"] == {"gated": 1}
    assert len(summary["gated_reports"]) == 1
    assert summary["gated_reports"][0]["report_name"] == "01-08-2026-nldc-psp.pdf"
