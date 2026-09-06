"""Tests for IEGC 2023 frequency and thermal flexibility classification."""

from __future__ import annotations

import sqlite3

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.quality.iegc_compliance import (
    INTEGRITY_IEGC_VIOLATION,
    INTEGRITY_OK,
    INTEGRITY_PHYSICALLY_IMPOSSIBLE,
    apply_iegc_frequency_flags,
    classify_frequency_hz,
    classify_thermal_mcr_ratio,
)


def test_frequency_50_39_is_promoted_as_iegc_violation() -> None:
    """August 2024 high-frequency events are statutory, not parse errors."""

    result = classify_frequency_hz(50.39)
    assert result.promote is True
    assert result.should_quarantine is False
    assert result.iegc_band_violation is True
    assert result.integrity == INTEGRITY_IEGC_VIOLATION


def test_frequency_inside_iegc_band_is_ok() -> None:
    """Nominal 50 Hz is not a violation."""

    result = classify_frequency_hz(50.0)
    assert result.integrity == INTEGRITY_OK
    assert result.iegc_band_violation is False


def test_frequency_70_hz_is_physically_impossible() -> None:
    """OCR transposition outside the physical envelope is quarantined."""

    result = classify_frequency_hz(70.0)
    assert result.should_quarantine is True
    assert result.integrity == INTEGRITY_PHYSICALLY_IMPOSSIBLE


def test_thermal_turndown_below_55_percent_mcr() -> None:
    """Generation under the IEGC 55% MCR floor is a flexibility flag."""

    result = classify_thermal_mcr_ratio(400.0, 1000.0)
    assert result.below_min_turndown is True
    assert result.status == INTEGRITY_IEGC_VIOLATION
    assert result.ratio == 0.4


def test_apply_flags_marks_srldc_high_frequency_without_dropping_the_row() -> None:
    """Curated frequency facts keep 50.39 Hz and stamp the IEGC flag."""

    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    conn.execute("INSERT INTO DimDates(DateID, ActualDate) VALUES (1, '2024-08-18')")
    conn.execute(
        """
        INSERT INTO FactSRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, MaximumFrequencyHz, AverageFrequencyHz
        ) VALUES (1, 1, 1, 50.39, 50.12)
        """
    )
    updated = apply_iegc_frequency_flags(conn, 1)
    row = conn.execute(
        "SELECT IegcBandViolation, FrequencyIntegrity, MaximumFrequencyHz "
        "FROM FactSRLDCRegionalDaily WHERE ReportDocumentID = 1"
    ).fetchone()
    assert updated >= 1
    assert row == (1, INTEGRITY_IEGC_VIOLATION, 50.39)
