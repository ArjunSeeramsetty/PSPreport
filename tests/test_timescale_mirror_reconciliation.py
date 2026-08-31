"""Tests for exact SQLite-to-Timescale current-truth mirror verification."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.quality.timescale_mirror_reconciliation import (
    CurrentMirrorRow,
    TimescaleMirrorMismatchError,
    reconcile_timescale_current_mirror,
    verify_exported_current_mirror,
)
from psp_pipeline.storage.observation_identity import build_series_key


def _observation() -> FactObservation:
    """Build one stable SRLDC observation for mirror test cases."""

    valid_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return FactObservation(
        entity_key="SR:region:Southern Region",
        metric_name="srldc.FactSRLDCRegionalDaily.DayEnergyMetMU",
        metric_id="FactSRLDCRegionalDaily.DayEnergyMetMU",
        time_block=None,
        operational_value=123.45,
        settlement_value=None,
        variance_pct=None,
        report_type="srldc_daily_psp",
        source_region="SR",
        valid_from=valid_from,
        valid_to=None,
        version_no=1,
        ingested_at=valid_from,
        timeseries_uuid="00000000-0000-0000-0000-000000000001",
    )


def test_reconcile_timescale_current_mirror_accepts_exact_current_row() -> None:
    """An exact current Timescale row satisfies the dual-write acceptance gate."""

    observation = _observation()
    series_key = build_series_key(
        entity_key=observation.entity_key,
        metric_name=observation.metric_name,
        time_block=None,
        report_type=observation.report_type,
        source_region=observation.source_region,
        valid_from=observation.valid_from.isoformat(),
        valid_to=None,
    )
    result = reconcile_timescale_current_mirror(
        [observation],
        [
            CurrentMirrorRow(
                series_key=series_key,
                timeseries_uuid=observation.timeseries_uuid,
                metric_id=observation.metric_id,
                operational_value=observation.operational_value,
                settlement_value=None,
            )
        ],
    )

    assert result.is_match
    assert result.exported_count == 1
    assert result.current_count == 1


def test_reconcile_timescale_current_mirror_rejects_missing_or_changed_rows() -> None:
    """Missing rows and metric/value drift make the pilot fail visibly."""

    observation = _observation()
    missing = reconcile_timescale_current_mirror([observation], [])
    assert not missing.is_match
    assert len(missing.missing_series_keys) == 1

    changed = reconcile_timescale_current_mirror(
        [observation],
        [
            CurrentMirrorRow(
                series_key=observation.series_key or build_series_key(
                    entity_key=observation.entity_key,
                    metric_name=observation.metric_name,
                    time_block=observation.time_block,
                    report_type=observation.report_type,
                    source_region=observation.source_region,
                    valid_from=observation.valid_from.isoformat(),
                    valid_to=None,
                ),
                timeseries_uuid=observation.timeseries_uuid,
                metric_id="FactSRLDCRegionalDaily.WrongMetric",
                operational_value=999.0,
                settlement_value=None,
            )
        ],
    )
    assert not changed.is_match
    assert len(changed.mismatched_series_keys) == 1


def test_verify_exported_current_mirror_raises_on_mismatch() -> None:
    """Production dual-write callers fail closed instead of returning a soft miss."""

    observation = _observation()
    with pytest.raises(TimescaleMirrorMismatchError, match="mirror mismatch"):
        verify_exported_current_mirror(
            [observation],
            "postgresql://test",
            current_row_fetcher=lambda _dsn, _rows: [],
        )


def test_verify_exported_current_mirror_accepts_matching_current_rows() -> None:
    """A matching current-truth fetch is the production dual-write acceptance path."""

    observation = _observation()
    series_key = build_series_key(
        entity_key=observation.entity_key,
        metric_name=observation.metric_name,
        time_block=None,
        report_type=observation.report_type,
        source_region=observation.source_region,
        valid_from=observation.valid_from.isoformat(),
        valid_to=None,
    )
    result = verify_exported_current_mirror(
        [observation],
        "postgresql://test",
        current_row_fetcher=lambda _dsn, _rows: [
            CurrentMirrorRow(
                series_key=series_key,
                timeseries_uuid=observation.timeseries_uuid,
                metric_id=observation.metric_id,
                operational_value=observation.operational_value,
                settlement_value=None,
            )
        ],
    )
    assert result.is_match
