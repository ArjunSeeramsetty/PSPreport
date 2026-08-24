"""Unit tests for the national 5-RLDC dimension quality audit."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.quality.national_dimension_audit import audit_national_dimensions
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def national_multi_rldc_db(tmp_path: Path) -> Path:
    """Create a database with multiple RLDCs to test aggregated national auditing."""
    db_path = tmp_path / "national_curated.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_curated_sqlite_schema(conn)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rldc TEXT NOT NULL,
            report_date TEXT NOT NULL,
            filename TEXT,
            is_valid INTEGER
        );

        INSERT INTO psp_report_document(id, rldc, report_date, filename, is_valid)
        VALUES
            (1, 'srldc', '2025-01-01', 'SRLDC_PSP_01_01_2025.pdf', 1),
            (2, 'nerldc', '2025-01-01', 'NER-PSP-REPORT-DATED-01-01-2025.pdf', 1);

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2025-01-01');

        -- SRLDC Fact references
        INSERT INTO FactSRLDCStateDaily(ReportDocumentID, DateID, StateID, DemandMetMU)
        VALUES (1, 1, (SELECT StateID FROM DimStates WHERE StateName = 'Karnataka'), 250.0);

        -- NERLDC Fact references
        INSERT INTO FactNERLDCStateDaily(ReportDocumentID, DateID, StateID, DemandMetMU)
        VALUES (2, 1, (SELECT StateID FROM DimStates WHERE StateName = 'Assam'), 28.2);

        INSERT INTO FactNERLDCVoltageProfile(ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV, MinimumKV)
        VALUES (2, 1, 1, 400.0, 415.0, 398.0);
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_audit_national_dimensions_aggregates_summary(
    national_multi_rldc_db: Path,
) -> None:
    report = audit_national_dimensions(national_multi_rldc_db)

    assert "national_summary" in report
    summary = report["national_summary"]
    assert "srldc" in summary["active_rldcs"]
    assert "nerldc" in summary["active_rldcs"]
    assert summary["total_reports_found"] == 2
    assert summary["total_states_count"] >= 2
    assert "regional_breakdowns" in report
    assert "srldc" in report["regional_breakdowns"]
    assert "nerldc" in report["regional_breakdowns"]


def test_audit_national_dimensions_raises_when_no_rldcs(tmp_path: Path) -> None:
    empty_db = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(empty_db)
    ensure_curated_sqlite_schema(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS psp_report_document (id INTEGER PRIMARY KEY, rldc TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="No supported RLDC reports found"):
        audit_national_dimensions(empty_db)


def test_audit_national_dimensions_nonexistent_file() -> None:
    with pytest.raises(FileNotFoundError):
        audit_national_dimensions(Path("nonexistent_db.sqlite"))
