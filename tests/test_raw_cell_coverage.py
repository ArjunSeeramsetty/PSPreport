"""Tests for the conservative raw-cell curated coverage gate."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.quality.raw_cell_coverage import generate_raw_cell_coverage_report


def test_raw_cell_coverage_distinguishes_mapped_excluded_and_unresolved(
    tmp_path: Path,
) -> None:
    """Only lineage and explicit structural rules may remove cells from review."""

    db_path = tmp_path / "coverage.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count, template_id
        ) VALUES (1, 'erldc', 'local', 'fixture.pdf', 'hash', '2026-08-30T00:00:00Z',
                  1.0, 0, 'native', 1000, 'erldc_fixture')
        """
    )
    cells = (
        (1, 1, 1, 1, 1, "Station"),
        (1, 1, 1, 1, 2, "MW"),
        (1, 1, 1, 2, 1, "Plant A"),
        (1, 1, 1, 2, 2, "25"),
        (1, 1, 1, 2, 3, "88"),
        (1, 1, 1, 2, 4, "-"),
        (1, 1, 1, 3, 1, "Unclassified note"),
    )
    conn.executemany(
        """
        INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no, cell_text,
            extraction_method, extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pdfplumber', '2026-08-30T00:00:00Z')
        """,
        cells,
    )
    metric_cell_id = conn.execute(
        "SELECT id FROM psp_raw_cell WHERE cell_text = '25'"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn,
            RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES (1, 'FactERLDCGenerationDaily', 'entity:plant-a', 'NetEnergyMU',
                  ?, 'pdfplumber', 1.0, '2026-08-30T00:00:00Z')
        """,
        (metric_cell_id,),
    )
    conn.commit()
    conn.close()

    report = generate_raw_cell_coverage_report(db_path, rldc="erldc")

    assert report["raw_nonempty_cell_count"] == 7
    assert report["mapped_cell_count"] == 1
    assert report["approved_exclusion_count"] == 4
    assert report["unresolved_cell_count"] == 2
    assert report["accounted_cell_pct"] == 71.43
    group = report["unresolved_groups"][0]
    assert group["col_no"] == 1
    assert group["examples"][0]["value"] == "Unclassified note"


def test_raw_cell_coverage_excludes_published_legends_and_signoffs(
    tmp_path: Path,
) -> None:
    """Footnotes and SLDC sign-off stamps are approved exclusions, not facts."""

    db_path = tmp_path / "legend.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count, template_id
        ) VALUES (1, 'erldc', 'local', 'fixture.pdf', 'hash', '2026-08-30T00:00:00Z',
                  1.0, 0, 'native', 1000, 'erldc_fixture')
        """
    )
    conn.executemany(
        """
        INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no, cell_text,
            extraction_method, extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pdfplumber', '2026-08-30T00:00:00Z')
        """,
        (
            (1, 5, 1, 1, 1, "IEGC Operating Band as per CERC regulations"),
            (1, 5, 1, 2, 1, "All figures in MW unless otherwise noted"),
            (1, 5, 1, 3, 1, "Prepared by Shift In-Charge"),
            (1, 5, 1, 4, 1, "4523.5"),
        ),
    )
    conn.commit()
    conn.close()

    report = generate_raw_cell_coverage_report(db_path, rldc="erldc")

    assert report["raw_nonempty_cell_count"] == 4
    assert report["approved_exclusion_count"] == 3
    assert report["unresolved_cell_count"] == 1
    assert report["unresolved_groups"][0]["examples"][0]["value"] == "4523.5"


def test_raw_cell_coverage_honors_existing_approved_dispositions(tmp_path: Path) -> None:
    """Existing per-source coverage decisions are reused rather than overwritten."""

    db_path = tmp_path / "approved.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count, template_id
        ) VALUES (1, 'srldc', 'local', 'fixture.pdf', 'hash', '2026-08-30T00:00:00Z',
                  1.0, 0, 'native', 1000, 'srldc_fixture')
        """
    )
    raw_cell_id = conn.execute(
        """
        INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no, cell_text,
            extraction_method, extracted_at
        ) VALUES (1, 1, 1, 1, 3, 'Publisher note', 'pdfplumber', '2026-08-30T00:00:00Z')
        RETURNING id
        """
    ).fetchone()[0]
    coverage_run_id = conn.execute(
        """
        INSERT INTO schema_coverage_run(
            ReportDocumentID, TemplateID, Status, ComputedAt
        ) VALUES (1, 'srldc_fixture', 'passed', '2026-08-30T00:00:00Z')
        RETURNING CoverageRunID
        """
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO schema_coverage_item(
            CoverageRunID, RawCellID, SourceReference, Disposition, Reason
        ) VALUES (?, ?, 'cell:1', 'intentionally_excluded', 'approved_note')
        """,
        (coverage_run_id, raw_cell_id),
    )
    conn.commit()
    conn.close()

    report = generate_raw_cell_coverage_report(db_path, rldc="srldc")

    assert report["approved_exclusion_count"] == 1
    assert report["unresolved_cell_count"] == 0


def test_reservoir_headers_are_approved_without_excluding_measure_cells(
    tmp_path: Path,
) -> None:
    """Reservoir column headings are presentation cells; values still need lineage."""

    db_path = tmp_path / "reservoir_headers.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute(
        """INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count, template_id
        ) VALUES (1, 'nerldc', 'local', 'fixture.pdf', 'hash',
                  '2026-08-30T00:00:00Z', 1.0, 0, 'native', 1000,
                  'nerldc_fixture')"""
    )
    conn.executemany(
        """INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no, cell_text,
            extraction_method, extracted_at
        ) VALUES (?, 4, 6, ?, ?, ?, 'pdfplumber', '2026-08-30T00:00:00Z')""",
        (
            (1, 1, 2, "DESIGNED"), (1, 2, 2, "MDDL (Mts)"),
            (1, 2, 3, "FRL (Mts)"), (1, 3, 1, "Kopili"),
            (1, 3, 2, "9696"),
        ),
    )
    conn.commit()
    conn.close()

    report = generate_raw_cell_coverage_report(db_path, rldc="nerldc")

    assert report["approved_exclusion_count"] == 3
    assert report["unresolved_cell_count"] == 2
    assert report["unresolved_groups"][0]["examples"][0]["value"] in {
        "Kopili", "9696"
    }


def test_rpc_entity_service_and_station_labels_are_accounted(tmp_path: Path) -> None:
    """RPC header labels and extra dimension columns on mapped rows are exclusions.

    An unmapped numeric on the same row stays unresolved so a missing charge
    cannot hide behind the service-type or station name.
    """

    db_path = tmp_path / "rpc_labels.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count, template_id
        ) VALUES (1, 'erpc', 'local', 'fixture.xlsx', 'hash', '2026-08-30T00:00:00Z',
                  1.0, 0, 'native', 100, 'rpc_weekly_dsm_v2022_entity_charges')
        """
    )
    cells = (
        (1, 1, 1, 1, 1, "Entity"),
        (1, 1, 1, 1, 2, "Service Type"),
        (1, 1, 1, 1, 3, "Payable (Rs)"),
        (1, 1, 1, 2, 1, "West Bengal"),
        (1, 1, 1, 2, 2, "SRAS"),
        (1, 1, 1, 2, 3, "1200"),
        (1, 1, 1, 2, 4, "88"),
        (1, 1, 2, 1, 1, "Beneficiary"),
        (1, 1, 2, 1, 2, "Station"),
        (1, 1, 2, 2, 1, "Bihar"),
        (1, 1, 2, 2, 2, "Farakka STPS"),
        (1, 1, 2, 2, 3, "450"),
    )
    conn.executemany(
        """
        INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no, cell_text,
            extraction_method, extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'rpc_table', '2026-08-30T00:00:00Z')
        """,
        cells,
    )
    payable_id = conn.execute(
        "SELECT id FROM psp_raw_cell WHERE cell_text = '1200'"
    ).fetchone()[0]
    allocation_id = conn.execute(
        "SELECT id FROM psp_raw_cell WHERE cell_text = '450'"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn,
            RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES
            (1, 'FactRPCWeeklyDSMAncillary', 'entity:wb', 'PayableRs',
             ?, 'rpc_header', 1.0, '2026-08-30T00:00:00Z'),
            (1, 'FactRPCMonthlyREAAllocation', 'entity:bihar', 'AllocatedCapacityMW',
             ?, 'rpc_header', 1.0, '2026-08-30T00:00:00Z')
        """,
        (payable_id, allocation_id),
    )
    conn.commit()
    conn.close()

    report = generate_raw_cell_coverage_report(db_path, rldc="erpc")
    unresolved = {
        example["value"]
        for group in report["unresolved_groups"]
        for example in group["examples"]
    }

    assert "Entity" not in unresolved
    assert "Service Type" not in unresolved
    assert "SRAS" not in unresolved
    assert "Farakka STPS" not in unresolved
    assert unresolved == {"88"}
    assert report["unresolved_cell_count"] == 1
