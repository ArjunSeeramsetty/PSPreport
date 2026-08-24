"""Unit tests for ERLDC observation export from curated SQLite facts."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from uuid import UUID

import pytest

from psp_pipeline.storage.sqlite_curated_export import export_erldc_daily_observations
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def curated_erldc_conn() -> sqlite3.Connection:
    """Return an in-memory SQLite database populated with curated ERLDC facts."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY,
            rldc TEXT NOT NULL
        );
        INSERT INTO psp_report_document(id, rldc) VALUES (1, 'erldc');

        CREATE TABLE IF NOT EXISTS FactERLDCRegionalDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            EveningPeakDemandMetMW REAL,
            OffPeakDemandMetMW REAL,
            DayEnergyMetMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCStateDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            ThermalGenerationMU REAL,
            HydroGenerationMU REAL,
            TotalGenerationMU REAL,
            RequirementMU REAL,
            ConsumptionMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCGenerationDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            StateID INTEGER,
            AggregateID INTEGER,
            InstalledCapacityMW REAL,
            GrossEnergyMU REAL,
            NetEnergyMU REAL,
            SectionName TEXT NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, SectionName)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCFrequencyDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            MaximumFrequencyHz REAL,
            MinimumFrequencyHz REAL,
            AverageFrequencyHz REAL,
            PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCVoltageProfile (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            VoltageNodeID INTEGER NOT NULL,
            NominalVoltageKV REAL NOT NULL,
            MaximumKV REAL,
            MinimumKV REAL,
            PRIMARY KEY(ReportDocumentID, DateID, VoltageNodeID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCReservoirDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ReservoirID INTEGER NOT NULL,
            CurrentLevelM REAL,
            CurrentEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ReservoirID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCInterRegionalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ElementID INTEGER NOT NULL,
            CounterpartyRegion TEXT NOT NULL,
            NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ElementID)
        );

        CREATE TABLE IF NOT EXISTS FactERLDCInternationalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            CountryID INTEGER NOT NULL,
            CounterpartyCountry TEXT NOT NULL,
            NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, CountryID)
        );

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2025-04-15');
        UPDATE DimStates SET StateCode = 'WB' WHERE StateName = 'West Bengal';
        """
    )
    er_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Eastern Region'"
    ).fetchone()[0]
    wb_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'West Bengal'"
    ).fetchone()[0]
    bhutan_id = conn.execute(
        "SELECT CountryID FROM DimCountries WHERE CountryName = 'Bhutan'"
    ).fetchone()[0]

    conn.executescript(
        f"""
        INSERT INTO DimGridEntities(EntityID, EntityName, EntityType, StateID, RegionID)
        VALUES (1, 'FSTPS', 'power_station', {wb_state_id}, {er_region_id});

        INSERT INTO DimVoltageNodes(VoltageNodeID, NodeName, NominalVoltageKV, RegionID)
        VALUES (1, 'JEERAT_400', 400.0, {er_region_id});

        INSERT INTO DimReservoirs(ReservoirID, ReservoirName, RegionID)
        VALUES (1, 'MAITHON', {er_region_id});

        INSERT INTO DimTransmissionElements(ElementID, ElementName, ElementType, FromRegionID)
        VALUES (1, '400KV_BINAGURI_BONGAIGAON', 'line', {er_region_id});

        INSERT INTO FactERLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, OffPeakDemandMetMW, DayEnergyMetMU
        ) VALUES (1, 1, {er_region_id}, 24500.0, 18200.0, 495.2);

        INSERT INTO FactERLDCStateDaily(
            ReportDocumentID, DateID, StateID, ThermalGenerationMU, HydroGenerationMU,
            TotalGenerationMU, RequirementMU, ConsumptionMU
        ) VALUES (1, 1, {wb_state_id}, 120.5, 15.2, 135.7, 185.0, 184.8);

        INSERT INTO FactERLDCGenerationDaily(
            ReportDocumentID, DateID, EntityID, StateID, InstalledCapacityMW,
            AggregateID, GrossEnergyMU, NetEnergyMU, SectionName
        ) VALUES (1, 1, 1, {wb_state_id}, 1, 2100.0, 45.2, 42.1, 'thermal');

        INSERT INTO FactERLDCFrequencyDaily(
            ReportDocumentID, DateID, RegionID, MaximumFrequencyHz, MinimumFrequencyHz, AverageFrequencyHz
        ) VALUES (1, 1, {er_region_id}, 50.15, 49.85, 50.00);

        INSERT INTO FactERLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV, MaximumKV, MinimumKV
        ) VALUES (1, 1, 1, 400.0, 412.0, 395.0);

        INSERT INTO FactERLDCReservoirDaily(
            ReportDocumentID, DateID, ReservoirID, CurrentLevelM, CurrentEnergyMU
        ) VALUES (1, 1, 1, 145.5, 85.0);

        INSERT INTO FactERLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion, NetEnergyMU
        ) VALUES (1, 1, 1, 'NER', 12.5);

        INSERT INTO FactERLDCInternationalExchange(
            ReportDocumentID, DateID, CountryID, CounterpartyCountry, NetEnergyMU
        ) VALUES (1, 1, {bhutan_id}, 'Bhutan', 8.2);
        """
    )
    conn.commit()
    return conn


def test_export_erldc_daily_observations_emits_valid_records(
    curated_erldc_conn: sqlite3.Connection,
) -> None:
    now = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    observations = export_erldc_daily_observations(
        curated_erldc_conn, report_document_id=1, ingested_at=now
    )
    assert len(observations) > 0

    entity_keys = {obs.entity_key for obs in observations}
    assert "ER:region:Eastern Region" in entity_keys
    assert "ER:state:WB" in entity_keys
    assert "ER:generation:FSTPS" in entity_keys
    assert "ER:voltage:JEERAT_400" in entity_keys
    assert "ER:reservoir:MAITHON" in entity_keys
    assert "ER:line:400KV_BINAGURI_BONGAIGAON" in entity_keys
    assert "ER:country:Bhutan" in entity_keys

    metrics = {obs.metric_name for obs in observations}
    assert "erldc.FactERLDCRegionalDaily.EveningPeakDemandMetMW" in metrics
    assert "erldc.FactERLDCRegionalDaily.DayEnergyMetMU" in metrics
    assert "erldc.FactERLDCStateDaily.ThermalGenerationMU" in metrics
    assert "erldc.FactERLDCStateDaily.TotalGenerationMU" in metrics
    assert "erldc.FactERLDCGenerationDaily.InstalledCapacityMW" in metrics
    assert "erldc.FactERLDCGenerationDaily.GrossEnergyMU" in metrics
    assert "erldc.FactERLDCFrequencyDaily.MaximumFrequencyHz" in metrics
    assert "erldc.FactERLDCVoltageProfile.MaximumKV" in metrics
    assert "erldc.FactERLDCReservoirDaily.CurrentLevelM" in metrics
    assert "erldc.FactERLDCInterRegionalExchange.NetEnergyMU" in metrics
    assert "erldc.FactERLDCInternationalExchange.NetEnergyMU" in metrics

    for obs in observations:
        assert isinstance(UUID(obs.timeseries_uuid), UUID)
        assert obs.source_region == "ER"
        assert obs.report_type == "erldc_daily_psp"
        assert obs.ingested_at == now
        assert obs.valid_from == datetime(2025, 4, 15, 0, 0, tzinfo=timezone.utc)


def test_export_erldc_daily_observations_no_dimension_leakage(
    curated_erldc_conn: sqlite3.Connection,
) -> None:
    observations = export_erldc_daily_observations(curated_erldc_conn)
    disallowed_substrings = (
        "ReportDocumentID",
        "DateID",
        "RegionID",
        "StateID",
        "EntityID",
        "StationID",
        "GeneratingUnitID",
        "AggregateID",
        "ElementID",
        "VoltageNodeID",
        "ReservoirID",
        "CountryID",
        "IsTotalRow",
    )
    for obs in observations:
        for disallowed in disallowed_substrings:
            assert disallowed not in obs.metric_name, (
                f"Dimension column '{disallowed}' leaked into metric name: '{obs.metric_name}'"
            )
        assert obs.source_region == "ER"
        assert obs.report_type == "erldc_daily_psp"


def test_export_erldc_daily_observations_filter_by_report_id(
    curated_erldc_conn: sqlite3.Connection,
) -> None:
    matching = export_erldc_daily_observations(
        curated_erldc_conn,
        report_document_id=1,
    )
    assert len(matching) > 0

    non_matching = export_erldc_daily_observations(
        curated_erldc_conn,
        report_document_id=999,
    )
    assert len(non_matching) == 0
