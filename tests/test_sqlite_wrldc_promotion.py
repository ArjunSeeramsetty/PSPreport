"""Regression coverage for the initial WRLDC curated promotion scope."""

from __future__ import annotations

import sqlite3

import pytest

from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema
from psp_pipeline.storage.sqlite_wrldc_promoter import (
    _market_day_energy_columns,
    _market_extrema_columns,
    _market_mechanism_columns,
)


WRLDC_TEMPLATE_ID = "wrldc_daily_psp_v2025_standard_11_column_generation"
WRLDC_9_COLUMN_TEMPLATE_ID = "wrldc_daily_psp_v2023_standard_09_column_generation"
WRLDC_2026_EARLY_TEMPLATE_ID = "wrldc_daily_psp_v2026_early_11_column_generation"
WRLDC_2024_REVISED_TEMPLATE_ID = "wrldc_daily_psp_v2024_revised_11_column_generation"
WRLDC_2025_REVISED_TEMPLATE_ID = "wrldc_daily_psp_v2025_revised_11_column_generation"
WRLDC_2024_TRANSITION_TEMPLATE_ID = "wrldc_daily_psp_v2024_transition_11_column_generation"


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


def test_wrldc_promotes_header_validated_conventional_generation_blocks() -> None:
    """Page-three and page-four grids retain their distinct verified grains."""
    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (10, 'wrldc', 'WRLDC_PSP_Report_01-01-2026.pdf', '2026-01-01', ?, 0)
        """,
        (WRLDC_2026_EARLY_TEMPLATE_ID,),
    )
    _insert_cells(conn, 10, 3, 1, {1: "MAHARASHTRA"})
    _insert_cells(conn, 10, 3, 2, {
        1: "Station/Constituents", 2: "Inst.Capacity", 3: "19:00 PeakMW",
        5: "03:00 OffPeakMW", 7: "DayPeak(MW)", 9: "Hrs",
        11: "MinGeneration(MW)", 14: "Hrs", 16: "Gross(MU)",
        18: "Net(MU)", 20: "AVG.MW",
    })
    _insert_cells(conn, 10, 3, 3, {
        2: "MW", 3: "PeakMW", 5: "OffPeakMW", 7: "MW", 9: "Hrs",
        11: "MW", 14: "Hrs", 16: "GrossMU", 18: "NetMU", 20: "AvgMW",
    })
    _insert_cells(conn, 10, 3, 4, {
        1: "APML TIRODA(5*660)", 2: "3300", 3: "3051", 5: "1725",
        7: "3122", 9: "20:11", 11: "1704", 14: "14:36", 16: "58.53",
        18: "55.43", 20: "2310",
    })
    _insert_cells(conn, 10, 3, 5, {
        1: "TOTAL THERMAL", 2: "3300", 3: "3051", 5: "1725",
        7: "3122", 9: "20:11", 11: "1704", 14: "14:36", 16: "58.53",
        18: "55.43", 20: "2310",
    })
    _insert_cells(conn, 10, 3, 6, {1: "3(B) Regional Entities Generation"})
    _insert_cells(conn, 10, 3, 7, {1: "ISGS"})
    _insert_cells(conn, 10, 3, 8, {
        1: "Station/Constituents", 2: "Inst.Capacity", 3: "19:00 PeakMW",
        4: "03:00 OffPeakMW", 6: "DayPeak(MW)", 8: "Hrs",
        10: "MinGeneration(MW)", 12: "Hrs", 13: "DayEnergy",
        15: "Gross(MU)", 17: "Net(MU)", 19: "AVG.MW",
    })
    _insert_cells(conn, 10, 3, 9, {
        2: "MW", 3: "PeakMW", 4: "OffPeakMW", 6: "MW", 8: "Hrs",
        10: "MW", 12: "Hrs", 13: "SCHD(MU)", 15: "GrossMU",
        17: "NetMU", 19: "AvgMW",
    })
    _insert_cells(conn, 10, 3, 10, {
        1: "GADARWARA(2*800)", 2: "1600", 3: "1484", 4: "865",
        6: "1532", 8: "19:48", 10: "785", 12: "13:02", 13: "29.05",
        15: "30.67", 17: "28.49", 19: "1187",
    })
    _insert_cells(conn, 10, 4, 1, {1: "IPP/JV"})
    _insert_cells(conn, 10, 4, 2, {
        1: "Station/Constituents", 2: "Inst.Capacity", 3: "19:00 PeakMW",
        4: "03:00 OffPeakMW", 5: "DayPeak(MW)", 6: "Hrs",
        7: "MinGeneration(MW)", 8: "Hrs", 9: "DayEnergy", 10: "Gross(MU)",
        11: "Net(MU)", 12: "AVG.MW",
    })
    _insert_cells(conn, 10, 4, 3, {
        2: "MW", 3: "PeakMW", 4: "OffPeakMW", 5: "MW", 6: "Hrs",
        7: "MW", 8: "Hrs", 9: "SCHD(MU)", 10: "GrossMU", 11: "NetMU",
        12: "AvgMW",
    })
    _insert_cells(conn, 10, 4, 4, {
        1: "ACBIL", 2: "493", 3: "401", 4: "400", 5: "405", 6: "04:50",
        7: "391", 8: "16:27", 9: "9.66", 10: "10.97", 11: "9.66", 12: "403",
    })
    _insert_cells(conn, 10, 4, 5, {
        1: "SUB-TOTAL", 2: "493", 3: "401", 4: "400", 5: "405", 6: "04:50",
        7: "391", 8: "16:27", 9: "9.66", 10: "10.97", 11: "9.66", 12: "403",
    })

    promote_report_to_curated(conn, 10)

    rows = conn.execute(
        """
        SELECT entity.EntityName, state.StateName, fact.SectionName,
               fact.OffPeakMW, fact.ScheduledEnergyMU, fact.GrossEnergyMU,
               fact.NetEnergyMU, fact.IsTotalRow
        FROM FactWRLDCGenerationDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        LEFT JOIN DimStates AS state ON state.StateID = fact.StateID
        WHERE fact.ReportDocumentID = 10
        ORDER BY fact.SectionName, fact.IsTotalRow, entity.EntityName
        """
    ).fetchall()
    lineage_count = conn.execute(
        "SELECT COUNT(*) FROM curated_field_lineage WHERE ReportDocumentID = 10"
    ).fetchone()[0]

    assert rows == [
        ("ACBIL", None, "regional_generation_ipp_jv", 400.0, 9.66, 10.97, 9.66, 0),
        ("SUB-TOTAL", None, "regional_generation_ipp_jv", 400.0, 9.66, 10.97, 9.66, 1),
        ("GADARWARA(2*800)", None, "regional_generation_isgs", 865.0, 29.05, 30.67, 28.49, 0),
        ("APML TIRODA(5*660)", "Maharashtra", "state_generation_14", 1725.0, None, 58.53, 55.43, 0),
        ("TOTAL THERMAL", "Maharashtra", "state_generation_14", 1725.0, None, 58.53, 55.43, 1),
    ]
    assert lineage_count == 53

    conn.execute(
        """
        UPDATE psp_raw_cell SET cell_text = 'SCHEDULE'
        WHERE report_document_id = 10 AND page_no = 4 AND row_no = 3 AND col_no = 9
        """
    )
    promote_report_to_curated(conn, 10)

    assert conn.execute(
        """
        SELECT COUNT(*) FROM FactWRLDCGenerationDaily
        WHERE ReportDocumentID = 10 AND SectionName = 'regional_generation_ipp_jv'
        """
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM FactWRLDCGenerationDaily WHERE ReportDocumentID = 10"
    ).fetchone()[0] == 3


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


def test_wrldc_promotes_2026_operational_tables_with_cell_lineage() -> None:
    """The 2026 page shifts retain all four operational fact grains."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (7, 'wrldc', 'WRLDC_PSP_Report_01-01-2026.pdf', '2026-01-01', ?, 0)
        """,
        ("wrldc_daily_psp_v2026_early_11_column_generation",),
    )
    _insert_cells(conn, 7, 6, 25, {1: "4(A) Inter-Regional Exchanges"})
    _insert_cells(conn, 7, 6, 28, {1: "EAST REGION and WEST REGION"})
    _insert_cells(conn, 7, 6, 29, {
        1: "1", 2: "220KV-KORBA-BUDIPADAR", 7: "72", 9: "13",
        11: "164", 14: "-21", 17: "1.1", 19: "-0.02", 22: "1.08",
    })
    _insert_cells_in_table(conn, 7, 7, 2, 3, {1: "50.28", 2: "17:02:10", 3: "49.74", 4: "09:06:00", 5: "50", 7: "0.042", 9: "0.065", 11: "50.13", 12: "49.84"})
    _insert_cells(conn, 7, 7, 11, {1: "Percentage of Time Frequency Remained outside IEGC Band", 14: "24.54"})
    _insert_cells(conn, 7, 7, 12, {1: "No. of hours frequency outside IEGC Band", 14: "5.8896"})
    _insert_cells_in_table(conn, 7, 7, 2, 4, {1: "6. Voltage Profile: 400kV"})
    _insert_cells_in_table(conn, 7, 7, 2, 7, {1: "AMRELI-400KV", 3: "435.14", 4: "13:04", 5: "408.5", 6: "09:25", 8: "0", 10: "27.3", 11: "72.7", 12: "17.4"})
    _insert_cells(conn, 7, 9, 1, {1: "8. Major Reservoir Particulars"})
    _insert_cells(conn, 7, 9, 4, {1: "INDIRASAGAR", 2: "243.23", 3: "262.13", 4: "1367", 6: "260.35", 8: "1160.83", 10: "259.69", 11: "1076.39", 12: "0", 15: "0", 17: "0"})

    promote_report_to_curated(conn, 7)

    assert conn.execute("SELECT COUNT(*) FROM FactWRLDCInterRegionalExchange").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM FactWRLDCFrequencyDaily").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM FactWRLDCVoltageProfile").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM FactWRLDCReservoirDaily").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM curated_field_lineage WHERE ReportDocumentID = 7 AND RawCellID IS NOT NULL"
    ).fetchone()[0] >= 20


def test_wrldc_promotes_verified_renewable_continuation_with_cell_lineage() -> None:
    """The dense and sparse renewable pages share one station-grain contract."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (8, 'wrldc', 'WRLDC_PSP_Report_01-01-2026.pdf', '2026-01-01', ?, 0)
        """,
        ("wrldc_daily_psp_v2026_early_11_column_generation",),
    )
    _insert_cells(conn, 8, 5, 1, {1: "RENEWABLE"})
    _insert_cells(conn, 8, 5, 4, {
        1: "ATHENASOLAR", 2: "250", 3: "0", 4: "0", 5: "197",
        6: "12:09", 7: "0", 8: "17:27", 9: "1.29", 10: "1.09",
        11: "1.09", 12: "45",
    })
    _insert_cells(conn, 8, 6, 1, {
        1: "CPTTNPLWIND(DAYAPAR)", 5: "126", 7: "12", 8: "12",
        10: "24", 13: "05:59", 14: "5", 16: "12:51", 17: "0.27",
        18: "0.34", 20: "0.34", 23: "14",
    })
    _insert_cells(conn, 8, 6, 2, {
        1: "TOTAL", 5: "16,250.08", 17: "77.84", 18: "78.49",
        20: "78.49", 23: "3275",
    })
    _insert_cells(conn, 8, 6, 3, {1: "REGIONAL GENERATION SUMMARY", 5: "457.38"})

    promote_report_to_curated(conn, 8)

    rows = conn.execute(
        """
        SELECT e.EntityName, f.InstalledCapacityMW, f.ScheduledEnergyMU,
               f.NetEnergyMU, f.AverageMW, f.IsTotalRow
        FROM FactWRLDCGenerationDaily AS f
        JOIN DimGridEntities AS e ON e.EntityID = f.EntityID
        WHERE f.ReportDocumentID = 8 AND f.SectionName = 'renewable_generation'
        ORDER BY f.IsTotalRow, e.EntityName
        """
    ).fetchall()
    lineage_count = conn.execute(
        """
        SELECT COUNT(*) FROM curated_field_lineage
        WHERE ReportDocumentID = 8 AND DestinationTable = 'FactWRLDCGenerationDaily'
        """
    ).fetchone()[0]

    assert rows == [
        ("ATHENASOLAR", 250.0, 1.29, 1.09, 45.0, 0),
        ("CPTTNPLWIND(DAYAPAR)", 126.0, 0.27, 0.34, 14.0, 0),
        ("TOTAL", 16250.08, 77.84, 78.49, 3275.0, 1),
    ]
    assert lineage_count == 27


def test_wrldc_promotes_header_derived_market_day_energy_with_lineage() -> None:
    """Page 8 day-energy rows preserve their entity grain and shifted headers."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (9, 'wrldc', 'WRLDC_PSP_Report_01-01-2026.pdf', '2026-01-01', ?, 0)
        """,
        ("wrldc_daily_psp_v2026_early_11_column_generation",),
    )
    _insert_cells(conn, 9, 8, 28, {1: "State", 6: "DayEnergy(MU)"})
    _insert_cells(conn, 9, 8, 29, {
        6: "ISGS+GNASchedule", 10: "T-GNABilateral(MW)",
        14: "GDAMSchedule", 17: "DAMSchedule", 21: "HPDAMSchedule",
        25: "RTMSchedule", 29: "Total(MU)",
    })
    _insert_cells(conn, 9, 8, 30, {
        1: "AMNSIL", 6: "6.8", 10: "0", 14: "1.39", 17: "3.21",
        21: "-", 25: "1.78", 29: "13.18",
    })
    _insert_cells(conn, 9, 8, 31, {
        1: "GUJARAT", 6: "151.93", 10: "2.66", 14: "3.79", 17: "36.63",
        21: "-", 25: "-1.93", 29: "193.08",
    })
    _insert_cells(conn, 9, 8, 32, {1: "TOTAL", 6: "158.73", 29: "206.26"})

    promote_report_to_curated(conn, 9)

    rows = conn.execute(
        """
        SELECT entity.EntityName, state.StateName, fact.GNAScheduleMU,
               fact.DAMScheduleMU, fact.RTMScheduleMU, fact.TotalMU
        FROM FactWRLDCMarketEnergyDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        LEFT JOIN DimStates AS state ON state.StateID = fact.StateID
        ORDER BY entity.EntityName
        """
    ).fetchall()
    lineage_count = conn.execute(
        """
        SELECT COUNT(*) FROM curated_field_lineage
        WHERE ReportDocumentID = 9
          AND DestinationTable = 'FactWRLDCMarketEnergyDaily'
        """
    ).fetchone()[0]

    assert rows == [
        ("AMNSIL", None, 6.8, 3.21, 1.78, 13.18),
        ("GUJARAT", "Gujarat", 151.93, 36.63, -1.93, 193.08),
    ]
    assert lineage_count == 12
    assert _market_day_energy_columns({
        6: (1, "ISGS+GNASchedule"), 10: (2, "T-GNABilateral(MW)"),
        14: (3, "GDAMSchedule"), 17: (4, "DAMSchedule"),
        20: (5, "HPDAMSchedule"), 24: (6, "RTMSchedule"),
        28: (7, "Total(MU)"),
    }) == {
        "GNAScheduleMU": 6, "TGNABilateralMU": 10, "GDAMScheduleMU": 14,
        "DAMScheduleMU": 17, "HPDAMScheduleMU": 20, "RTMScheduleMU": 24,
        "TotalMU": 28,
    }


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


def _insert_cells_in_table(
    conn: sqlite3.Connection,
    report_id: int,
    page_no: int,
    table_no: int,
    row_no: int,
    cells: dict[int, str],
) -> None:
    """Insert one sparse row into a non-default raw PDF table."""

    for col_no, text in cells.items():
        raw_id = page_no * 1_000_000 + table_no * 100_000 + row_no * 100 + col_no
        conn.execute(
            """
            INSERT INTO psp_raw_cell(
                id, report_document_id, page_no, table_no, row_no, col_no, cell_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (raw_id, report_id, page_no, table_no, row_no, col_no, text),
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


def test_wrldc_market_header_contracts_cover_2025_and_2026_geometries() -> None:
    """Point and extrema headers resolve by names despite yearly column shifts."""

    point_2025 = _market_mechanism_columns({
        2: (1, "T-GNA Bilateral (MW)"), 3: (2, "IEX GDAM (MW)"),
        5: (3, "IEX DAM (MW)"), 6: (4, "IEX HPDAM (MW)"),
        7: (5, "IEX RTM (MW)"), 9: (6, "PXIL GDAM (MW)"),
        11: (7, "PXIL DAM (MW)"), 12: (8, "PXIL HPDAM (MW)"),
        14: (9, "PXI RTM (MW)"), 16: (10, "HPX GDAM (MW)"),
        17: (11, "HPX DAM (MW)"), 18: (12, "HPX HPDAM (MW)"),
        20: (13, "HPX RTM (MW)"),
    })
    point_2026 = _market_mechanism_columns({
        2: (1, "T-GNA Bilateral (MW)"), 4: (2, "IEX GDAM (MW)"),
        6: (3, "IEX DAM (MW)"), 8: (4, "IEX HPDAM (MW)"),
        11: (5, "IEX RTM (MW)"), 13: (6, "PXIL GDAM (MW)"),
        16: (7, "PXIL DAM (MW)"), 18: (8, "PXIL HPDAM (MW)"),
        20: (9, "PXI RTM (MW)"), 23: (10, "HPX GDAM (MW)"),
        26: (11, "HPX DAM (MW)"), 28: (12, "HPX HPDAM (MW)"),
        30: (13, "HPX RTM (MW)"),
    })
    extrema_headers = _market_mechanism_columns({
        3: (1, "ISGS+GNA Schedule"), 7: (2, "T-GNA Bilateral (MW)"),
        12: (3, "IEX GDAM (MW)"), 15: (4, "PXIL GDAM (MW)"),
        19: (5, "HPX GDAM (MW)"), 23: (6, "IEX DAM (MW)"),
        27: (7, "PXIL DAM (MW)"),
    })
    extrema_pairs = _market_extrema_columns(extrema_headers, {
        3: (1, "Maximum"), 4: (2, "Minimum"), 7: (3, "Maximum"),
        9: (4, "Minimum"), 12: (5, "Maximum"), 13: (6, "Minimum"),
        15: (7, "Maximum"), 17: (8, "Minimum"), 19: (9, "Maximum"),
        22: (10, "Minimum"), 23: (11, "Maximum"), 25: (12, "Minimum"),
        27: (13, "Maximum"), 30: (14, "Minimum"),
    })

    assert len(point_2025) == len(point_2026) == 13
    assert point_2025["IEXDAM"] == 5
    assert point_2026["IEXDAM"] == 6
    assert extrema_pairs == {
        "GNASchedule": (3, 4), "TGNABilateral": (7, 9),
        "IEXGDAM": (12, 13), "PXILGDAM": (15, 17),
        "HPXGDAM": (19, 22), "IEXDAM": (23, 25), "PXILDAM": (27, 30),
    }


def test_wrldc_2024_revised_promotes_market_day_energy_on_page_seven() -> None:
    """The 2024-revised family publishes the same MU contract on page 7."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (10, 'wrldc', 'WRLDC_PSP_Report_15-12-2024.pdf', '2024-12-15', ?, 0)
        """,
        (WRLDC_2024_REVISED_TEMPLATE_ID,),
    )
    _insert_cells(conn, 10, 7, 28, {1: "State", 6: "DayEnergy(MU)"})
    _insert_cells(conn, 10, 7, 29, {
        6: "ISGS+GNASchedule", 10: "T-GNABilateral(MW)",
        14: "GDAMSchedule", 17: "DAMSchedule", 21: "HPDAMSchedule",
        25: "RTMSchedule", 29: "Total(MU)",
    })
    _insert_cells(conn, 10, 7, 30, {
        1: "GUJARAT", 6: "151.93", 10: "2.66", 14: "3.79", 17: "36.63",
        21: "-", 25: "-1.93", 29: "193.08",
    })
    _insert_cells(conn, 10, 7, 31, {1: "TOTAL", 6: "151.93", 29: "193.08"})

    promote_report_to_curated(conn, 10)

    rows = conn.execute(
        """
        SELECT entity.EntityName, state.StateName, fact.GNAScheduleMU,
               fact.DAMScheduleMU, fact.RTMScheduleMU, fact.TotalMU
        FROM FactWRLDCMarketEnergyDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        LEFT JOIN DimStates AS state ON state.StateID = fact.StateID
        WHERE fact.ReportDocumentID = 10
        """
    ).fetchall()
    lineage_count = conn.execute(
        """
        SELECT COUNT(*) FROM curated_field_lineage
        WHERE ReportDocumentID = 10
          AND DestinationTable = 'FactWRLDCMarketEnergyDaily'
        """
    ).fetchone()[0]
    assert rows == [("GUJARAT", "Gujarat", 151.93, 36.63, -1.93, 193.08)]
    assert lineage_count == 6


@pytest.mark.parametrize(
    ("report_id", "template_id"),
    [
        (11, WRLDC_2025_REVISED_TEMPLATE_ID),
        (12, WRLDC_2024_TRANSITION_TEMPLATE_ID),
    ],
)
def test_wrldc_revised_families_promote_native_market_extrema(
    report_id: int,
    template_id: str,
) -> None:
    """2025-revised and 2024-transition promote complete 8(B) max/min pairs."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    _create_raw_tables(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, local_path, report_date, template_id, semantic_pass_required
        ) VALUES (?, 'wrldc', 'WRLDC_PSP_Report_01-01-2025.pdf', '2025-01-01', ?, 0)
        """,
        (report_id, template_id),
    )
    _insert_cells(conn, report_id, 8, 2, {
        1: "State", 3: "ISGS+GNA Schedule", 7: "T-GNA Bilateral (MW)",
        12: "IEX GDAM (MW)", 15: "PXIL GDAM (MW)", 19: "HPX GDAM (MW)",
        23: "IEX DAM (MW)", 27: "PXIL DAM (MW)",
    })
    _insert_cells(conn, report_id, 8, 3, {
        3: "Maximum", 4: "Minimum", 7: "Maximum", 9: "Minimum",
        12: "Maximum", 13: "Minimum", 15: "Maximum", 17: "Minimum",
        19: "Maximum", 22: "Minimum", 23: "Maximum", 25: "Minimum",
        27: "Maximum", 30: "Minimum",
    })
    _insert_cells(conn, report_id, 8, 4, {
        1: "GUJARAT", 3: "210", 4: "12", 7: "40", 9: "1",
        12: "55", 13: "0", 15: "0", 17: "0",
        19: "0", 22: "0", 23: "88", 25: "3",
        27: "0", 30: "0",
    })
    _insert_cells(conn, report_id, 8, 5, {1: "TOTAL"})

    promote_report_to_curated(conn, report_id)

    rows = conn.execute(
        """
        SELECT fact.Mechanism, fact.MaximumMW, fact.MinimumMW
        FROM FactWRLDCMarketExtremaDaily AS fact
        JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID
        JOIN DimStates AS state ON state.StateID = fact.StateID
        WHERE fact.ReportDocumentID = ? AND state.StateName = 'Gujarat'
        ORDER BY fact.Mechanism
        """,
        (report_id,),
    ).fetchall()
    assert rows == [
        ("GNASchedule", 210.0, 12.0),
        ("HPXGDAM", 0.0, 0.0),
        ("IEXDAM", 88.0, 3.0),
        ("IEXGDAM", 55.0, 0.0),
        ("PXILDAM", 0.0, 0.0),
        ("PXILGDAM", 0.0, 0.0),
        ("TGNABilateral", 40.0, 1.0),
    ]
