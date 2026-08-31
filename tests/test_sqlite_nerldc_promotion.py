"""Regression coverage for the verified NERLDC Phase-A promotion contract."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import (
    LocalReportInput,
    run_rldc_local_pdf_ingestion,
)


def test_nerldc_2025_local_fixture_promotes_core_curated_facts(
    tmp_path: Path,
) -> None:
    """The verified 2025 report writes regional, state, and generation facts."""
    fixture = Path("downloads/NERLDC_PSP/NER-PSP-REPORT-DATED-01-01-2025.pdf")
    if not fixture.exists():
        pytest.skip(f"local NERLDC fixture missing: {fixture}")

    database_path = tmp_path / "nerldc_curated.sqlite"
    result = run_rldc_local_pdf_ingestion(
        database_path,
        [
            LocalReportInput(
                rldc="nerldc",
                local_path=fixture,
                report_date=date(2025, 1, 1),
            )
        ],
    )

    assert result["reports_persisted"] == 1
    conn = sqlite3.connect(database_path)
    counts = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM FactNERLDCRegionalDaily),
            (SELECT COUNT(*) FROM FactNERLDCStateDaily),
            (SELECT COUNT(*) FROM FactNERLDCGenerationDaily),
                (SELECT COUNT(*) FROM FactNERLDCFrequencyDaily),
                (SELECT COUNT(*) FROM FactNERLDCVoltageProfile),
                (SELECT COUNT(*) FROM FactNERLDCReservoirDaily),
                (SELECT COUNT(*) FROM FactNERLDCInterRegionalExchange),
                (SELECT COUNT(*) FROM FactNERLDCInternationalExchange),
            (SELECT COUNT(*) FROM curated_field_lineage)
        """
    ).fetchone()
    assert counts[0:4] == (1, 7, 44, 1)
    assert counts[4] >= 20
    assert counts[5] == 9
    assert counts[6] >= 10
    assert counts[7] == 1
    assert counts[8] > 600
    state_names = conn.execute(
        """
        SELECT s.StateName
        FROM FactNERLDCStateDaily AS f
        JOIN DimStates AS s ON s.StateID = f.StateID
        ORDER BY s.StateName
        """
    ).fetchall()
    assert [name for (name,) in state_names] == [
        "Arunachal Pradesh",
        "Assam",
        "Manipur",
        "Meghalaya",
        "Mizoram",
        "Nagaland",
        "Tripura",
    ]
    conn.close()


@pytest.mark.parametrize(
    (
        "filename",
        "report_date",
        "has_regional_schedule_table",
        "expected_reservoir_count",
    ),
    [
        ("NER-PSP-REPORT-DATED-01-04-2023.pdf", date(2023, 4, 1), True, 9),
        ("NER-PSP-REPORT-DATED-01-01-2024.pdf", date(2024, 1, 1), False, 9),
        ("NER-PSP-REPORT-DATED-01-01-2026.pdf", date(2026, 1, 1), True, 10),
    ],
)
def test_nerldc_nine_column_layouts_promote_generation_and_operational_facts(
    tmp_path: Path,
    filename: str,
    report_date: date,
    has_regional_schedule_table: bool,
    expected_reservoir_count: int,
) -> None:
    """The approved nine-column families retain generation and operational facts."""

    fixture = Path("downloads/NERLDC_PSP") / filename
    if not fixture.exists():
        pytest.skip(f"local NERLDC fixture missing: {fixture}")

    database_path = tmp_path / f"{report_date.isoformat()}.sqlite"
    run_rldc_local_pdf_ingestion(
        database_path,
        [
            LocalReportInput(
                rldc="nerldc",
                local_path=fixture,
                report_date=report_date,
            )
        ],
    )
    with sqlite3.connect(database_path) as conn:
        counts = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM FactNERLDCRegionalDaily),
                (SELECT COUNT(*) FROM FactNERLDCStateDaily),
                (SELECT COUNT(*) FROM FactNERLDCGenerationDaily),
                (SELECT COUNT(*) FROM FactNERLDCFrequencyDaily),
                (SELECT COUNT(*) FROM FactNERLDCVoltageProfile),
                (SELECT COUNT(*) FROM FactNERLDCInterRegionalExchange)
            """
        ).fetchone()
    assert counts[:2] == (1, 7)
    assert counts[3] == 1
    if has_regional_schedule_table:
        assert counts[2] > 44
    else:
        assert counts[2] == 44
    assert counts[4] >= 20
    assert counts[5] == 10
    reservoir_count = conn.execute(
        "SELECT COUNT(*) FROM FactNERLDCReservoirDaily"
    ).fetchone()[0]
    reservoir_lineage_count = conn.execute(
        "SELECT COUNT(*) FROM curated_field_lineage "
        "WHERE DestinationTable = 'FactNERLDCReservoirDaily'"
    ).fetchone()[0]
    assert reservoir_count == expected_reservoir_count
    assert reservoir_lineage_count >= 60


def test_nerldc_2026_promotes_regional_schedule_ui_and_rras(
    tmp_path: Path,
) -> None:
    """The 2026 regional table preserves its published energy schedule fields."""

    fixture = Path("downloads/NERLDC_PSP/NER-PSP-REPORT-DATED-01-01-2026.pdf")
    if not fixture.exists():
        pytest.skip(f"local NERLDC fixture missing: {fixture}")
    database_path = tmp_path / "nerldc_2026_regional_generation.sqlite"
    run_rldc_local_pdf_ingestion(
        database_path,
        [
            LocalReportInput(
                rldc="nerldc",
                local_path=fixture,
                report_date=date(2026, 1, 1),
            )
        ],
    )
    with sqlite3.connect(database_path) as conn:
        row = conn.execute(
            """
            SELECT f.GrossEnergyMU, f.NetEnergyMU, f.ScheduledEnergyMU,
                   f.UIMU, f.RRASScheduleMU, f.SectionName
            FROM FactNERLDCGenerationDaily AS f
            JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
            WHERE entity.EntityName = 'Agartala GT'
              AND f.SectionName = 'regional_generation:neepco'
            """
        ).fetchone()
        lineage_count = conn.execute(
            """
            SELECT COUNT(*) FROM curated_field_lineage
            WHERE DestinationTable = 'FactNERLDCGenerationDaily'
              AND DestinationColumn IN (
                  'GrossEnergyMU', 'NetEnergyMU', 'ScheduledEnergyMU',
                  'UIMU', 'RRASScheduleMU'
              )
            """
        ).fetchone()[0]
    assert row == (1.7, 1.65, 1.53, 0.12, 0.11, "regional_generation:neepco")
    assert lineage_count >= 5
