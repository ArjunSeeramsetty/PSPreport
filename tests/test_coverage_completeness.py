"""Tests that corpus floor-pass is not treated as full PSP and RPC coverage."""

from __future__ import annotations

from pathlib import Path

import sqlite3

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.pipelines.stages import evaluate_curated_coverage_contract
from psp_pipeline.quality.coverage_completeness import (
    RPC_FACT_TABLES,
    RPC_SOURCES,
    assess_coverage_completeness,
)
from psp_pipeline.quality.coverage_contract import CoverageProfileResult, load_coverage_manifest


_MANIFEST = Path(__file__).parent / "fixtures" / "manifest.json"

# 2026-01-01 six-source replay attempt2 accounted-cell percentages.
_ATTEMPT2_ACCOUNTED = {
    "srldc": 96.29,
    "nrldc": 85.50,
    "wrldc": 86.05,
    "erldc": 61.71,
    "nerldc": 59.27,
    "grid_india_national": 84.33,
}
_CORPUS_FLOORS = {
    "srldc": 95.0,
    "nrldc": 80.0,
    "wrldc": 69.0,
    "erldc": 54.0,
    "nerldc": 59.0,
    "grid_india_national": 84.0,
}


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


def _corpus_profile(actual: dict[str, float] | None = None) -> CoverageProfileResult:
    accounted = actual or dict(_ATTEMPT2_ACCOUNTED)
    return CoverageProfileResult(
        profile_name="corpus",
        required=False,
        floors=dict(_CORPUS_FLOORS),
        actual=accounted,
        missing_sources=(),
        failures=(),
    )


def test_manifest_states_that_corpus_floors_are_not_full_coverage() -> None:
    """The optional corpus profile must not be readable as a 100% contract."""

    corpus = load_coverage_manifest(_MANIFEST)["profiles"]["corpus"]
    assert corpus["required"] is False
    description = corpus["description"].lower()
    assert "100%" in description or "not 100%" in description
    assert "rpc" in description


def test_attempt2_replay_passes_floors_but_is_not_full_psp_and_rpc_coverage() -> None:
    """The 2026-01-01 six-source replay is document-complete, not data-complete."""

    profile = _corpus_profile()
    assert profile.passed is True
    assert profile.full_cell_coverage is False

    verdict = assess_coverage_completeness(
        profile,
        fact_table_counts={table: 0 for table in RPC_FACT_TABLES},
        balance={
            "nldc_comparisons": {
                "day_energy_met_mu": {
                    "within_tolerance": False,
                    "variance_pct": -10.24,
                }
            }
        },
        present_documents=_ATTEMPT2_ACCOUNTED,
    )

    assert verdict.floor_pass is True
    assert verdict.all_psp_documents_present is True
    assert verdict.full_cell_coverage is False
    assert verdict.rpc_status == "not_demonstrated"
    assert verdict.rpc_fact_row_count == 0
    assert verdict.energy_reconciliation_certified is False
    assert "variance_pct=-10.24" in verdict.energy_reconciliation_status
    assert verdict.full_psp_and_rpc_coverage is False
    assert verdict.sources_below_full_cell_coverage["erldc"] == 61.71
    assert verdict.sources_below_full_cell_coverage["nerldc"] == 59.27
    notes = " ".join(verdict.notes)
    assert "not a 100% requirement" in notes
    assert "FactRPC*" in notes
    assert "Energy reconciliation is uncertified" in notes


def test_full_psp_and_rpc_coverage_requires_cells_rpc_facts_and_all_documents() -> None:
    """A certified PSP+RPC corpus is 100% cells plus demonstrated RPC facts."""

    accounted = {
        **{source: 100.0 for source in _ATTEMPT2_ACCOUNTED},
        **{source: 100.0 for source in RPC_SOURCES},
    }
    verdict = assess_coverage_completeness(
        CoverageProfileResult(
            profile_name="synthetic",
            required=True,
            floors={source: 100.0 for source in accounted},
            actual=accounted,
            missing_sources=(),
            failures=(),
        ),
        fact_table_counts={table: 4 for table in RPC_FACT_TABLES},
        balance={
            "nldc_comparisons": {
                "day_energy_met_mu": {"within_tolerance": True, "variance_pct": 0.1}
            }
        },
        present_documents=_ATTEMPT2_ACCOUNTED,
    )

    assert verdict.full_cell_coverage is True
    assert verdict.rpc_status == "full"
    assert verdict.energy_reconciliation_certified is True
    assert verdict.full_psp_and_rpc_coverage is True


def test_energy_certification_is_independent_of_psp_rpc_coverage() -> None:
    """A stale -10.24% energy gap cannot certify the pipeline even at 100% cells."""

    accounted = {source: 100.0 for source in _ATTEMPT2_ACCOUNTED}
    verdict = assess_coverage_completeness(
        CoverageProfileResult(
            profile_name="corpus",
            required=False,
            floors=dict(_CORPUS_FLOORS),
            actual=accounted,
            missing_sources=(),
            failures=(),
        ),
        fact_table_counts={table: 1 for table in RPC_FACT_TABLES},
        balance={
            "nldc_comparisons": {
                "day_energy_met_mu": {
                    "within_tolerance": False,
                    "variance_pct": -10.24,
                }
            }
        },
        present_documents=_ATTEMPT2_ACCOUNTED,
    )

    assert verdict.full_cell_coverage is True
    assert verdict.rpc_status == "floor_pass"
    assert verdict.full_psp_and_rpc_coverage is False
    assert verdict.energy_reconciliation_certified is False


def test_curated_coverage_stage_floor_pass_is_not_full_report_coverage(
    tmp_path: Path,
) -> None:
    """DAG XCom can pass corpus floors while completeness stays incomplete."""

    db_path = tmp_path / "daily.sqlite"
    _seed_mapped_cell(db_path, "srldc")

    payload = evaluate_curated_coverage_contract(
        db_path,
        manifest_path=_MANIFEST,
        profile_name="corpus",
        fail_hard=False,
    )

    assert payload["passed"] is True
    assert payload["profiles"]["corpus"]["passed"] is True
    assert payload["profiles"]["corpus"]["full_cell_coverage"] is True
    assert payload["full_psp_and_rpc_coverage"] is False
    completeness = payload["coverage_completeness"]
    assert completeness["floor_pass"] is True
    assert completeness["all_psp_documents_present"] is False
    assert completeness["rpc_status"] == "not_demonstrated"
    assert completeness["energy_reconciliation_certified"] is False
