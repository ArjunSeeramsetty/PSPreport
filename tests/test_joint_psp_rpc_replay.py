"""Joint six-source PSP plus RPC fixture completeness and OpenLineage facets."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import ensure_sqlite_schema
from psp_pipeline.quality.coverage_completeness import PSP_DAILY_SOURCES, RPC_SOURCES
from psp_pipeline.quality.joint_psp_rpc_replay import evaluate_joint_psp_rpc_replay
from psp_pipeline.quality.rpc_fixtures import write_canonical_rpc_fixtures


def _seed_psp_document(db_path: Path, source: str, report_id: int) -> None:
    """Insert one fully-accounted raw cell so a PSP source document is present."""

    conn = sqlite3.connect(db_path)
    ensure_sqlite_schema(conn)
    conn.execute(
        """
        INSERT INTO psp_report_document(
            id, rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count, template_id,
            report_date
        ) VALUES (?, ?, 'fixture', ?, 'hash', '2026-01-01T00:00:00Z',
                  1.0, 0, 'native', 1, 'synthetic', '2026-01-01')
        """,
        (report_id, source, f"{source}.pdf"),
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


def _seed_six_psp_documents(db_path: Path) -> None:
    """Persist one document for each daily PSP source."""

    for report_id, source in enumerate(PSP_DAILY_SOURCES, start=1):
        _seed_psp_document(db_path, source, report_id)


def _assertions(payload: dict) -> dict[str, dict]:
    """Index OpenLineage data-quality assertions by assertion name."""

    return {
        item["assertion"]: item
        for item in payload["openlineage"]["outputs"][0]["facets"][
            "dataQualityAssertions"
        ]["assertions"]
    }


def test_joint_psp_rpc_replay_shows_six_psp_docs_and_rpc_floor_pass(
    tmp_path: Path,
) -> None:
    """One SQLite replay can carry six PSP documents and five-RPC fixtures together."""

    db_path = tmp_path / "joint.sqlite"
    _seed_six_psp_documents(db_path)
    fixture_dir = tmp_path / "rpc"
    write_canonical_rpc_fixtures(fixture_dir)

    payload = evaluate_joint_psp_rpc_replay(
        db_path,
        ingest_rpc_fixtures=True,
        rpc_fixture_dir=fixture_dir,
        run_id="joint-test",
    )

    completeness = payload["coverage_completeness"]
    assert completeness["all_psp_documents_present"] is True
    assert set(completeness["psp_documents_present"]) == set(PSP_DAILY_SOURCES)
    assert completeness["rpc_status"] in {"floor_pass", "full"}
    assert completeness["rpc_fact_row_count"] >= 8
    assert completeness["full_psp_and_rpc_coverage"] is False
    assert completeness["full_cell_coverage"] is False
    assert completeness["energy_reconciliation_certified"] is False
    assert set(completeness["accounted_cell_pct_by_source"]) >= set(RPC_SOURCES)

    facet = payload["openlineage"]["outputs"][0]["facets"]["coverageCompleteness"]
    assertions = _assertions(payload)
    assert facet["all_psp_documents_present"] is True
    assert facet["rpc_status"] in {"floor_pass", "full"}
    assert facet["full_psp_and_rpc_coverage"] is False
    assert assertions["all_psp_documents_present"]["success"] is True
    assert assertions["rpc_status"]["actual"] in {"floor_pass", "full"}
    assert assertions["rpc_status"]["success"] is (
        assertions["rpc_status"]["actual"] == "full"
    )
    assert assertions["energy_reconciliation_certified"]["success"] is False
    assert payload["rpc_fixtures"]["reports_persisted"] == 6
    assert payload["openlineage"]["run"]["runId"] == "joint-test"
    assert payload["openlineage"]["job"]["name"] == "psp.joint_psp_rpc_replay"


def test_joint_replay_without_rpc_fixtures_stays_not_demonstrated(tmp_path: Path) -> None:
    """Six PSP documents alone still do not demonstrate RPC settlement coverage."""

    db_path = tmp_path / "psp-only.sqlite"
    _seed_six_psp_documents(db_path)

    payload = evaluate_joint_psp_rpc_replay(db_path, ingest_rpc_fixtures=False)

    completeness = payload["coverage_completeness"]
    assert completeness["all_psp_documents_present"] is True
    assert completeness["rpc_status"] == "not_demonstrated"
    assert completeness["rpc_fact_row_count"] == 0
    assert completeness["full_psp_and_rpc_coverage"] is False
    assert payload["rpc_fixtures"] is None
    facet = payload["openlineage"]["outputs"][0]["facets"]["coverageCompleteness"]
    assert facet["rpc_status"] == "not_demonstrated"
    assert facet["all_psp_documents_present"] is True
    assert facet["full_psp_and_rpc_coverage"] is False


def test_rpc_floor_pass_does_not_hide_a_missing_psp_document(tmp_path: Path) -> None:
    """RPC fixtures cannot stand in for an absent daily PSP source document."""

    db_path = tmp_path / "missing-psp.sqlite"
    for report_id, source in enumerate(PSP_DAILY_SOURCES[:-1], start=1):
        _seed_psp_document(db_path, source, report_id)
    fixture_dir = tmp_path / "rpc"
    write_canonical_rpc_fixtures(fixture_dir)

    payload = evaluate_joint_psp_rpc_replay(
        db_path,
        ingest_rpc_fixtures=True,
        rpc_fixture_dir=fixture_dir,
        require_sources=PSP_DAILY_SOURCES,
    )

    completeness = payload["coverage_completeness"]
    assert completeness["all_psp_documents_present"] is False
    assert completeness["rpc_status"] in {"floor_pass", "full"}
    assert completeness["full_psp_and_rpc_coverage"] is False
    assertions = _assertions(payload)
    assert assertions["all_psp_documents_present"]["success"] is False
    assert assertions["rpc_status"]["success"] is False


_ATTEMPT2_PDFS = (
    Path("downloads/ERLDC_PSP/Power Supply Position Report_01012026.pdf"),
    Path("downloads/NERLDC_PSP/NER-PSP-REPORT-DATED-01-01-2026.pdf"),
    Path("downloads/NRLDC_PSP/tu3jPAbbZo4XMsihlvNG-w-daily010126.pdf"),
    Path("downloads/SRLDC_PSP/01-01-2026-psp.pdf"),
    Path("downloads/WRLDC_PSP/WRLDC_PSP_Report_01-01-2026.pdf"),
    Path("downloads/NLDC_PSP/01.01.26_NLDC_PSP_872.pdf"),
)


@pytest.mark.skipif(
    not all(path.exists() for path in _ATTEMPT2_PDFS),
    reason="2026-01-01 six-source PSP PDFs are not present in downloads/",
)
def test_six_source_replay_stamps_joint_openlineage_with_rpc_fixtures(
    tmp_path: Path,
) -> None:
    """The approved 2026-01-01 PDF replay plus RPC fixtures speak with one facet."""

    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "run_six_source_replay.py"
    spec = importlib.util.spec_from_file_location("run_six_source_replay", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    summary = module.run_replay_for_date(
        "2026-01-01",
        tmp_path / "six.sqlite",
        tmp_path / "six.json",
        load_timescale=False,
        sync_neo4j=False,
        ingest_rpc_fixtures=True,
    )
    completeness = summary["coverage_completeness"]
    facet = summary["openlineage"]["outputs"][0]["facets"]["coverageCompleteness"]
    assert completeness["all_psp_documents_present"] is True
    assert completeness["rpc_status"] in {"floor_pass", "full"}
    assert completeness["full_psp_and_rpc_coverage"] is False
    assert completeness["energy_reconciliation_certified"] is True
    assert facet["all_psp_documents_present"] is True
    assert facet["rpc_status"] == completeness["rpc_status"]
    assert facet["full_psp_and_rpc_coverage"] is False
    assert facet["energy_reconciliation_certified"] is True
    assert summary["rpc_fixtures"]["reports_persisted"] == 6
    assert summary["openlineage"]["job"]["name"] == "psp.six_source_replay"
