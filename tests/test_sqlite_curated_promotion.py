from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import LocalReportInput, run_rldc_local_pdf_ingestion


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
        "market": 81,
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
