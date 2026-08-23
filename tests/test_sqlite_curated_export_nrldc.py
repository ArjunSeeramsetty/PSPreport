"""Unit tests for export_nrldc_daily_observations()."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from uuid import UUID

import pytest

from psp_pipeline.storage.sqlite_curated_export import export_nrldc_daily_observations
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def in_memory_nrldc_curated_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
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
        VALUES(1, 'nrldc', '2026-05-29', 'daily290526.pdf', 1);

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate)
        VALUES(1, '2026-05-29');

        UPDATE DimStates SET StateCode = 'DL' WHERE StateName = 'Delhi';
        """
    )
    # Fetch seeded region and state IDs
    nr_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Northern Region'"
    ).fetchone()[0]
    dl_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Delhi'"
    ).fetchone()[0]

    conn.executescript(
        f"""
        INSERT OR IGNORE INTO DimGridEntities(EntityID, EntityName, EntityType, StateID, RegionID)
        VALUES(1, 'DADRI_TPS', 'power_station', {dl_state_id}, {nr_region_id});

        INSERT OR IGNORE INTO DimVoltageNodes(VoltageNodeID, NodeName, NominalVoltageKV, RegionID)
        VALUES(1, 'AGRA_765', 765.0, {nr_region_id});

        INSERT OR IGNORE INTO DimReservoirs(ReservoirID, ReservoirName, RegionID)
        VALUES(1, 'BHAKRA', {nr_region_id});

        INSERT OR IGNORE INTO DimTransmissionElements(ElementID, ElementName, ElementType, FromRegionID)
        VALUES(1, '765KV_AGRA_GWALIOR', 'line', {nr_region_id});

        INSERT OR IGNORE INTO DimTransmissionElements(ElementID, ElementName, ElementType, FromRegionID)
        VALUES(2, '132KV_MUZAFFARPUR_DHANBASHA', 'line', {nr_region_id});

        INSERT INTO FactNRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID,
            EveningPeakDemandMetMW, EveningPeakShortageMW,
            DayEnergyMetMU, DayEnergyShortageMU
        ) VALUES (
            1, 1, {nr_region_id},
            25430.0, 0.0,
            580.45, 0.0
        );

        INSERT INTO FactNRLDCStateDaily(
            ReportDocumentID, DateID, StateID,
            ThermalGenerationMU, HydroGenerationMU,
            ScheduledDrawalMU, ActualDrawalMU,
            RequirementMU, ConsumptionMU
        ) VALUES (
            1, 1, {dl_state_id},
            12.5, 0.0,
            110.0, 112.5,
            125.0, 125.0
        );

        INSERT INTO FactNRLDCGenerationDaily(
            ReportDocumentID, DateID, EntityID, StateID, StationID,
            InstalledCapacityMW, EveningPeakMW, GrossEnergyMU, NetEnergyMU, AverageMW,
            SectionName
        ) VALUES (
            1, 1, 1, {dl_state_id}, 1,
            1820.0, 1500.0, 32.4, 30.1, 1350.0,
            'thermal'
        );

        INSERT INTO FactNRLDCFrequencyDaily(
            ReportDocumentID, DateID, RegionID,
            MaximumFrequencyHz, MinimumFrequencyHz, AverageFrequencyHz,
            Maximum15MinuteBlockFrequencyHz, Minimum15MinuteBlockFrequencyHz
        ) VALUES (
            1, 1, {nr_region_id},
            50.15, 49.85, 49.99,
            50.10, 49.88
        );

        INSERT INTO FactNRLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID,
            NominalVoltageKV, MaximumKV, MinimumKV
        ) VALUES (
            1, 1, 1,
            765.0, 782.0, 755.0
        );

        INSERT INTO FactNRLDCReservoirDaily(
            ReportDocumentID, DateID, ReservoirID,
            CurrentLevelM, CurrentEnergyMU, InflowCusec
        ) VALUES (
            1, 1, 1,
            1650.5, 125.4, 4500.0
        );

        INSERT INTO FactNRLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion,
            EveningPeakMW, ImportEnergyMU, ExportEnergyMU, NetEnergyMU
        ) VALUES (
            1, 1, 1, 'WR',
            1200.0, 15.5, 2.5, 13.0
        );

        INSERT INTO FactNRLDCInterRegionalScheduleExchange(
            ReportDocumentID, DateID, CounterpartyRegion,
            ISGSAndGNAScheduleMU, BilateralScheduleMU, TotalScheduleMU,
            ActualMU, DeviationMU
        ) VALUES (
            1, 1, 'ER',
            100.0, 20.0, 120.0,
            122.5, 2.5
        );

        INSERT INTO FactNRLDCInternationalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyCountry,
            EveningPeakMW, ExportEnergyMU, NetEnergyMU, ScheduleEnergyMU
        ) VALUES (
            1, 1, 2, 'NEPAL',
            150.0, 3.5, -3.5, 3.6
        );
        """
    )
    conn.commit()
    yield conn
    conn.close()


def test_export_nrldc_daily_observations_metadata(in_memory_nrldc_curated_db):
    conn = in_memory_nrldc_curated_db
    ingested_at = datetime(2026, 5, 30, 6, 0, 0, tzinfo=timezone.utc)
    observations = export_nrldc_daily_observations(conn, ingested_at=ingested_at)

    assert len(observations) > 0

    for obs in observations:
        assert obs.metric_name.startswith("nrldc.")
        assert obs.source_region == "NR"
        assert obs.report_type == "nrldc_daily_psp"
        assert obs.valid_from == datetime(2026, 5, 29, 0, 0, tzinfo=timezone.utc)
        assert obs.ingested_at == ingested_at
        assert obs.version_no == 1
        assert isinstance(obs.operational_value, float)
        # Ensure timeseries_uuid is a valid UUID
        parsed_uuid = UUID(obs.timeseries_uuid)
        assert str(parsed_uuid) == obs.timeseries_uuid


def test_export_nrldc_daily_observations_no_dimension_leakage(in_memory_nrldc_curated_db):
    conn = in_memory_nrldc_curated_db
    observations = export_nrldc_daily_observations(conn)

    disallowed_parts = {
        "ReportDocumentID",
        "DateID",
        "RegionID",
        "StateID",
        "EntityID",
        "GenerationSourceID",
        "StationID",
        "GeneratingUnitID",
        "AggregateID",
        "ElementID",
        "VoltageNodeID",
        "ReservoirID",
        "IsTotalRow",
    }

    for obs in observations:
        metric_column = obs.metric_name.split(".")[-1]
        assert metric_column not in disallowed_parts, f"Dimension column {metric_column} leaked into metric"


def test_export_nrldc_daily_observations_entity_keys(in_memory_nrldc_curated_db):
    conn = in_memory_nrldc_curated_db
    observations = export_nrldc_daily_observations(conn)

    entity_keys = {obs.entity_key for obs in observations}
    assert "NR:region:Northern Region" in entity_keys
    assert "NR:state:DL" in entity_keys
    assert "NR:generation:DADRI_TPS" in entity_keys
    assert "NR:voltage:AGRA_765" in entity_keys
    assert "NR:reservoir:BHAKRA" in entity_keys
    assert "NR:line:765KV_AGRA_GWALIOR" in entity_keys
    assert "NR:interregional-schedule:ER" in entity_keys
    assert "NR:international-line:132KV_MUZAFFARPUR_DHANBASHA" in entity_keys


def test_export_nrldc_daily_observations_deterministic_uuid(in_memory_nrldc_curated_db):
    conn = in_memory_nrldc_curated_db
    fixed_time = datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc)

    run_1 = export_nrldc_daily_observations(conn, ingested_at=fixed_time)
    run_2 = export_nrldc_daily_observations(conn, ingested_at=fixed_time)

    assert len(run_1) == len(run_2)
    for obs1, obs2 in zip(run_1, run_2, strict=True):
        assert obs1.timeseries_uuid == obs2.timeseries_uuid
        assert obs1.metric_name == obs2.metric_name
        assert obs1.entity_key == obs2.entity_key
        assert obs1.operational_value == obs2.operational_value
