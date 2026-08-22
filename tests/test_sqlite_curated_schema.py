from __future__ import annotations

import sqlite3

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema


def test_sqlite_schema_includes_governed_srldc_tables() -> None:
    conn = sqlite3.connect(":memory:")

    ensure_sqlite_schema(conn)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "FactAllIndiaDailySummary" in tables
    assert "FactStateDailyEnergy" in tables
    assert "FactTimeBlockPowerData" in tables
    assert "MetaTableColumnUnits" in tables
    assert "psp_raw_cell" in tables
    assert "FactSRLDCRegionalDaily" in tables
    assert "FactSRLDCStateDaily" in tables
    assert "FactSRLDCVoltageProfile" in tables
    assert "FactSRLDCRegionalMarketTransaction" in tables
    assert "FactSRLDCOperationalEvent" in tables
    assert "FactSRLDCRegionalDailySummary" not in tables
    assert "FactSRLDCStateDailyPosition" not in tables
    assert "FactSRLDCLoadForecast" not in tables
    assert "FactSRLDCFrequencySummary" not in tables
    assert "FactSRLDCFrequencyBand" not in tables
    assert "FactSRLDCCurtailment" not in tables
    assert "FactSRLDCNonCompliance" not in tables
    assert "schema_field" in tables
    assert "schema_proposal" in tables
    assert "schema_coverage_run" in tables
    assert "curated_field_lineage" in tables
    regional_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(FactSRLDCRegionalDaily)")
    }
    assert {
        "MaximumFrequencyHz",
        "FrequencyVariationIndex",
        "DurationBelow49_70Pct",
        "DurationAbove50_05Pct",
        "FrequencyBandDefinitionVersion",
    } <= regional_columns
    state_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(FactSRLDCStateDaily)")
    }
    assert {
        "ForecastType",
        "ForecastDemandMU",
        "ActualDemandMU",
        "ForecastDeviationMU",
        "ForecastDeviationPct",
    } <= state_columns


def test_sqlite_curated_schema_seeds_dimensions_and_unit_mappings() -> None:
    conn = sqlite3.connect(":memory:")

    ensure_sqlite_schema(conn)

    assert conn.execute("SELECT COUNT(*) FROM DimUnits").fetchone()[0] == 9
    assert conn.execute("SELECT COUNT(*) FROM DimRegions").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM DimStates").fetchone()[0] >= 39
    unit = conn.execute(
        """
        SELECT u.UnitSymbol
        FROM MetaTableColumnUnits AS m
        JOIN DimUnits AS u ON m.UnitID = u.UnitID
        WHERE m.TableName = 'FactStateDailyEnergy'
          AND m.ColumnName = 'EnergyMet'
        """
    ).fetchone()
    assert unit == ("MU",)
    required_fields = conn.execute(
        "SELECT COUNT(*) FROM schema_field WHERE RequirementLevel = 'required'"
    ).fetchone()[0]
    assert required_fields >= 16
    approved_mappings = conn.execute(
        "SELECT COUNT(*) FROM schema_field_mapping WHERE ApprovalStatus = 'approved'"
    ).fetchone()[0]
    assert approved_mappings >= 40
