"""Market contracts transcribed from the 2026-01-01 ER/NER raw matrices."""

from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.storage.sqlite_market_promoter import (
    ensure_market_tables,
    promote_market_rows,
)


def _rows(values):
    return [{col: (100 * index + col, text) for col, text in row.items()}
            for index, row in enumerate(values, 1)]


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    ensure_market_tables(connection)
    connection.execute("""CREATE TABLE curated_field_lineage (
        ReportDocumentID INTEGER, DestinationTable TEXT, DestinationKey TEXT,
        DestinationColumn TEXT, RawCellID INTEGER, ExtractionMethod TEXT,
        Confidence REAL, CreatedAt TEXT,
        UNIQUE(DestinationTable, DestinationKey, DestinationColumn, RawCellID))""")
    yield connection
    connection.close()


def test_ner_peak_and_off_peak_preserve_sign_zero_and_lineage(conn):
    rows = _rows([
        {2: "Off- Peak Hours (03:00)", 9: "Peak Hours (19:00)"},
        {1: "State", 2: "T-GNA Bilateral (MW)", 4: "IEX DAM (MW)",
         5: "IEX RTM (MW)", 9: "Bilateral (MW)", 11: "IEX DAM (MW)",
         12: "IEX RTM (MW)"},
        {1: "ASSAM", 2: "153.73", 4: "-250.72", 5: "-121.37",
         9: "142.61", 11: "0", 12: "-458.95"},
    ])
    for _ in range(2):
        promote_market_rows(conn, 1, 1, "NERLDC", rows, lambda label: (7, 2))
    assert conn.execute("SELECT COUNT(*) FROM FactNERLDCMarketPointDaily").fetchone()[0] == 6
    assert conn.execute("SELECT ScheduledMW FROM FactNERLDCMarketPointDaily "
                        "WHERE TimeCategory='peak' AND Mechanism='IEXRTM'").fetchone()[0] == -458.95
    assert conn.execute("SELECT RawCellID FROM curated_field_lineage WHERE "
                        "DestinationKey LIKE '%TimeCategory=peak;Mechanism=IEXDAM'").fetchone()[0] == 311
    assert conn.execute("SELECT COUNT(*) FROM curated_field_lineage").fetchone()[0] == 6


def test_sparse_er_headers_do_not_guess_ambiguous_or_unknown_columns(conn):
    rows = _rows([
        {2: "PeakHours(19:00)"},
        {1: "State", 2: "T-GNA BILATERAL (MW)", 5: "IEX GDAM (MW)",
         8: "IEX DAM (MW)", 11: "Unknown Product (MW)", 13: "IEX RTM (MW)", 16: ""},
        {1: "SIKKIM", 2: "9.51", 5: "-", 8: "0", 11: "999", 13: "-26", 14: "7"},
    ])
    promote_market_rows(conn, 1, 1, "ERLDC", rows, lambda label: (4, 1))
    assert conn.execute("SELECT Mechanism, ScheduledMW FROM FactERLDCMarketPointDaily "
                        "ORDER BY Mechanism").fetchall() == [("IEXDAM", 0), ("TGNABilateral", 9.51)]


def test_duplicate_point_headers_are_unresolved(conn):
    rows = _rows([{2: "Peak Hours (19:00)"},
                  {1: "State", 2: "IEX DAM (MW)", 3: "IEX DAM (MW)"},
                  {1: "ASSAM", 2: "10", 3: "20"}])
    promote_market_rows(conn, 1, 1, "NERLDC", rows, lambda label: (1, 1))
    assert conn.execute("SELECT COUNT(*) FROM FactNERLDCMarketPointDaily").fetchone()[0] == 0


def test_ner_energy_and_extrema_have_distinct_units(conn):
    energy = _rows([
        {2: "Day Energy (MU)"},
        {1: "State", 2: "GNA Schedule", 3: "T-GNA BILT Schedule", 4: "GDAM Schedule",
         5: "DAM Schedule", 6: "RTM Schedule", 7: "Total (MU)"},
        {1: "ASSAM", 2: "25.6", 3: "3.51", 4: "-", 5: "-2.81", 6: "-2.65", 7: "23.65"},
    ])
    extrema = _rows([
        {2: "IEX DAM (MW)", 4: "PXI DAM(MW)", 6: "IEX RTM (MW)"},
        {1: "State", 2: "Maximum", 3: "Minimum", 4: "Minimum", 5: "Minimum",
         6: "Maximum", 7: "Minimum"},
        {1: "MANIPUR", 2: "0", 3: "0", 4: "7", 5: "8", 6: "53.63", 7: "-88"},
    ])
    for rows in (energy, extrema):
        promote_market_rows(conn, 1, 1, "NERLDC", rows, lambda label: (1, 1))
    assert conn.execute("SELECT GDAMScheduleMU, RTMScheduleMU, TotalMU FROM "
                        "FactNERLDCMarketEnergyDaily").fetchone() == (None, -2.65, 23.65)
    assert conn.execute("SELECT Mechanism, MaximumMW, MinimumMW FROM "
                        "FactNERLDCMarketExtremaDaily ORDER BY Mechanism").fetchall() == [
                            ("IEXDAM", 0, 0), ("IEXRTM", 53.63, -88)]


def test_local_replay_market_coverage_and_export(tmp_path):
    """Replay saved raw cells on a copy and measure only the market increment."""
    from psp_pipeline.quality.raw_cell_coverage import generate_raw_cell_coverage_report
    from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema
    from psp_pipeline.storage.sqlite_curated_export import export_all_daily_observations
    from psp_pipeline.storage.sqlite_erldc_promoter import _promote_market_sections
    from psp_pipeline.storage.sqlite_nerldc_promoter import _markets

    source = Path("data/sqlite/local_six_source_replay_2026_01_01.sqlite")
    if not source.exists():
        pytest.skip("Local six-source raw-cell replay unavailable")
    db = tmp_path / "market-replay.sqlite"
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as original:
        with sqlite3.connect(db) as copy:
            original.backup(copy)
    before = {name: generate_raw_cell_coverage_report(db, rldc=name)
              for name in ("erldc", "nerldc")}
    with sqlite3.connect(db) as copy:
        ensure_curated_sqlite_schema(copy)
        for report, source_name, date_id in copy.execute(
            "SELECT p.id, p.rldc, d.DateID FROM psp_report_document p "
            "JOIN DimDates d ON d.ActualDate=p.report_date WHERE p.rldc IN ('erldc','nerldc')"
        ).fetchall():
            if source_name == "erldc":
                _promote_market_sections(copy, report, date_id)
            else:
                region = copy.execute("SELECT RegionID FROM DimRegions WHERE "
                                      "RegionName='North Eastern Region'").fetchone()[0]
                _markets(copy, report, date_id, region)
        observations = export_all_daily_observations(copy)
        for prefix in ("ER:market-participant:", "NER:market-participant:"):
            assert any(o.entity_key.startswith(prefix) and ':market:point:' in o.entity_key
                       for o in observations)
    for name in before:
        after = generate_raw_cell_coverage_report(db, rldc=name)
        assert after["mapped_cell_count"] > before[name]["mapped_cell_count"]
        assert after["unresolved_cell_count"] < before[name]["unresolved_cell_count"]
        print(name, before[name]["accounted_cell_pct"], after["accounted_cell_pct"],
              "new mapped", after["mapped_cell_count"] - before[name]["mapped_cell_count"])
