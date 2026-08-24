"""Unit tests for the NERLDC-scoped dimension quality audit."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.quality.nerldc_dimension_audit import audit_nerldc_dimensions
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def mixed_nerldc_curated_db(tmp_path: Path) -> Path:
    """Create a database with NERLDC report document and facts."""
    db_path = tmp_path / "mixed_nerldc.sqlite"
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
        VALUES (1, 'nerldc', '2025-04-15', 'NER-PSP-REPORT-DATED-15-04-2025.pdf', 1);

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate)
        VALUES (1, '2025-04-15');

        CREATE TABLE IF NOT EXISTS FactNERLDCStateDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            ConsumptionMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID)
        );

        CREATE TABLE IF NOT EXISTS FactNERLDCGenerationDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            StateID INTEGER,
            StationID INTEGER,
            SectionName TEXT NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, SectionName)
        );

        CREATE TABLE IF NOT EXISTS FactNERLDCVoltageProfile (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            VoltageNodeID INTEGER NOT NULL,
            MaximumKV REAL,
            MinimumKV REAL,
            PRIMARY KEY(ReportDocumentID, DateID, VoltageNodeID)
        );

        CREATE TABLE IF NOT EXISTS FactNERLDCReservoirDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ReservoirID INTEGER NOT NULL,
            CurrentLevelM REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ReservoirID)
        );

        CREATE TABLE IF NOT EXISTS FactNERLDCInterRegionalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ElementID INTEGER NOT NULL,
            NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ElementID)
        );

        CREATE TABLE IF NOT EXISTS FactNERLDCInternationalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            CountryID INTEGER NOT NULL,
            NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, CountryID)
        );
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_audit_nerldc_dimensions_nonexistent_file() -> None:
    with pytest.raises(FileNotFoundError):
        audit_nerldc_dimensions(Path("nonexistent_db.sqlite"))


def test_audit_nerldc_dimensions_no_nerldc_reports(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_curated_sqlite_schema(conn)
    conn.close()

    with pytest.raises(ValueError, match="0 NERLDC report documents"):
        audit_nerldc_dimensions(db_path)


def test_audit_nerldc_dimensions_summary(mixed_nerldc_curated_db: Path) -> None:
    result = audit_nerldc_dimensions(mixed_nerldc_curated_db)
    assert result["nerldc_reports_found"] == 1
    assert "summary" in result
    assert result["summary"]["dim_states_count"] >= 0
    assert result["summary"]["states_unresolved_region_count"] == 0


def test_audit_nerldc_dimensions_includes_exchange_topology_and_country(
    tmp_path: Path,
) -> None:
    """The audit reads the live endpoint and country dimension contracts."""

    db_path = tmp_path / "nerldc_exchange_audit.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_curated_sqlite_schema(conn)
    conn.execute(
        "CREATE TABLE psp_report_document ("
        "id INTEGER PRIMARY KEY, rldc TEXT NOT NULL, report_date TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO psp_report_document(id, rldc, report_date) "
        "VALUES (1, 'nerldc', '2025-01-01')"
    )
    conn.execute("INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2025-01-01')")
    ner_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'North Eastern Region'"
    ).fetchone()[0]
    eastern_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Eastern Region'"
    ).fetchone()[0]
    assam_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Assam'"
    ).fetchone()[0]
    west_bengal_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'West Bengal'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO DimTransmissionElements("
        "ElementID, ElementName, ElementType, FromRegionID, ToRegionID, "
        "FromStateID, ToStateID, FromCountryID, ToCountryID) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            "400KV-BONGAIGAON-ALIPURDUAR-1",
            "line",
            ner_region_id,
            eastern_region_id,
            assam_state_id,
            west_bengal_state_id,
            None,
            None,
        ),
    )
    conn.execute("INSERT OR IGNORE INTO DimCountries(CountryName) VALUES ('Bhutan')")
    bhutan_country_id = conn.execute(
        "SELECT CountryID FROM DimCountries WHERE CountryName = 'Bhutan'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO FactNERLDCInterRegionalExchange("
        "ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU) "
        "VALUES (1, 1, 1, 'Eastern Region', 12.5)"
    )
    conn.execute(
        "INSERT INTO FactNERLDCInternationalExchange("
        "ReportDocumentID, DateID, CountryID, CounterpartyCountry, NetEnergyMU) "
        "VALUES (1, 1, ?, 'Bhutan', 4.5)",
        (bhutan_country_id,),
    )
    conn.commit()
    conn.close()

    result = audit_nerldc_dimensions(db_path)

    assert result["summary"]["dim_transmission_elements_count"] == 1
    assert result["summary"]["dim_countries_count"] == 1
    assert result["summary"]["transmission_elements_unresolved_region_count"] == 0
    assert result["summary"]["transmission_elements_unresolved_state_count"] == 0
