"""Tests for OpenLineage column-lineage emission from curated_field_lineage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from psp_pipeline.lineage.openlineage import build_column_lineage_event
from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema


def test_column_lineage_facet_points_at_the_raw_cell_coordinate(
    tmp_path: Path,
) -> None:
    """Auditors can trace a Timescale column back to a pdfplumber cell."""

    db_path = tmp_path / "lineage.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.executescript(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count
        ) VALUES (
            1, 'srldc', 'https://example.test/SRLDC_PSP', '2024-04-15.pdf',
            'hash', '2024-04-16T00:00:00+00:00', 1.0, 0, 'native', 100
        );
        INSERT INTO psp_raw_cell(
            id, report_document_id, page_no, table_no, row_no, col_no,
            cell_text, extraction_method, extracted_at
        ) VALUES (
            44, 1, 1, 1, 3, 1, '950.5', 'pdfplumber', '2024-04-16T00:00:00+00:00'
        );
        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey,
            DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES (
            1, 'FactSRLDCRegionalDaily', 'report=1;date=1;region=1',
            'EveningPeakDemandMetMW', 44, 'pdfplumber', 1.0, '2024-04-16T00:00:00+00:00'
        );
        """
    )
    conn.commit()
    conn.close()

    event = build_column_lineage_event(
        db_path,
        run_id="run-1",
        event_time=datetime(2024, 4, 16, tzinfo=timezone.utc),
    )
    fields = event["outputs"][0]["facets"]["columnLineage"]["fields"]
    demand = fields["FactSRLDCRegionalDaily.EveningPeakDemandMetMW"]
    source = demand["inputFields"][0]
    assert source["namespace"] == "psp://downloads/srldc"
    assert source["name"] == "2024-04-15.pdf"
    assert source["field"] == "p1_t1_r3_c1"
    assert event["run"]["runId"] == "run-1"


def test_text_item_lineage_includes_bounding_box(tmp_path: Path) -> None:
    """LiteParse spatial items expose geometric boxes in the OpenLineage facet."""

    db_path = tmp_path / "spatial.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.executescript(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count
        ) VALUES (
            1, 'nerldc', 'https://example.test/NERLDC', 'nerldc.pdf',
            'hash', '2024-04-16T00:00:00+00:00', 1.0, 0, 'native', 100
        );
        INSERT INTO psp_raw_text_item(
            id, report_document_id, page_no, item_no, item_text,
            x, y, width, height, confidence, extraction_method, extracted_at
        ) VALUES (
            9, 1, 3, 1, '120.5', 45.2, 120.5, 20.0, 8.0, 1.0, 'liteparse',
            '2024-04-16T00:00:00+00:00'
        );
        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey,
            DestinationColumn, RawTextItemID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES (
            1, 'FactNERLDCRegionalDaily', 'report=1', 'DayEnergyMetMU',
            9, 'liteparse', 1.0, '2024-04-16T00:00:00+00:00'
        );
        """
    )
    conn.commit()
    conn.close()

    event = build_column_lineage_event(db_path, run_id="run-2")
    fields = event["outputs"][0]["facets"]["columnLineage"]["fields"]
    box = fields["FactNERLDCRegionalDaily.DayEnergyMetMU"]["inputFields"][0]["boundingBox"]
    assert box["x0"] == 45.2
    assert box["y0"] == 120.5
    assert box["page_no"] == 3
