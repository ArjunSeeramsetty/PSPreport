"""Unit tests for ERLDC curated coverage report generator."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.quality.erldc_coverage_report import generate_erldc_coverage_report
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def mock_erldc_coverage_db(tmp_path: Path) -> Path:
    """Create a database with a mix of promoted flat reports and gated split reports."""

    db_path = tmp_path / "mock_erldc_coverage.sqlite"
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
            (1, 'erldc', '2024-04-15', 'erldc_daily_psp_v2024_flat_09_column_generation', 0),
            (2, 'erldc', '2024-05-15', 'erldc_daily_psp_v2024_flat_09_column_generation', 0),
            (3, 'erldc', '2025-01-15', 'erldc_daily_psp_v2025_split_10_column_generation', 1);

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2024-04-15'), (2, '2024-05-15'), (3, '2025-01-15');

        -- Fact rows for report 1 and 2 only
        INSERT INTO FactERLDCRegionalDaily(ReportDocumentID, DateID, RegionID, DayEnergyMetMU)
        VALUES (1, 1, 1, 500.0), (2, 2, 1, 510.0);

        INSERT INTO FactERLDCStateDaily(ReportDocumentID, DateID, StateID, ConsumptionMU)
        VALUES (1, 1, 1, 100.0), (2, 2, 1, 105.0);

        INSERT INTO FactERLDCGenerationDaily(ReportDocumentID, DateID, EntityID, StateID, AggregateID, GrossEnergyMU, SectionName)
        VALUES (1, 1, 1, 1, 1, 45.0, 'thermal'), (2, 2, 1, 1, 1, 46.0, 'thermal');

        INSERT INTO FactERLDCFrequencyDaily(ReportDocumentID, DateID, RegionID, AverageFrequencyHz)
        VALUES (1, 1, 1, 50.0);

        INSERT INTO FactERLDCReservoirDaily(ReportDocumentID, DateID, ReservoirID, CurrentLevelM)
        VALUES (1, 1, 1, 140.0);

        INSERT INTO curated_field_lineage(ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt)
        VALUES (1, 'FactERLDCRegionalDaily', 'k1', 'DayEnergyMetMU', 101, 'pdfplumber', 1.0, '2026-08-24T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_generate_erldc_coverage_report(mock_erldc_coverage_db: Path) -> None:
    report = generate_erldc_coverage_report(mock_erldc_coverage_db)

    assert report["total_raw_reports"] == 3
    assert report["total_curated_reports"] == 2
    assert report["overall_promotion_rate_pct"] == 66.67
    assert report["total_lineage_records"] == 1

    # Check sections
    sections = {s["fact_table"]: s for s in report["sections"]}
    assert sections["FactERLDCRegionalDaily"]["total_rows"] == 2
    assert sections["FactERLDCRegionalDaily"]["distinct_reports"] == 2
    assert sections["FactERLDCRegionalDaily"]["report_coverage_pct"] == 66.67
    assert sections["FactERLDCVoltageProfile"]["total_rows"] == 0

    # Check templates
    templates = {t["template_id"]: t for t in report["templates"]}
    flat = templates["erldc_daily_psp_v2024_flat_09_column_generation"]
    assert flat["total_reports"] == 2
    assert flat["promoted_reports"] == 2
    assert flat["gated_reports"] == 0
    assert flat["promotion_rate_pct"] == 100.0

    split = templates["erldc_daily_psp_v2025_split_10_column_generation"]
    assert split["total_reports"] == 1
    assert split["promoted_reports"] == 0
    assert split["gated_reports"] == 1
    assert split["promotion_rate_pct"] == 0.0


def test_coverage_report_empty_db(tmp_path: Path) -> None:
    empty_db = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(empty_db)
    ensure_curated_sqlite_schema(conn)
    conn.close()

    report = generate_erldc_coverage_report(empty_db)
    assert report["total_raw_reports"] == 0
    assert report["total_curated_reports"] == 0
    assert report["overall_promotion_rate_pct"] == 0.0


def test_coverage_report_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        generate_erldc_coverage_report("nonexistent.sqlite")
