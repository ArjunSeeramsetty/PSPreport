"""Tests for the file-backed Airflow stage-payload contract."""

from __future__ import annotations

from psp_pipeline.pipelines.staging import read_stage_payload, write_stage_payload
from psp_pipeline.pipelines.stages import repromote_srldc_curated


def test_stage_payload_round_trip_uses_a_small_reference(tmp_path) -> None:
    """Keep task XCom values to a run identifier and a file path."""

    payload = {"facts": [{"metric": "demand", "value": 42.0}]}
    reference = write_stage_payload(tmp_path, "run-1", "parsed", payload)

    assert reference["run_id"] == "run-1"
    assert set(reference) == {"run_id", "path"}
    assert read_stage_payload(reference) == payload


def test_curated_promotion_is_a_noop_when_local_database_is_absent(tmp_path) -> None:
    """Allow feature-gated Airflow tasks to remain fail-soft before first load."""

    assert repromote_srldc_curated(tmp_path / "missing.sqlite") == {
        "reports_total": 0,
        "promoted": 0,
        "skipped": 0,
    }
