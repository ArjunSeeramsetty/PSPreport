"""Tests for the explicit raw-cell coverage acceptance contract."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.pipelines.stages import evaluate_curated_coverage_contract
from psp_pipeline.quality.coverage_contract import (
    assert_coverage_floors,
    enforce_coverage_manifest,
    evaluate_coverage_floors,
    load_coverage_manifest,
)


_MANIFEST = Path(__file__).parent / "fixtures" / "manifest.json"


def _seed_mapped_cell(db_path: Path, source: str, report_id: int = 1) -> None:
    """Build a minimal fully-accounted raw-cell fixture for one source."""

    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count, template_id
        ) VALUES (?, ?, 'fixture', 'synthetic.pdf', 'hash', '2026-01-01T00:00:00Z',
                  1.0, 0, 'native', 1, 'synthetic')
        """,
        (report_id, source),
    )
    raw_cell_id = conn.execute(
        """
        INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no, cell_text,
            extraction_method, extracted_at
        ) VALUES (?, 1, 1, 1, 2, '42', 'fixture', '2026-01-01T00:00:00Z')
        RETURNING id
        """,
        (report_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO curated_field_lineage(
            ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn,
            RawCellID, ExtractionMethod, Confidence, CreatedAt
        ) VALUES (?, 'FactSynthetic', ?, 'Value', ?, 'fixture', 1.0,
                  '2026-01-01T00:00:00Z')
        """,
        (report_id, f"report={report_id}", raw_cell_id),
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


def test_required_synthetic_profile_gates_ci_without_corpus_pdfs(tmp_path: Path) -> None:
    """CI can enforce 100% synthetic floors while leaving corpus optional."""

    db_path = tmp_path / "synthetic.sqlite"
    _seed_mapped_cell(db_path, "srldc")

    results = enforce_coverage_manifest(
        db_path,
        _MANIFEST,
        only_required=True,
    )

    assert set(results) == {"synthetic"}
    assert results["synthetic"].passed
    assert results["synthetic"].actual["srldc"] == 100.0


def test_coverage_evaluation_fails_closed_when_a_required_source_is_absent(
    tmp_path: Path,
) -> None:
    """Full-corpus replay cannot treat a vanished source as a passing skip."""

    db_path = tmp_path / "missing.sqlite"
    _seed_mapped_cell(db_path, "srldc")

    result = evaluate_coverage_floors(
        db_path,
        {"srldc": 100.0, "erldc": 54.0},
        require_sources=["srldc", "erldc"],
    )

    assert result.actual == {"srldc": 100.0}
    assert result.missing_sources == ("erldc",)
    assert result.passed is False
    with pytest.raises(AssertionError, match="missing sources: erldc"):
        enforce_coverage_manifest(
            db_path,
            _MANIFEST,
            profile_name="corpus",
            require_sources=["erldc"],
        )


def test_curated_coverage_stage_is_fail_soft_for_daily_orchestration(
    tmp_path: Path,
) -> None:
    """The DAG records a corpus miss without raising out of the stage."""

    db_path = tmp_path / "daily.sqlite"
    _seed_mapped_cell(db_path, "srldc")

    payload = evaluate_curated_coverage_contract(
        db_path,
        manifest_path=_MANIFEST,
        profile_name="corpus",
        require_sources=["nrldc"],
        fail_hard=False,
    )

    assert payload["passed"] is False
    assert tuple(payload["profiles"]["corpus"]["missing_sources"]) == ("nrldc",)


def test_synthetic_profile_enforces_lineage_and_null_rate_floors(tmp_path: Path) -> None:
    """CI coverage is not just row presence: lineage rate and null rate are gated."""

    db_path = tmp_path / "lineage.sqlite"
    _seed_mapped_cell(db_path, "srldc")

    results = enforce_coverage_manifest(db_path, _MANIFEST, only_required=True)
    assert results["synthetic"].actual["srldc.lineage_rate_pct"] == 100.0
    assert results["synthetic"].actual["srldc.null_rate_pct"] == 0.0
    assert results["synthetic"].actual["srldc/synthetic.lineage_rate_pct"] == 100.0

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO psp_raw_cell(
            report_document_id, page_no, table_no, row_no, col_no, cell_text,
            extraction_method, extracted_at
        ) VALUES (1, 1, 1, 2, 2, 'orphan', 'fixture', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    result = evaluate_coverage_floors(
        db_path,
        {"srldc": 0.0},
        lineage_rate_floors={"srldc": 100.0},
        null_rate_ceilings={"srldc": 0.0},
    )
    assert result.passed is False
    assert any("lineage_rate_pct" in item for item in result.failures)
