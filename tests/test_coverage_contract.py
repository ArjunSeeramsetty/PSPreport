"""Tests for the explicit raw-cell coverage acceptance contract."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.quality.coverage_contract import (
    assert_coverage_floors,
    load_coverage_manifest,
)


_MANIFEST = Path(__file__).parent / "fixtures" / "manifest.json"


def _seed_mapped_cell(db_path: Path, source: str) -> None:
    """Build a minimal fully-accounted raw-cell fixture for one source."""

    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count, template_id
        ) VALUES (1, ?, 'fixture', 'synthetic.pdf', 'hash', '2026-01-01T00:00:00Z',
                  1.0, 0, 'native', 1, 'synthetic')
        """,
        (source,),
    )
    raw_cell_id = conn.execute(
        """
        INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no, cell_text,
            extraction_method, extracted_at
        ) VALUES (1, 1, 1, 1, 2, '42', 'fixture', '2026-01-01T00:00:00Z')
        RETURNING id
        """
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn,
            RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES (1, 'FactSynthetic', 'report=1', 'Value', ?, 'fixture', 1.0,
                  '2026-01-01T00:00:00Z')
        """,
        (raw_cell_id,),
    )
    conn.commit()
    conn.close()


def test_manifest_declares_required_synthetic_and_optional_corpus_profiles() -> None:
    """CI configuration makes its required evidence tier explicit."""

    manifest = load_coverage_manifest(_MANIFEST)
    assert manifest["profiles"]["synthetic"]["required"] is True
    assert manifest["profiles"]["corpus"]["required"] is False


def test_coverage_floor_gate_rejects_a_source_below_its_contract(tmp_path: Path) -> None:
    """A synthetic fixture fails immediately when mapped lineage regresses."""

    db_path = tmp_path / "coverage.sqlite"
    _seed_mapped_cell(db_path, "srldc")

    assert assert_coverage_floors(db_path, {"srldc": 100.0}) == {"srldc": 100.0}
    with pytest.raises(AssertionError, match="srldc"):
        assert_coverage_floors(db_path, {"srldc": 100.01})
