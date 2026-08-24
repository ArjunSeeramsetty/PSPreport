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
            (SELECT COUNT(*) FROM FactNERLDCInterRegionalExchange),
            (SELECT COUNT(*) FROM FactNERLDCInternationalExchange),
            (SELECT COUNT(*) FROM curated_field_lineage)
        """
    ).fetchone()
    assert counts[0:4] == (1, 7, 44, 1)
    assert counts[4] >= 20
    assert counts[5] >= 10
    assert counts[6] == 1
    assert counts[7] > 600
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
    ("filename", "report_date"),
    [
        ("NER-PSP-REPORT-DATED-01-04-2023.pdf", date(2023, 4, 1)),
        ("NER-PSP-REPORT-DATED-01-01-2024.pdf", date(2024, 1, 1)),
        ("NER-PSP-REPORT-DATED-01-01-2026.pdf", date(2026, 1, 1)),
    ],
)
def test_nerldc_nine_column_layouts_promote_generation_and_operational_facts(
    tmp_path: Path,
    filename: str,
    report_date: date,
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
    assert counts[:4] == (1, 7, 44, 1)
    assert counts[4] >= 20
    assert counts[5] == 10
