"""Unit and integration tests for unified multi-RLDC observation export."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import UUID

import pytest

from psp_pipeline.storage.sqlite_curated_export import (
    CuratedSourceExportError,
    export_all_daily_observations,
    export_registered_daily_observations,
)
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


@pytest.fixture
def multi_rldc_curated_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create an in-memory SQLite database populated with curated facts across multiple RLDCs."""
    conn = sqlite3.connect(tmp_path / "multi_rldc.sqlite")
    ensure_curated_sqlite_schema(conn)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY,
            rldc TEXT NOT NULL
        );
        INSERT INTO psp_report_document(id, rldc) VALUES (1, 'srldc'), (2, 'nerldc');

        INSERT OR IGNORE INTO DimDates(DateID, ActualDate) VALUES (1, '2025-01-01');

        -- SRLDC Facts
        INSERT INTO FactSRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, DayEnergyMetMU
        ) VALUES (
            1, 1,
            (SELECT RegionID FROM DimRegions WHERE RegionName = 'Southern Region'),
            45000.0, 950.0
        );

        INSERT INTO FactSRLDCStateDaily(
            ReportDocumentID, DateID, StateID, AvailabilityMU, DemandMetMU
        ) VALUES (
            1, 1,
            (SELECT StateID FROM DimStates WHERE StateName = 'Karnataka'),
            255.0, 250.0
        );

        -- NERLDC Facts
        INSERT INTO FactNERLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, DayEnergyMetMU
        ) VALUES (
            2, 1,
            (SELECT RegionID FROM DimRegions WHERE RegionName = 'North Eastern Region'),
            2561.0, 48.5
        );

        INSERT INTO FactNERLDCStateDaily(
            ReportDocumentID, DateID, StateID, TotalAvailabilityMU, DemandMetMU
        ) VALUES (
            2, 1,
            (SELECT StateID FROM DimStates WHERE StateName = 'Assam'),
            28.5, 28.2
        );
        """
    )
    conn.commit()
    return conn


def test_export_all_daily_observations_exports_all_present_regions(
    multi_rldc_curated_conn: sqlite3.Connection,
) -> None:
    observations = export_all_daily_observations(
        multi_rldc_curated_conn,
        ingested_at=datetime(2026, 8, 25, 2, 0, 0, tzinfo=timezone.utc),
    )

    assert len(observations) >= 4
    regions = {obs.source_region for obs in observations}
    assert "SR" in regions
    assert "NER" in regions

    for obs in observations:
        assert isinstance(UUID(obs.timeseries_uuid), UUID)
        assert obs.metric_id == f"{obs.destination_table}.{obs.destination_column}"


def test_export_all_daily_observations_filters_by_rldc(
    multi_rldc_curated_conn: sqlite3.Connection,
) -> None:
    observations_sr = export_all_daily_observations(
        multi_rldc_curated_conn,
        rldcs=["srldc"],
    )
    assert all(obs.source_region == "SR" for obs in observations_sr)
    assert len(observations_sr) >= 2

    observations_ner = export_all_daily_observations(
        multi_rldc_curated_conn,
        rldcs=["nerldc"],
    )
    assert all(obs.source_region == "NER" for obs in observations_ner)
    assert len(observations_ner) >= 2


@pytest.mark.parametrize("rldc", ["srldc", "nerldc"])
def test_registry_exporter_has_stable_fixture_snapshot(
    multi_rldc_curated_conn: sqlite3.Connection,
    rldc: str,
) -> None:
    """The declarative exporter keeps a stable portable observation shape."""

    timestamp = datetime(2026, 8, 25, 2, 0, 0, tzinfo=timezone.utc)
    observations = export_registered_daily_observations(
        multi_rldc_curated_conn,
        rldc,
        ingested_at=timestamp,
    )

    snapshot = sorted(
        (
            item.entity_key,
            item.metric_name,
            item.operational_value,
            item.destination_column,
        )
        for item in observations
    )
    assert snapshot
    assert all(
        metric_name.startswith(f"{rldc}.")
        for _, metric_name, _, _ in snapshot
    )


def test_export_all_daily_observations_uses_registry_engine(
    monkeypatch: pytest.MonkeyPatch,
    multi_rldc_curated_conn: sqlite3.Connection,
) -> None:
    """The unified path does not invoke compatibility exporter wrappers."""

    calls: list[str] = []

    def record_registered_export(*args, **kwargs):
        calls.append(args[1])
        return []

    monkeypatch.setattr(
        "psp_pipeline.storage.sqlite_curated_export.export_registered_daily_observations",
        record_registered_export,
    )

    export_all_daily_observations(
        multi_rldc_curated_conn,
        rldcs=["srldc", "nerldc"],
    )

    assert calls == ["srldc", "nerldc"]


def test_export_all_daily_observations_fails_closed_when_a_source_exporter_raises(
    monkeypatch: pytest.MonkeyPatch,
    multi_rldc_curated_conn: sqlite3.Connection,
) -> None:
    """A required source export error is quarantined instead of silently skipped."""

    original = export_registered_daily_observations

    def boom(conn, rldc, report_document_id=None, ingested_at=None):
        if rldc == "nerldc":
            raise RuntimeError("nerldc exporter exploded")
        return original(
            conn,
            rldc,
            report_document_id=report_document_id,
            ingested_at=ingested_at,
        )

    monkeypatch.setattr(
        "psp_pipeline.storage.sqlite_curated_export.export_registered_daily_observations",
        boom,
    )

    try:
        export_all_daily_observations(
            multi_rldc_curated_conn,
            rldcs=["srldc", "nerldc"],
        )
    except CuratedSourceExportError as exc:
        assert "nerldc" in exc.failures
        assert "srldc" not in exc.failures
        assert exc.observations
    else:
        raise AssertionError("expected CuratedSourceExportError")

    hold = multi_rldc_curated_conn.execute(
        """
        SELECT SourceID, Stage, ReasonCode FROM promotion_quarantine
        WHERE ReasonCode = 'source_export_failed'
        """
    ).fetchone()
    assert hold == ("nerldc", "curated_export", "source_export_failed")


def test_export_curated_observations_cli(tmp_path: Path, multi_rldc_curated_conn: sqlite3.Connection) -> None:
    db_file = tmp_path / "multi_rldc.sqlite"
    out_file = tmp_path / "exported_observations.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/export_curated_observations.py",
            "--db",
            str(db_file),
            "--output",
            str(out_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Exported" in result.stdout
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) >= 4
    assert all(line["metric_id"] for line in lines)
