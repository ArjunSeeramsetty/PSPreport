"""Tests for source-aware all-India regional synthesis."""

from __future__ import annotations

import sqlite3

from psp_pipeline.reconciliation.all_india_balance import (
    synthesize_all_india_daily_balance,
)
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


def test_synthesis_uses_latest_available_regional_reports_and_nldc_summary() -> None:
    """Regional totals are summed once and compared to an available NLDC row."""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_curated_sqlite_schema(conn)
    conn.executescript(
        """
        CREATE TABLE psp_report_document (
            id INTEGER PRIMARY KEY,
            rldc TEXT NOT NULL,
            report_date TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        INSERT INTO DimDates(DateID, ActualDate) VALUES (1, '2026-05-01');
        INSERT INTO psp_report_document VALUES
            (1, 'srldc', '2026-05-01', '2026-05-01T08:00:00+00:00'),
            (2, 'nrldc', '2026-05-01', '2026-05-01T08:00:00+00:00'),
            (3, 'srldc', '2026-05-01', '2026-05-01T10:00:00+00:00');
        INSERT INTO FactSRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, DayEnergyMetMU
        ) VALUES (1, 1, 3, 100, 10), (3, 1, 3, 110, 11);
        INSERT INTO FactNRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, DayEnergyMetMU
        ) VALUES (2, 1, 1, 200, 20);
        INSERT INTO FactSRLDCStateDaily(
            ReportDocumentID, DateID, StateID, ThermalGenerationMU, SolarGenerationMU
        ) VALUES (3, 1, 1, 4, 2);
        INSERT INTO FactNRLDCStateDaily(
            ReportDocumentID, DateID, StateID, ThermalGenerationMU, HydroGenerationMU
        ) VALUES (2, 1, 2, 8, 3);
        INSERT INTO FactAllIndiaDailySummary(DateID, RegionID, EveningPeakDemandMet, EnergyMet)
        VALUES (1, NULL, 310, 31);
        """
    )

    result = synthesize_all_india_daily_balance(conn, 1)

    assert result.sources_present == ("srldc", "nrldc")
    assert result.sources_missing == ("wrldc", "erldc", "nerldc")
    assert result.evening_peak_demand_met_mw == 310.0
    assert result.day_energy_met_mu == 31.0
    assert result.fuel_generation_mu == {
        "hydro_generation_mu": 3.0,
        "solar_generation_mu": 2.0,
        "thermal_generation_mu": 12.0,
    }
    assert result.nldc_comparisons["evening_peak_demand_met_mw"].within_tolerance
    assert result.nldc_comparisons["day_energy_met_mu"].within_tolerance


def test_synthesis_does_not_fabricate_an_nldc_comparison() -> None:
    """No comparison is emitted unless a national published value exists."""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_curated_sqlite_schema(conn)
    conn.executescript(
        """
        CREATE TABLE psp_report_document (
            id INTEGER PRIMARY KEY,
            rldc TEXT NOT NULL,
            report_date TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        INSERT INTO DimDates(DateID, ActualDate) VALUES (1, '2026-05-01');
        INSERT INTO psp_report_document VALUES
            (1, 'nerldc', '2026-05-01', '2026-05-01T08:00:00+00:00');
        INSERT INTO FactNERLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, DayEnergyMetMU
        ) VALUES (1, 1, 5, 40, 4);
        """
    )

    result = synthesize_all_india_daily_balance(conn, 1)

    assert result.sources_present == ("nerldc",)
    assert result.nldc_comparisons == {}
