"""Unit tests for export_wrldc_daily_observations()."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from uuid import UUID

import pytest

from psp_pipeline.storage.sqlite_curated_export import export_wrldc_daily_observations
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def in_memory_wrldc_curated_db() -> sqlite3.Connection:
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
        VALUES(1, 'wrldc', '2025-04-15', 'WRLDC_PSP_Report_15-04-2025.pdf', 1);

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate)
        VALUES(1, '2025-04-15');

        UPDATE DimStates SET StateCode = 'MH' WHERE StateName = 'Maharashtra';
        UPDATE DimStates SET StateCode = 'GUJ' WHERE StateName = 'Gujarat';
        """
    )
    wr_region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Western Region'"
    ).fetchone()[0]
    mh_state_id = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = 'Maharashtra'"
    ).fetchone()[0]

    conn.executescript(
        f"""
        INSERT OR IGNORE INTO DimGridEntities(EntityID, EntityName, EntityType, StateID, RegionID)
        VALUES(1, 'KORADI_TPS', 'power_station', {mh_state_id}, {wr_region_id});

        INSERT OR IGNORE INTO DimVoltageNodes(VoltageNodeID, NodeName, NominalVoltageKV, RegionID)
        VALUES(1, 'PADGHE_765', 765.0, {wr_region_id});

        INSERT OR IGNORE INTO DimReservoirs(ReservoirID, ReservoirName, RegionID)
        VALUES(1, 'KOYNA', {wr_region_id});

        INSERT OR IGNORE INTO DimTransmissionElements(ElementID, ElementName, ElementType, FromRegionID)
        VALUES(1, '765KV_GWALIOR_AGRA', 'line', {wr_region_id});

        INSERT INTO FactWRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID,
            EveningPeakDemandMetMW, EveningPeakShortageMW,
            DayEnergyMetMU, DayEnergyShortageMU
        ) VALUES (
            1, 1, {wr_region_id},
            34500.0, 0.0,
            780.25, 0.0
        );

        INSERT INTO FactWRLDCStateDaily(
            ReportDocumentID, DateID, StateID,
            ThermalGenerationMU, HydroGenerationMU,
            ScheduledDrawalMU, ActualDrawalMU,
            RequirementMU, ConsumptionMU
        ) VALUES (
            1, 1, {mh_state_id},
            24.5, 5.0,
            120.0, 122.5,
            151.5, 151.5
        );

        INSERT INTO FactWRLDCGenerationDaily(
            ReportDocumentID, DateID, EntityID, StateID, StationID,
            InstalledCapacityMW, EveningPeakMW, MinimumGenerationMW,
            ScheduledEnergyMU, GrossEnergyMU, NetEnergyMU, AverageMW,
            SectionName
        ) VALUES (
            1, 1, 1, {mh_state_id}, 1,
            2400.0, 2100.0, 1200.0,
            45.0, 48.0, 44.5, 1854.0,
            'thermal'
        );

        INSERT INTO FactWRLDCFrequencyDaily(
            ReportDocumentID, DateID, RegionID,
            MaximumFrequencyHz, MinimumFrequencyHz, AverageFrequencyHz,
            Maximum15MinuteBlockFrequencyHz, Minimum15MinuteBlockFrequencyHz
        ) VALUES (
            1, 1, {wr_region_id},
            50.12, 49.88, 49.98,
            50.08, 49.91
        );

        INSERT INTO FactWRLDCVoltageProfile(
            ReportDocumentID, DateID, VoltageNodeID,
            NominalVoltageKV, MaximumKV, MinimumKV
        ) VALUES (
            1, 1, 1,
            765.0, 785.0, 750.0
        );

        INSERT INTO FactWRLDCReservoirDaily(
            ReportDocumentID, DateID, ReservoirID,
            CurrentLevelM, CurrentEnergyMU
        ) VALUES (
            1, 1, 1,
            650.2, 110.5
        );

        INSERT INTO FactWRLDCInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion,
            EveningPeakMW, ImportEnergyMU, ExportEnergyMU, NetEnergyMU
        ) VALUES (
            1, 1, 1, 'NR',
            1500.0, 25.5, 5.0, 20.5
        );
        """
    )
    return conn


def test_export_wrldc_daily_observations_returns_expected_fields(
    in_memory_wrldc_curated_db: sqlite3.Connection,
) -> None:
    now = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    observations = export_wrldc_daily_observations(
        in_memory_wrldc_curated_db,
        report_document_id=1,
        ingested_at=now,
    )

    assert len(observations) > 0

    for obs in observations:
        assert obs.source_region == "WR"
        assert obs.report_type == "wrldc_daily_psp"
        assert obs.ingested_at == now
        assert obs.valid_from == datetime(2025, 4, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert obs.metric_name.startswith("wrldc.FactWRLDC")
        assert isinstance(obs.operational_value, float)
        assert UUID(obs.timeseries_uuid)


def test_export_wrldc_daily_observations_entity_keys_and_metrics(
    in_memory_wrldc_curated_db: sqlite3.Connection,
) -> None:
    observations = export_wrldc_daily_observations(in_memory_wrldc_curated_db)

    entity_keys = {obs.entity_key for obs in observations}
    assert "WR:region:Western Region" in entity_keys
    assert "WR:state:Maharashtra" in entity_keys
    assert "WR:generation:KORADI_TPS:section:thermal" in entity_keys
    assert "WR:voltage:PADGHE_765" in entity_keys
    assert "WR:reservoir:KOYNA" in entity_keys
    assert "WR:line:765KV_GWALIOR_AGRA" in entity_keys

    metrics = {obs.metric_name for obs in observations}
    assert "wrldc.FactWRLDCRegionalDaily.EveningPeakDemandMetMW" in metrics
    assert "wrldc.FactWRLDCRegionalDaily.DayEnergyMetMU" in metrics
    assert "wrldc.FactWRLDCStateDaily.ThermalGenerationMU" in metrics
    assert "wrldc.FactWRLDCStateDaily.ConsumptionMU" in metrics
    assert "wrldc.FactWRLDCGenerationDaily.InstalledCapacityMW" in metrics
    assert "wrldc.FactWRLDCGenerationDaily.MinimumGenerationMW" in metrics
    assert "wrldc.FactWRLDCGenerationDaily.NetEnergyMU" in metrics
    assert "wrldc.FactWRLDCFrequencyDaily.MaximumFrequencyHz" in metrics
    assert "wrldc.FactWRLDCVoltageProfile.MaximumKV" in metrics
    assert "wrldc.FactWRLDCReservoirDaily.CurrentLevelM" in metrics
    assert "wrldc.FactWRLDCInterRegionalExchange.NetEnergyMU" in metrics


def test_export_wrldc_daily_observations_no_dimension_leakage(
    in_memory_wrldc_curated_db: sqlite3.Connection,
) -> None:
    observations = export_wrldc_daily_observations(in_memory_wrldc_curated_db)

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
        "IsTotalRow",
    )

    for obs in observations:
        for disallowed in disallowed_substrings:
            assert disallowed not in obs.metric_name, (
                f"Dimension column '{disallowed}' leaked into metric name: '{obs.metric_name}'"
            )


def test_export_wrldc_daily_observations_filter_by_report_id(
    in_memory_wrldc_curated_db: sqlite3.Connection,
) -> None:
    matching = export_wrldc_daily_observations(
        in_memory_wrldc_curated_db,
        report_document_id=1,
    )
    assert len(matching) > 0

    non_matching = export_wrldc_daily_observations(
        in_memory_wrldc_curated_db,
        report_document_id=999,
    )
    assert len(non_matching) == 0
