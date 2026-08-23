"""Regression coverage for the initial WRLDC curated promotion scope."""

from __future__ import annotations

import sqlite3

from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


WRLDC_TEMPLATE_ID = "wrldc_daily_psp_v2025_standard_11_column_generation"
WRLDC_9_COLUMN_TEMPLATE_ID = "wrldc_daily_psp_v2023_standard_09_column_generation"


def test_wrldc_promotes_regional_state_and_generation_with_lineage() -> None:
    """Verified page-one to page-three fields retain their source-cell lineage."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (1, 'wrldc', 'WRLDC_PSP_Report_15-04-2025.pdf', '2025-04-15', ?, 0)
        """,
        (WRLDC_TEMPLATE_ID,),
    )
    _insert_cells(conn, 1, 1, 4, {
        1: "71,501", 2: "0", 7: "71,501", 11: "49.91", 14: "67,850",
        18: "0", 25: "67,850", 30: "50.04", 32: "1,716.8", 38: "0",
    })
    _insert_cells(conn, 1, 1, 5, {1: "2(A) Load Details"})
    _insert_cells(conn, 1, 1, 8, {
        1: "GUJARAT", 4: "165.9", 5: "2.8", 9: "6.9", 12: "51.5",
        14: "84.5", 16: "0", 20: "311.6", 24: "189.1", 28: "178.7",
        31: "-10.4", 33: "490.3", 36: "490.3", 39: "0", 42: "490.3",
    })
    _insert_cells(conn, 1, 1, 18, {1: "2(B) State Demand"})
    _insert_cells(conn, 1, 1, 21, {
        1: "GUJARAT", 3: "20,278", 6: "0", 13: "20,278", 15: "17,709",
        21: "0", 29: "17,709", 32: "20,426", 35: "487.99", 40: "-2.31",
    })
    _insert_cells(conn, 1, 1, 31, {1: "2(C) Maximum Demand"})
    _insert_cells(conn, 1, 1, 34, {
        1: "GUJARAT", 3: "20,500", 8: "20:00", 13: "0", 19: "20,500",
        26: "350.0", 31: "17:25", 35: "-200.0", 41: "16:47",
    })
    _insert_cells(conn, 1, 2, 1, {1: "GUJARAT"})
    _insert_cells(conn, 1, 2, 2, {1: "THERMAL"})
    _insert_cells(conn, 1, 2, 3, {
        1: "TEST TPS(2*250)", 2: "500", 3: "345", 4: "361", 5: "392",
        6: "22:19", 7: "258", 8: "13:28", 9: "8.41", 10: "7.16", 11: "298",
    })

    promote_report_to_curated(conn, 1)

    regional = conn.execute(
        "SELECT EveningPeakDemandMetMW, DayEnergyMetMU FROM FactWRLDCRegionalDaily"
    ).fetchone()
    gujarat = conn.execute(
        """
        SELECT f.TotalGenerationMU, f.ForecastDeviationMU, f.MaximumACEMW
        FROM FactWRLDCStateDaily AS f
        JOIN DimStates AS s ON s.StateID = f.StateID
        WHERE s.StateName = 'Gujarat'
        """
    ).fetchone()
    generation = conn.execute(
        "SELECT InstalledCapacityMW, NetEnergyMU, MinimumGenerationMW FROM FactWRLDCGenerationDaily"
    ).fetchone()
    lineage_count = conn.execute(
        "SELECT COUNT(*) FROM curated_field_lineage WHERE ReportDocumentID = 1"
    ).fetchone()

    assert regional == (71501.0, 1716.8)
    assert gujarat == (311.6, -2.31, 350.0)
    assert generation == (500.0, 7.16, 258.0)
    assert lineage_count[0] >= 30


def test_wrldc_promotes_nine_column_generation_without_minimum_fields() -> None:
    """The early layout does not fabricate the absent minimum-generation pair."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (2, 'wrldc', 'WRLDC_PSP_Report_01-04-2023.pdf', '2023-04-01', ?, 0)
        """,
        (WRLDC_9_COLUMN_TEMPLATE_ID,),
    )
    _insert_cells(conn, 2, 2, 1, {1: "GUJARAT"})
    _insert_cells(conn, 2, 2, 2, {1: "THERMAL"})
    _insert_cells(conn, 2, 2, 3, {
        1: "TEST TPS(2*250)", 2: "500", 3: "345", 4: "361", 5: "392",
        6: "22:19", 7: "8.41", 8: "7.16", 9: "298",
    })

    promote_report_to_curated(conn, 2)

    generation = conn.execute(
        """
        SELECT InstalledCapacityMW, GrossEnergyMU, NetEnergyMU, AverageMW,
               MinimumGenerationMW, MinimumGenerationTime
        FROM FactWRLDCGenerationDaily
        """
    ).fetchone()
    assert generation == (500.0, 8.41, 7.16, 298.0, None, None)


def test_wrldc_promotes_owned_scope_when_drift_is_limited_to_later_pages() -> None:
    """A page-six drift cannot suppress verified page-one to page-three facts."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required,
            structure_deviation_reason
        ) VALUES (3, 'wrldc', 'WRLDC_PSP_Report_15-06-2023.pdf', '2023-06-15', ?, 1,
                  'shape_mismatch=p6_t1:56x20')
        """,
        (WRLDC_9_COLUMN_TEMPLATE_ID,),
    )
    _insert_cells(conn, 3, 1, 4, {1: "70,000", 2: "0", 7: "70,000"})
    _insert_cells(conn, 3, 2, 1, {1: "GUJARAT"})
    _insert_cells(conn, 3, 2, 2, {1: "THERMAL"})
    _insert_cells(conn, 3, 2, 3, {1: "TEST TPS", 2: "500", 7: "8.41", 8: "7.16", 9: "298"})

    promote_report_to_curated(conn, 3)

    assert conn.execute("SELECT COUNT(*) FROM FactWRLDCRegionalDaily").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM FactWRLDCGenerationDaily").fetchone()[0] == 1


def test_wrldc_blocks_owned_scope_when_drift_touches_page_one() -> None:
    """A page-one mismatch remains blocked until its own contract is verified."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required,
            structure_deviation_reason
        ) VALUES (4, 'wrldc', 'WRLDC_PSP_Report_31-07-2023.pdf', '2023-07-31', ?, 1,
                  'shape_mismatch=p1_t1:59x36')
        """,
        (WRLDC_9_COLUMN_TEMPLATE_ID,),
    )
    _insert_cells(conn, 4, 1, 4, {1: "70,000", 2: "0", 7: "70,000"})

    promote_report_to_curated(conn, 4)

    assert conn.execute("SELECT COUNT(*) FROM FactWRLDCRegionalDaily").fetchone()[0] == 0


def test_wrldc_operational_fact_schema_has_source_specific_grains() -> None:
    """Operational sections retain their native regional, node, reservoir, and line grains."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)

    columns_by_table = {
        table: {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for table in (
            "FactWRLDCFrequencyDaily",
            "FactWRLDCVoltageProfile",
            "FactWRLDCReservoirDaily",
            "FactWRLDCInterRegionalExchange",
        )
    }

    assert {"RegionID", "Maximum15MinuteBlockFrequencyHz"}.issubset(
        columns_by_table["FactWRLDCFrequencyDaily"]
    )
    assert {"VoltageNodeID", "NominalVoltageKV", "IEGCBandPct"}.issubset(
        columns_by_table["FactWRLDCVoltageProfile"]
    )
    assert {"ReservoirID", "DesignedEnergyMU", "ProgressiveUsageMU"}.issubset(
        columns_by_table["FactWRLDCReservoirDaily"]
    )
    assert {"ElementID", "CounterpartyRegion", "NetEnergyMU"}.issubset(
        columns_by_table["FactWRLDCInterRegionalExchange"]
    )


def test_wrldc_promotes_verified_operational_sections_with_cell_lineage() -> None:
    """The 2025 layout preserves source cells for lines, nodes, and reservoirs."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (5, 'wrldc', 'WRLDC_PSP_Report_15-04-2025.pdf', '2025-04-15', ?, 0)
        """,
        (WRLDC_TEMPLATE_ID,),
    )
    _insert_cells(conn, 5, 5, 67, {1: "4(A) Inter-Regional Exchanges"})
    _insert_cells(conn, 5, 5, 70, {1: "EAST REGION and WEST REGION"})
    _insert_cells(conn, 5, 5, 71, {
        1: "1", 2: "400KV-RAIGARH-JHARSUGUDA", 7: "125", 9: "132",
        11: "168", 14: "-13", 17: "2.27", 19: "0", 22: "2.27",
    })
    _insert_cells(conn, 5, 6, 64, {1: "6. Voltage Profile: 400kV"})
    _insert_cells(conn, 5, 6, 69, {
        1: "AMRELI-400KV", 4: "429.96", 6: "04:17", 8: "407.37",
        10: "14:55", 13: "0", 15: "43.3", 17: "56.7", 19: "13.6",
    })
    _insert_cells(conn, 5, 7, 22, {1: "6.1 Voltage Profile: 765kV"})
    _insert_cells(conn, 5, 7, 25, {
        1: "BINA-765KV", 4: "785.1", 6: "13:03", 8: "760.43",
        10: "19:25", 13: "0", 15: "100", 17: "0", 19: "0",
    })
    _insert_cells(conn, 5, 8, 38, {1: "8. Major Reservoir Particulars"})
    _insert_cells(conn, 5, 8, 41, {
        1: "INDIRASAGAR", 2: "243.23", 5: "262.13", 8: "1367",
        11: "254.06", 13: "252.33", 16: "255.61", 18: "680.49",
        21: "0", 26: "0", 29: "0",
    })

    promote_report_to_curated(conn, 5)

    exchange = conn.execute(
        "SELECT CounterpartyRegion, EveningPeakMW, NetEnergyMU FROM FactWRLDCInterRegionalExchange"
    ).fetchone()
    voltage = conn.execute(
        "SELECT COUNT(*), MIN(NominalVoltageKV), MAX(NominalVoltageKV) FROM FactWRLDCVoltageProfile"
    ).fetchone()
    reservoir = conn.execute(
        "SELECT MinimumDrawdownLevelM, CurrentEnergyMU FROM FactWRLDCReservoirDaily"
    ).fetchone()
    destinations = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT DestinationTable FROM curated_field_lineage WHERE ReportDocumentID = 5"
        )
    }

    assert exchange == ("ER", 125.0, 2.27)
    assert voltage == (2, 400.0, 765.0)
    assert reservoir == (243.23, 252.33)
    assert {
        "FactWRLDCInterRegionalExchange",
        "FactWRLDCVoltageProfile",
        "FactWRLDCReservoirDaily",
    }.issubset(destinations)


def test_wrldc_promotes_frequency_from_text_lines_with_line_lineage() -> None:
    """Section 5 extrema retain native PDF text-line provenance."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (6, 'wrldc', 'WRLDC_PSP_Report_15-04-2025.pdf', '2025-04-15', ?, 0)
        """,
        (WRLDC_TEMPLATE_ID,),
    )
    _insert_raw_line(
        conn,
        601,
        6,
        6,
        59,
        "Percentage of Time Frequency Remained outside IEGC Band 18.8",
    )
    _insert_raw_line(
        conn,
        602,
        6,
        6,
        60,
        "No. of hours frequency outside IEGC Band 4.512",
    )
    _insert_raw_line(
        conn,
        603,
        6,
        6,
        63,
        "50.2 17:02:20 49.78 19:24:50 50 0.028 0.053 50.11 49.83",
    )

    promote_report_to_curated(conn, 6)

    frequency = conn.execute(
        """
        SELECT MaximumFrequencyHz, MinimumFrequencyHz,
               Maximum15MinuteBlockFrequencyHz, PercentageOutsideIEGCBand,
               HoursOutsideIEGCBand
        FROM FactWRLDCFrequencyDaily
        """
    ).fetchone()
    lineage = conn.execute(
        """
        SELECT COUNT(*), MIN(RawLineID), MAX(RawLineID)
        FROM curated_field_lineage
        WHERE ReportDocumentID = 6
          AND DestinationTable = 'FactWRLDCFrequencyDaily'
        """
    ).fetchone()

    assert frequency == (50.2, 49.78, 50.11, 18.8, 4.512)
    assert lineage == (11, 601, 603)


def _create_raw_tables(conn: sqlite3.Connection) -> None:
    """Create the immutable raw tables required by curated promotion tests."""
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
        CREATE TABLE psp_raw_line (
            id INTEGER PRIMARY KEY,
            report_document_id INTEGER NOT NULL,
            page_no INTEGER NOT NULL,
            line_no INTEGER NOT NULL,
            line_text TEXT
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


def _insert_raw_line(
    conn: sqlite3.Connection,
    raw_line_id: int,
    report_id: int,
    page_no: int,
    line_no: int,
    text: str,
) -> None:
    """Insert a native PDF text line for non-tabular fact promotion tests."""
    conn.execute(
        """
        INSERT INTO psp_raw_line(id, report_document_id, page_no, line_no, line_text)
        VALUES (?, ?, ?, ?, ?)
        """,
        (raw_line_id, report_id, page_no, line_no, text),
    )
