"""Tests for exact curated SQLite to Timescale cell-lineage projection."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.storage.sqlite_curated_export import (
    export_observation_lineage,
    export_srldc_daily_observations,
)


def test_exported_srldc_metric_retains_one_exact_raw_cell() -> None:
    """A promoted regional measure keeps its original PDF grid coordinate."""

    conn = sqlite3.connect(":memory:")
    ensure_sqlite_schema(conn)
    conn.executescript(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count
        ) VALUES (
            1, 'srldc', 'https://example.test/report.pdf', 'report.pdf',
            'report-content-hash', '2026-08-25T00:00:00+00:00', 1.0, 0,
            'native', 100
        );
        INSERT INTO DimDates(DateID, ActualDate) VALUES (1, '2026-08-25');
        INSERT INTO FactSRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, DayEnergyMetMU
        ) VALUES (1, 1, 1, 950.5);
        INSERT INTO psp_raw_cell(
            id, report_document_id, page_no, table_no, row_no, col_no,
            cell_text, extraction_method, extracted_at
        ) VALUES (44, 1, 1, 2, 3, 4, '950.5', 'pdfplumber', '2026-08-25T00:00:00+00:00');
        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey,
            DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES (
            1, 'FactSRLDCRegionalDaily', 'report=1;date=1;region=1',
            'DayEnergyMetMU', 44, 'pdfplumber', 1.0, '2026-08-25T00:00:00+00:00'
        );
        """
    )
    conn.commit()

    observations = export_srldc_daily_observations(
        conn,
        ingested_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    target = [
        observation
        for observation in observations
        if observation.metric_name.endswith(".DayEnergyMetMU")
    ]
    assert len(target) == 1
    assert target[0].destination_key == "report=1;date=1;region=1"

    lineage = export_observation_lineage(conn, target)

    assert len(lineage) == 1
    assert lineage[0].timeseries_uuid == target[0].timeseries_uuid
    assert lineage[0].raw_kind == "cell"
    assert lineage[0].raw_item_id == 44
    assert (lineage[0].page_no, lineage[0].table_no) == (1, 2)
    assert (lineage[0].row_no, lineage[0].col_no) == (3, 4)
