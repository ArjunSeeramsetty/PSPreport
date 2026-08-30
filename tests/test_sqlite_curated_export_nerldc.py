"""Unit tests for NERLDC curated observation export."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from uuid import UUID

import pytest

from psp_pipeline.storage.sqlite_curated_export import export_nerldc_daily_observations
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def curated_nerldc_conn() -> sqlite3.Connection:
    """Return an in-memory database populated with representative NERLDC facts."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    ner_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'North Eastern Region'"
    ).fetchone()[0]
    assam_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Assam'"
    ).fetchone()[0]
    conn.execute("UPDATE DimStates SET StateCode = 'AS' WHERE StateID = ?", (assam_state_id,))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY,
            rldc TEXT NOT NULL
        );
        INSERT INTO psp_report_document(id, rldc) VALUES (1, 'nerldc');
        INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2025-01-01');
        INSERT INTO DimGridEntities(EntityID, EntityName, EntityType, StateID, RegionID)
        VALUES (1, 'KOPILI_HEP', 'generating_entity', %d, %d);
        INSERT INTO DimVoltageNodes(VoltageNodeID, NodeName, NominalVoltageKV, StateID, RegionID)
        VALUES (1, 'BONGAIGAON - 400KV', 400.0, %d, %d);
        INSERT INTO DimTransmissionElements(
            ElementID, ElementName, ElementType, FromRegionID
        ) VALUES (1, '400KV-BONGAIGAON-ALIPURDUAR-1', 'line', %d);
        INSERT OR IGNORE INTO DimCountries(CountryName)
        VALUES ('Bhutan');
        """
        % (assam_state_id, ner_region_id, assam_state_id, ner_region_id, ner_region_id)
    )
    bhutan_country_id = conn.execute(
        "SELECT CountryID FROM DimCountries WHERE CountryName = 'Bhutan'"
    ).fetchone()[0]
    conn.executescript(
        """
        INSERT INTO FactNERLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, DayEnergyMetMU
        ) VALUES (1, 1, %d, 2561.0, 48.5);
        INSERT INTO FactNERLDCStateDaily(
            ReportDocumentID, DateID, StateID, TotalAvailabilityMU, DemandMetMU
        ) VALUES (1, 1, %d, 28.5, 28.2);
        INSERT INTO FactNERLDCGenerationDaily(
            ReportDocumentID, DateID, EntityID, StateID, StationID, NetEnergyMU, SectionName
        ) VALUES (1, 1, 1, %d, 1, 12.5, 'state_generation_assam');
        INSERT INTO FactNERLDCFrequencyDaily(
            ReportDocumentID, DateID, RegionID, MaximumFrequencyHz, MinimumFrequencyHz, AverageFrequencyHz
        ) VALUES (1, 1, %d, 50.15, 49.85, 50.02);
        INSERT INTO FactNERLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV, MinimumKV
        ) VALUES (1, 1, 1, 400.0, 415.0, 398.0);
        INSERT INTO FactNERLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU
        ) VALUES (1, 1, 1, 'Eastern Region', 18.2);
        INSERT INTO FactNERLDCInternationalExchange(
            ReportDocumentID, DateID, CountryID, CounterpartyCountry, NetEnergyMU
        ) VALUES (1, 1, %d, 'Bhutan', 6.4);
        """
        % (ner_region_id, assam_state_id, assam_state_id, ner_region_id, bhutan_country_id)
    )
    conn.commit()
    yield conn
    conn.close()


def test_export_nerldc_daily_observations_generates_valid_records(
    curated_nerldc_conn: sqlite3.Connection,
) -> None:
    """NERLDC facts emit bitemporal measurements without dimension leakage."""

    recorded_at = datetime(2026, 8, 25, 2, 0, 0, tzinfo=timezone.utc)
    observations = export_nerldc_daily_observations(
        curated_nerldc_conn, report_document_id=1, ingested_at=recorded_at
    )

    assert observations
    entity_keys = {item.entity_key for item in observations}
    assert "NER:region:North Eastern Region" in entity_keys
    assert "NER:state:Assam" in entity_keys
    assert "NER:generation:KOPILI_HEP:section:state_generation_assam" in entity_keys
    assert "NER:voltage:BONGAIGAON - 400KV" in entity_keys
    assert "NER:line:400KV-BONGAIGAON-ALIPURDUAR-1" in entity_keys
    assert "NER:country:Bhutan" in entity_keys

    for item in observations:
        assert item.metric_name.startswith("nerldc.")
        assert item.source_region == "NER"
        assert item.report_type == "nerldc_daily_psp"
        assert item.valid_from == datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert item.ingested_at == recorded_at
        assert isinstance(UUID(item.timeseries_uuid), UUID)
        assert not any(
            part in item.metric_name
            for part in ("ReportDocumentID", "DateID", "RegionID", "StateID", "EntityID")
        )
