"""Regression coverage for NLDC raw-cell curated promotion."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.parsing.nldc_parser import extract_nldc_raw_cells
from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def nldc_pdf_path() -> Path:
    """Return the local public Grid-India NLDC PSP fixture."""

    return Path("downloads/NLDC_PSP/25-08-2026-nldc-psp.pdf")


@pytest.fixture
def in_memory_db() -> sqlite3.Connection:
    """Create raw and curated tables with foreign keys enabled."""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "CREATE TABLE psp_report_document("
        "id INTEGER PRIMARY KEY, rldc TEXT NOT NULL, local_path TEXT, "
        "report_date TEXT NOT NULL, template_id TEXT, "
        "semantic_pass_required INTEGER, structure_deviation_reason TEXT)"
    )
    conn.execute(
        "CREATE TABLE psp_raw_cell("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, report_document_id INTEGER NOT NULL, "
        "page_no INTEGER NOT NULL, table_no INTEGER NOT NULL, row_no INTEGER NOT NULL, "
        "col_no INTEGER NOT NULL, cell_text TEXT, extraction_method TEXT NOT NULL, "
        "extracted_at TEXT NOT NULL, "
        "FOREIGN KEY(report_document_id) REFERENCES psp_report_document(id))"
    )
    ensure_curated_sqlite_schema(conn)
    yield conn
    conn.close()


def test_nldc_raw_cell_promotion_preserves_document_and_cell_lineage(
    nldc_pdf_path: Path,
    in_memory_db: sqlite3.Connection,
) -> None:
    """Promote page-two summaries and page-three line flows from raw cells."""

    if not nldc_pdf_path.exists():
        pytest.skip(f"Fixture {nldc_pdf_path} not found")

    report_id = 100
    in_memory_db.execute(
        "INSERT INTO psp_report_document(id, rldc, report_date) VALUES (?, ?, ?)",
        (report_id, "grid_india_national", "2026-08-25"),
    )
    extracted_at = datetime.now(timezone.utc).isoformat()
    in_memory_db.executemany(
        "INSERT INTO psp_raw_cell("
        "report_document_id, page_no, table_no, row_no, col_no, cell_text, "
        "extraction_method, extracted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                report_id,
                cell.page_no,
                cell.table_no,
                cell.row_no,
                cell.col_no,
                cell.cell_text,
                cell.extraction_method,
                extracted_at,
            )
            for cell in extract_nldc_raw_cells(nldc_pdf_path)
        ],
    )

    promote_report_to_curated(in_memory_db, report_id)

    national = in_memory_db.execute("SELECT * FROM FactNLDCDailyNational").fetchone()
    assert national is not None
    assert national["EveningPeakDemandMetMW"] > 200000

    regional = in_memory_db.execute(
        "SELECT fact.* FROM FactNLDCDailyRegional fact "
        "JOIN DimRegions region ON region.RegionID = fact.RegionID "
        "WHERE region.RegionName = 'Northern Region'"
    ).fetchone()
    assert regional is not None
    assert regional["EveningPeakDemandMetMW"] > 50000

    frequency = in_memory_db.execute(
        "SELECT * FROM FactNLDCDailyFrequency"
    ).fetchone()
    assert frequency is not None
    assert frequency["FVI"] > 0

    exchange = in_memory_db.execute(
        "SELECT fact.*, element.ElementName "
        "FROM FactNLDCDailyInterRegionalExchange fact "
        "JOIN DimTransmissionElements element ON element.ElementID = fact.ElementID "
        "WHERE element.ElementName = 'ALIPURDUAR-AGRA'"
    ).fetchone()
    assert exchange is not None
    assert exchange["VoltageLevel"] == "HVDC"
    assert exchange["NetMU"] == pytest.approx(-7.2)

    lineage_count = in_memory_db.execute(
        "SELECT COUNT(*) FROM curated_field_lineage "
        "WHERE ReportDocumentID = ? AND RawCellID IS NOT NULL",
        (report_id,),
    ).fetchone()[0]
    assert lineage_count > 0


def test_nldc_fact_foreign_keys_follow_raw_document_contract() -> None:
    """The normal schema initializer creates NLDC facts after raw persistence."""

    conn = sqlite3.connect(":memory:")
    try:
        ensure_sqlite_schema(conn)
        for table_name in (
            "FactNLDCDailyNational",
            "FactNLDCDailyRegional",
            "FactNLDCDailyFrequency",
            "FactNLDCDailyInterRegionalExchange",
        ):
            foreign_tables = {
                str(row[2])
                for row in conn.execute(f"PRAGMA foreign_key_list({table_name})")
            }
            assert "psp_report_document" in foreign_tables
    finally:
        conn.close()
