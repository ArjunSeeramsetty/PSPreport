"""Header-driven RPC DSM/REA parsing, coverage boundaries, and dual-write export."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3

from psp_pipeline.acquisition.adapters.rpc import ERPCAdapter, rpc_adapter_for
from psp_pipeline.parsing.rpc.contracts import classify_rpc_document
from psp_pipeline.parsing.rpc.dsm import DSM_ENTITY_FIELDS, parse_weekly_dsm_tables
from psp_pipeline.parsing.rpc.headers import bind_header_columns, locate_header_row
from psp_pipeline.parsing.rpc.rea import parse_monthly_rea_tables
from psp_pipeline.parsing.rpc.tables import ExtractedTable
from psp_pipeline.pipelines.rldc_daily_psp import DownloadedReport, ensure_sqlite_schema
from psp_pipeline.pipelines.rpc_settlement import persist_local_rpc_report
from psp_pipeline.storage.sqlite_curated_export import export_registered_daily_observations
from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated
from psp_pipeline.storage.sqlite_rpc_promoter import promote_rpc_report_to_curated
from psp_pipeline.storage.wide_facts import export_wide_facts


def _table(*rows: tuple[str, ...], page_no: int = 4, table_no: int = 2) -> ExtractedTable:
    """Build one extracted table that is deliberately not on page one."""

    return ExtractedTable(page_no, table_no, None, rows)


def test_classify_rpc_document_identifies_dsm_week_and_rea_month() -> None:
    """Filenames carry enough metadata to classify family and accounting window."""

    dsm = classify_rpc_document("ERPC_DSM_Account_Week_35_of_2026.pdf")
    assert dsm.family == "weekly_dsm"
    assert dsm.supported is True
    assert dsm.week_start == date(2026, 8, 24)
    rea = classify_rpc_document("SRPC Regional Energy Account August 2026.xlsx")
    assert rea.family == "monthly_rea"
    assert rea.period_month == "2026-08"


def test_ui_era_and_nine_column_rea_are_unsupported_families() -> None:
    """Legacy UI accounts and 9-column REA matrices stay outside the contract."""

    ui = classify_rpc_document("NRPC_UI_Charges_Week_12_of_2014.pdf")
    assert ui.supported is False
    assert ui.template_id == "rpc_weekly_dsm_v2014_ui_charges"
    legacy = classify_rpc_document("WRPC_REA_9column_matrix_March_2012.xls")
    assert legacy.supported is False
    assert legacy.template_id == "rpc_monthly_rea_v2010_9_column_matrix"


def test_dsm_header_location_ignores_page_number() -> None:
    """A narrative section that shifts the DSM table still matches by header."""

    table = _table(
        ("Weekly narrative that used to live above the charges table", "", "", "", ""),
        ("Entity", "Scheduled Energy (MU)", "Actual Energy (MU)", "Deviation (MU)", "DSM Charges (Rs)"),
        ("Bihar", "120.5", "118.0", "-2.5", "145000"),
        page_no=11,
    )
    index = locate_header_row(table.rows, DSM_ENTITY_FIELDS)
    assert index == 1
    parsed = parse_weekly_dsm_tables((table,))
    assert parsed.contract_matched is True
    assert parsed.entity_rows[0].entity_name == "Bihar"
    assert parsed.entity_rows[0].values["ScheduledEnergyMU"] == 120.5
    assert parsed.entity_rows[0].values["FrequencyLinkedDeviationChargeRs"] == 145000.0


def test_malformed_duplicate_dsm_charge_headers_skip_pair_not_energy() -> None:
    """Duplicate charge labels skip that pair without dropping scheduled energy."""

    table = _table(
        (
            "Constituent",
            "Scheduled Energy (MU)",
            "Actual Energy (MU)",
            "Deviation (MU)",
            "DSM Charges (Rs)",
            "DSM Charges (Rs)",
        ),
        ("Odisha", "80.0", "82.1", "2.1", "1000", "2000"),
    )
    binding = bind_header_columns(table.rows[0], DSM_ENTITY_FIELDS)
    assert "ScheduledEnergyMU" in binding.columns
    assert "FrequencyLinkedDeviationChargeRs" not in binding.columns
    assert "SustainedDeviationPenaltyRs" not in binding.columns
    parsed = parse_weekly_dsm_tables((table,))
    assert parsed.contract_matched is True
    assert parsed.entity_rows[0].values["DeviationMU"] == 2.1
    assert "FrequencyLinkedDeviationChargeRs" not in parsed.entity_rows[0].values
    assert "FrequencyLinkedDeviationChargeRs" in parsed.skipped_fields


def test_legacy_nine_column_rea_matrix_is_refused() -> None:
    """A 9-column REA mix of PAF and share columns is quarantined, not guessed."""

    table = _table(
        ("Station", "IC", "PAF", "Deemed", "Schedule", "Aux", "Share", "Capacity", "Energy"),
        ("Farakka", "2100", "85", "12", "11", "1", "3", "400", "8"),
        page_no=2,
    )
    parsed = parse_monthly_rea_tables((table,))
    assert parsed.contract_matched is False
    assert parsed.unsupported_family == "rpc_monthly_rea_v2010_9_column_matrix"
    assert parsed.station_rows == ()


def test_rea_station_and_peak_offpeak_allocation_parse_from_headers() -> None:
    """PAFM and peak/off-peak allocations bind from published column titles."""

    station = _table(
        (
            "Generating Station",
            "Installed Capacity (MW)",
            "PAFM (%)",
            "Scheduled Generation (MU)",
            "Deemed Generation (MU)",
        ),
        ("Kahalgaon STPS", "2340", "92.5", "140.0", "142.2"),
    )
    allocation = _table(
        ("Beneficiary", "Station", "Peak Allocation (MW)", "Off-Peak Allocation (MW)", "Energy Share (MU)"),
        ("Bihar", "Kahalgaon STPS", "450", "380", "95.5"),
        page_no=5,
        table_no=1,
    )
    parsed = parse_monthly_rea_tables((station, allocation))
    assert parsed.contract_matched is True
    assert parsed.station_rows[0].values["PAFMPct"] == 92.5
    windows = {row.allocation_window: row.values["AllocatedCapacityMW"] for row in parsed.allocation_rows}
    assert windows == {"peak": 450.0, "off_peak": 380.0}


def test_erpc_adapter_discovers_dsm_and_rea_inside_publication_window() -> None:
    """Listing discovery keeps same-host settlement files in the lag window."""

    html = """
    <html><body>
      <a href="/files/ERPC_DSM_Account_18-08-2026_to_24-08-2026.pdf">DSM Week</a>
      <a href="/files/ERPC_REA_August_2026.xlsx">REA August</a>
      <a href="https://other.gov.in/files/ERPC_DSM_Account_18-08-2026_to_24-08-2026.pdf">off host</a>
      <a href="/files/daily_psp.pdf">PSP</a>
    </body></html>
    """
    links = ERPCAdapter().links_from_html(
        html, "https://erpc.gov.in/en/commercial/", date(2026, 8, 28)
    )
    families = {link.report_family for link in links}
    assert families == {"weekly_dsm", "monthly_rea"}
    assert all(link.source_id == "erpc" for link in links)
    assert rpc_adapter_for("nerpc") is not None


def test_rpc_adapter_uses_registry_listing_domain_and_keywords() -> None:
    """The external source registry must override portal-specific defaults."""

    adapter = rpc_adapter_for(
        "erpc",
        {
            "listing_url": "https://reports.example.gov/settlement/index.html",
            "allow_domains": ["reports.example.gov"],
            "include_keywords": ["account statement"],
        },
    )
    assert adapter is not None
    assert adapter._listing_url == "https://reports.example.gov/settlement/index.html"
    links = adapter.links_from_html(
        '<a href="/files/account_statement_DSM_18-08-2026_to_24-08-2026.pdf">'
        "account statement</a>",
        adapter._listing_url,
        date(2026, 8, 28),
    )
    assert [link.url for link in links] == [
        "https://reports.example.gov/files/account_statement_DSM_18-08-2026_to_24-08-2026.pdf"
    ]


def _seed_rpc_report(conn: sqlite3.Connection, *, family: str, template_id: str, table: ExtractedTable) -> int:
    """Persist one synthetic RPC document and its raw cells."""

    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count,
            report_date, report_family, template_id, semantic_pass_required
        ) VALUES (1, 'erpc', 'fixture', 'ERPC_DSM_Account_Week_35_of_2026.pdf', 'hash',
                  '2026-08-28T00:00:00Z', 0.0, 0, 'native', 20, '2026-08-24', ?, ?, 0)
        """,
        (family, template_id),
    )
    now = "2026-08-28T00:00:00Z"
    for row_no, row in enumerate(table.rows, start=1):
        for col_no, text in enumerate(row, start=1):
            if not text:
                continue
            conn.execute(
                """
                INSERT INTO psp_raw_cell(
                    report_document_id, page_no, table_no, row_no, col_no,
                    cell_text, extraction_method, extracted_at
                ) VALUES (1, ?, ?, ?, ?, ?, 'rpc_table', ?)
                """,
                (table.page_no, table.table_no, row_no, col_no, text, now),
            )
    conn.commit()
    return 1


def test_rpc_promoter_writes_dsm_facts_lineage_and_settlement_export() -> None:
    """Clean DSM energy and charges dual-write as settlement_value observations."""

    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    table = _table(
        ("Entity", "Scheduled Energy (MU)", "Actual Energy (MU)", "Deviation (MU)", "Frequency Linked Charges (Rs)"),
        ("West Bengal", "200.0", "198.5", "-1.5", "25000"),
        page_no=6,
    )
    report_id = _seed_rpc_report(
        conn,
        family="weekly_dsm",
        template_id="rpc_weekly_dsm_v2022_entity_charges",
        table=table,
    )
    promote_report_to_curated(conn, report_id)
    row = conn.execute(
        "SELECT ScheduledEnergyMU, FrequencyLinkedDeviationChargeRs FROM FactRPCWeeklyDSMEntity"
    ).fetchone()
    assert row == (200.0, 25000.0)
    lineage = conn.execute("SELECT COUNT(*) FROM curated_field_lineage").fetchone()[0]
    assert lineage >= 2
    observations = export_registered_daily_observations(conn, "erpc", report_document_id=report_id)
    assert observations
    assert all(item.settlement_value is not None for item in observations)
    assert all(item.operational_value is None for item in observations)
    wide = export_wide_facts(observations)
    assert wide
    assert "ScheduledEnergyMU" in wide[0].metrics or any(
        "ScheduledEnergyMU" in item.metrics for item in wide
    )


def test_rpc_promoter_quarantines_unsupported_nine_column_rea() -> None:
    """The 9-column REA family is held instead of being coerced into allocations."""

    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    table = _table(
        ("Station", "IC", "PAF", "Deemed", "Schedule", "Aux", "Share", "Capacity", "Energy"),
        ("Farakka", "2100", "85", "12", "11", "1", "3", "400", "8"),
    )
    report_id = _seed_rpc_report(
        conn,
        family="monthly_rea",
        template_id="rpc_monthly_rea_v2010_9_column_matrix",
        table=table,
    )
    promote_rpc_report_to_curated(conn, report_id)
    assert conn.execute("SELECT COUNT(*) FROM FactRPCMonthlyREAStation").fetchone()[0] == 0
    hold = conn.execute(
        "SELECT ReasonCode, Status FROM promotion_quarantine"
    ).fetchone()
    assert hold == ("rpc_unsupported_family", "pending")


def test_persist_local_rpc_report_promotes_from_extracted_workbook(tmp_path: Path) -> None:
    """Excel extraction plus promotion yields curated REA station facts."""

    from openpyxl import Workbook

    path = tmp_path / "ERPC_REA_August_2026.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "REA"
    sheet.append(
        [
            "Generating Station",
            "Installed Capacity (MW)",
            "PAFM (%)",
            "Deemed Generation (MU)",
        ]
    )
    sheet.append(["Farakka STPS", 2100, 88.0, 155.4])
    workbook.save(path)
    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    persist_local_rpc_report(
        conn,
        DownloadedReport(
            rldc="erpc",
            source_url="https://erpc.gov.in/files/ERPC_REA_August_2026.xlsx",
            local_path=path,
            content_hash="abc",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            report_date=date(2026, 8, 1),
            report_family="monthly_rea",
            discovery_confidence=0.9,
            response_content_length=path.stat().st_size,
            response_last_modified=None,
        ),
    )
    station = conn.execute(
        "SELECT InstalledCapacityMW, PAFMPct, DeemedGenerationMU FROM FactRPCMonthlyREAStation"
    ).fetchone()
    assert station == (2100.0, 88.0, 155.4)


def test_malformed_dsm_pair_still_promotes_clean_energy_columns() -> None:
    """A duplicated DSM Charges header does not drop the rest of the entity row."""

    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    table = _table(
        (
            "Entity",
            "Scheduled Energy (MU)",
            "Actual Energy (MU)",
            "Deviation (MU)",
            "DSM Charges (Rs)",
            "DSM Charges (Rs)",
        ),
        ("Jharkhand", "50", "49", "-1", "10", "20"),
    )
    report_id = _seed_rpc_report(
        conn,
        family="weekly_dsm",
        template_id="rpc_weekly_dsm_v2022_entity_charges",
        table=table,
    )
    promote_report_to_curated(conn, report_id)
    row = conn.execute(
        """
        SELECT ScheduledEnergyMU, DeviationMU, FrequencyLinkedDeviationChargeRs
        FROM FactRPCWeeklyDSMEntity
        """
    ).fetchone()
    assert row == (50.0, -1.0, None)
