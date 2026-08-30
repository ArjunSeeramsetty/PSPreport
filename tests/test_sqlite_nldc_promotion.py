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
    assert national["PeakShortageMW"] == pytest.approx(2083.0)

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
    assert in_memory_db.execute(
        "SELECT COUNT(*) FROM DimTransmissionElements WHERE ElementName = 'ER'"
    ).fetchone()[0] == 0

    lineage_count = in_memory_db.execute(
        "SELECT COUNT(*) FROM curated_field_lineage "
        "WHERE ReportDocumentID = ? AND RawCellID IS NOT NULL",
        (report_id,),
    ).fetchone()[0]
    assert lineage_count > 0

    snapshots = in_memory_db.execute(
        "SELECT * FROM FactNLDC15MinuteGridSnapshot ORDER BY BlockStartTime"
    ).fetchall()
    assert len(snapshots) == 96
    assert snapshots[0]["BlockStartTime"] == "00:00"
    assert snapshots[0]["FrequencyHz"] is not None
    assert snapshots[0]["StorageDemandMW"] is not None
    assert snapshots[0]["StorageGenerationMW"] is not None
    assert in_memory_db.execute(
        "SELECT COUNT(*) FROM curated_field_lineage "
        "WHERE ReportDocumentID = ? "
        "AND DestinationTable = 'FactNLDC15MinuteGridSnapshot'",
        (report_id,),
    ).fetchone()[0] >= 96 * 10

    cross_border = in_memory_db.execute(
        "SELECT fact.* FROM FactNLDCCrossBorderExchangeDaily AS fact "
        "JOIN DimCountries AS country ON country.CountryID = fact.CountryID "
        "WHERE country.CountryName = 'Bangladesh' AND fact.Direction = 'export'"
    ).fetchone()
    assert cross_border is not None
    assert cross_border["GNAMU"] == pytest.approx(22.98)
    assert cross_border["TGNABilateralMU"] == pytest.approx(0.24)
    assert cross_border["TotalMU"] == pytest.approx(23.22)
    assert in_memory_db.execute(
        "SELECT COUNT(*) FROM FactNLDCCrossBorderExchangeDaily"
    ).fetchone()[0] == 15


@pytest.mark.parametrize(
    ("filename", "report_date", "maximum_demand_mw", "maximum_od_mw", "maximum_ud_mw"),
    [
        ("01.04.23_NLDC_PSP.pdf", "2023-04-01", 5839.0, 222.0, None),
        ("01.04.25_NLDC_PSP.pdf", "2025-04-01", 7420.0, 623.0, None),
        ("25-08-2026-nldc-psp.pdf", "2026-08-25", 16194.0, 887.0, -680.0),
    ],
)
def test_nldc_control_area_drawal_promotes_across_layout_epochs(
    filename: str,
    report_date: str,
    maximum_demand_mw: float,
    maximum_od_mw: float,
    maximum_ud_mw: float | None,
    in_memory_db: sqlite3.Connection,
) -> None:
    """Promote the stable control-area matrix across page and column variants."""

    pdf_path = Path("downloads/NLDC_PSP") / filename
    if not pdf_path.exists():
        pytest.skip(f"Fixture {pdf_path} not found")
    report_id = 200
    in_memory_db.execute(
        "INSERT INTO psp_report_document(id, rldc, report_date) VALUES (?, ?, ?)",
        (report_id, "grid_india_national", report_date),
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
            for cell in extract_nldc_raw_cells(pdf_path)
        ],
    )

    promote_report_to_curated(in_memory_db, report_id)

    punjab = in_memory_db.execute(
        "SELECT fact.* FROM FactNLDCDailyControlAreaDrawal AS fact "
        "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID "
        "WHERE fact.ReportDocumentID = ? AND entity.EntityName = 'Punjab'",
        (report_id,),
    ).fetchone()
    assert punjab is not None
    assert punjab["MaximumDemandMetMW"] == pytest.approx(maximum_demand_mw)
    assert punjab["MaximumOverDrawalMW"] == pytest.approx(maximum_od_mw)
    if maximum_ud_mw is None:
        assert punjab["MaximumUnderDrawalMW"] is None
    else:
        assert punjab["MaximumUnderDrawalMW"] == pytest.approx(maximum_ud_mw)
    assert in_memory_db.execute(
        "SELECT COUNT(*) FROM FactNLDCDailyControlAreaDrawal "
        "WHERE ReportDocumentID = ?",
        (report_id,),
    ).fetchone()[0] >= 37
    assert in_memory_db.execute(
        "SELECT COUNT(*) FROM curated_field_lineage "
        "WHERE ReportDocumentID = ? "
        "AND DestinationTable = 'FactNLDCDailyControlAreaDrawal'",
        (report_id,),
    ).fetchone()[0] > 0


def test_nldc_2025_grid_snapshots_preserve_absent_storage_columns(
    in_memory_db: sqlite3.Connection,
) -> None:
    """The pre-storage 13-column snapshot contract must not fabricate fields."""

    pdf_path = Path("downloads/NLDC_PSP/01.04.25_NLDC_PSP.pdf")
    if not pdf_path.exists():
        pytest.skip(f"Fixture {pdf_path} not found")
    report_id = 300
    in_memory_db.execute(
        "INSERT INTO psp_report_document(id, rldc, report_date) VALUES (?, ?, ?)",
        (report_id, "grid_india_national", "2025-04-01"),
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
            for cell in extract_nldc_raw_cells(pdf_path)
        ],
    )

    promote_report_to_curated(in_memory_db, report_id)

    rows = in_memory_db.execute(
        "SELECT * FROM FactNLDC15MinuteGridSnapshot "
        "WHERE ReportDocumentID = ? ORDER BY BlockStartTime",
        (report_id,),
    ).fetchall()
    assert len(rows) == 96
    assert rows[0]["BlockStartTime"] == "00:00"
    assert rows[0]["StorageDemandMW"] is None
    assert rows[0]["StorageGenerationMW"] is None
    assert rows[0]["TotalGenerationMW"] is not None


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
            "FactNLDCDailyControlAreaDrawal",
            "FactNLDC15MinuteGridSnapshot",
            "FactNLDCCrossBorderExchangeDaily",
        ):
            foreign_tables = {
                str(row[2])
                for row in conn.execute(f"PRAGMA foreign_key_list({table_name})")
            }
            assert "psp_report_document" in foreign_tables
    finally:
        conn.close()
