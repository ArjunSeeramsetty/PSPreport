"""Unit tests for NERLDC curated coverage report generator."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.quality.nerldc_coverage_report import generate_nerldc_coverage_report
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def mock_nerldc_coverage_db(tmp_path: Path) -> Path:
    """Create a database with a mix of promoted and unpromoted reports."""
    db_path = tmp_path / "mock_nerldc_coverage.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_curated_sqlite_schema(conn)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rldc TEXT NOT NULL,
            report_date TEXT NOT NULL,
            template_id TEXT,
            semantic_pass_required INTEGER DEFAULT 0
        );

        INSERT INTO psp_report_document(id, rldc, report_date, template_id, semantic_pass_required)
        VALUES
            (1, 'nerldc', '2025-01-01', 'nerldc_daily_psp_v2025_standard_10_column_generation', 0),
            (2, 'nerldc', '2025-01-15', 'nerldc_daily_psp_v2025_standard_10_column_generation', 0),
            (3, 'nerldc', '2023-04-15', 'nerldc_daily_psp_v2023_standard_09_column_generation', 1);

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2025-01-01'), (2, '2025-01-15'), (3, '2023-04-15');

        -- Fact rows for report 1 and 2 only
        INSERT INTO FactNERLDCRegionalDaily(ReportDocumentID, DateID, RegionID, DayEnergyMetMU)
        VALUES (1, 1, 5, 45.0), (2, 2, 5, 46.0);

        INSERT INTO FactNERLDCStateDaily(ReportDocumentID, DateID, StateID, DemandMetMU)
        VALUES (1, 1, 33, 20.0), (2, 2, 33, 21.0);

        INSERT INTO FactNERLDCGenerationDaily(ReportDocumentID, DateID, EntityID, StateID, StationID, NetEnergyMU, SectionName)
        VALUES (1, 1, 1, 33, 1, 10.0, 'state_gen'), (2, 2, 1, 33, 1, 11.0, 'state_gen');

        INSERT INTO FactNERLDCFrequencyDaily(ReportDocumentID, DateID, RegionID, AverageFrequencyHz)
        VALUES (1, 1, 5, 50.0);

        INSERT INTO curated_field_lineage(ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt)
        VALUES (1, 'FactNERLDCRegionalDaily', 'k1', 'DayEnergyMetMU', 101, 'pdfplumber', 1.0, '2026-08-25T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_generate_nerldc_coverage_report(mock_nerldc_coverage_db: Path) -> None:
    report = generate_nerldc_coverage_report(mock_nerldc_coverage_db)

    assert report["total_raw_reports"] == 3
    assert report["total_curated_reports"] == 2
    assert report["overall_promotion_rate_pct"] == 66.67
    assert report["total_lineage_records"] == 1

    # Check section breakdown
    sections = {s["fact_table"]: s for s in report["sections"]}
    assert sections["FactNERLDCRegionalDaily"]["total_rows"] == 2
    assert sections["FactNERLDCRegionalDaily"]["distinct_reports"] == 2
    assert sections["FactNERLDCRegionalDaily"]["report_coverage_pct"] == 66.67
    assert sections["FactNERLDCStateDaily"]["total_rows"] == 2
    assert sections["FactNERLDCGenerationDaily"]["total_rows"] == 2
    assert sections["FactNERLDCFrequencyDaily"]["total_rows"] == 1
    assert sections["FactNERLDCVoltageProfile"]["total_rows"] == 0
    assert "FactNERLDCReservoirDaily" not in sections

    # Check template breakdown
    templates = {t["template_id"]: t for t in report["templates"]}
    assert "nerldc_daily_psp_v2025_standard_10_column_generation" in templates
    assert templates["nerldc_daily_psp_v2025_standard_10_column_generation"]["total_reports"] == 2
    assert templates["nerldc_daily_psp_v2025_standard_10_column_generation"]["promoted_reports"] == 2
    assert templates["nerldc_daily_psp_v2025_standard_10_column_generation"]["promotion_rate_pct"] == 100.0


def test_generate_nerldc_coverage_report_empty_db(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_curated_sqlite_schema(conn)
    conn.close()

    report = generate_nerldc_coverage_report(db_path)
    assert report["total_raw_reports"] == 0
    assert report["total_curated_reports"] == 0
    assert report["overall_promotion_rate_pct"] == 0.0


def test_generate_nerldc_coverage_report_nonexistent_db() -> None:
    with pytest.raises(FileNotFoundError):
        generate_nerldc_coverage_report(Path("nonexistent_file.sqlite"))
