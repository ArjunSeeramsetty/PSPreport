"""Unit tests for Grid-India NLDC observation and lineage export from curated SQLite facts."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from uuid import UUID

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.storage.sqlite_curated_export import (
    export_all_daily_observations,
    export_observation_lineage,
    export_registered_daily_observations,
)
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def curated_nldc_conn() -> sqlite3.Connection:
    """Return an in-memory SQLite database populated with curated NLDC facts and lineage."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_sqlite_schema(conn)
    ensure_curated_sqlite_schema(conn)

    conn.executescript(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count
        ) VALUES (
            1, 'grid_india_national', 'https://webcdn.grid-india.in/report.pdf', 'report.pdf',
            'nldc-hash-1', '2026-08-25T10:00:00+00:00', 1.0, 0, 'native', 5000
        );

        INSERT INTO DimDates(DateID, ActualDate) VALUES (1, '2026-08-25');

        INSERT OR IGNORE INTO DimRegions(RegionID, RegionName) VALUES
            (1, 'Northern Region'),
            (2, 'Western Region'),
            (3, 'Southern Region'),
            (4, 'Eastern Region'),
            (5, 'North Eastern Region');

        INSERT INTO DimTransmissionElements(ElementID, ElementName, ElementType, NominalVoltageKV, CircuitCount) VALUES
            (10, 'ALIPURDUAR-AGRA', 'hvdc', 800.0, 2),
            (11, 'CHAMPA-KURUKSHETRA', 'hvdc', 800.0, 2);

        INSERT INTO DimGridEntities(EntityID, EntityName, EntityType, RegionID) VALUES
            (20, 'Punjab', 'control_area', 1);

        INSERT INTO FactNLDCDailyNational(
            ReportDocumentID, DateID, EveningPeakDemandMetMW, PeakShortageMW,
            EnergyMetMU, HydroGenMU, WindGenMU, SolarGenMU, EnergyShortageMU,
            MaxDemandMetMW, TimeOfMaxDemand
        ) VALUES (
            1, 1, 239057.0, 2083.0, 5530.0, 710.0, 480.0, 572.0, 8.23, 247536.0, '15:33'
        );

        INSERT INTO FactNLDCDailyRegional(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, PeakShortageMW,
            EnergyMetMU, HydroGenMU, WindGenMU, SolarGenMU, EnergyShortageMU,
            MaxDemandMetMW, TimeOfMaxDemand
        ) VALUES
            (1, 1, 1, 85000.0, 500.0, 1800.0, 300.0, 100.0, 200.0, 2.5, 87000.0, '14:20'),
            (1, 1, 2, 70000.0, 300.0, 1500.0, 150.0, 200.0, 150.0, 1.2, 72000.0, '19:45');

        INSERT INTO FactNLDCDailyFrequency(
            ReportDocumentID, DateID, FVI, Below_49_7, From_49_7_to_49_8,
            From_49_8_to_49_9, Below_49_9, From_49_9_to_50_05, Above_50_05
        ) VALUES (
            1, 1, 0.038, 0.0, 0.02, 3.5, 3.52, 85.4, 11.08
        );

        INSERT INTO FactNLDCDailyInterRegionalExchange(
            ReportDocumentID, DateID, ElementID, CounterpartyRegion, VoltageLevel,
            CircuitCount, MaxImportMW, MaxExportMW, ImportMU, ExportMU, NetMU
        ) VALUES
            (1, 1, 10, 'Northern Region', 'HVDC', 2, 0.0, 746.0, 0.0, 7.2, -7.2),
            (1, 1, 11, 'Northern Region', 'HVDC', 2, 0.0, 4535.0, 0.0, 56.4, -56.4);

        INSERT INTO FactNLDCDailyControlAreaDrawal(
            ReportDocumentID, DateID, EntityID, RegionID, MaximumDemandMetMW,
            DrawalScheduleMU, MaximumOverDrawalMW
        ) VALUES (1, 1, 20, 1, 16194.0, 235.2, 887.0);

        INSERT INTO FactNLDC15MinuteGridSnapshot(
            ReportDocumentID, DateID, BlockStartTime, FrequencyHz, DemandMetMW,
            NuclearGenerationMW, TotalGenerationMW
        ) VALUES (1, 1, '00:15', 50.01, 225158.0, 5485.0, 228472.0);

        INSERT INTO FactNLDC15MinuteGridSnapshot(
            ReportDocumentID, DateID, BlockStartTime, FrequencyHz, DemandMetMW,
            NuclearGenerationMW, TotalGenerationMW
        ) VALUES (1, 1, '00:30', 50.02, 223863.0, 5494.0, 227323.0);

        -- Lineage setup
        INSERT INTO psp_raw_cell(
            id, report_document_id, page_no, table_no, row_no, col_no,
            cell_text, extraction_method, extracted_at
        ) VALUES
            (101, 1, 2, 1, 1, 7, '239057', 'pdfplumber', '2026-08-25T10:00:00+00:00'),
            (102, 1, 2, 1, 2, 7, '2083', 'pdfplumber', '2026-08-25T10:00:00+00:00'),
            (103, 1, 3, 1, 3, 9, '-7.2', 'pdfplumber', '2026-08-25T10:00:00+00:00'),
            (104, 1, 2, 3, 2, 3, '16194', 'pdfplumber', '2026-08-25T10:00:00+00:00');
        
        INSERT INTO psp_raw_cell(
            id, report_document_id, page_no, table_no, row_no, col_no,
            cell_text, extraction_method, extracted_at
        ) VALUES
            (105, 1, 5, 1, 6, 3, '225158', 'pdfplumber', '2026-08-25T10:00:00+00:00');
        
        INSERT INTO psp_raw_cell(
            id, report_document_id, page_no, table_no, row_no, col_no,
            cell_text, extraction_method, extracted_at
        ) VALUES
            (106, 1, 5, 1, 7, 3, '223863', 'pdfplumber', '2026-08-25T10:00:00+00:00');

        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey,
            DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES
            (1, 'FactNLDCDailyNational', 'report=1;date=1', 'EveningPeakDemandMetMW', 101, 'pdfplumber', 1.0, '2026-08-25T10:00:00+00:00'),
            (1, 'FactNLDCDailyNational', 'report=1;date=1', 'PeakShortageMW', 102, 'pdfplumber', 1.0, '2026-08-25T10:00:00+00:00'),
            (1, 'FactNLDCDailyInterRegionalExchange', 'report=1;date=1;element=10;counterparty=Northern Region', 'NetMU', 103, 'pdfplumber', 1.0, '2026-08-25T10:00:00+00:00'),
            (1, 'FactNLDCDailyControlAreaDrawal', 'report=1;date=1;entity=20;region=1', 'MaximumDemandMetMW', 104, 'pdfplumber', 1.0, '2026-08-25T10:00:00+00:00');
        
        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey,
            DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES
            (1, 'FactNLDC15MinuteGridSnapshot', 'report=1;date=1;block=00:15', 'DemandMetMW', 105, 'pdfplumber', 1.0, '2026-08-25T10:00:00+00:00');
        
        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey,
            DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES
            (1, 'FactNLDC15MinuteGridSnapshot', 'report=1;date=1;block=00:30', 'DemandMetMW', 106, 'pdfplumber', 1.0, '2026-08-25T10:00:00+00:00');
        """
    )
    conn.commit()
    return conn


def test_nldc_exported_metric_naming_and_entity_grains(
    curated_nldc_conn: sqlite3.Connection,
) -> None:
    """Exported NLDC observations must use nldc. prefixes, ALL region, and structured entity keys."""
    recorded_at = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
    observations = export_registered_daily_observations(
        curated_nldc_conn,
        "grid_india_national",
        ingested_at=recorded_at,
    )

    assert len(observations) > 0

    # 1. Every observation has source_region == 'ALL' and report_type == 'nldc_daily_psp'
    for obs in observations:
        assert obs.source_region == "ALL"
        assert obs.report_type == "nldc_daily_psp"
        assert obs.metric_name.startswith("nldc.FactNLDC")

    # 2. Check metric names do not leak dimension IDs
    forbidden_suffixes = {".DateID", ".RegionID", ".ElementID", ".ReportDocumentID"}
    for obs in observations:
        assert not any(obs.metric_name.endswith(s) for s in forbidden_suffixes)

    # 3. Check entity key formats
    entity_keys = {obs.entity_key for obs in observations}
    assert "NLDC:national" in entity_keys
    assert "NLDC:region:Northern Region" in entity_keys
    assert "NLDC:region:Western Region" in entity_keys
    assert "NLDC:frequency" in entity_keys
    assert "NLDC:line:ALIPURDUAR-AGRA" in entity_keys
    assert "NLDC:line:CHAMPA-KURUKSHETRA" in entity_keys
    assert "NLDC:control-area:Punjab" in entity_keys
    assert "NLDC:all-india-grid" in entity_keys

    snapshot = next(
        observation
        for observation in observations
        if observation.metric_name
        == "nldc.FactNLDC15MinuteGridSnapshot.DemandMetMW"
    )
    assert snapshot.time_block == "00:15"
    assert snapshot.valid_from.isoformat() == "2026-08-25T00:15:00+00:00"
    assert snapshot.valid_to is not None
    assert snapshot.valid_to.isoformat() == "2026-08-25T00:30:00+00:00"


def test_nldc_exported_timeseries_uuid_is_deterministic(
    curated_nldc_conn: sqlite3.Connection,
) -> None:
    """Observations for identical grains must have deterministic timeseries UUIDs."""
    t1 = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 25, 14, 0, 0, tzinfo=timezone.utc)

    obs1 = export_registered_daily_observations(curated_nldc_conn, "grid_india_national", ingested_at=t1)
    obs2 = export_registered_daily_observations(curated_nldc_conn, "grid_india_national", ingested_at=t2)

    assert len(obs1) == len(obs2)
    uuids1 = [o.timeseries_uuid for o in obs1]
    uuids2 = [o.timeseries_uuid for o in obs2]

    assert uuids1 == uuids2
    for uid in uuids1:
        assert UUID(uid)


def test_nldc_observation_lineage_export(
    curated_nldc_conn: sqlite3.Connection,
) -> None:
    """NLDC observation lineage must map accurately to source raw cells."""
    recorded_at = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
    observations = export_registered_daily_observations(
        curated_nldc_conn,
        "grid_india_national",
        ingested_at=recorded_at,
    )

    peak_obs = [
        o for o in observations
        if o.metric_name == "nldc.FactNLDCDailyNational.EveningPeakDemandMetMW"
    ]
    assert len(peak_obs) == 1
    assert peak_obs[0].operational_value == 239057.0

    lineage = export_observation_lineage(curated_nldc_conn, peak_obs)
    assert len(lineage) == 1
    assert lineage[0].timeseries_uuid == peak_obs[0].timeseries_uuid
    assert lineage[0].raw_kind == "cell"
    assert lineage[0].raw_item_id == 101
    assert lineage[0].page_no == 2
    assert lineage[0].table_no == 1
    assert lineage[0].row_no == 1
    assert lineage[0].col_no == 7

    drawal_obs = [
        observation
        for observation in observations
        if observation.metric_name
        == "nldc.FactNLDCDailyControlAreaDrawal.MaximumDemandMetMW"
    ]
    assert len(drawal_obs) == 1
    assert drawal_obs[0].entity_key == "NLDC:control-area:Punjab"
    drawal_lineage = export_observation_lineage(curated_nldc_conn, drawal_obs)
    assert [item.raw_item_id for item in drawal_lineage] == [104]

    snapshot_obs = [
        observation
        for observation in observations
        if observation.metric_name
        == "nldc.FactNLDC15MinuteGridSnapshot.DemandMetMW"
    ]
    assert len(snapshot_obs) == 2
    snapshot_lineage = export_observation_lineage(curated_nldc_conn, snapshot_obs)
    assert [item.raw_item_id for item in snapshot_lineage] == [105, 106]


def test_nldc_correction_version_export(
    curated_nldc_conn: sqlite3.Connection,
) -> None:
    """A revised NLDC publication (revision 2) exports updated operational values with new lineage."""
    # Insert revision 2 of the document
    curated_nldc_conn.executescript(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count
        ) VALUES (
            2, 'grid_india_national', 'https://webcdn.grid-india.in/report_rev2.pdf', 'report_rev2.pdf',
            'nldc-hash-2', '2026-08-26T10:00:00+00:00', 1.0, 0, 'native', 5000
        );

        INSERT INTO FactNLDCDailyNational(
            ReportDocumentID, DateID, EveningPeakDemandMetMW, PeakShortageMW,
            EnergyMetMU, HydroGenMU, WindGenMU, SolarGenMU, EnergyShortageMU,
            MaxDemandMetMW, TimeOfMaxDemand
        ) VALUES (
            2, 1, 240500.0, 1950.0, 5550.0, 715.0, 485.0, 575.0, 7.50, 248000.0, '15:40'
        );

        INSERT INTO psp_raw_cell(
            id, report_document_id, page_no, table_no, row_no, col_no,
            cell_text, extraction_method, extracted_at
        ) VALUES
            (201, 2, 2, 1, 1, 7, '240500', 'pdfplumber', '2026-08-26T10:00:00+00:00');

        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey,
            DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES
            (2, 'FactNLDCDailyNational', 'report=2;date=1', 'EveningPeakDemandMetMW', 201, 'pdfplumber', 1.0, '2026-08-26T10:00:00+00:00');
        """
    )
    curated_nldc_conn.commit()

    recorded_at = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
    rev2_obs = export_all_daily_observations(
        curated_nldc_conn,
        rldcs=["grid_india_national"],
        report_document_id=2,
        ingested_at=recorded_at,
    )

    peak_rev2 = [
        o for o in rev2_obs
        if o.metric_name == "nldc.FactNLDCDailyNational.EveningPeakDemandMetMW"
    ]
    assert len(peak_rev2) == 1
    assert peak_rev2[0].operational_value == 240500.0
    assert peak_rev2[0].destination_key == "report=2;date=1"

    lineage_rev2 = export_observation_lineage(curated_nldc_conn, peak_rev2)
    assert len(lineage_rev2) == 1
    assert lineage_rev2[0].raw_item_id == 201
