"""Regression tests for the initial NRLDC curated promotion slice."""

from __future__ import annotations

import sqlite3

from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema
from psp_pipeline.storage.sqlite_nrldc_promoter import repromote_nrldc_reports


NRLDC_2025_TEMPLATE_ID = "nrldc_daily_psp_v2025_standard_11_column_generation"


def test_nrldc_promotes_regional_state_and_generation_facts() -> None:
    """Section 1, Section 2(A), and state generation retain cell lineage."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (1, 'nrldc', 'daily201225.pdf', '2025-12-20', ?, 0)
        """,
        (NRLDC_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 1, 1, 4, {
        1: "60,306", 3: "106", 7: "60,412", 10: "50.061",
        13: "37,543", 16: "0", 21: "37,543", 27: "50.031",
        30: "1,294", 37: "0.88",
    })
    _insert_cells(conn, 1, 1, 5, {1: "2(A) State's Load Details"})
    _insert_cells(conn, 1, 1, 8, {
        1: "PUNJAB", 4: "71.12", 6: "11.63", 8: "0", 11: "3.61",
        14: "0", 17: "2.01", 22: "88.36", 24: "70.5", 28: "71.13",
        31: "0.63", 34: "159.49", 37: "0", 39: "159.49",
    })
    _insert_cells(conn, 1, 1, 9, {1: "2(B) State Demands"})
    _insert_cells(conn, 1, 2, 1, {1: "DELHI"})
    _insert_cells(conn, 1, 2, 2, {1: "Station/Constituents", 2: "Inst.Capacity"})
    _insert_cells(conn, 1, 2, 4, {
        1: "BAWANA GPS(2*253+4*216)", 2: "1,370", 3: "186", 4: "180",
        5: "258.03", 6: "07:00", 7: "0", 8: "", 9: "4.21", 10: "4.04", 11: "168",
    })
    _insert_cells(conn, 1, 10, 1, {1: "4(A) INTER REGIONAL EXCHANGES"})
    _insert_cells(conn, 1, 10, 2, {1: "Import/Export between EAST REGION and NORTH REGION"})
    _insert_cells(conn, 1, 10, 3, {
        3: "765KV-SASARAM-FATEHPUR", 7: "530", 9: "-1,138", 12: "1,138",
        15: "649", 19: "10.2", 22: "0", 24: "10.2",
    })
    _insert_cells(conn, 1, 10, 4, {1: "4(B) Inter Regional Schedule"})
    _insert_cells(conn, 1, 10, 5, {1: "5. Frequency Profile"})
    _insert_cells(conn, 1, 10, 6, {
        1: "50.396", 3: "18:03", 4: "49.816", 8: "14:37", 12: "50.023",
        15: "0.076", 18: "0.084", 19: "50.281", 22: "49.863", 24: "99.99",
    })
    _insert_cells(conn, 1, 11, 1, {1: "6.1 Voltage Profile: 765kV"})
    _insert_cells(conn, 1, 11, 3, {
        1: "ANTA RS 765KV", 3: "791", 6: "19:10", 10: "772", 14: "14:40",
        18: "0", 20: "0", 22: "0", 24: "0", 27: "0",
    })
    _insert_cells(conn, 1, 12, 1, {1: "8. Major Reservoir Particulars"})
    _insert_cells(conn, 1, 12, 3, {
        1: "Bhakra", 3: "445.62", 7: "513.59", 12: "1728.8", 17: "482.03",
        19: "503", 23: "476.21", 25: "375", 28: "305.85", 31: "385.76",
    })
    _insert_cells(conn, 1, 12, 4, {1: "9. System Reliability Indices"})

    promote_report_to_curated(conn, 1)

    regional = conn.execute(
        "SELECT EveningPeakDemandMetMW, DayEnergyMetMU FROM FactNRLDCRegionalDaily"
    ).fetchone()
    punjab = conn.execute(
        """
        SELECT f.ThermalGenerationMU, f.TotalGenerationMU, f.ConsumptionMU
        FROM FactNRLDCStateDaily AS f
        JOIN DimStates AS s ON s.StateID = f.StateID
        WHERE s.StateName = 'Punjab'
        """
    ).fetchone()
    generation = conn.execute(
        """
        SELECT InstalledCapacityMW, NetEnergyMU, AverageMW
        FROM FactNRLDCGenerationDaily
        """
    ).fetchone()
    coverage = conn.execute(
        "SELECT MappedFieldCount, AmbiguousFieldCount, Status FROM schema_coverage_run"
    ).fetchone()

    assert regional == (60306.0, 1294.0)
    assert punjab == (71.12, 88.36, 159.49)
    assert generation == (1370.0, 4.04, 168.0)
    assert conn.execute("SELECT COUNT(*) FROM FactNRLDCFrequencyDaily").fetchone() == (1,)
    assert conn.execute("SELECT COUNT(*) FROM FactNRLDCVoltageProfile").fetchone() == (1,)
    assert conn.execute("SELECT COUNT(*) FROM FactNRLDCReservoirDaily").fetchone() == (1,)
    assert conn.execute(
        "SELECT NetEnergyMU FROM FactNRLDCInterRegionalExchange"
    ).fetchone() == (10.2,)
    assert coverage[0] > 0
    assert coverage[1] == 0
    assert coverage[2] == "review_required"


def test_nrldc_repromotion_replays_known_templates() -> None:
    """A mapping revision can replay NRLDC facts without opening the PDF again."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (1, 'nrldc', 'daily201225.pdf', '2025-12-20', ?, 0)
        """,
        (NRLDC_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 1, 1, 4, {1: "60,306", 30: "1,294"})

    result = repromote_nrldc_reports(conn)

    assert result == {"reports_repromoted": 1}
    fact_count = conn.execute(
        "SELECT COUNT(*) FROM FactNRLDCRegionalDaily"
    ).fetchone()
    assert fact_count == (1,)


def test_nrldc_promotes_stable_pages_despite_later_page_drift() -> None:
    """Later unowned-page drift does not discard page-one regional facts."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required,
            structure_deviation_reason
        ) VALUES (1, 'nrldc', 'daily201225.pdf', '2025-12-20', ?, 1, ?)
        """,
        (NRLDC_2025_TEMPLATE_ID, "shape_mismatch=p11_t1:53x24"),
    )
    _insert_cells(conn, 1, 1, 4, {1: "60,306", 30: "1,294"})

    promote_report_to_curated(conn, 1)

    fact_count = conn.execute(
        "SELECT COUNT(*) FROM FactNRLDCRegionalDaily"
    ).fetchone()
    assert fact_count == (1,)


def test_nrldc_blocks_and_clears_facts_for_owned_page_drift() -> None:
    """A page-one to four deviation cannot leave stale curated facts behind."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required,
            structure_deviation_reason
        ) VALUES (1, 'nrldc', 'daily201225.pdf', '2025-12-20', ?, 1, ?)
        """,
        (NRLDC_2025_TEMPLATE_ID, "shape_mismatch=p2_t1:63x11"),
    )
    _insert_cells(conn, 1, 1, 4, {1: "60,306", 30: "1,294"})

    promote_report_to_curated(conn, 1)

    fact_count = conn.execute(
        "SELECT COUNT(*) FROM FactNRLDCRegionalDaily"
    ).fetchone()
    assert fact_count == (0,)


def _create_raw_tables(conn: sqlite3.Connection) -> None:
    """Create the raw ingestion tables needed by the isolated promoter fixture."""
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_document_id INTEGER NOT NULL,
            page_no INTEGER NOT NULL,
            table_no INTEGER NOT NULL,
            row_no INTEGER NOT NULL,
            col_no INTEGER NOT NULL,
            cell_text TEXT NOT NULL
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
    """Insert one sparse raw PDF row for an NRLDC promotion fixture."""
    conn.executemany(
        """
        INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no, cell_text
        ) VALUES (?, ?, 1, ?, ?, ?)
        """,
        ((report_id, page_no, row_no, column, value) for column, value in cells.items()),
    )
