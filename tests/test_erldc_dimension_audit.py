"""Unit tests for the ERLDC-scoped dimension quality audit."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.quality.erldc_dimension_audit import audit_erldc_dimensions
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def mixed_rldc_curated_db(tmp_path: Path) -> Path:
    """Create a database whose ERLDC and WRLDC dimensions are disjoint."""

    db_path = tmp_path / "mixed_erldc.sqlite"
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
            (1, 'erldc', '2025-04-15', 'Power Supply Position Report_15042025.pdf', 1),
            (2, 'wrldc', '2025-04-15', 'WRLDC_PSP_Report_15-04-2025.pdf', 1);

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate)
        VALUES (1, '2025-04-15');

        CREATE TABLE IF NOT EXISTS FactERLDCStateDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            ConsumptionMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCGenerationDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            StateID INTEGER,
            StationID INTEGER,
            SectionName TEXT NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, SectionName)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCVoltageProfile (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            VoltageNodeID INTEGER NOT NULL,
            NominalVoltageKV REAL,
            MaximumKV REAL,
            PRIMARY KEY(ReportDocumentID, DateID, VoltageNodeID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCReservoirDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ReservoirID INTEGER NOT NULL,
            CurrentLevelM REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ReservoirID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCInterRegionalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ElementID INTEGER NOT NULL,
            NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ElementID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCInternationalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            CountryID INTEGER NOT NULL,
            NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, CountryID)
        );
        """
    )
    er_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Eastern Region'"
    ).fetchone()[0]
    wr_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Western Region'"
    ).fetchone()[0]
    wb_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'West Bengal'"
    ).fetchone()[0]
    mh_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Maharashtra'"
    ).fetchone()[0]
    bhutan_id = conn.execute(
        "SELECT CountryID FROM DimCountries WHERE CountryName = 'Bhutan'"
    ).fetchone()[0]

    conn.executescript(
        f"""
        INSERT INTO DimGridEntities(
            EntityID, EntityName, EntityType, StateID, RegionID
        ) VALUES
            (1, 'FSTPS', 'power_station', {wb_state_id}, {er_region_id}),
            (2, 'KORADI_TPS', 'power_station', {mh_state_id}, {wr_region_id});

        INSERT INTO DimVoltageNodes(
            VoltageNodeID, NodeName, NominalVoltageKV, StateID, RegionID
        ) VALUES
            (1, 'JEERAT_400', 400.0, {wb_state_id}, {er_region_id}),
            (2, 'PADGHE_765', 765.0, {mh_state_id}, {wr_region_id});

        INSERT INTO DimReservoirs(ReservoirID, ReservoirName, StateID, RegionID)
        VALUES
            (1, 'MAITHON', {wb_state_id}, {er_region_id}),
            (2, 'KOYNA', {mh_state_id}, {wr_region_id});

        INSERT INTO DimTransmissionElements(
            ElementID, ElementName, ElementType, FromRegionID, ToRegionID,
            FromStateID, ToStateID
        ) VALUES
            (1, '400KV_BINAGURI_BONGAIGAON', 'line', {er_region_id}, {er_region_id},
             {wb_state_id}, {wb_state_id}),
            (2, '765KV_PADGHE_KARJAT', 'line', {wr_region_id}, {wr_region_id},
             {mh_state_id}, {mh_state_id});

        INSERT INTO FactERLDCStateDaily(
            ReportDocumentID, DateID, StateID, ConsumptionMU
        ) VALUES (1, 1, {wb_state_id}, 184.5);
        INSERT INTO FactERLDCGenerationDaily(
            ReportDocumentID, DateID, EntityID, StateID, StationID, SectionName
        ) VALUES (1, 1, 1, {wb_state_id}, 1, 'thermal');
        INSERT INTO FactERLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV
        ) VALUES (1, 1, 1, 400.0, 412.0);
        INSERT INTO FactERLDCReservoirDaily(
            ReportDocumentID, DateID, ReservoirID, CurrentLevelM
        ) VALUES (1, 1, 1, 145.2);
        INSERT INTO FactERLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU
        ) VALUES (1, 1, 1, 'NER', 12.5);
        INSERT INTO FactERLDCInternationalExchange(
            ReportDocumentID, DateID, CountryID, CounterpartyCountry, NetEnergyMU
        ) VALUES (1, 1, {bhutan_id}, 'Bhutan', 8.2);

        INSERT INTO FactWRLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV
        ) VALUES (2, 1, 2, 765.0, 780.0);
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_audit_erldc_dimensions_scopes_to_erldc_facts_only(
    mixed_rldc_curated_db: Path,
) -> None:
    """Only dimensions referenced by ERLDC facts are reported."""

    audit = audit_erldc_dimensions(mixed_rldc_curated_db)

    assert audit["erldc_reports_found"] == 1
    assert audit["summary"]["dim_states_count"] == 1
    assert audit["summary"]["dim_grid_entities_count"] == 1
    assert audit["summary"]["dim_voltage_nodes_count"] == 1
    assert audit["summary"]["dim_reservoirs_count"] == 1
    assert audit["summary"]["dim_transmission_elements_count"] == 1
    assert audit["summary"]["dim_countries_count"] == 1
    assert audit["voltage_nodes"]["ids"] == [1]
    assert audit["reservoirs"]["ids"] == [1]
    assert audit["transmission_elements"]["ids"] == [1]
    assert "PADGHE_765" not in str(audit)
    assert "KOYNA" not in str(audit)


def test_audit_erldc_dimensions_raises_when_no_erldc_documents(
    tmp_path: Path,
) -> None:
    """An audit cannot silently fall back to another RLDC's facts."""

    db_path = tmp_path / "wrldc_only.sqlite"
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
        VALUES (1, 'wrldc', '2025-04-15', 'WRLDC_PSP_Report_15-04-2025.pdf', 1);
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="contains 0 ERLDC report documents"):
        audit_erldc_dimensions(db_path)


def test_audit_erldc_dimensions_raises_for_missing_database(tmp_path: Path) -> None:
    """A missing database produces an explicit, actionable error."""

    with pytest.raises(FileNotFoundError, match="not found"):
        audit_erldc_dimensions(tmp_path / "missing.sqlite")


def test_audit_separates_topology_enrichment_from_dimension_failures(
    mixed_rldc_curated_db: Path,
) -> None:
    """PSP-only labels do not become false dimension-quality failures."""
    conn = sqlite3.connect(mixed_rldc_curated_db)
    bihar_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Bihar'"
    ).fetchone()[0]
    er_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Eastern Region'"
    ).fetchone()[0]
    conn.executescript(
        f"""
        INSERT INTO DimGridEntities(
            EntityID, EntityName, EntityType, StateID, RegionID
        ) VALUES (3, 'KAHALGAON_STPS', 'power_station', {bihar_id}, {er_region_id});
        INSERT INTO FactERLDCGenerationDaily(
            ReportDocumentID, DateID, EntityID, StateID, StationID, SectionName
        ) VALUES (1, 1, 3, {bihar_id}, 3, 'thermal');

        INSERT INTO DimVoltageNodes(
            VoltageNodeID, NodeName, NominalVoltageKV, RegionID
        ) VALUES (3, 'UNMAPPED_ER_400', 400.0, {er_region_id});
        INSERT INTO FactERLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV
        ) VALUES (1, 1, 3, 400.0, 408.0);

        INSERT INTO DimTransmissionElements(
            ElementID, ElementName, ElementType, NominalVoltageKV
        ) VALUES (3, '400KV_UNKNOWN_ER_LINK', 'line', 400.0);
        INSERT INTO FactERLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU
        ) VALUES (1, 1, 3, 'NR', 5.0);
        """
    )
    conn.commit()
    conn.close()

    audit = audit_erldc_dimensions(mixed_rldc_curated_db)

    assert audit["grid_entities"]["duplicates"] == []
    assert audit["voltage_nodes"]["unresolved_state"] == []
    assert audit["transmission_elements"]["unresolved_region"] == []
    assert audit["transmission_elements"]["unresolved_state"] == []
    assert audit["summary"]["voltage_nodes_topology_enrichment_pending_count"] == 1
    assert (
        audit["summary"]["transmission_elements_topology_enrichment_pending_count"]
        == 1
    )
