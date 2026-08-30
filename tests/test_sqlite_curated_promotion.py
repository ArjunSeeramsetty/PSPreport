from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import LocalReportInput, run_rldc_local_pdf_ingestion
from psp_pipeline.storage.sqlite_curated_promoter import repromote_srldc_reports
from psp_pipeline.storage.sqlite_curated_export import (
    export_observation_lineage,
    export_srldc_daily_observations,
)


def test_repromotion_replaces_existing_coverage_evidence(tmp_path: Path) -> None:
    """A repeat promotion must not retain stale coverage rows or items."""

    pdf_path = Path("downloads/SRLDC_PSP/27-05-2026-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp.db"
    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2026, 5, 27))],
    )

    with sqlite3.connect(db_path) as conn:
        first = repromote_srldc_reports(conn)
        second = repromote_srldc_reports(conn)
        assert first == second == {"reports_total": 1, "promoted": 1, "skipped": 0}
        assert conn.execute("SELECT COUNT(*) FROM schema_coverage_run").fetchone()[0] == 1
        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM schema_coverage_item AS item
            LEFT JOIN schema_coverage_run AS run
              ON run.CoverageRunID = item.CoverageRunID
            WHERE run.CoverageRunID IS NULL
            """
        ).fetchone()[0] == 0


def test_template_matched_srldc_report_promotes_with_lineage_and_coverage(tmp_path: Path) -> None:
    pdf_path = Path("downloads/SRLDC_PSP/27-05-2026-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp.db"

    result = run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2026, 5, 27))],
    )

    assert result["reports_persisted"] == 1
    conn = sqlite3.connect(db_path)
    summary = conn.execute(
        """
        SELECT EveningPeakDemandMetMW, EveningPeakShortageMW, DayEnergyMetMU,
               DayEnergyShortageMU, MaximumDemandMetMW, MaximumDemandTime,
               ScheduleDrawalMU, ActualDrawalMU, OverUnderDrawalMU
        FROM FactSRLDCRegionalDaily
        """
    ).fetchone()
    assert summary == (55086.0, 0.0, 1232.27, 0.0, 58515.0, "14:56:00", 504.78, 505.36, 0.58)

    assert conn.execute("SELECT COUNT(*) FROM FactAllIndiaDailySummary").fetchone()[0] == 0

    state_count = conn.execute("SELECT COUNT(*) FROM FactSRLDCStateDaily").fetchone()[0]
    assert state_count == 6
    andhra = conn.execute(
        """
        SELECT MaximumDemandMetMW, ShortageAtMaximumDemandMW, DemandMetMU,
               NetScheduleMU, UIMU, EnergyShortageMU, ForecastType,
               ForecastDemandMU, ActualDemandMU, ForecastDeviationMU
        FROM FactSRLDCStateDaily AS f
        JOIN DimStates AS s ON f.StateID = s.StateID
        WHERE s.StateName = 'Andhra Pradesh'
        """
    ).fetchone()
    assert andhra[:6] == (12040.0, 0.0, 240.67, 68.38, -2.29, 0.0)
    assert andhra[6] == "LGBR"
    assert all(value is not None for value in andhra[7:])

    generation_count = conn.execute(
        "SELECT COUNT(*) FROM FactSRLDCGenerationDaily"
    ).fetchone()[0]
    assert generation_count == 283
    hinduja = conn.execute(
        """
        SELECT f.InstalledCapacityMW, f.NetEnergyMU, f.AverageMW,
               s.StateName, gs.SourceName, f.GenerationGrain
        FROM FactSRLDCGenerationDaily AS f
        JOIN DimGridEntities AS e ON e.EntityID = f.EntityID
        LEFT JOIN DimStates AS s ON s.StateID = f.StateID
        LEFT JOIN DimGenerationSources AS gs
          ON gs.GenerationSourceID = f.GenerationSourceID
        WHERE e.EntityName = 'HINDUJA POWER CORPORATION LTD ( 2*520 )'
        """
    ).fetchone()
    assert hinduja == (
        1040.0, 19.59, 816.0, "Andhra Pradesh", "Thermal", "power_station"
    )
    total_thermal = conn.execute(
        """
        SELECT s.StateName, gs.SourceName, f.GenerationGrain, f.IsTotalRow,
               f.InstalledCapacityMW
        FROM FactSRLDCGenerationDaily AS f
        JOIN DimGridEntities AS e ON e.EntityID = f.EntityID
        LEFT JOIN DimStates AS s ON s.StateID = f.StateID
        LEFT JOIN DimGenerationSources AS gs
          ON gs.GenerationSourceID = f.GenerationSourceID
        WHERE e.EntityName = 'Total Thermal' AND s.StateName = 'Andhra Pradesh'
        """
    ).fetchone()
    assert total_thermal == (
        "Andhra Pradesh", "Thermal", "aggregate", 1, 8310.0
    )

    frequency = conn.execute(
        """
        SELECT MaximumFrequencyHz, MinimumFrequencyHz, AverageFrequencyHz,
               DurationBelow49_90Pct, Duration49_90To50_05InclusivePct,
               DurationAbove50_05Pct
        FROM FactSRLDCRegionalDaily
        """
    ).fetchone()
    assert frequency == (50.227, 49.742, 50.008, 3.854, 80.694, 15.451)

    assert conn.execute(
        "SELECT COUNT(*) FROM FactSRLDCVoltageProfile"
    ).fetchone()[0] == 26
    kurnool_voltage = conn.execute(
        """
        SELECT MaximumKV, MinimumKV, LowCriticalPct, LowWarningPct,
               HighWarningPct, HighCriticalPct, s.StateName, r.RegionName
        FROM FactSRLDCVoltageProfile AS f
        JOIN DimVoltageNodes AS n ON n.VoltageNodeID = f.VoltageNodeID
        LEFT JOIN DimStates AS s ON s.StateID = n.StateID
        LEFT JOIN DimRegions AS r ON r.RegionID = n.RegionID
        WHERE n.NodeName = 'KURNOOL - 765KV'
        """
    ).fetchone()
    assert kurnool_voltage == (
        813.0, 775.0, 0.0, 0.0, 92.57, 23.89,
        "Andhra Pradesh", "Southern Region",
    )

    assert conn.execute(
        "SELECT COUNT(*) FROM FactSRLDCReservoirDaily"
    ).fetchone()[0] == 8
    idukki = conn.execute(
        """
        SELECT MinimumDrawdownLevelM, FullReservoirLevelM, DesignedEnergyMU,
               CurrentLevelM, CurrentEnergyMU, PreviousYearLevelM,
               PreviousYearEnergyMU, InflowMU, UsageMU,
               ProgressiveInflowMU, ProgressiveUsageMU,
               s.StateName, rg.RegionName
        FROM FactSRLDCReservoirDaily AS f
        JOIN DimReservoirs AS r ON r.ReservoirID = f.ReservoirID
        LEFT JOIN DimStates AS s ON s.StateID = r.StateID
        LEFT JOIN DimRegions AS rg ON rg.RegionID = r.RegionID
        WHERE r.ReservoirName = 'IDUKKI'
        """
    ).fetchone()
    assert idukki == (
        694.94, 732.43, 2148.0, 706.75, 483.0, 711.29,
        719.0, 2.11, 10.86, 24.14, 218.04,
        "Kerala", "Southern Region",
    )

    assert conn.execute(
        "SELECT COUNT(*) FROM FactSRLDCInterRegionalExchange"
    ).fetchone()[0] == 45
    srikakulam = conn.execute(
        """
        SELECT EveningPeakMW, OffPeakMW, MaximumImportMW,
               ImportEnergyMU, ExportEnergyMU, NetEnergyMU,
               fs.StateName, fr.RegionName, ts.StateName, tr.RegionName
        FROM FactSRLDCInterRegionalExchange AS f
        JOIN DimTransmissionElements AS e ON e.ElementID = f.ElementID
        LEFT JOIN DimStates AS fs ON fs.StateID = e.FromStateID
        LEFT JOIN DimRegions AS fr ON fr.RegionID = e.FromRegionID
        LEFT JOIN DimStates AS ts ON ts.StateID = e.ToStateID
        LEFT JOIN DimRegions AS tr ON tr.RegionID = e.ToRegionID
        WHERE e.ElementName = '765KV-SRIKAKULAM-ANGUL'
          AND f.ExchangeCategory = 'physical_flow'
        """
    ).fetchone()
    assert srikakulam == (
        962.0, 480.0, 1362.0, 42.08, 0.0, 42.08,
        "Andhra Pradesh", "Southern Region", "Odisha", "Eastern Region",
    )

    assert conn.execute(
        "SELECT COUNT(*) FROM FactSRLDCMarketTransaction"
    ).fetchone()[0] == 282
    andhra_peak_dam = conn.execute(
        """
        SELECT f.ScheduledMW
        FROM FactSRLDCMarketTransaction AS f
        JOIN DimStates AS s ON s.StateID = f.StateID
        JOIN DimExchangeMechanisms AS m ON m.MechanismID = f.MechanismID
        WHERE s.StateName = 'Andhra Pradesh'
          AND m.MechanismName = 'IEX DAM'
          AND f.TimeCategory = 'evening_peak'
        """
    ).fetchone()
    assert andhra_peak_dam == (329.07,)

    assert conn.execute(
        "SELECT COUNT(*) FROM FactSRLDCOperationalEvent"
    ).fetchone()[0] == 90
    tamil_non_compliance = conn.execute(
        """
        SELECT e.OccurrenceCount
        FROM FactSRLDCOperationalEvent AS e
        JOIN DimStates AS s ON s.StateID = e.StateID
        JOIN DimEventTypes AS t ON t.EventTypeID = e.EventTypeID
        WHERE s.StateName = 'Tamil Nadu'
          AND t.EventTypeName = 'frequency_deviation_non_compliance'
        """
    ).fetchone()
    assert tamil_non_compliance == (5,)

    annotation_counts = dict(conn.execute(
        """
        SELECT SectionName, COUNT(*) FROM FactSRLDCReportAnnotation
        GROUP BY SectionName
        """
    ).fetchall())
    assert annotation_counts == {
        "significant_events": 1,
        "transmission_constraints": 7,
        "weather_condition": 3,
    }

    assert conn.execute(
        """
        SELECT COUNT(*) FROM FactSRLDCGenerationDaily
        WHERE StationID IS NULL AND AggregateID IS NULL
        """
    ).fetchone()[0] == 0
    assert conn.execute(
        """
        SELECT COUNT(*) FROM FactSRLDCGenerationDaily
        WHERE GenerationSourceID IS NULL
        """
    ).fetchone()[0] == 0
    assert conn.execute(
        """
        SELECT COUNT(*) FROM FactSRLDCGenerationDaily
        WHERE StateID IS NULL
          AND SectionName NOT LIKE 'regional_%'
        """
    ).fetchone()[0] == 0
    hinduja_identity = conn.execute(
        """
        SELECT s.StationCode, s.CanonicalStationName,
               gs.SourceName, f.GenerationGrain
        FROM FactSRLDCGenerationDaily AS f
        JOIN DimGridEntities AS e ON e.EntityID = f.EntityID
        JOIN DimPowerStations AS s ON s.StationID = f.StationID
        JOIN DimGenerationSources AS gs
          ON gs.GenerationSourceID = f.GenerationSourceID
        WHERE e.EntityName = 'HINDUJA POWER CORPORATION LTD ( 2*520 )'
        """
    ).fetchone()
    assert hinduja_identity[0].startswith("STN-")
    assert hinduja_identity[1] == "HINDUJA POWER CORPORATION LTD"
    assert hinduja_identity[2] == "Thermal"
    assert hinduja_identity[3] == "power_station"
    assert conn.execute(
        "SELECT COUNT(*) FROM DimGeneratingUnits"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM dimension_resolution_issue"
    ).fetchone()[0] == 0
    dimension_counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "DimPowerStations", "DimGeneratingUnits",
            "DimGenerationAggregates", "DimEntityAliases",
        )
    }

    assert conn.execute("SELECT COUNT(*) FROM FactSRLDCStateDaily").fetchone()[0] == 6
    lineage_count = conn.execute(
        "SELECT COUNT(*) FROM curated_field_lineage"
    ).fetchone()[0]
    assert lineage_count > 3800
    coverage = conn.execute(
        """
        SELECT MappedFieldCount, AmbiguousFieldCount, MissingRequiredCount,
               LineageCompleteCount, Status
        FROM schema_coverage_run
        """
    ).fetchone()
    assert coverage[0] == lineage_count
    assert coverage[1] > 0
    assert coverage[2] == 0
    assert coverage[3] == lineage_count
    assert coverage[4] == "review_required"
    assert conn.execute(
        "SELECT CoveragePct FROM schema_coverage_run"
    ).fetchone()[0] > 85.0
    assert conn.execute("SELECT COUNT(*) FROM schema_proposal").fetchone()[0] > 0
    first_cell_ids = conn.execute(
        "SELECT id FROM psp_raw_cell ORDER BY id LIMIT 10"
    ).fetchall()
    first_coverage_items = conn.execute(
        "SELECT COUNT(*) FROM schema_coverage_item"
    ).fetchone()[0]
    conn.close()

    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2026, 5, 27))],
    )
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT id FROM psp_raw_cell ORDER BY id LIMIT 10").fetchall() == first_cell_ids
    assert conn.execute("SELECT COUNT(*) FROM schema_coverage_run").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM schema_coverage_item").fetchone()[0] == first_coverage_items
    assert conn.execute("SELECT COUNT(*) FROM curated_field_lineage").fetchone()[0] == lineage_count
    assert {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in dimension_counts
    } == dimension_counts
    conn.close()


def test_compact_srldc_template_promotes_shifted_sections(tmp_path: Path) -> None:
    pdf_path = Path("downloads/SRLDC_PSP/01-01-2026-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("Compact SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_compact.db"

    result = run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2026, 1, 1))],
    )

    assert result["reports_persisted"] == 1
    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT template_id FROM psp_report_document"
    ).fetchone()[0] == "srldc_daily_psp_v2026_01"
    assert conn.execute(
        "SELECT semantic_pass_required FROM psp_report_document"
    ).fetchone()[0] == 0
    counts = {
        "generation": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCGenerationDaily"
        ).fetchone()[0],
        "state": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCStateDaily"
        ).fetchone()[0],
        "voltage": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCVoltageProfile"
        ).fetchone()[0],
        "reservoir": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCReservoirDaily"
        ).fetchone()[0],
        "exchange": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCInterRegionalExchange"
        ).fetchone()[0],
        "market": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCMarketTransaction"
        ).fetchone()[0],
        "events": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCOperationalEvent"
        ).fetchone()[0],
        "annotations": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCReportAnnotation"
        ).fetchone()[0],
    }
    assert counts == {
        "generation": 219,
        "state": 6,
        "voltage": 26,
        "reservoir": 8,
        "exchange": 45,
        "market": 282,
        "events": 90,
        "annotations": 11,
    }
    assert conn.execute(
        "SELECT COUNT(*) FROM FactSRLDCGenerationDaily WHERE GenerationSourceID IS NULL"
    ).fetchone()[0] == 0
    assert conn.execute(
        """
        SELECT COUNT(*) FROM FactSRLDCGenerationDaily
        WHERE StateID IS NULL AND SectionName NOT LIKE 'regional_%'
        """
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT CoveragePct FROM schema_coverage_run"
    ).fetchone()[0] > 80.0
    assert conn.execute(
        """
        SELECT s.StateName, r.RegionName
        FROM DimVoltageNodes AS n
        LEFT JOIN DimStates AS s ON s.StateID = n.StateID
        LEFT JOIN DimRegions AS r ON r.RegionID = n.RegionID
        WHERE n.NodeName = 'KURNOOL - 765KV'
        """
    ).fetchone() == ("Andhra Pradesh", "Southern Region")
    assert conn.execute(
        """
        SELECT s.StateName, rg.RegionName
        FROM DimReservoirs AS d
        LEFT JOIN DimStates AS s ON s.StateID = d.StateID
        LEFT JOIN DimRegions AS rg ON rg.RegionID = d.RegionID
        WHERE d.ReservoirName = 'IDUKKI'
        """
    ).fetchone() == ("Kerala", "Southern Region")
    assert conn.execute(
        """
        SELECT fs.StateName, fr.RegionName, ts.StateName, tr.RegionName
        FROM DimTransmissionElements AS e
        LEFT JOIN DimStates AS fs ON fs.StateID = e.FromStateID
        LEFT JOIN DimRegions AS fr ON fr.RegionID = e.FromRegionID
        LEFT JOIN DimStates AS ts ON ts.StateID = e.ToStateID
        LEFT JOIN DimRegions AS tr ON tr.RegionID = e.ToRegionID
        WHERE e.ElementName = '765KV-SRIKAKULAM-ANGUL'
        """
    ).fetchone() == (
        "Andhra Pradesh", "Southern Region", "Odisha", "Eastern Region"
    )
    conn.close()


def test_flat_8_srldc_template_promotes_historical_flattened_layout(tmp_path: Path) -> None:
    pdf_path = Path("downloads/SRLDC_PSP/15-12-2024-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("Flattened 8-page SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_flat8.db"

    result = run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2024, 12, 15))],
    )

    assert result["reports_persisted"] == 1
    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT template_id FROM psp_report_document"
    ).fetchone()[0] == "srldc_daily_psp_v2024_flat_08"
    assert conn.execute(
        "SELECT semantic_pass_required FROM psp_report_document"
    ).fetchone()[0] == 0
    counts = {
        "regional": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCRegionalDaily"
        ).fetchone()[0],
        "state": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCStateDaily"
        ).fetchone()[0],
        "generation": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCGenerationDaily"
        ).fetchone()[0],
        "voltage": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCVoltageProfile"
        ).fetchone()[0],
        "reservoir": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCReservoirDaily"
        ).fetchone()[0],
        "exchange": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCInterRegionalExchange"
        ).fetchone()[0],
        "market": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCMarketTransaction"
        ).fetchone()[0],
        "events": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCOperationalEvent"
        ).fetchone()[0],
        "annotations": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCReportAnnotation"
        ).fetchone()[0],
    }
    assert counts == {
        "regional": 1,
        "state": 6,
        "generation": 128,
        "voltage": 22,
        "reservoir": 8,
        "exchange": 21,
        "market": 90,
        "events": 42,
        "annotations": 2,
    }
    assert conn.execute(
        "SELECT CoveragePct FROM schema_coverage_run"
    ).fetchone()[0] > 45.0
    assert conn.execute(
        "SELECT COUNT(*) FROM FactSRLDCReservoirDaily WHERE DesignedEnergyMU IS NOT NULL"
    ).fetchone()[0] == 8
    assert conn.execute(
        "SELECT COUNT(*) FROM FactSRLDCVoltageProfile WHERE MaximumKV IS NOT NULL"
    ).fetchone()[0] == 22
    conn.close()


def test_flat_6_2023_generation_columns_preserve_gross_net_and_average(
    tmp_path: Path,
) -> None:
    """Map the verified nine-column 2023 station-generation layout."""

    pdf_path = Path("downloads/SRLDC_PSP/01-04-2023-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("April 2023 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_april_2023.db"

    result = run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2023, 4, 1))],
    )

    assert result["reports_persisted"] == 1
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """
        SELECT f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW,
               f.MinimumGenerationMW, f.MinimumGenerationTime
        FROM FactSRLDCGenerationDaily AS f
        JOIN DimGridEntities AS e ON e.EntityID = f.EntityID
        WHERE e.EntityName = 'BHADRADRITPS(4*270)'
        """
    ).fetchone()
    conn.close()

    assert row == (21.16, 19.39, 808.0, None, None)

    conn = sqlite3.connect(db_path)
    renewable = conn.execute(
        """
        SELECT f.InstalledCapacityMW, f.EveningPeakMW, f.OffPeakMW,
               f.DayPeakMW, f.DayPeakTime, f.GrossEnergyMU, f.NetEnergyMU,
               f.AverageMW
        FROM FactSRLDCGenerationDaily AS f
        JOIN DimGridEntities AS e ON e.EntityID = f.EntityID
        WHERE e.EntityName = 'BEETAM(1*220)'
        """
    ).fetchone()
    wind_total = conn.execute(
        """
        SELECT f.InstalledCapacityMW, f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW
        FROM FactSRLDCGenerationDaily AS f
        JOIN DimGridEntities AS e ON e.EntityID = f.EntityID
        WHERE e.EntityName = 'TotalRENEWABLE_WIND'
        """
    ).fetchone()
    conn.close()

    assert renewable == (220.0, 44.0, 22.0, 144.0, "17:41:00", 0.78, 0.78, 33.0)
    assert wind_total == (1516.0, 5.43, 5.43, 228.0)
    conn = sqlite3.connect(db_path)
    hinduja = conn.execute(
        """
        SELECT f.InstalledCapacityMW, f.EveningPeakMW, f.OffPeakMW,
               f.DayPeakMW, f.DayPeakTime, f.GrossEnergyMU, f.NetEnergyMU,
               f.AverageMW, source.SourceName
        FROM FactSRLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        JOIN DimGenerationSources AS source
          ON source.GenerationSourceID = f.GenerationSourceID
        WHERE entity.EntityName = 'HINDUJAPOWERCORPORATIONLTD(2*520)'
        """
    ).fetchone()
    disposition = conn.execute(
        """
        SELECT item.Disposition
        FROM schema_coverage_item AS item
        JOIN psp_raw_cell AS raw ON raw.id = item.RawCellID
        WHERE raw.page_no = 4 AND raw.table_no = 1 AND raw.row_no = 3
          AND raw.col_no = 9
        """
    ).fetchone()
    conn.close()
    assert hinduja == (
        1040.0, 588.0, 599.0, 605.0, "14:58:00", 13.17, 13.17, 549.0,
        "Thermal",
    )
    assert disposition == ("header",)


def test_flat_6_state_position_uses_sparse_page_one_columns(tmp_path: Path) -> None:
    """Map each published flat-six state-position metric to its fact column."""

    pdf_path = Path("downloads/SRLDC_PSP/01-04-2023-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("April 2023 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_flat6_state_position.db"

    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2023, 4, 1))],
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT f.ThermalGenerationMU, f.HydroGenerationMU,
                   f.GasDieselNapthaGenerationMU, f.WindGenerationMU,
                   f.SolarGenerationMU, f.OtherGenerationMU, f.NetScheduleMU,
                   f.DrawalMU, f.UIMU, f.AvailabilityMU, f.DemandMetMU,
                   f.EnergyShortageMU, f.EveningPeakDemandMetMW,
                   f.EveningPeakShortageMW, f.EveningPeakRequirementMW,
                   f.OffPeakDemandMetMW, f.OffPeakShortageMW,
                   f.OffPeakRequirementMW, f.ForecastDemandMU,
                   f.ActualDemandMU, f.ForecastDeviationMU,
                   f.MaximumDemandMetMW, f.MaximumDemandTime,
                   f.RequirementAtMaximumDemandMW, f.MaximumRequirementMW
            FROM FactSRLDCStateDaily AS f
            JOIN DimStates AS state ON state.StateID = f.StateID
            WHERE state.StateName = 'Andhra Pradesh'
            """
        ).fetchone()

    assert row == (
        111.07, 7.6, 0.0, 7.86, 15.31, 1.6, 77.26, 76.92, -0.34,
        220.71, 220.36, 0.0, 8670.0, 24.0, 8646.0, 8090.0, 24.0,
        8066.0, 230.0, 239.64, -9.64, 10979.0, "12:31:00", 10979.0,
        10979.0,
    )


def test_flat_6_page_five_physical_exchange_uses_shifted_columns(
    tmp_path: Path,
) -> None:
    """Keep the Page 5 continuation's export and net-energy coordinates."""

    pdf_path = Path("downloads/SRLDC_PSP/01-04-2023-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("April 2023 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_flat6_exchange.db"

    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2023, 4, 1))],
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT f.EveningPeakMW, f.OffPeakMW, f.MaximumImportMW,
                   f.MaximumExportMW, f.ImportEnergyMU, f.ExportEnergyMU,
                   f.NetEnergyMU
            FROM FactSRLDCInterRegionalExchange AS f
            JOIN DimTransmissionElements AS element ON element.ElementID = f.ElementID
            WHERE element.ElementName = 'TOTALIREXCHANGE'
              AND f.ExchangeCategory = 'physical_flow'
            """
        ).fetchone()

    assert row == (10008.0, 12784.0, 17089.0, 1216.0, 339.84, 21.1, 318.74)


def test_flat_6_market_range_lineage_uses_shifted_columns(tmp_path: Path) -> None:
    """Preserve Page 6 flat-six market offsets even when values are zero."""

    pdf_path = Path("downloads/SRLDC_PSP/01-04-2023-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("April 2023 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_flat6_market_ranges.db"

    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2023, 4, 1))],
    )

    with sqlite3.connect(db_path) as conn:
        columns = conn.execute(
            """
            SELECT lineage.DestinationKey, lineage.DestinationColumn, raw.col_no
            FROM curated_field_lineage AS lineage
            JOIN psp_raw_cell AS raw ON raw.id = lineage.RawCellID
            WHERE lineage.DestinationTable = 'FactSRLDCMarketTransaction'
              AND raw.page_no = 6 AND raw.row_no = 24
              AND raw.col_no IN (32, 35)
            ORDER BY raw.col_no
            """
        ).fetchall()
        pxil_dam = conn.execute(
            """
            SELECT lineage.DestinationColumn, raw.col_no
            FROM curated_field_lineage AS lineage
            JOIN psp_raw_cell AS raw ON raw.id = lineage.RawCellID
            WHERE lineage.DestinationTable = 'FactSRLDCMarketTransaction'
              AND raw.page_no = 6 AND raw.row_no = 33
              AND raw.col_no IN (14, 18)
            ORDER BY raw.col_no
            """
        ).fetchall()

    assert [item[1:] for item in columns] == [("MaximumMW", 32), ("MinimumMW", 35)]
    assert pxil_dam == [("MaximumMW", 14), ("MinimumMW", 18)]


def test_flat_7_generation_columns_preserve_minimum_generation(tmp_path: Path) -> None:
    """Keep the full eleven-column generation schema for late-2024 reports."""

    pdf_path = Path("downloads/SRLDC_PSP/15-10-2024-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("October 2024 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_october_2024.db"

    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2024, 10, 15))],
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """
        SELECT f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW,
               f.MinimumGenerationMW, f.MinimumGenerationTime
        FROM FactSRLDCGenerationDaily AS f
        JOIN DimGridEntities AS e ON e.EntityID = f.EntityID
        WHERE e.EntityName = 'BHADRADRITPS(4*270)'
        """
    ).fetchone()
    conn.close()

    assert row == (11.48, 10.12, 422.0, 413.0, "15:22:00")


def test_flat_7_2023_generation_rows_use_compact_energy_columns(tmp_path: Path) -> None:
    """Recognize the pre-minimum-generation variant within the flat-07 family."""

    pdf_path = Path("downloads/SRLDC_PSP/15-10-2023-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("October 2023 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_october_2023.db"

    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2023, 10, 15))],
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW,
                   f.MinimumGenerationMW, f.MinimumGenerationTime
            FROM FactSRLDCGenerationDaily AS f
            JOIN DimGridEntities AS e ON e.EntityID = f.EntityID
            WHERE e.EntityName = 'BHADRADRITPS(4*270)'
            """
        ).fetchone()

    assert row == (20.31, 18.48, 770.0, None, None)


def test_flat_7_state_position_uses_extended_page_one_columns(tmp_path: Path) -> None:
    """Map flat-seven state energy, forecast, peak, and ACE coordinates."""

    pdf_path = Path("downloads/SRLDC_PSP/15-10-2023-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("October 2023 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_flat7_state_position.db"

    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2023, 10, 15))],
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT f.OtherGenerationMU, f.NetScheduleMU, f.DrawalMU, f.UIMU,
                   f.AvailabilityMU, f.DemandMetMU, f.ForecastDemandMU,
                   f.ActualDemandMU, f.ForecastDeviationMU,
                   f.DemandAtMaximumRequirementMW, f.AceMaximumMW,
                   f.AceMaximumTime, f.AceMinimumMW, f.AceMinimumTime
            FROM FactSRLDCStateDaily AS f
            JOIN DimStates AS state ON state.StateID = f.StateID
            WHERE state.StateName = 'Andhra Pradesh'
            """
        ).fetchone()

    assert row == (
        1.89, 112.59, 112.07, -0.52, 240.14, 239.62, 233.0, 226.38,
        6.62, 12443.0, 664.56, "13:08:00", -616.82, "08:14:00",
    )


def test_flat_7_page_four_uses_heading_driven_wide_renewable_geometry(
    tmp_path: Path,
) -> None:
    """Map the shifted 2024 Page 4 renewable generation sections."""

    pdf_path = Path("downloads/SRLDC_PSP/15-01-2024-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("January 2024 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_january_2024.db"

    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2024, 1, 15))],
    )

    with sqlite3.connect(db_path) as conn:
        beetam = conn.execute(
            """
            SELECT f.InstalledCapacityMW, f.EveningPeakMW, f.OffPeakMW,
                   f.DayPeakMW, f.DayPeakTime, f.GrossEnergyMU,
                   f.NetEnergyMU, f.AverageMW, source.SourceName
            FROM FactSRLDCGenerationDaily AS f
            JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
            JOIN DimGenerationSources AS source
              ON source.GenerationSourceID = f.GenerationSourceID
            WHERE entity.EntityName = 'BEETAM(1*220)'
            """
        ).fetchone()
        wind_total = conn.execute(
            """
            SELECT f.InstalledCapacityMW, f.GrossEnergyMU, f.NetEnergyMU,
                   f.AverageMW, source.SourceName
            FROM FactSRLDCGenerationDaily AS f
            JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
            JOIN DimGenerationSources AS source
              ON source.GenerationSourceID = f.GenerationSourceID
            WHERE entity.EntityName = 'TotalRENEWABLE_WIND'
            """
        ).fetchone()

    assert beetam == (220.0, 56.0, 23.0, 61.0, "20:03:00", 1.0, 1.0, 42.0, "Wind")
    assert wind_total == (1864.0, 9.16, 7.45, 312.0, "Wind")


def test_flat_8_forecast_uses_signed_deviation_to_derive_consumption(
    tmp_path: Path,
) -> None:
    """Apply the published flattened-table forecast minus consumption convention."""

    pdf_path = Path("downloads/SRLDC_PSP/15-12-2024-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("December 2024 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_december_2024.db"
    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2024, 12, 15))],
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """
        SELECT f.ForecastDemandMU, f.ActualDemandMU, f.ForecastDeviationMU
        FROM FactSRLDCStateDaily AS f
        JOIN DimStates AS s ON s.StateID = f.StateID
        WHERE s.StateName = 'Andhra Pradesh'
        """
    ).fetchone()
    conn.close()

    assert row == (193.0, 196.74, -3.74)


def test_flat_8_2025_frequency_profile_maps_published_bands(tmp_path: Path) -> None:
    """Map the shifted 2025 flattened frequency profile coordinates."""

    pdf_path = Path("downloads/SRLDC_PSP/15-07-2025-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("July 2025 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_july_2025.db"
    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2025, 7, 15))],
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """
        SELECT DurationBelow49_90Pct, Duration49_90To50_05InclusivePct,
               DurationAbove50_05Pct, MaximumFrequencyHz,
               MinimumFrequencyHz, AverageFrequencyHz
        FROM FactSRLDCRegionalDaily
        """
    ).fetchone()
    conn.close()

    assert row == (12.199, 67.431, 20.37, 50.177, 49.608, 49.989)
    assert round(sum(row[:3]), 3) == 100.0


def test_flat_6_regional_market_totals_and_frequency_extrema_are_promoted(
    tmp_path: Path,
) -> None:
    """Keep regional TOTAL market rows distinct from state transactions."""

    pdf_path = Path("downloads/SRLDC_PSP/01-04-2023-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("April 2023 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_april_2023.db"
    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2023, 4, 1))],
    )

    with sqlite3.connect(db_path) as conn:
        regional_market = conn.execute(
            """
            SELECT market.ScheduledMW
            FROM FactSRLDCRegionalMarketTransaction AS market
            JOIN DimExchangeMechanisms AS mechanism
              ON mechanism.MechanismID = market.MechanismID
            WHERE mechanism.MechanismName = 'TGNA'
              AND market.TimeCategory = 'off_peak'
            """
        ).fetchone()
        extrema = conn.execute(
            """
            SELECT Maximum15MinuteBlockFrequencyHz,
                   Minimum15MinuteBlockFrequencyHz
            FROM FactSRLDCRegionalDaily
            """
        ).fetchone()
        observations = export_srldc_daily_observations(conn)

    assert regional_market == (4739.6,)
    assert extrema == (50.19, 49.88)
    assert any(
        observation.metric_name.endswith("Maximum15MinuteBlockFrequencyHz")
        for observation in observations
    )


def test_srldc_governed_exports_have_exact_cell_lineage(tmp_path: Path) -> None:
    """Export every lineage-safe numeric SRLDC fact family without collisions."""

    pdf_path = Path("downloads/SRLDC_PSP/01-01-2026-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("January 2026 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_january_2026.db"
    run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2026, 1, 1))],
    )

    with sqlite3.connect(db_path) as conn:
        observations = export_srldc_daily_observations(conn)
        lineage = export_observation_lineage(conn, observations)

    exported_tables = {item.destination_table for item in observations}
    assert exported_tables == {
        "FactSRLDCRegionalDaily",
        "FactSRLDCStateDaily",
        "FactSRLDCGenerationDaily",
        "FactSRLDCInterRegionalExchange",
        "FactSRLDCVoltageProfile",
        "FactSRLDCReservoirDaily",
        "FactSRLDCMarketTransaction",
        "FactSRLDCRegionalMarketTransaction",
    }
    assert all(item.destination_key is not None for item in observations)
    assert len({item.series_key for item in observations}) == len(observations)
    assert {item.timeseries_uuid for item in lineage} == {
        item.timeseries_uuid for item in observations
    }
    assert not any("MechanismID" in item.metric_name for item in observations)
    assert not any(
        item.metric_name.endswith("ForecastDeviationPct") for item in observations
    )


@pytest.mark.parametrize(
    ("filename", "report_date"),
    [
        ("01-04-2023-psp.pdf", date(2023, 4, 1)),
        ("15-04-2024-psp.pdf", date(2024, 4, 15)),
        ("01-01-2026-psp.pdf", date(2026, 1, 1)),
    ],
)
def test_srldc_governed_exports_preserve_lineage_across_layout_eras(
    tmp_path: Path,
    filename: str,
    report_date: date,
) -> None:
    """Keep exported SRLDC fields collision-free across approved layout eras."""

    pdf_path = Path("downloads/SRLDC_PSP") / filename
    if not pdf_path.exists():
        pytest.skip(f"SRLDC fixture PDF is not available locally: {filename}")
    db_path = tmp_path / f"srldc_export_{report_date.isoformat()}.db"
    result = run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, report_date)],
    )
    assert result["reports_persisted"] == 1

    with sqlite3.connect(db_path) as conn:
        observations = export_srldc_daily_observations(conn)
        lineage = export_observation_lineage(conn, observations)

    assert observations
    assert all(item.destination_key is not None for item in observations)
    assert len({item.series_key for item in observations}) == len(observations)
    assert {item.timeseries_uuid for item in lineage} == {
        item.timeseries_uuid for item in observations
    }


def test_april_2024_wide_operations_layout_promotes_all_available_fact_domains(
    tmp_path: Path,
) -> None:
    """Promote the verified April 2024 sparse-column SRLDC layout."""

    pdf_path = Path("downloads/SRLDC_PSP/15-04-2024-psp.pdf")
    if not pdf_path.exists():
        pytest.skip("April 2024 SRLDC fixture PDF is not available locally")
    db_path = tmp_path / "rldc_daily_psp_april_2024.db"

    result = run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput("srldc", pdf_path, date(2024, 4, 15))],
    )

    assert result["reports_persisted"] == 1
    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT template_id FROM psp_report_document"
    ).fetchone()[0] == "srldc_daily_psp_v2024_flat_06_wide_operations"
    assert conn.execute(
        "SELECT semantic_pass_required FROM psp_report_document"
    ).fetchone()[0] == 0

    counts = {
        "regional": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCRegionalDaily"
        ).fetchone()[0],
        "state": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCStateDaily"
        ).fetchone()[0],
        "generation": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCGenerationDaily"
        ).fetchone()[0],
        "voltage": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCVoltageProfile"
        ).fetchone()[0],
        "reservoir": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCReservoirDaily"
        ).fetchone()[0],
        "exchange": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCInterRegionalExchange"
        ).fetchone()[0],
        "market": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCMarketTransaction"
        ).fetchone()[0],
        "events": conn.execute(
            "SELECT COUNT(*) FROM FactSRLDCOperationalEvent"
        ).fetchone()[0],
    }
    assert counts == {
        "regional": 1,
        "state": 6,
        "generation": 107,
        "voltage": 14,
        "reservoir": 8,
        "exchange": 32,
        "market": 268,
        "events": 18,
    }

    voltage_counts = dict(conn.execute(
        """
        SELECT n.NominalVoltageKV, COUNT(*)
        FROM FactSRLDCVoltageProfile AS f
        JOIN DimVoltageNodes AS n ON n.VoltageNodeID = f.VoltageNodeID
        GROUP BY n.NominalVoltageKV
        """
    ).fetchall())
    assert voltage_counts == {220.0: 10, 765.0: 4}
    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM FactSRLDCMarketTransaction AS f
        JOIN DimExchangeMechanisms AS m ON m.MechanismID = f.MechanismID
        WHERE m.MechanismName = 'HPX RTM'
        """
    ).fetchone()[0] == 16
    assert conn.execute(
        """
        SELECT MaximumFrequencyHz, MinimumFrequencyHz, AverageFrequencyHz,
               DurationBelow49_90Pct, Duration49_90To50_05InclusivePct,
               DurationAbove50_05Pct
        FROM FactSRLDCRegionalDaily
        """
    ).fetchone() == (50.279, 49.64, 49.983, 13.194, 70.914, 15.891)
    coverage = conn.execute(
        """
        SELECT ValidationFailureCount, AmbiguousFieldCount, Status
        FROM schema_coverage_run
        """
    ).fetchone()
    # The 9-column generation mapping exposes 3 genuine published energy-power discrepancies in this fixture
    assert coverage[0] == 3
    assert coverage[1] > 0
    assert coverage[2] == "review_required"
    dispositions = dict(conn.execute(
        """
        SELECT Disposition, COUNT(*)
        FROM schema_coverage_item
        GROUP BY Disposition
        """
    ).fetchall())
    assert dispositions["header"] > 0
    assert dispositions["ambiguous"] > 0
    assert conn.execute(
        """
        SELECT c.Disposition
        FROM schema_coverage_item AS c
        JOIN psp_raw_cell AS r ON r.id = c.RawCellID
        WHERE r.page_no = 1 AND r.table_no = 1 AND r.row_no = 4 AND r.col_no = 15
        """
    ).fetchone()[0] == "ambiguous"
    assert conn.execute(
        """
        SELECT SectionName, PageNo, AnnotationText
        FROM FactSRLDCReportAnnotation
        """
    ).fetchall() == [(
        "availability_note",
        1,
        "*MWAvailabiltyindicatedaboveincludesSRISTSLoss.",
    )]
    conn.close()
