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
from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema

NERLDC_2023_TEMPLATE_ID = "nerldc_daily_psp_v2023_standard_09_column_generation"
NERLDC_2024_TEMPLATE_ID = "nerldc_daily_psp_v2024_standard_09_column_generation"


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


def test_nerldc_nine_column_regional_generation_does_not_invent_ui_rras() -> None:
    """Historical page-3 regional tables bind peak/energy columns without UI/RRAS."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (3, 'nerldc', 'NER-PSP-REPORT-DATED-01-04-2023.pdf', '2023-04-01', ?, 0)
        """,
        (NERLDC_2023_TEMPLATE_ID,),
    )
    _insert_cells(conn, 3, 3, 1, {
        1: "Station/Constituents", 2: "Inst.Capacity", 3: "19:00 Peak",
        4: "Off Peak", 5: "Day Peak", 6: "Hrs", 7: "Gross(MU)",
        8: "Net(MU)", 9: "Avg.MW",
    })
    _insert_cells(conn, 3, 3, 2, {1: "NEEPCO"})
    _insert_cells(conn, 3, 3, 3, {
        1: "Agartala GT", 2: "135", 3: "84", 4: "72", 5: "90",
        6: "19:15", 7: "1.70", 8: "1.65", 9: "69",
    })
    _insert_cells(conn, 3, 3, 4, {
        1: "Sub-Total", 2: "135", 3: "84", 4: "72", 5: "90",
        6: "19:15", 7: "1.70", 8: "1.65", 9: "69",
    })

    promote_report_to_curated(conn, 3)

    row = conn.execute(
        """
        SELECT f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW, f.EveningPeakMW,
               f.ScheduledEnergyMU, f.UIMU, f.RRASScheduleMU, f.SectionName,
               f.IsTotalRow
        FROM FactNERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 3 AND entity.EntityName = 'Agartala GT'
        """
    ).fetchone()
    subtotal = conn.execute(
        """
        SELECT f.SectionName, f.IsTotalRow, f.NetEnergyMU
        FROM FactNERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 3 AND entity.EntityName = 'Sub-Total'
        """
    ).fetchone()
    assert row == (1.7, 1.65, 69.0, 84.0, None, None, None, "regional_generation:neepco", 0)
    assert subtotal == ("regional_generation:neepco", 1, 1.65)


def test_nerldc_page_two_state_generation_is_not_regionalized() -> None:
    """A 9-column state table on page 2 keeps its state grain."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (4, 'nerldc', 'NER-PSP-REPORT-DATED-01-01-2024.pdf', '2024-01-01', ?, 0)
        """,
        (NERLDC_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 4, 2, 1, {
        1: "Station/Constituents", 2: "Inst.Capacity", 3: "Peak",
        7: "Gross(MU)", 8: "Net(MU)", 9: "Avg.MW",
    })
    _insert_cells(conn, 4, 2, 2, {1: "ASSAM"})
    _insert_cells(conn, 4, 2, 3, {
        1: "NTPS", 2: "120", 3: "80", 8: "1.20", 9: "50",
    })

    promote_report_to_curated(conn, 4)

    row = conn.execute(
        """
        SELECT f.SectionName, f.NetEnergyMU, s.StateName
        FROM FactNERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        JOIN DimStates AS s ON s.StateID = f.StateID
        WHERE f.ReportDocumentID = 4 AND entity.EntityName = 'NTPS'
        """
    ).fetchone()
    regional = conn.execute(
        """
        SELECT COUNT(*) FROM FactNERLDCGenerationDaily
        WHERE ReportDocumentID = 4 AND SectionName LIKE 'regional_generation:%'
        """
    ).fetchone()[0]
    assert row[0].startswith("state_generation_")
    assert row[1:] == (1.2, "Assam")
    assert regional == 0


def test_nerldc_wide_regional_headers_bind_core_energy_only() -> None:
    """A 2024-style wide regional table maps unique energy headers, not UI/RRAS."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (5, 'nerldc', 'NER-PSP-REPORT-DATED-01-01-2024.pdf', '2024-01-01', ?, 0)
        """,
        (NERLDC_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 5, 3, 1, {
        1: "Station/Constituents", 2: "Inst.Capacity", 14: "Gross(MU)",
        16: "Net(MU)", 19: "Avg.MW",
    })
    _insert_cells(conn, 5, 3, 2, {1: "OTPC"})
    _insert_cells(conn, 5, 3, 3, {
        1: "Palatana GBPP (2*363.3)", 2: "726.6", 14: "12.40", 16: "11.80", 19: "492",
    })

    promote_report_to_curated(conn, 5)

    row = conn.execute(
        """
        SELECT entity.EntityName, f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW,
               f.ScheduledEnergyMU, f.UIMU, f.SectionName
        FROM FactNERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 5
        """
    ).fetchone()
    assert row == (
        "OTPC Palatana",
        12.4,
        11.8,
        492.0,
        None,
        None,
        "regional_generation:otpc",
    )


def _create_raw_tables(conn: sqlite3.Connection) -> None:
    """Create the immutable raw tables required by NERLDC promotion tests."""

    conn.executescript(
        """
        CREATE TABLE psp_report_document (
            id INTEGER PRIMARY KEY,
            rldc TEXT NOT NULL,
            local_path TEXT NOT NULL,
            report_date TEXT NOT NULL,
            template_id TEXT,
            semantic_pass_required INTEGER NOT NULL DEFAULT 0,
            structure_deviation_reason TEXT
        );
        CREATE TABLE psp_raw_cell (
            id INTEGER PRIMARY KEY,
            report_document_id INTEGER NOT NULL,
            page_no INTEGER NOT NULL,
            table_no INTEGER NOT NULL,
            row_no INTEGER NOT NULL,
            col_no INTEGER NOT NULL,
            cell_text TEXT
        );
        """
    )


def _insert_cells(
    conn: sqlite3.Connection,
    report_id: int,
    page_no: int,
    row_no: int,
    cells: dict[int, str],
) -> None:
    """Insert one sparse raw PDF row with stable synthetic identifiers."""

    for col_no, text in cells.items():
        raw_id = page_no * 10000 + row_no * 100 + col_no
        conn.execute(
            """
            INSERT INTO psp_raw_cell(
                id, report_document_id, page_no, table_no, row_no, col_no, cell_text
            ) VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (raw_id, report_id, page_no, row_no, col_no, text),
        )
