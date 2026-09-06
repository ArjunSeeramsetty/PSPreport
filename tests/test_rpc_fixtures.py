"""Live RPC fixture workbooks promote FactRPC* rows through persist_local_rpc_report."""

from __future__ import annotations

from pathlib import Path

from psp_pipeline.pipelines.stages import evaluate_curated_coverage_contract
from psp_pipeline.quality.coverage_completeness import assess_coverage_completeness
from psp_pipeline.quality.coverage_contract import evaluate_coverage_manifest
from psp_pipeline.quality.rpc_fixtures import (
    ingest_rpc_fixture_reports,
    write_canonical_rpc_fixtures,
)


def test_canonical_rpc_fixtures_promote_settlement_facts(tmp_path: Path) -> None:
    """DSM and REA workbooks leave discovery/staging and land in FactRPC* tables."""

    fixture_dir = tmp_path / "rpc"
    write_canonical_rpc_fixtures(fixture_dir)
    db_path = tmp_path / "rpc.sqlite"
    result = ingest_rpc_fixture_reports(db_path, fixture_dir=fixture_dir)

    assert result["reports_persisted"] == 3
    assert result["rpc_fact_row_count"] >= 3
    assert result["fact_table_counts"]["FactRPCWeeklyDSMEntity"] >= 2
    assert result["fact_table_counts"]["FactRPCMonthlyREAStation"] >= 1

    coverage = evaluate_coverage_manifest(db_path, profile_name="corpus")
    verdict = assess_coverage_completeness(
        coverage["corpus"],
        db_path=str(db_path),
        fact_table_counts=result["fact_table_counts"],
    )
    assert verdict.rpc_status == "floor_pass"
    assert verdict.rpc_fact_row_count >= 3
    assert verdict.full_psp_and_rpc_coverage is False
    assert "erpc" in verdict.accounted_cell_pct_by_source
    assert "nrpc" in verdict.accounted_cell_pct_by_source


def test_coverage_stage_openlineage_facet_shows_demonstrated_rpc(tmp_path: Path) -> None:
    """DAG coverage XCom stamps RPC floor-pass into the OpenLineage dataset facet."""

    fixture_dir = tmp_path / "rpc"
    write_canonical_rpc_fixtures(fixture_dir)
    db_path = tmp_path / "rpc-lineage.sqlite"
    ingest_rpc_fixture_reports(db_path, fixture_dir=fixture_dir)

    payload = evaluate_curated_coverage_contract(
        db_path,
        profile_name="corpus",
        fail_hard=False,
    )
    facet = payload["openlineage"]["outputs"][0]["facets"]["coverageCompleteness"]
    assertions = {
        item["assertion"]: item
        for item in payload["openlineage"]["outputs"][0]["facets"]["dataQualityAssertions"][
            "assertions"
        ]
    }
    assert facet["rpc_status"] == "floor_pass"
    assert facet["rpc_fact_row_count"] >= 3
    assert facet["full_psp_and_rpc_coverage"] is False
    assert assertions["rpc_status"]["success"] is False
    assert assertions["rpc_status"]["actual"] == "floor_pass"
    assert "erpc" in facet["accounted_cell_pct_by_source"]
