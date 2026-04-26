from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated
from psp_pipeline.schema_design.service import persist_report_schema_proposals


def test_unrecognized_srldc_template_creates_proposal_without_fact_rows() -> None:
    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count,
            report_date, report_family, template_id, template_version,
            template_confidence, semantic_pass_required
        ) VALUES (
            'srldc', 'local://legacy.pdf', 'legacy.pdf', 'legacy-hash', ?,
            0, 0, 'native text', 1000, '2025-06-30', 'psp',
            'srldc_daily_psp_v2026_05', '2026.05', 0, 1
        )
        """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    report_id = conn.execute("SELECT id FROM psp_report_document").fetchone()[0]

    promote_report_to_curated(conn, report_id)

    proposal = conn.execute(
        "SELECT ProposalType, Status FROM schema_proposal WHERE ReportDocumentID = ?",
        (report_id,),
    ).fetchone()
    assert proposal == ("new_template", "pending")
    assert conn.execute("SELECT COUNT(*) FROM FactSRLDCRegionalDaily").fetchone()[0] == 0


def test_two_report_versions_can_coexist_for_same_valid_date() -> None:
    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    date_id = conn.execute(
        """
        INSERT INTO DimDates(ActualDate) VALUES ('2026-05-27') RETURNING DateID
        """
    ).fetchone()[0]
    region_id = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = 'Southern Region'"
    ).fetchone()[0]
    for report_id, value in ((101, 55000.0), (102, 55100.0)):
        conn.execute(
            """
            INSERT INTO FactSRLDCRegionalDaily(
                ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW
            ) VALUES (?, ?, ?, ?)
            """,
            (report_id, date_id, region_id, value),
        )

    values = conn.execute(
        """
        SELECT ReportDocumentID, EveningPeakDemandMetMW
        FROM FactSRLDCRegionalDaily ORDER BY ReportDocumentID
        """
    ).fetchall()
    assert values == [(101, 55000.0), (102, 55100.0)]


def test_stored_raw_cells_generate_approval_gated_proposals() -> None:
    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count
        ) VALUES ('srldc', 'local://x', 'x.pdf', 'x-hash', ?, 0, 0, 'native', 100)
        """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    report_id = conn.execute("SELECT id FROM psp_report_document").fetchone()[0]
    cells = (
        (1, 1, 1, 1, "State"),
        (1, 1, 1, 2, "Demand (MW)"),
        (1, 1, 2, 1, "Name"),
        (1, 1, 2, 2, "Value"),
        (1, 1, 3, 1, "Karnataka"),
        (1, 1, 3, 2, "12345"),
    )
    conn.executemany(
        """
        INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no,
            cell_text, extraction_method, extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pdfplumber', ?)
        """,
        ((report_id, *cell, datetime.now(timezone.utc).isoformat()) for cell in cells),
    )

    inserted = persist_report_schema_proposals(conn, report_id)

    assert inserted > 0
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_proposal WHERE Status = 'pending'"
    ).fetchone()[0] == inserted
