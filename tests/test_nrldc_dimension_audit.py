"""Unit tests for NRLDC dimension quality audit."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import pytest

from psp_pipeline.quality.nrldc_dimension_audit import audit_nrldc_dimensions
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def mixed_rldc_curated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "mixed_test.sqlite"
    conn = sqlite3.connect(str(db_path))
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

        -- SRLDC report document and facts
        INSERT INTO psp_report_document(id, rldc, report_date, filename, is_valid)
        VALUES(1, 'srldc', '2024-05-15', 'psp150524.pdf', 1);

        -- NRLDC report document and facts
        INSERT INTO psp_report_document(id, rldc, report_date, filename, is_valid)
        VALUES(2, 'nrldc', '2026-05-29', 'daily290526.pdf', 1);

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES(1, '2026-05-29');

        -- SRLDC-only voltage node (ID 1)
        INSERT OR IGNORE INTO DimVoltageNodes(VoltageNodeID, NodeName, NominalVoltageKV, RegionID)
        VALUES(1, 'SR_SUBSTATION_400', 400.0, 2);

        -- NRLDC-referenced voltage node (ID 2)
        INSERT OR IGNORE INTO DimVoltageNodes(VoltageNodeID, NodeName, NominalVoltageKV, RegionID)
        VALUES(2, 'AGRA_765', 765.0, 1);

        -- SRLDC fact references node 1
        INSERT INTO FactSRLDCVoltageProfile(ReportDocumentID, DateID, VoltageNodeID, MaximumKV, MinimumKV)
        VALUES(1, 1, 1, 420.0, 390.0);

        -- NRLDC fact references node 2
        INSERT INTO FactNRLDCVoltageProfile(ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV, MinimumKV)
        VALUES(2, 1, 2, 765.0, 780.0, 750.0);

        -- SRLDC-only reservoir (ID 1)
        INSERT OR IGNORE INTO DimReservoirs(ReservoirID, ReservoirName, RegionID)
        VALUES(1, 'SR_SRISAILAM', 2);

        -- NRLDC-referenced reservoir (ID 2)
        INSERT OR IGNORE INTO DimReservoirs(ReservoirID, ReservoirName, RegionID)
        VALUES(2, 'BHAKRA', 1);

        -- NRLDC fact references reservoir 2
        INSERT INTO FactNRLDCReservoirDaily(ReportDocumentID, DateID, ReservoirID, CurrentLevelM, CurrentEnergyMU)
        VALUES(2, 1, 2, 1650.0, 120.0);

        -- SRLDC-only transmission line (ID 1)
        INSERT OR IGNORE INTO DimTransmissionElements(ElementID, ElementName, ElementType, FromRegionID)
        VALUES(1, 'SR_LINE_400KV', 'line', 2);

        -- NRLDC-referenced transmission line (ID 2)
        INSERT OR IGNORE INTO DimTransmissionElements(ElementID, ElementName, ElementType, FromRegionID)
        VALUES(2, '765KV_AGRA_GWALIOR', 'line', 1);

        -- NRLDC fact references element 2
        INSERT INTO FactNRLDCInterRegionalExchange(ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU)
        VALUES(2, 1, 2, 'WR', 10.0);
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_audit_nrldc_dimensions_scopes_to_nrldc_facts_only(mixed_rldc_curated_db: Path):
    audit = audit_nrldc_dimensions(mixed_rldc_curated_db)

    # Should only audit node 2 (AGRA_765), not node 1 (SR_SUBSTATION_400)
    assert audit["summary"]["dim_voltage_nodes_count"] == 1
    audited_nodes = [item["name"] for group in audit["voltage_nodes"].values() for item in (group if isinstance(group, list) else [])]
    assert "AGRA_765" in str(audit["voltage_nodes"])
    assert "SR_SUBSTATION_400" not in str(audit["voltage_nodes"])

    # Should only audit reservoir 2 (BHAKRA), not reservoir 1 (SR_SRISAILAM)
    assert audit["summary"]["dim_reservoirs_count"] == 1
    assert "BHAKRA" in str(audit["reservoirs"])
    assert "SR_SRISAILAM" not in str(audit["reservoirs"])

    # Should only audit transmission element 2 (765KV_AGRA_GWALIOR), not element 1
    assert audit["summary"]["dim_transmission_elements_count"] == 1
    assert "765KV_AGRA_GWALIOR" in str(audit["transmission_elements"])
    assert "SR_LINE_400KV" not in str(audit["transmission_elements"])


def test_audit_nrldc_dimensions_raises_when_no_nrldc_docs(tmp_path: Path):
    db_path = tmp_path / "srldc_only.sqlite"
    conn = sqlite3.connect(str(db_path))
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
        VALUES(1, 'srldc', '2024-05-15', 'psp150524.pdf', 1);
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="contains 0 NRLDC report documents"):
        audit_nrldc_dimensions(db_path)


def test_audit_nrldc_dimensions_raises_when_file_not_found(tmp_path: Path):
    missing_path = tmp_path / "non_existent.sqlite"
    with pytest.raises(FileNotFoundError, match="not found"):
        audit_nrldc_dimensions(missing_path)
