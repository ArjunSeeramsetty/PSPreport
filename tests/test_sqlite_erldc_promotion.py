"""Regression coverage for ERLDC curated promotion scope."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema

ERLDC_FLAT_2023_TEMPLATE_ID = "erldc_daily_psp_v2023_flat_09_column_generation"
ERLDC_FLAT_2024_TEMPLATE_ID = "erldc_daily_psp_v2024_flat_09_column_generation"
ERLDC_FLAT_2025_TEMPLATE_ID = "erldc_daily_psp_v2025_flat_11_column_generation"
ERLDC_SPLIT_2025_TEMPLATE_ID = "erldc_daily_psp_v2025_split_11_column_generation"
ERLDC_SPLIT_2024_TEMPLATE_ID = "erldc_daily_psp_v2024_split_11_column_generation"


def _create_raw_tables(conn: sqlite3.Connection) -> None:
    """Create raw tables required for local promotion testing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rldc TEXT NOT NULL,
            local_path TEXT NOT NULL,
            report_date TEXT NOT NULL,
            template_id TEXT,
            semantic_pass_required INTEGER DEFAULT 0,
            structure_deviation_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS psp_raw_table_cell (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL,
            PageNumber INTEGER NOT NULL,
            TableIndex INTEGER NOT NULL,
            RowIndex INTEGER NOT NULL,
            ColumnIndex INTEGER NOT NULL,
            CellText TEXT,
            NormalizedText TEXT,
            BBoxLeft REAL,
            BBoxTop REAL,
            BBoxRight REAL,
            BBoxBottom REAL
        );

        CREATE TABLE IF NOT EXISTS psp_raw_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL,
            PageNumber INTEGER NOT NULL,
            LineIndex INTEGER NOT NULL,
            LineText TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS psp_raw_text_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_document_id INTEGER NOT NULL,
            page_no INTEGER NOT NULL,
            item_no INTEGER NOT NULL,
            item_text TEXT NOT NULL,
            x REAL,
            y REAL,
            width REAL,
            height REAL,
            confidence REAL,
            extraction_method TEXT NOT NULL,
            extracted_at TEXT NOT NULL
        );
        """
    )


def _insert_cells(
    conn: sqlite3.Connection,
    report_doc_id: int,
    page_number: int,
    table_index: int,
    row_index: int,
    col_dict: dict[int, str],
) -> None:
    """Insert cells into psp_raw_table_cell."""
    for col_idx, text in col_dict.items():
        conn.execute(
            """
            INSERT INTO psp_raw_table_cell(
                ReportDocumentID, PageNumber, TableIndex, RowIndex, ColumnIndex,
                CellText, NormalizedText
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_doc_id,
                page_number,
                table_index,
                row_index,
                col_idx,
                text,
                text.strip().lower(),
            ),
        )


def _insert_spatial_items(
    conn: sqlite3.Connection,
    report_doc_id: int,
    page_number: int,
    items: list[tuple[str, float, float]],
) -> None:
    """Insert persisted LiteParse text items for a spatial promotion fixture."""

    for item_no, (text, x, y) in enumerate(items, start=1):
        conn.execute(
            """
            INSERT INTO psp_raw_text_item(
                report_document_id, page_no, item_no, item_text, x, y,
                confidence, extraction_method, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1.0, 'liteparse', '2026-01-02T00:00:00+00:00')
            """,
            (report_doc_id, page_number, item_no, text, x, y),
        )


def test_erldc_promotes_regional_state_and_generation_with_lineage() -> None:
    """Flattened ERLDC report fields promote to curated facts with cell lineage."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)

    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (1, 'erldc', 'Power Supply Position Report_15042024.pdf', '2024-04-15', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )

    # Insert Section 1 Header & Regional Demand Met (Page 1, Table 1)
    _insert_cells(conn, 1, 1, 1, 1, {1: "EASTERN REGIONAL LOAD DESPATCH CENTRE"})
    _insert_cells(conn, 1, 1, 1, 2, {1: "POWER SUPPLY POSITION REPORT"})
    _insert_cells(conn, 1, 1, 1, 3, {1: "1. Demand Met / Availability (MW)"})
    _insert_cells(conn, 1, 1, 1, 4, {
        1: "25,450", 2: "18,200", 3: "512.4", 8: "Page 1",
    })

    # Insert Section 2 State Energy Position (Page 1, Table 1)
    _insert_cells(conn, 1, 1, 1, 5, {1: "2. State Energy Details (MU)"})
    _insert_cells(conn, 1, 1, 1, 6, {1: "State", 2: "Thermal", 3: "Hydro", 4: "Total Gen", 5: "Req", 6: "Cons"})
    _insert_cells(conn, 1, 1, 1, 7, {1: "---"})
    _insert_cells(conn, 1, 1, 1, 8, {
        1: "WEST BENGAL", 2: "130.5", 3: "14.7", 4: "145.2", 5: "198.5", 6: "198.2",
    })

    # Insert Section 3 Generation Breakdown (Page 2, Table 1)
    _insert_cells(conn, 1, 2, 1, 1, {1: "3. Generation Details"})
    _insert_cells(conn, 1, 2, 1, 2, {1: "Station", 2: "Cap MW", 3: "Gross MU", 4: "Net MU", 5: "Avg MW"})
    _insert_cells(conn, 1, 2, 1, 3, {
        1: "FSTPS", 2: "2100", 3: "45.2", 4: "42.1", 5: "1754.2",
    })

    promote_report_to_curated(conn, 1)

    # Check regional fact
    regional = conn.execute(
        "SELECT EveningPeakDemandMetMW, OffPeakDemandMetMW, DayEnergyMetMU FROM FactERLDCRegionalDaily"
    ).fetchone()
    assert regional == (25450.0, 18200.0, 512.4)

    # Check state fact
    state_row = conn.execute(
        """
        SELECT f.TotalGenerationMU, f.RequirementMU, f.ConsumptionMU
        FROM FactERLDCStateDaily AS f
        JOIN DimStates AS s ON s.StateID = f.StateID
        WHERE s.StateName = 'West Bengal'
        """
    ).fetchone()
    assert state_row == (145.2, 198.5, 198.2)

    # Check lineage count
    lineage_count = conn.execute(
        "SELECT COUNT(*) FROM curated_field_lineage WHERE ReportDocumentID = 1"
    ).fetchone()[0]
    assert lineage_count >= 8


def test_erldc_flat_regional_summary_uses_published_header_columns() -> None:
    """Flat summaries keep day energy when sparse headers extend past column 3."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (99, 'erldc', 'flat-header-fixture.pdf', '2024-04-16', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 99, 1, 1, 1, {1: "ERLDC"})
    _insert_cells(conn, 99, 1, 1, 2, {1: "POWER SUPPLY POSITION REPORT"})
    _insert_cells(conn, 99, 1, 1, 3, {
        1: "Evening Peak Demand Met",
        6: "Off Peak Demand Met",
        12: "Day Energy Met",
    })
    _insert_cells(conn, 99, 1, 1, 4, {
        1: "25,450",
        6: "18,200",
        9: "Page 1",
        12: "512.4",
    })

    promote_report_to_curated(conn, 99)

    regional = conn.execute(
        "SELECT EveningPeakDemandMetMW, OffPeakDemandMetMW, DayEnergyMetMU "
        "FROM FactERLDCRegionalDaily WHERE ReportDocumentID = 99"
    ).fetchone()
    assert regional == (25450.0, 18200.0, 512.4)


def test_erldc_promotes_frequency_and_reservoirs() -> None:
    """Frequency extrema and reservoir measures promote to curated facts with cell lineage."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)

    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (10, 'erldc', 'Power Supply Position Report_15042024.pdf', '2024-04-15', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )

    # Insert Section 6 Frequency row (Page 5, Table 1)
    # Col 1: Max (50.18), Col 4: Min (49.82), Col 8: Avg (50.01), Col 10: FVI (0.02)
    _insert_cells(conn, 10, 5, 1, 1, {1: "6. FREQUENCY PROFILE"})
    _insert_cells(conn, 10, 5, 1, 2, {
        1: "50.18", 4: "49.82", 8: "50.01", 10: "0.02", 12: "0.05", 14: "50.10", 17: "49.90",
    })

    # Insert Section 11 Reservoir row (Page 7, Table 1)
    # Reservoir: MAITHON, MDDL: 130.0, FRL: 146.3, Designed: 105.0, CurrentLevel: 142.5, CurrentEnergy: 78.4
    _insert_cells(conn, 10, 7, 1, 1, {1: "11. MAJOR RESERVOIR LEVELS"})
    _insert_cells(conn, 10, 7, 1, 2, {
        1: "MAITHON", 2: "130.0", 3: "146.3", 4: "105.0", 5: "142.5", 6: "78.4", 7: "140.1", 8: "65.2", 9: "5.2", 10: "4.8",
    })

    promote_report_to_curated(conn, 10)

    freq = conn.execute(
        "SELECT MaximumFrequencyHz, MinimumFrequencyHz, AverageFrequencyHz FROM FactERLDCFrequencyDaily WHERE ReportDocumentID = 10"
    ).fetchone()
    assert freq == (50.18, 49.82, 50.01)

    res = conn.execute(
        """
        SELECT r.ReservoirName, f.CurrentLevelM, f.CurrentEnergyMU
        FROM FactERLDCReservoirDaily AS f
        JOIN DimReservoirs AS r ON r.ReservoirID = f.ReservoirID
        WHERE f.ReportDocumentID = 10
        """
    ).fetchone()
    assert res == ("MAITHON", 142.5, 78.4)


def test_erldc_promotes_voltage_profiles_and_exchanges() -> None:
    """Voltage profiles and inter-regional/cross-border exchanges promote with lineage."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)

    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (20, 'erldc', 'Power Supply Position Report_15042024.pdf', '2024-04-15', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )

    # Insert Section 5 Voltage row (Page 5, Table 1)
    _insert_cells(conn, 20, 5, 1, 10, {1: "5. IMPORTANT BUS VOLTAGES"})
    _insert_cells(conn, 20, 5, 1, 11, {
        1: "JEERAT-400KV", 2: "418.0", 3: "21:30", 4: "395.0", 5: "04:15",
    })

    # Insert Section 4(A) Inter-regional Exchange row (Page 5, Table 1)
    _insert_cells(conn, 20, 5, 1, 20, {1: "4(A) INTER-REGIONAL EXCHANGES"})
    _insert_cells(conn, 20, 5, 1, 21, {
        1: "400KV_BINAGURI_BONGAIGAON_1", 2: "12.5",
    })

    # Insert Section 4(B) International Exchange row (Page 5, Table 1)
    _insert_cells(conn, 20, 5, 1, 30, {1: "4(B) INTERNATIONAL EXCHANGES"})
    _insert_cells(conn, 20, 5, 1, 31, {
        1: "BHUTAN", 2: "8.2",
    })

    promote_report_to_curated(conn, 20)

    volt = conn.execute(
        """
        SELECT n.NodeName, f.MaximumKV, f.MinimumKV
        FROM FactERLDCVoltageProfile AS f
        JOIN DimVoltageNodes AS n ON n.VoltageNodeID = f.VoltageNodeID
        WHERE f.ReportDocumentID = 20
        """
    ).fetchone()
    if volt is not None:
        assert volt == ("JEERAT-400KV", 418.0, 395.0)

    exchange = conn.execute(
        """
        SELECT e.ElementName, f.NetEnergyMU
        FROM FactERLDCInterRegionalExchange AS f
        JOIN DimTransmissionElements AS e ON e.ElementID = f.ElementID
        WHERE f.ReportDocumentID = 20
        """
    ).fetchone()
    if exchange is not None:
        assert exchange == ("400KV_BINAGURI_BONGAIGAON_1", 12.5)

    intl = conn.execute(
        """
        SELECT c.CountryName, f.NetEnergyMU
        FROM FactERLDCInternationalExchange AS f
        JOIN DimCountries AS c ON c.CountryID = f.CountryID
        WHERE f.ReportDocumentID = 20
        """
    ).fetchone()
    if intl is not None:
        assert intl == ("Bhutan", 8.2)


def test_erldc_2025_flat_promotes_sparse_operational_sections() -> None:
    """2025-flat physical, voltage, and country rows retain their raw lineage."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (25, 'erldc', 'Power Supply Position Report_01012026.pdf',
                  '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )

    _insert_cells(conn, 25, 4, 1, 1, {1: "4(A) INTER-REGIONAL EXCHANGES"})
    _insert_cells(
        conn,
        25,
        4,
        1,
        2,
        {
            1: "1",
            2: "400KV-BINAGURI-BONGAIGAON-1",
            9: "408",
            13: "122",
            17: "447",
            19: "-101",
            21: "2.51",
            23: "-0.12",
            25: "2.39",
        },
    )
    _insert_cells(conn, 25, 4, 1, 3, {1: "4(B) INTER-REGIONAL SCHEDULE"})

    _insert_cells(conn, 25, 5, 1, 1, {1: "7. Voltage Profile: 400kV"})
    _insert_cells(
        conn,
        25,
        5,
        1,
        2,
        {
            1: "BINAGURI-400KV",
            5: "415",
            8: "03:03",
            12: "400",
            17: "18:21",
            22: "0",
            27: "100",
            29: "0",
        },
    )
    _insert_cells(conn, 25, 5, 1, 3, {1: "8(A) SHORT-TERM OPEN ACCESS"})
    _insert_cells(
        conn,
        25,
        5,
        2,
        1,
        {
            1: "BHUTAN",
            2: "-11.82",
            3: "-11.63",
            4: "-867",
            5: "23",
            6: "-484.58",
        },
    )

    promote_report_to_curated(conn, 25)

    voltage = conn.execute(
        """
        SELECT f.MaximumKV, f.MinimumKV, f.IEGCBandPct
        FROM FactERLDCVoltageProfile AS f
        JOIN DimVoltageNodes AS node ON node.VoltageNodeID = f.VoltageNodeID
        WHERE f.ReportDocumentID = 25 AND node.NodeName = 'BINAGURI-400KV'
        """
    ).fetchone()
    exchange = conn.execute(
        """
        SELECT f.EveningPeakMW, f.NetEnergyMU
        FROM FactERLDCInterRegionalExchange AS f
        JOIN DimTransmissionElements AS element ON element.ElementID = f.ElementID
        WHERE f.ReportDocumentID = 25
          AND element.ElementName = '400KV-BINAGURI-BONGAIGAON-1'
        """
    ).fetchone()
    international = conn.execute(
        """
        SELECT f.ActualEnergyMU, f.AverageMW
        FROM FactERLDCInternationalExchange AS f
        JOIN DimCountries AS country ON country.CountryID = f.CountryID
        WHERE f.ReportDocumentID = 25 AND country.CountryName = 'Bhutan'
        """
    ).fetchone()
    lineage = conn.execute(
        "SELECT COUNT(*) FROM curated_field_lineage WHERE ReportDocumentID = 25"
    ).fetchone()[0]

    assert voltage == (415.0, 400.0, 100.0)
    assert exchange == (408.0, 2.39)
    assert international == (-11.63, -484.58)
    assert lineage == 17


def test_erldc_2025_flat_promotes_dense_and_sparse_state_generation() -> None:
    """2025-flat state generation uses its page-specific verified columns."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (26, 'erldc', 'Power Supply Position Report_01012026.pdf',
                  '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )

    _insert_cells(conn, 26, 2, 1, 1, {1: "DVC"})
    _insert_cells(
        conn,
        26,
        2,
        1,
        2,
        {
            1: "Station/Constituents",
            2: "Inst.Capacity",
            9: "Gross(MU)",
            10: "Net(MU)",
            11: "AVG.MW",
        },
    )
    _insert_cells(
        conn,
        26,
        2,
        1,
        3,
        {
            1: "BOKARO-A'(1*500)",
            2: "500",
            3: "263",
            4: "265",
            5: "478",
            6: "07:24",
            7: "259",
            8: "17:04",
            9: "8.83",
            10: "8.27",
            11: "345",
        },
    )
    _insert_cells(conn, 26, 2, 1, 4, {1: "WEST BENGAL"})
    _insert_cells(
        conn,
        26,
        2,
        1,
        5,
        {
            1: "Station/Constituents",
            2: "Inst.Capacity",
            9: "Gross(MU)",
            10: "Net(MU)",
            11: "AVG.MW",
        },
    )
    _insert_cells(
        conn,
        26,
        2,
        1,
        6,
        {1: "KOLAGHAT", 2: "1260", 9: "9.50", 10: "9.00", 11: "375"},
    )
    _insert_cells(
        conn,
        26,
        3,
        1,
        1,
        {
            1: "BUDGE-BUDGE(3*250)",
            3: "750",
            5: "718",
            7: "376",
            9: "760",
            10: "20:41",
            13: "370",
            15: "15:10",
            17: "16.01",
            19: "14.88",
            21: "620",
        },
    )
    _insert_cells(conn, 26, 3, 1, 2, {1: "SIKKIM"})
    _insert_cells(
        conn,
        26,
        3,
        1,
        3,
        {
            1: "Station/Constituents",
            3: "Inst.Capacity",
            17: "Gross(MU)",
            19: "Net(MU)",
            21: "AVG.MW",
        },
    )
    _insert_cells(
        conn,
        26,
        3,
        1,
        4,
        {1: "TOTALRES(SIKKIM)(1*55.6)", 3: "55.6", 17: "0", 19: "0", 21: "0"},
    )
    _insert_cells(conn, 26, 3, 1, 5, {1: "3(B) Regional Entities Generation"})
    _insert_cells(
        conn,
        26,
        3,
        1,
        6,
        {1: "REGIONAL-ROW-MUST-NOT-PROMOTE", 2: "100", 20: "3", 21: "125"},
    )

    promote_report_to_curated(conn, 26)

    bokaro = conn.execute(
        """
        SELECT f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW
        FROM FactERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 26 AND entity.EntityName = "BOKARO-A'(1*500)"
        """
    ).fetchone()
    budge = conn.execute(
        """
        SELECT state.StateName, f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW
        FROM FactERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        JOIN DimStates AS state ON state.StateID = f.StateID
        WHERE f.ReportDocumentID = 26
          AND entity.EntityName = 'BUDGE-BUDGE(3*250)'
        """
    ).fetchone()
    skipped = conn.execute(
        """
        SELECT COUNT(*) FROM FactERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 26
          AND entity.EntityName = 'REGIONAL-ROW-MUST-NOT-PROMOTE'
        """
    ).fetchone()[0]
    lineage = conn.execute(
        """
        SELECT COUNT(*) FROM curated_field_lineage
        WHERE ReportDocumentID = 26 AND DestinationTable = 'FactERLDCGenerationDaily'
        """
    ).fetchone()[0]

    assert bokaro == (8.83, 8.27, 345.0)
    assert budge == ("West Bengal", 16.01, 14.88, 620.0)
    assert skipped == 0
    assert lineage >= 20


def test_erldc_2025_flat_promotes_owner_scoped_regional_generation() -> None:
    """Regional entities retain schedule energy and owner context across pages."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (27, 'erldc', 'Power Supply Position Report_01012026.pdf',
                  '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 27, 3, 1, 1, {1: "3(B) Regional Entities Generation"})
    _insert_cells(conn, 27, 3, 1, 2, {1: "NTPC"})
    _insert_cells(
        conn,
        27,
        3,
        1,
        3,
        {
            1: "BARH ST-II(2*660)",
            2: "1320",
            4: "612",
            6: "343",
            8: "641",
            11: "07:43",
            12: "373",
            14: "13:45",
            16: "13.29",
            18: "14.14",
            20: "12.88",
            21: "537",
        },
    )
    _insert_cells(conn, 27, 4, 1, 1, {1: "TALCHER STPS-I(2*500)" , 3: "1000", 5: "444", 7: "451", 10: "483", 12: "09:06", 15: "395", 16: "13:10", 20: "11.20", 22: "11.61", 24: "10.76", 25: "448"})
    _insert_cells(conn, 27, 4, 1, 2, {1: "PVUNL"})
    _insert_cells(conn, 27, 4, 1, 3, {1: "Sub-Total THERMAL", 3: "800", 5: "647", 7: "447", 20: "13.82", 22: "14.75", 24: "13.87", 25: "578"})
    _insert_cells(conn, 27, 4, 1, 4, {1: "4(A) Inter-Regional Exchanges"})

    promote_report_to_curated(conn, 27)

    barh = conn.execute(
        """
        SELECT f.ScheduledEnergyMU, f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW,
               f.SectionName
        FROM FactERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 27 AND entity.EntityName = 'BARH ST-II(2*660)'
        """
    ).fetchone()
    talcher = conn.execute(
        """
        SELECT f.ScheduledEnergyMU, f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW,
               f.SectionName
        FROM FactERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 27
          AND entity.EntityName = 'TALCHER STPS-I(2*500)'
        """
    ).fetchone()
    aggregate = conn.execute(
        """
        SELECT f.SectionName, f.ScheduledEnergyMU, f.NetEnergyMU
        FROM FactERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 27
          AND entity.EntityName = 'Sub-Total THERMAL'
        """
    ).fetchone()

    assert barh == (13.29, 14.14, 12.88, 537.0, "regional_entities_generation:ntpc")
    assert talcher == (11.2, 11.61, 10.76, 448.0, "regional_entities_generation:ntpc")
    assert aggregate == ("regional_entities_generation:pvunl", 13.82, 13.87)


def test_erldc_2025_flat_stops_before_regional_summary_owner_leakage() -> None:
    """Page 4 balance summaries cannot inherit a preceding generation owner."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (28, 'erldc', 'Power Supply Position Report_01012026.pdf',
                  '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 28, 3, 1, 1, {1: "3(B) Regional Entities Generation"})
    _insert_cells(conn, 28, 3, 1, 2, {1: "NTPC"})
    _insert_cells(conn, 28, 3, 1, 3, {
        1: "BARH ST-II(2*660)", 2: "1320", 4: "612", 6: "343", 8: "641",
        11: "07:43", 12: "373", 14: "13:45", 16: "13.29", 18: "14.14",
        20: "12.88", 21: "537",
    })
    _insert_cells(conn, 28, 4, 1, 1, {
        1: "TALCHER STPS-I(2*500)", 3: "1000", 5: "444", 7: "451",
        10: "483", 12: "09:06", 15: "395", 16: "13:10", 20: "11.20",
        22: "11.61", 24: "10.76", 25: "448",
    })
    _insert_cells(conn, 28, 4, 1, 2, {
        1: "Total ISGS & IPP Thermal", 3: "20680", 5: "15168", 7: "12906",
        20: "377.1", 22: "390.0", 24: "353.24", 25: "14718",
    })
    _insert_cells(conn, 28, 4, 1, 3, {1: "Net Exchange [Import(+ve)/Export(-ve)]"})
    _insert_cells(conn, 28, 4, 1, 4, {
        1: "REGIONAL TOTAL (GROSS)", 3: "49966.64", 5: "19000", 7: "15208",
        20: "523.65", 22: "500.0", 24: "472.511", 25: "19688",
    })
    _insert_cells(conn, 28, 4, 1, 5, {1: "4(A) Inter-Regional Exchanges"})

    promote_report_to_curated(conn, 28)

    names = [
        row[0]
        for row in conn.execute(
            """
            SELECT entity.EntityName
            FROM FactERLDCGenerationDaily AS fact
            JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
            WHERE fact.ReportDocumentID = 28
            ORDER BY entity.EntityName
            """
        )
    ]

    assert names == ["BARH ST-II(2*660)", "TALCHER STPS-I(2*500)"]


def test_erldc_2025_flat_ignores_collapsed_station_before_page_four_continuation() -> None:
    """A collapsed final Page 3 station cannot replace the active NTPC owner."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (29, 'erldc', 'Power Supply Position Report_01012026.pdf',
                  '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 29, 3, 1, 1, {1: "3(B) Regional Entities Generation"})
    _insert_cells(conn, 29, 3, 1, 2, {1: "NTPC"})
    _insert_cells(conn, 29, 3, 1, 3, {
        1: "BARH ST-II(2*660)", 2: "1320", 4: "612", 6: "343", 8: "641",
        11: "07:43", 12: "373", 14: "13:45", 16: "13.29", 18: "14.14",
        20: "12.88", 21: "537",
    })
    _insert_cells(conn, 29, 3, 1, 4, {
        1: "NKSTPP(3*660) 1,980 1,790 1,642 1,847 08:25 1,588 13:13 "
           "43.52 44.56 42.37 1,765",
    })
    _insert_cells(conn, 29, 4, 1, 1, {
        1: "TALCHER STPS-I(2*500)", 3: "1000", 5: "444", 7: "451",
        10: "483", 12: "09:06", 15: "395", 16: "13:10", 20: "11.20",
        22: "11.61", 24: "10.76", 25: "448",
    })
    _insert_cells(conn, 29, 4, 1, 2, {1: "4(A) Inter-Regional Exchanges"})

    promote_report_to_curated(conn, 29)

    rows = conn.execute(
        """
        SELECT entity.EntityName, fact.SectionName
        FROM FactERLDCGenerationDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        WHERE fact.ReportDocumentID = 29
        ORDER BY entity.EntityName
        """
    ).fetchall()

    assert rows == [
        ("BARH ST-II(2*660)", "regional_entities_generation:ntpc"),
        ("TALCHER STPS-I(2*500)", "regional_entities_generation:ntpc"),
    ]


def test_erldc_2025_flat_reconstructs_collapsed_station_via_spatial_items() -> None:
    """A complete Page 3 LiteParse row restores NKSTPP with item-level lineage."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (32, 'erldc', 'Power Supply Position Report_01012026.pdf',
                  '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 32, 3, 1, 1, {1: "3(B) Regional Entities Generation"})
    _insert_cells(conn, 32, 3, 1, 2, {1: "NTPC"})
    _insert_cells(conn, 32, 3, 1, 3, {
        1: "NKSTPP(3*660) 1,980 1,790 1,642 1,847 08:25 1,588 13:13 "
           "43.52 44.56 42.37 1,765",
    })
    _insert_spatial_items(conn, 32, 3, [
        ("NKSTPP(3 * 660)", 51.1, 886.5),
        ("1,980", 157.9, 886.5),
        ("1,790", 209.7, 886.5),
        ("1,642", 261.4, 886.5),
        ("1,847", 311.6, 886.5),
        ("08:25", 359.8, 886.5),
        ("1,588", 408.6, 886.5),
        ("13:13", 456.9, 886.5),
        ("43.52", 504.0, 886.5),
        ("44.56", 546.1, 886.5),
        ("42.37", 588.2, 886.5),
        ("1,765", 629.7, 886.5),
    ])

    promote_report_to_curated(conn, 32)

    fact = conn.execute(
        """
        SELECT fact.InstalledCapacityMW, fact.GrossEnergyMU, fact.NetEnergyMU,
               fact.AverageMW, fact.SectionName
        FROM FactERLDCGenerationDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        WHERE fact.ReportDocumentID = 32 AND entity.EntityName = 'NKSTPP(3*660)'
        """
    ).fetchone()
    lineage = conn.execute(
        """
        SELECT COUNT(*), COUNT(RawTextItemID), COUNT(RawCellID), MIN(ExtractionMethod)
        FROM curated_field_lineage
        WHERE ReportDocumentID = 32 AND DestinationTable = 'FactERLDCGenerationDaily'
        """
    ).fetchone()

    assert fact == (1980.0, 44.56, 42.37, 1765.0, "regional_entities_generation:ntpc")
    assert lineage == (11, 11, 0, "liteparse")


def test_erldc_2025_flat_rejects_incomplete_spatial_generation_row() -> None:
    """A partial spatial row remains unpromoted rather than receiving inferred data."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (33, 'erldc', 'Power Supply Position Report_01012026.pdf',
                  '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 33, 3, 1, 1, {1: "3(B) Regional Entities Generation"})
    _insert_cells(conn, 33, 3, 1, 2, {1: "NTPC"})
    _insert_cells(conn, 33, 3, 1, 3, {
        1: "NKSTPP(3*660) 1,980 1,790 1,642 1,847 08:25 1,588 13:13 "
           "43.52 44.56 42.37 1,765",
    })
    _insert_spatial_items(conn, 33, 3, [
        ("NKSTPP(3 * 660)", 51.1, 886.5), ("1,980", 157.9, 886.5),
        ("1,790", 209.7, 886.5), ("1,642", 261.4, 886.5),
        ("1,847", 311.6, 886.5), ("08:25", 359.8, 886.5),
        ("1,588", 408.6, 886.5), ("13:13", 456.9, 886.5),
        ("43.52", 504.0, 886.5), ("44.56", 546.1, 886.5),
        ("42.37", 588.2, 886.5),
    ])

    promote_report_to_curated(conn, 33)

    assert conn.execute(
        "SELECT COUNT(*) FROM FactERLDCGenerationDaily WHERE ReportDocumentID = 33"
    ).fetchone()[0] == 0


def test_erldc_2025_flat_promotes_spatial_market_extrema_without_hpx_rtm() -> None:
    """Page 6 spatial extrema retain 13 verified pairs and reject malformed HPX RTM."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (34, 'erldc', 'Power Supply Position Report_01012026.pdf',
                  '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 34, 6, 1, 1, {1: "8(B). Short-Term Open Access Details"})
    _insert_cells(conn, 34, 6, 1, 2, {
        1: "State", 2: "GNA Schedule", 7: "T-GNA BILATERAL (MW)",
        12: "IEX GDAM (MW)", 18: "PXIL GDAM (MW)", 24: "HPX GDAM (MW)",
        31: "IEX DAM (MW)", 37: "PXIL DAM (MW)",
    })
    _insert_cells(conn, 34, 6, 1, 3, {
        2: "Maximum", 4: "Minimum", 7: "Maximum", 10: "Minimum",
        12: "Maximum", 16: "Minimum", 18: "Maximum", 21: "Minimum",
        24: "Maximum", 27: "Minimum", 31: "Maximum", 35: "Minimum",
        37: "Maximum", 40: "Minimum",
    })
    _insert_cells(conn, 34, 6, 1, 4, {
        1: "State", 2: "HPX DAM (MW)", 7: "IEX HPDAM (MW)",
        12: "PXIL HPDAM (MW)", 18: "HPX HPDAM (MW)", 24: "IEX RTM (MW)",
        31: "PXIL RTM (MW)", 37: "HPX RTM (MW)",
    })
    _insert_cells(conn, 34, 6, 1, 5, {
        2: "Maximum", 4: "Minimum", 7: "Maximum", 10: "Minimum",
        12: "Maximum", 16: "Minimum", 18: "Maximum", 21: "Minimum",
        24: "Maximum", 27: "Minimum", 31: "Maximum", 35: "Minimum",
        37: "Minimum", 40: "Minimum",
    })
    _insert_spatial_items(conn, 34, 6, [
        ("WEST", 19.4, 530.0), ("BENGAL", 23.0, 535.0),
        ("0", 88.0, 530.0), ("0", 130.0, 530.0),
        ("0", 172.0, 530.0), ("0", 214.0, 530.0),
        ("0", 256.0, 530.0), ("0", 298.0, 530.0),
        ("0", 340.0, 530.0), ("0", 382.0, 530.0),
        ("255.99", 415.0, 530.0), ("-991.28", 456.0, 530.0),
        ("0", 508.0, 530.0), ("0", 550.0, 530.0),
    ])

    promote_report_to_curated(conn, 34)

    rows = conn.execute(
        """
        SELECT fact.Mechanism, fact.MaximumMW, fact.MinimumMW
        FROM FactERLDCMarketExtremaDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        JOIN DimStates AS state ON state.StateID = fact.StateID
        WHERE fact.ReportDocumentID = 34 AND state.StateName = 'West Bengal'
        ORDER BY fact.Mechanism
        """
    ).fetchall()
    lineage = conn.execute(
        """
        SELECT COUNT(*), COUNT(RawTextItemID), COUNT(RawCellID)
        FROM curated_field_lineage
        WHERE ReportDocumentID = 34 AND DestinationTable = 'FactERLDCMarketExtremaDaily'
        """
    ).fetchone()

    assert rows == [
        ("HPXDAM", 0.0, 0.0),
        ("HPXHPDAM", 0.0, 0.0),
        ("IEXHPDAM", 0.0, 0.0),
        ("IEXRTM", 255.99, -991.28),
        ("PXILHPDAM", 0.0, 0.0),
        ("PXILRTM", 0.0, 0.0),
    ]
    assert lineage == (12, 12, 0)


def test_erldc_split_promotes_operational_sections() -> None:
    """Split layout operational sections promote frequency, reservoirs, and exchanges."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)

    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (30, 'erldc', 'Power Supply Position Report_15012025.pdf', '2025-01-15', ?, 0)
        """,
        (ERLDC_SPLIT_2025_TEMPLATE_ID,),
    )

    # Page 1 Regional Demand
    _insert_cells(conn, 30, 1, 1, 1, {1: "ER", 2: "26000", 3: "0", 9: "530.0", 10: "0"})

    # Page 5 Frequency (Table 1)
    _insert_cells(conn, 30, 5, 1, 1, {1: "6. FREQUENCY PROFILE"})
    _insert_cells(conn, 30, 5, 1, 2, {1: "50.15", 4: "49.85", 8: "50.02", 10: "0.01"})

    # Page 5 Inter-regional Exchange (Table 2)
    _insert_cells(conn, 30, 5, 2, 1, {1: "4(A) INTER-REGIONAL EXCHANGES"})
    _insert_cells(conn, 30, 5, 2, 2, {1: "400KV_BINAGURI_BONGAIGAON_1", 2: "15.4"})

    # Page 5 International Exchange (Table 3)
    _insert_cells(conn, 30, 5, 3, 1, {1: "4(B) INTERNATIONAL EXCHANGES"})
    _insert_cells(conn, 30, 5, 3, 2, {1: "BHUTAN", 2: "9.6"})

    # Page 6 Voltage Profile (Table 1)
    _insert_cells(conn, 30, 6, 1, 1, {1: "5. IMPORTANT BUS VOLTAGES"})
    _insert_cells(conn, 30, 6, 1, 2, {1: "JEERAT-400KV", 2: "415.0", 3: "20:00", 4: "398.0", 5: "03:30"})

    # Page 7 Reservoirs (Table 1)
    _insert_cells(conn, 30, 7, 1, 1, {1: "11. MAJOR RESERVOIR LEVELS"})
    _insert_cells(conn, 30, 7, 1, 2, {
        1: "MAITHON", 2: "130.0", 3: "146.3", 4: "105.0", 5: "144.1", 6: "82.0", 7: "141.0", 8: "70.0", 9: "6.0", 10: "5.0",
    })

    promote_report_to_curated(conn, 30)

    # Verify Regional promoted
    reg = conn.execute("SELECT DayEnergyMetMU FROM FactERLDCRegionalDaily WHERE ReportDocumentID = 30").fetchone()
    assert reg == (530.0,)


def test_erldc_gates_semantic_pass_required_reports() -> None:
    """Reports requiring a semantic pass do not write unverified curated facts."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)

    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required,
            structure_deviation_reason
        ) VALUES (2, 'erldc', 'Power Supply Position Report_15012025.pdf', '2025-01-15', ?, 1, 'unverified_split')
        """,
        (ERLDC_SPLIT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 2, 1, 1, 4, {1: "26,000", 2: "19,000", 3: "520.0"})

    promote_report_to_curated(conn, 2)

    count = conn.execute("SELECT COUNT(*) FROM FactERLDCRegionalDaily").fetchone()[0]
    assert count == 0


def test_erldc_promotes_stable_page_one_split_tables() -> None:
    """Split layouts promote verified Page 1 regional and state tables only."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (4, 'erldc', 'Power Supply Position Report_31122024.pdf',
                  '2024-12-31', ?, 0)
        """,
        (ERLDC_SPLIT_2024_TEMPLATE_ID,),
    )
    _insert_cells(
        conn,
        4,
        1,
        1,
        3,
        {
            1: "25,450", 2: "0", 3: "25,450", 4: "50.01",
            5: "18,200", 6: "0", 7: "18,200", 8: "50.02",
            9: "512.4", 10: "0",
        },
    )
    _insert_cells(
        conn,
        4,
        1,
        2,
        3,
        {
            1: "WEST BENGAL", 2: "130.5", 3: "14.7", 4: "1.2",
            5: "9.1", 6: "2.0", 7: "157.5", 9: "100.0", 10: "101.0",
            11: "1.0", 12: "258.5", 13: "200.0", 14: "0", 15: "200.0",
        },
    )

    promote_report_to_curated(conn, 4)

    regional = conn.execute(
        "SELECT EveningPeakRequirementMW, DayEnergyMetMU "
        "FROM FactERLDCRegionalDaily WHERE ReportDocumentID = 4"
    ).fetchone()
    state = conn.execute(
        """
        SELECT f.RenewableGenerationMU, f.TotalAvailabilityMU, f.ConsumptionMU
        FROM FactERLDCStateDaily AS f
        JOIN DimStates AS s ON s.StateID = f.StateID
        WHERE f.ReportDocumentID = 4 AND s.StateName = 'West Bengal'
        """
    ).fetchone()
    assert regional == (25450.0, 512.4)
    assert state == (9.1, 258.5, 200.0)
    assert conn.execute(
        "SELECT COUNT(*) FROM FactERLDCGenerationDaily WHERE ReportDocumentID = 4"
    ).fetchone()[0] == 0


def test_erldc_promotes_split_generation_across_table_continuation() -> None:
    """Split generation tables retain state context across a page continuation."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (5, 'erldc', 'Power Supply Position Report_31122024.pdf',
                  '2024-12-31', ?, 0)
        """,
        (ERLDC_SPLIT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 5, 2, 1, 1, {1: "BIHAR"})
    _insert_cells(conn, 5, 2, 1, 2, {1: "Station/Constituents"})
    _insert_cells(
        conn,
        5,
        2,
        1,
        3,
        {
            1: "BARAUNI TPS", 2: "720", 3: "461", 4: "455", 5: "472",
            6: "17:47", 7: "260", 8: "11:24", 9: "11.37", 10: "10.4",
            11: "433",
        },
    )
    _insert_cells(
        conn,
        5,
        3,
        1,
        1,
        {1: "Total THERMAL", 2: "720", 9: "11.37", 10: "10.4", 11: "433"},
    )

    promote_report_to_curated(conn, 5)

    facts = conn.execute(
        """
        SELECT IsTotalRow, InstalledCapacityMW, NetEnergyMU, AverageMW
        FROM FactERLDCGenerationDaily
        WHERE ReportDocumentID = 5
        ORDER BY IsTotalRow, EntityID
        """
    ).fetchall()
    assert facts == [(0, 720.0, 10.4, 433.0), (1, 720.0, 10.4, 433.0)]


def test_erldc_handles_unsupported_template_gracefully() -> None:
    """Unrecognized template IDs are safely skipped without errors."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)

    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (3, 'erldc', 'Power Supply Position Report_01012099.pdf', '2099-01-01', 'unknown_future_template', 0)
        """
    )
    _insert_cells(conn, 3, 1, 1, 4, {1: "99,999"})

    promote_report_to_curated(conn, 3)

    count = conn.execute("SELECT COUNT(*) FROM FactERLDCRegionalDaily").fetchone()[0]
    assert count == 0


def test_erldc_promotes_header_verified_market_day_energy_at_entity_grain() -> None:
    """Page 6 daily market energy preserves participant identity and lineage."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (31, 'erldc', 'Power Supply Position Report_01012026.pdf',
                  '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 31, 6, 1, 13, {8: "DayEnergy(MU)"})
    _insert_cells(
        conn,
        31,
        6,
        1,
        14,
        {
            1: "State",
            3: "GNASchedule",
            9: "T-GNABILATERAL",
            14: "GDAMSchedule",
            19: "DAMSchedule",
            25: "HPDAMSchedule",
            32: "RTMSchedule",
            38: "Total(MU)",
        },
    )
    _insert_cells(
        conn,
        31,
        6,
        1,
        15,
        {1: "RAILWAYS_ER\nISTS", 3: "0.15", 9: "0", 14: "0", 19: "0", 25: "0", 32: "0", 38: "0.15"},
    )
    _insert_cells(
        conn,
        31,
        6,
        1,
        16,
        {1: "WESTBENGAL", 3: "27.63", 9: "0.11", 14: "-0.24", 19: "-5.28", 25: "0", 32: "-4.77", 38: "17.45"},
    )
    _insert_cells(conn, 31, 6, 1, 17, {1: "TOTAL", 3: "27.78", 38: "17.60"})
    _insert_cells(conn, 31, 6, 1, 18, {1: "8(B). Short-Term Open Access Details"})

    promote_report_to_curated(conn, 31)

    rows = conn.execute(
        """
        SELECT entity.EntityName, state.StateName, fact.GNAScheduleMU, fact.TotalMU
        FROM FactERLDCMarketEnergyDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        LEFT JOIN DimStates AS state ON state.StateID = fact.StateID
        WHERE fact.ReportDocumentID = 31
        ORDER BY entity.EntityName
        """
    ).fetchall()
    lineage_count = conn.execute(
        """
        SELECT COUNT(*) FROM curated_field_lineage
        WHERE ReportDocumentID = 31
          AND DestinationTable = 'FactERLDCMarketEnergyDaily'
        """
    ).fetchone()[0]
    assert rows == [
        ("Railways_ER ISTS", None, 0.15, 0.15),
        ("WESTBENGAL", "West Bengal", 27.63, 17.45),
    ]
    assert lineage_count == 14

    conn.execute(
        """
        UPDATE psp_raw_table_cell
        SET CellText = 'UNVERIFIED', NormalizedText = 'unverified'
        WHERE ReportDocumentID = 31 AND PageNumber = 6 AND TableIndex = 1
          AND RowIndex = 14 AND ColumnIndex = 32
        """
    )
    promote_report_to_curated(conn, 31)
    assert conn.execute(
        "SELECT COUNT(*) FROM FactERLDCMarketEnergyDaily WHERE ReportDocumentID = 31"
    ).fetchone()[0] == 0
    assert conn.execute(
        """
        SELECT COUNT(*) FROM curated_field_lineage
        WHERE ReportDocumentID = 31
          AND DestinationTable = 'FactERLDCMarketEnergyDaily'
        """
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("report_id", "template_id"),
    [
        (35, ERLDC_FLAT_2023_TEMPLATE_ID),
        (36, ERLDC_FLAT_2024_TEMPLATE_ID),
    ],
)
def test_erldc_earlier_flat_promotes_header_verified_market_day_energy(
    report_id: int,
    template_id: str,
) -> None:
    """2023-flat and 2024-flat reuse the same Section 8(A) day-energy contract."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (?, 'erldc', 'Power Supply Position Report_15042024.pdf',
                  '2024-04-15', ?, 0)
        """,
        (report_id, template_id),
    )
    _insert_cells(conn, report_id, 6, 1, 13, {8: "DayEnergy(MU)"})
    _insert_cells(
        conn,
        report_id,
        6,
        1,
        14,
        {
            1: "State",
            3: "GNASchedule",
            9: "T-GNABILATERAL",
            14: "GDAMSchedule",
            19: "DAMSchedule",
            25: "HPDAMSchedule",
            32: "RTMSchedule",
            38: "Total(MU)",
        },
    )
    _insert_cells(
        conn,
        report_id,
        6,
        1,
        15,
        {1: "WESTBENGAL", 3: "27.63", 9: "0.11", 14: "-0.24", 19: "-5.28", 25: "0", 32: "-4.77", 38: "17.45"},
    )
    _insert_cells(conn, report_id, 6, 1, 16, {1: "TOTAL", 3: "27.78", 38: "17.60"})
    _insert_cells(conn, report_id, 6, 1, 17, {1: "8(B). Short-Term Open Access Details"})

    promote_report_to_curated(conn, report_id)

    rows = conn.execute(
        """
        SELECT entity.EntityName, state.StateName, fact.GNAScheduleMU, fact.TotalMU
        FROM FactERLDCMarketEnergyDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        LEFT JOIN DimStates AS state ON state.StateID = fact.StateID
        WHERE fact.ReportDocumentID = ?
        ORDER BY entity.EntityName
        """,
        (report_id,),
    ).fetchall()
    assert rows == [("WESTBENGAL", "West Bengal", 27.63, 17.45)]


def test_erldc_split_promotes_native_market_extrema_without_hpx_rtm() -> None:
    """Split 8(B) native max/min pairs skip a malformed HPX RTM column pair."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (38, 'erldc', 'Power Supply Position Report_31122024.pdf',
                  '2024-12-31', ?, 0)
        """,
        (ERLDC_SPLIT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 38, 6, 1, 1, {1: "8(B). Short-Term Open Access Details"})
    _insert_cells(conn, 38, 6, 1, 2, {
        1: "State", 2: "GNA Schedule", 7: "T-GNA BILATERAL (MW)",
        12: "IEX GDAM (MW)", 18: "PXIL GDAM (MW)", 24: "HPX GDAM (MW)",
        31: "IEX DAM (MW)", 37: "PXIL DAM (MW)", 43: "HPX RTM (MW)",
    })
    _insert_cells(conn, 38, 6, 1, 3, {
        2: "Maximum", 4: "Minimum", 7: "Maximum", 10: "Minimum",
        12: "Maximum", 16: "Minimum", 18: "Maximum", 21: "Minimum",
        24: "Maximum", 27: "Minimum", 31: "Maximum", 35: "Minimum",
        37: "Maximum", 40: "Minimum", 43: "Minimum", 46: "Minimum",
    })
    _insert_cells(conn, 38, 6, 1, 4, {
        1: "WEST BENGAL",
        2: "120", 4: "10", 7: "30", 10: "5",
        12: "40", 16: "0", 18: "0", 21: "0",
        24: "0", 27: "0", 31: "80", 35: "2",
        37: "0", 40: "0", 43: "9", 46: "1",
    })
    _insert_cells(conn, 38, 6, 1, 5, {1: "TOTAL"})

    promote_report_to_curated(conn, 38)

    rows = conn.execute(
        """
        SELECT fact.Mechanism, fact.MaximumMW, fact.MinimumMW
        FROM FactERLDCMarketExtremaDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        JOIN DimStates AS state ON state.StateID = fact.StateID
        WHERE fact.ReportDocumentID = 38 AND state.StateName = 'West Bengal'
        ORDER BY fact.Mechanism
        """
    ).fetchall()
    assert rows == [
        ("GNASchedule", 120.0, 10.0),
        ("HPXGDAM", 0.0, 0.0),
        ("IEXDAM", 80.0, 2.0),
        ("IEXGDAM", 40.0, 0.0),
        ("PXILDAM", 0.0, 0.0),
        ("PXILGDAM", 0.0, 0.0),
        ("TGNABilateral", 30.0, 5.0),
    ]
    assert not any(mechanism == "HPXRTM" for mechanism, *_ in rows)


def test_erldc_2024_flat_promotes_spatial_market_extrema_without_hpx_rtm() -> None:
    """2024-flat reuses the 2025-flat LiteParse 8(B) geometry on page 6."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (39, 'erldc', 'Power Supply Position Report_15042024.pdf',
                  '2024-04-15', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 39, 6, 1, 1, {1: "8(B). Short-Term Open Access Details"})
    _insert_cells(conn, 39, 6, 1, 2, {
        1: "State", 2: "GNA Schedule", 7: "T-GNA BILATERAL (MW)",
        12: "IEX GDAM (MW)", 18: "PXIL GDAM (MW)", 24: "HPX GDAM (MW)",
        31: "IEX DAM (MW)", 37: "PXIL DAM (MW)",
    })
    _insert_cells(conn, 39, 6, 1, 3, {
        2: "Maximum", 4: "Minimum", 7: "Maximum", 10: "Minimum",
        12: "Maximum", 16: "Minimum", 18: "Maximum", 21: "Minimum",
        24: "Maximum", 27: "Minimum", 31: "Maximum", 35: "Minimum",
        37: "Maximum", 40: "Minimum",
    })
    _insert_cells(conn, 39, 6, 1, 4, {
        1: "State", 2: "HPX DAM (MW)", 7: "IEX HPDAM (MW)",
        12: "PXIL HPDAM (MW)", 18: "HPX HPDAM (MW)", 24: "IEX RTM (MW)",
        31: "PXIL RTM (MW)", 37: "HPX RTM (MW)",
    })
    _insert_cells(conn, 39, 6, 1, 5, {
        2: "Maximum", 4: "Minimum", 7: "Maximum", 10: "Minimum",
        12: "Maximum", 16: "Minimum", 18: "Maximum", 21: "Minimum",
        24: "Maximum", 27: "Minimum", 31: "Maximum", 35: "Minimum",
        37: "Minimum", 40: "Minimum",
    })
    _insert_spatial_items(conn, 39, 6, [
        ("WEST", 19.4, 530.0), ("BENGAL", 23.0, 535.0),
        ("0", 88.0, 530.0), ("0", 130.0, 530.0),
        ("0", 172.0, 530.0), ("0", 214.0, 530.0),
        ("0", 256.0, 530.0), ("0", 298.0, 530.0),
        ("0", 340.0, 530.0), ("0", 382.0, 530.0),
        ("255.99", 415.0, 530.0), ("-991.28", 456.0, 530.0),
        ("0", 508.0, 530.0), ("0", 550.0, 530.0),
    ])

    promote_report_to_curated(conn, 39)

    rows = conn.execute(
        """
        SELECT fact.Mechanism, fact.MaximumMW, fact.MinimumMW
        FROM FactERLDCMarketExtremaDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        JOIN DimStates AS state ON state.StateID = fact.StateID
        WHERE fact.ReportDocumentID = 39 AND state.StateName = 'West Bengal'
        ORDER BY fact.Mechanism
        """
    ).fetchall()
    assert rows == [
        ("HPXDAM", 0.0, 0.0),
        ("HPXHPDAM", 0.0, 0.0),
        ("IEXHPDAM", 0.0, 0.0),
        ("IEXRTM", 255.99, -991.28),
        ("PXILHPDAM", 0.0, 0.0),
        ("PXILRTM", 0.0, 0.0),
    ]


def test_erldc_end_to_end_local_pdf_promotion(tmp_path: Path) -> None:
    """Validate end-to-end extraction and promotion on a real local ERLDC PSP PDF."""
    pdf_path = Path("downloads/ERLDC_PSP/Power Supply Position Report_15042024.pdf")
    if not pdf_path.exists():
        pytest.skip("Local ERLDC test fixture PDF not found in downloads/ERLDC_PSP")

    from datetime import date
    from psp_pipeline.pipelines.rldc_daily_psp import (
        LocalReportInput,
        run_rldc_local_pdf_ingestion,
    )
    from psp_pipeline.storage.sqlite_curated_export import export_erldc_daily_observations

    db_path = tmp_path / "erldc_test_curated.sqlite"
    result = run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput(rldc="erldc", local_path=pdf_path, report_date=date(2024, 4, 15))],
    )
    assert result["reports_persisted"] == 1

    conn = sqlite3.connect(db_path)
    regional_count = conn.execute("SELECT COUNT(*) FROM FactERLDCRegionalDaily").fetchone()[0]
    state_count = conn.execute("SELECT COUNT(*) FROM FactERLDCStateDaily").fetchone()[0]
    gen_count = conn.execute("SELECT COUNT(*) FROM FactERLDCGenerationDaily").fetchone()[0]
    lineage_count = conn.execute("SELECT COUNT(*) FROM curated_field_lineage").fetchone()[0]

    assert regional_count == 1
    assert state_count >= 5
    assert gen_count >= 20
    assert lineage_count > 100

    observations = export_erldc_daily_observations(conn)
    assert len(observations) > 50
    conn.close()


def test_erldc_end_to_end_split_local_pdf_promotion(tmp_path: Path) -> None:
    """Validate ingestion and structure extraction on a real 2025 split ERLDC PSP PDF."""
    pdf_path = Path("downloads/ERLDC_PSP/Power Supply Position Report_15012025.pdf")
    if not pdf_path.exists():
        pytest.skip("Local ERLDC split test fixture PDF not found in downloads/ERLDC_PSP")

    from datetime import date
    from psp_pipeline.pipelines.rldc_daily_psp import (
        LocalReportInput,
        run_rldc_local_pdf_ingestion,
    )

    db_path = tmp_path / "erldc_split_test.sqlite"
    result = run_rldc_local_pdf_ingestion(
        db_path,
        [LocalReportInput(rldc="erldc", local_path=pdf_path, report_date=date(2025, 1, 15))],
    )
    assert result["reports_persisted"] == 1

    conn = sqlite3.connect(db_path)
    raw_cells = conn.execute("SELECT COUNT(*) FROM psp_raw_cell").fetchone()[0]
    assert raw_cells > 200
    conn.close()


def test_erldc_stacked_header_regional_promotes_compact_over_occupancy_collision() -> None:
    """Two-tier headers bind compact columns before numeric occupancy collides."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (42, 'erldc', 'stacked-compact-regional.pdf', '2024-04-15', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 42, 1, 1, 1, {1: "ERLDC"})
    _insert_cells(conn, 42, 1, 1, 2, {
        1: "Evening Peak (20:00) MW",
        2: "Off Peak (03:00) MW",
        3: "Day Energy (MU)",
    })
    _insert_cells(conn, 42, 1, 1, 3, {
        1: "Demand Met",
        2: "Demand Met",
        3: "Met",
    })
    _insert_cells(conn, 42, 1, 1, 4, {
        1: "25,450",
        2: "18,200",
        3: "512.4",
        6: "9,999",
        12: "1.1",
    })

    promote_report_to_curated(conn, 42)

    regional = conn.execute(
        "SELECT EveningPeakDemandMetMW, OffPeakDemandMetMW, DayEnergyMetMU "
        "FROM FactERLDCRegionalDaily WHERE ReportDocumentID = 42"
    ).fetchone()
    assert regional == (25450.0, 18200.0, 512.4)
    assert conn.execute(
        """
        SELECT COUNT(*) FROM promotion_quarantine
        WHERE ReportDocumentID = 42 AND Stage = 'layout_resolution'
        """
    ).fetchone()[0] == 0


def test_erldc_stacked_header_regional_promotes_wide_over_occupancy_collision() -> None:
    """Stacked wide labels keep day energy off compact occupancy columns."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (43, 'erldc', 'stacked-wide-regional.pdf', '2024-04-16', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 43, 1, 1, 1, {1: "ERLDC"})
    _insert_cells(conn, 43, 1, 1, 2, {
        1: "Evening Peak (20:00) MW",
        6: "Off Peak (03:00) MW",
        12: "Day Energy (MU)",
    })
    _insert_cells(conn, 43, 1, 1, 3, {
        1: "Demand Met",
        6: "Demand Met",
        12: "Met",
    })
    _insert_cells(conn, 43, 1, 1, 4, {
        1: "25,450",
        2: "111.1",
        3: "222.2",
        6: "18,200",
        12: "512.4",
    })

    promote_report_to_curated(conn, 43)

    regional = conn.execute(
        "SELECT EveningPeakDemandMetMW, OffPeakDemandMetMW, DayEnergyMetMU "
        "FROM FactERLDCRegionalDaily WHERE ReportDocumentID = 43"
    ).fetchone()
    assert regional == (25450.0, 18200.0, 512.4)


def test_erldc_flat_regional_quarantines_ambiguous_compact_and_wide_occupancy() -> None:
    """A label-less row that fits both regional signatures is not guessed."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (40, 'erldc', 'ambiguous-regional.pdf', '2024-04-15', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 40, 1, 1, 1, {1: "ERLDC"})
    _insert_cells(conn, 40, 1, 1, 2, {1: "POWER SUPPLY POSITION REPORT"})
    _insert_cells(conn, 40, 1, 1, 3, {1: "1. Demand Met / Availability (MW)"})
    _insert_cells(conn, 40, 1, 1, 4, {
        1: "25,450", 2: "18,200", 3: "512.4", 6: "18,200", 12: "512.4",
    })

    promote_report_to_curated(conn, 40)

    assert conn.execute(
        "SELECT COUNT(*) FROM FactERLDCRegionalDaily WHERE ReportDocumentID = 40"
    ).fetchone()[0] == 0
    hold = conn.execute(
        """
        SELECT ReasonCode, Stage FROM promotion_quarantine
        WHERE ReportDocumentID = 40 AND Stage = 'layout_resolution'
        """
    ).fetchone()
    assert hold == ("ambiguous_layout", "layout_resolution")


def test_erldc_flat_layouts_ignore_decorative_trailing_columns() -> None:
    """State, generation, and frequency keep compact maps when extra cells exist."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (41, 'erldc', 'decorative-columns.pdf', '2024-04-15', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 41, 1, 1, 1, {1: "EASTERN REGIONAL LOAD DESPATCH CENTRE"})
    _insert_cells(conn, 41, 1, 1, 2, {1: "POWER SUPPLY POSITION REPORT"})
    _insert_cells(conn, 41, 1, 1, 3, {1: "1. Demand Met / Availability (MW)"})
    _insert_cells(conn, 41, 1, 1, 4, {1: "25,450", 2: "18,200", 3: "512.4", 20: "Page 1"})
    _insert_cells(conn, 41, 1, 1, 5, {1: "2. State Energy Details (MU)"})
    _insert_cells(conn, 41, 1, 1, 6, {1: "State", 2: "Thermal", 3: "Hydro", 4: "Total Gen", 5: "Req", 6: "Cons"})
    _insert_cells(conn, 41, 1, 1, 8, {
        1: "WEST BENGAL", 2: "130.5", 3: "14.7", 4: "145.2", 5: "198.5", 6: "198.2", 20: "note",
    })
    _insert_cells(conn, 41, 2, 1, 1, {1: "3. Generation Details"})
    _insert_cells(conn, 41, 2, 1, 2, {1: "Station", 2: "Cap MW", 3: "Gross MU", 4: "Net MU", 5: "Avg MW"})
    _insert_cells(conn, 41, 2, 1, 3, {
        1: "FSTPS", 2: "2100", 3: "45.2", 4: "42.1", 5: "1754.2", 12: "spacer",
    })
    _insert_cells(conn, 41, 5, 1, 1, {1: "6. FREQUENCY PROFILE"})
    _insert_cells(conn, 41, 5, 1, 2, {
        1: "50.18", 4: "49.82", 8: "50.01", 10: "0.02", 12: "0.05", 14: "50.10", 17: "49.90", 25: "25",
    })

    promote_report_to_curated(conn, 41)

    regional = conn.execute(
        "SELECT EveningPeakDemandMetMW, OffPeakDemandMetMW, DayEnergyMetMU "
        "FROM FactERLDCRegionalDaily WHERE ReportDocumentID = 41"
    ).fetchone()
    assert regional == (25450.0, 18200.0, 512.4)
    state_row = conn.execute(
        """
        SELECT f.TotalGenerationMU, f.RequirementMU, f.ConsumptionMU
        FROM FactERLDCStateDaily AS f
        JOIN DimStates AS s ON s.StateID = f.StateID
        WHERE f.ReportDocumentID = 41 AND s.StateName = 'West Bengal'
        """
    ).fetchone()
    assert state_row == (145.2, 198.5, 198.2)
    generation = conn.execute(
        "SELECT GrossEnergyMU, NetEnergyMU, AverageMW FROM FactERLDCGenerationDaily "
        "WHERE ReportDocumentID = 41"
    ).fetchone()
    assert generation == (45.2, 42.1, 1754.2)
    freq = conn.execute(
        "SELECT MaximumFrequencyHz, MinimumFrequencyHz FROM FactERLDCFrequencyDaily "
        "WHERE ReportDocumentID = 41"
    ).fetchone()
    assert freq == (50.18, 49.82)


def test_erldc_promotes_frequency_operating_band_percentages() -> None:
    """IEGC three-bucket duration rows attach to the daily frequency fact."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (44, 'erldc', 'frequency-bands.pdf', '2024-04-15', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 44, 5, 1, 1, {1: "6. FREQUENCY PROFILE"})
    _insert_cells(conn, 44, 5, 1, 2, {
        1: "50.18", 4: "49.82", 8: "50.01", 10: "0.02", 12: "0.05", 14: "50.10", 17: "49.90",
    })
    _insert_cells(conn, 44, 5, 1, 3, {1: "% time frequency remained below 49.90 Hz", 2: "2.10"})
    _insert_cells(conn, 44, 5, 1, 4, {1: "49.90-50.05 Hz", 2: "95.40"})
    _insert_cells(conn, 44, 5, 1, 5, {1: "% time frequency remained above 50.05 Hz", 2: "2.50"})

    promote_report_to_curated(conn, 44)

    freq = conn.execute(
        """
        SELECT MaximumFrequencyHz, DurationBelow49_90Pct,
               Duration49_90To50_05Pct, DurationAbove50_05Pct
        FROM FactERLDCFrequencyDaily WHERE ReportDocumentID = 44
        """
    ).fetchone()
    assert freq == (50.18, 2.1, 95.4, 2.5)
    band_lineage = conn.execute(
        """
        SELECT COUNT(*) FROM curated_field_lineage
        WHERE ReportDocumentID = 44
          AND DestinationTable = 'FactERLDCFrequencyDaily'
          AND DestinationColumn IN (
              'DurationBelow49_90Pct', 'Duration49_90To50_05Pct',
              'DurationAbove50_05Pct'
          )
        """
    ).fetchone()[0]
    assert band_lineage == 3


def test_erldc_2025_flat_promotes_state_entity_owner_generation() -> None:
    """3(A) CESC and WBPDCL stations keep owner-scoped section names."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (45, 'erldc', 'state-entities.pdf', '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 45, 3, 1, 1, {1: "3(A) State Entities Generation"})
    _insert_cells(conn, 45, 3, 1, 2, {1: "CESC"})
    _insert_cells(
        conn,
        45,
        3,
        1,
        3,
        {
            1: "BUDGE BUDGE",
            3: "750",
            5: "620",
            7: "410",
            9: "640",
            10: "07:15",
            13: "380",
            15: "14:20",
            17: "16.01",
            19: "14.88",
            21: "620",
        },
    )
    _insert_cells(conn, 45, 3, 1, 4, {1: "WBPDCL"})
    _insert_cells(
        conn,
        45,
        3,
        1,
        5,
        {
            1: "BAKRESWAR",
            3: "1050",
            5: "800",
            7: "500",
            17: "20.10",
            19: "18.80",
            21: "783",
        },
    )
    _insert_cells(conn, 45, 3, 1, 6, {1: "3(B) Regional Entities Generation"})

    promote_report_to_curated(conn, 45)

    budge = conn.execute(
        """
        SELECT f.GrossEnergyMU, f.NetEnergyMU, f.AverageMW, f.SectionName, s.StateName
        FROM FactERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        LEFT JOIN DimStates AS s ON s.StateID = f.StateID
        WHERE f.ReportDocumentID = 45 AND entity.EntityName = 'BUDGE BUDGE'
        """
    ).fetchone()
    bakreswar = conn.execute(
        """
        SELECT f.SectionName, f.NetEnergyMU
        FROM FactERLDCGenerationDaily AS f
        JOIN DimGridEntities AS entity ON entity.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 45 AND entity.EntityName = 'BAKRESWAR'
        """
    ).fetchone()
    leaked = conn.execute(
        """
        SELECT COUNT(*) FROM FactERLDCGenerationDaily
        WHERE ReportDocumentID = 45 AND SectionName LIKE 'state_generation_%'
        """
    ).fetchone()[0]
    assert budge == (16.01, 14.88, 620.0, "state_entities_generation:cesc", "West Bengal")
    assert bakreswar == ("state_entities_generation:wbpdcl", 18.8)
    assert leaked == 0


def test_erldc_2025_flat_promotes_interregional_corridor_totals() -> None:
    """Published ER-NR / ER-WR corridor totals resolve from the registry."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (46, 'erldc', 'corridor-exchanges.pdf', '2026-01-01', ?, 0)
        """,
        (ERLDC_FLAT_2025_TEMPLATE_ID,),
    )
    _insert_cells(conn, 46, 4, 1, 1, {1: "4(A) INTER-REGIONAL EXCHANGES"})
    _insert_cells(
        conn,
        46,
        4,
        1,
        2,
        {
            1: "1",
            2: "ER-NR",
            9: "1200",
            13: "800",
            17: "1400",
            19: "-200",
            21: "18.4",
            23: "-2.1",
            25: "16.3",
        },
    )
    _insert_cells(conn, 46, 4, 1, 3, {1: "4(B) INTER-REGIONAL SCHEDULE"})

    promote_report_to_curated(conn, 46)

    corridor = conn.execute(
        """
        SELECT element.ElementName, f.CounterpartyRegion, f.EveningPeakMW, f.NetEnergyMU
        FROM FactERLDCInterRegionalExchange AS f
        JOIN DimTransmissionElements AS element ON element.ElementID = f.ElementID
        WHERE f.ReportDocumentID = 46
        """
    ).fetchone()
    assert corridor == ("ER-NR", "Northern Region", 1200.0, 16.3)


def test_erldc_flat_state_drawal_binds_from_published_headers() -> None:
    """Optional drawal columns promote only when the header tokens are unique."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (47, 'erldc', 'state-drawal.pdf', '2024-04-15', ?, 0)
        """,
        (ERLDC_FLAT_2024_TEMPLATE_ID,),
    )
    _insert_cells(conn, 47, 1, 1, 1, {1: "ERLDC"})
    _insert_cells(conn, 47, 1, 1, 2, {1: "POWER SUPPLY POSITION REPORT"})
    _insert_cells(
        conn,
        47,
        1,
        1,
        3,
        {
            1: "State",
            2: "Thermal",
            3: "Hydro",
            4: "Total Gen",
            5: "Req",
            6: "Cons",
            7: "Scheduled Drawal",
            8: "Actual Drawal",
            9: "UI (MU)",
        },
    )
    _insert_cells(conn, 47, 1, 1, 4, {
        1: "WEST BENGAL",
        2: "130.5",
        3: "14.7",
        4: "145.2",
        5: "198.5",
        6: "198.2",
        7: "50.1",
        8: "48.4",
        9: "-1.7",
    })

    promote_report_to_curated(conn, 47)

    state_row = conn.execute(
        """
        SELECT f.TotalGenerationMU, f.ScheduledDrawalMU, f.ActualDrawalMU, f.UIMU
        FROM FactERLDCStateDaily AS f
        JOIN DimStates AS s ON s.StateID = f.StateID
        WHERE f.ReportDocumentID = 47 AND s.StateName = 'West Bengal'
        """
    ).fetchone()
    assert state_row == (145.2, 50.1, 48.4, -1.7)
