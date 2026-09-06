"""Tests for ODCS YAML evaluation against curated SQLite tables."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.quality.odcs_contract import (
    default_odcs_directory,
    evaluate_odcs_contract,
    evaluate_odcs_directory,
    load_odcs_contract,
)


def test_committed_srldc_contract_is_valid_odcs_yaml() -> None:
    """The headline regional fact table has a machine-readable ODCS spec."""

    path = default_odcs_directory() / "fact_srldc_regional_daily.yaml"
    spec = load_odcs_contract(path)
    assert spec["id"] == "urn:datacontract:psp:fact-srldc-regional-daily"
    assert spec["schema"][0]["physicalName"] == "FactSRLDCRegionalDaily"


def test_empty_fact_table_skips_odcs_instead_of_failing(tmp_path: Path) -> None:
    """Coverage fixtures without regional rows must not fail the contract."""

    db_path = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.close()
    result = evaluate_odcs_directory(db_path)
    assert result.skipped is True
    assert result.passed is True


def test_null_required_demand_fails_odcs(tmp_path: Path) -> None:
    """Dropping a required IEGC-facing measure is a breaking contract failure."""

    db_path = tmp_path / "nulls.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute("INSERT INTO DimDates(DateID, ActualDate) VALUES (1, '2026-01-01')")
    conn.execute(
        """
        INSERT INTO FactSRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW,
            EveningPeakShortageMW, DayEnergyMetMU
        ) VALUES (1, 1, 1, NULL, 0.0, 10.0)
        """
    )
    conn.commit()
    conn.close()
    result = evaluate_odcs_contract(
        db_path, default_odcs_directory() / "fact_srldc_regional_daily.yaml"
    )
    assert result.passed is False
    assert any("EveningPeakDemandMetMW" in failure for failure in result.failures)


def test_complete_regional_row_passes_odcs(tmp_path: Path) -> None:
    """A fully populated grain satisfies required fields and quality bounds."""

    db_path = tmp_path / "ok.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute("INSERT INTO DimDates(DateID, ActualDate) VALUES (1, '2026-01-01')")
    conn.execute(
        """
        INSERT INTO FactSRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW,
            EveningPeakShortageMW, DayEnergyMetMU, AverageFrequencyHz
        ) VALUES (1, 1, 1, 12000.0, 0.0, 250.5, 50.01)
        """
    )
    conn.commit()
    conn.close()
    result = evaluate_odcs_contract(
        db_path, default_odcs_directory() / "fact_srldc_regional_daily.yaml"
    )
    assert result.passed is True
    assert result.skipped is False
