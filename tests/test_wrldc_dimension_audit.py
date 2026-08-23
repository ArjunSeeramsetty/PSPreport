"""Unit tests for the WRLDC-scoped dimension quality audit."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.quality.wrldc_dimension_audit import audit_wrldc_dimensions
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def mixed_rldc_curated_db(tmp_path: Path) -> Path:
    """Create a database whose WRLDC and NRLDC dimensions are disjoint."""

    db_path = tmp_path / "mixed_wrldc.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_curated_sqlite_schema(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rldc TEXT NOT NULL,
            report_date TEXT NOT NULL,
            source_url TEXT,
            filename TEXT,
            sha256 TEXT,
            local_path TEXT,
            pdf_char_count INTEGER,
            is_valid INTEGER,
            ocr_recommended INTEGER,
            reconciliation_status TEXT,
            created_at TEXT
        );

        INSERT INTO psp_report_document(id, rldc, report_date, filename, is_valid)
        VALUES
            (1, 'wrldc', '2025-04-15', 'WRLDC_PSP_Report_15-04-2025.pdf', 1),
            (2, 'nrldc', '2025-04-15', 'daily150425.pdf', 1);

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate)
        VALUES (1, '2025-04-15');
        """
    )
    wr_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Western Region'"
    ).fetchone()[0]
    nr_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Northern Region'"
    ).fetchone()[0]
    mh_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Maharashtra'"
    ).fetchone()[0]
    dl_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Delhi'"
    ).fetchone()[0]

    conn.executescript(
        f"""
        INSERT INTO DimGridEntities(
            EntityID, EntityName, EntityType, StateID, RegionID
        ) VALUES
            (1, 'KORADI_TPS', 'power_station', {mh_state_id}, {wr_region_id}),
            (2, 'DADRI_TPS', 'power_station', {dl_state_id}, {nr_region_id});

        INSERT INTO DimVoltageNodes(
            VoltageNodeID, NodeName, NominalVoltageKV, StateID, RegionID
        ) VALUES
            (1, 'PADGHE_765', 765.0, {mh_state_id}, {wr_region_id}),
            (2, 'AGRA_765', 765.0, {dl_state_id}, {nr_region_id});

        INSERT INTO DimReservoirs(ReservoirID, ReservoirName, StateID, RegionID)
        VALUES
            (1, 'KOYNA', {mh_state_id}, {wr_region_id}),
            (2, 'BHAKRA', {dl_state_id}, {nr_region_id});

        INSERT INTO DimTransmissionElements(
            ElementID, ElementName, ElementType, FromRegionID, ToRegionID,
            FromStateID, ToStateID
        ) VALUES
            (1, '765KV_PADGHE_KARJAT', 'line', {wr_region_id}, {wr_region_id},
             {mh_state_id}, {mh_state_id}),
            (2, '765KV_AGRA_GWALIOR', 'line', {nr_region_id}, {nr_region_id},
             {dl_state_id}, {dl_state_id});

        INSERT INTO FactWRLDCStateDaily(
            ReportDocumentID, DateID, StateID, ConsumptionMU
        ) VALUES (1, 1, {mh_state_id}, 151.5);
        INSERT INTO FactWRLDCGenerationDaily(
            ReportDocumentID, DateID, EntityID, StateID, StationID, SectionName
        ) VALUES (1, 1, 1, {mh_state_id}, 1, 'thermal');
        INSERT INTO FactWRLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV
        ) VALUES (1, 1, 1, 765.0, 780.0);
        INSERT INTO FactWRLDCReservoirDaily(
            ReportDocumentID, DateID, ReservoirID, CurrentLevelM
        ) VALUES (1, 1, 1, 650.2);
        INSERT INTO FactWRLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU
        ) VALUES (1, 1, 1, 'NR', 20.5);

        INSERT INTO FactNRLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV
        ) VALUES (2, 1, 2, 765.0, 780.0);
        INSERT INTO FactNRLDCReservoirDaily(
            ReportDocumentID, DateID, ReservoirID, CurrentLevelM
        ) VALUES (2, 1, 2, 1650.0);
        INSERT INTO FactNRLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU
        ) VALUES (2, 1, 2, 'ER', 10.0);
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_audit_wrldc_dimensions_scopes_to_wrldc_facts_only(
    mixed_rldc_curated_db: Path,
) -> None:
    """Only dimensions referenced by WRLDC facts are reported."""

    audit = audit_wrldc_dimensions(mixed_rldc_curated_db)

    assert audit["wrldc_reports_found"] == 1
    assert audit["summary"]["dim_states_count"] == 1
    assert audit["summary"]["dim_grid_entities_count"] == 1
    assert audit["summary"]["dim_voltage_nodes_count"] == 1
    assert audit["summary"]["dim_reservoirs_count"] == 1
    assert audit["summary"]["dim_transmission_elements_count"] == 1
    assert audit["voltage_nodes"]["ids"] == [1]
    assert audit["reservoirs"]["ids"] == [1]
    assert audit["transmission_elements"]["ids"] == [1]
    assert "AGRA_765" not in str(audit)
    assert "BHAKRA" not in str(audit)
    assert "765KV_AGRA_GWALIOR" not in str(audit)


def test_audit_wrldc_dimensions_raises_when_no_wrldc_documents(
    tmp_path: Path,
) -> None:
    """An audit cannot silently fall back to another RLDC's facts."""

    db_path = tmp_path / "nrldc_only.sqlite"
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
        VALUES (1, 'nrldc', '2025-04-15', 'daily150425.pdf', 1);
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="contains 0 WRLDC report documents"):
        audit_wrldc_dimensions(db_path)


def test_audit_wrldc_dimensions_raises_for_missing_database(tmp_path: Path) -> None:
    """A missing database produces an explicit, actionable error."""

    with pytest.raises(FileNotFoundError, match="not found"):
        audit_wrldc_dimensions(tmp_path / "missing.sqlite")


def test_audit_separates_topology_enrichment_from_dimension_failures(
    mixed_rldc_curated_db: Path,
) -> None:
    """PSP-only labels do not become false dimension-quality failures."""
    conn = sqlite3.connect(mixed_rldc_curated_db)
    gujarat_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Gujarat'"
    ).fetchone()[0]
    wr_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Western Region'"
    ).fetchone()[0]
    conn.executescript(
        f"""
        INSERT INTO DimGridEntities(
            EntityID, EntityName, EntityType, StateID, RegionID
        ) VALUES (3, 'KORADI_TPS', 'power_station', {gujarat_id}, {wr_region_id});
        INSERT INTO FactWRLDCGenerationDaily(
            ReportDocumentID, DateID, EntityID, StateID, StationID, SectionName
        ) VALUES (1, 1, 3, {gujarat_id}, 3, 'thermal');

        INSERT INTO DimVoltageNodes(
            VoltageNodeID, NodeName, NominalVoltageKV, RegionID
        ) VALUES (3, 'UNMAPPED_400', 400.0, {wr_region_id});
        INSERT INTO FactWRLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV
        ) VALUES (1, 1, 3, 400.0, 408.0);

        INSERT INTO DimTransmissionElements(
            ElementID, ElementName, ElementType, NominalVoltageKV
        ) VALUES (3, '400KV_UNKNOWN_LINK', 'line', 400.0);
        INSERT INTO FactWRLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU
        ) VALUES (1, 1, 3, 'ER', 5.0);
        """
    )
    conn.commit()
    conn.close()

    audit = audit_wrldc_dimensions(mixed_rldc_curated_db)

    assert audit["grid_entities"]["duplicates"] == []
    assert audit["voltage_nodes"]["unresolved_state"] == []
    assert audit["transmission_elements"]["unresolved_region"] == []
    assert audit["transmission_elements"]["unresolved_state"] == []
    assert audit["summary"]["voltage_nodes_topology_enrichment_pending_count"] == 1
    assert (
        audit["summary"]["transmission_elements_topology_enrichment_pending_count"]
        == 1
    )
