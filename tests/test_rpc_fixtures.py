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


def test_write_canonical_rpc_fixtures_replaces_stale_workbooks(tmp_path: Path) -> None:
    """Only the five-RPC week-35 DSM set and ERPC REA remain after rewrite."""

    from psp_pipeline.quality.rpc_fixtures import (
        CANONICAL_RPC_FIXTURES,
        ensure_canonical_rpc_fixtures,
    )

    fixture_dir = tmp_path / "rpc"
    fixture_dir.mkdir()
    stale = fixture_dir / "NRPC_DSM_Account_Week_36_of_2026.xlsx"
    stale.write_bytes(b"stale")
    written = write_canonical_rpc_fixtures(fixture_dir)
    names = {path.name for path in written}
    assert names == {str(spec["filename"]) for spec in CANONICAL_RPC_FIXTURES}
    assert not stale.exists()
    assert {path.name for path in fixture_dir.glob("*.xlsx")} == names

    marker = fixture_dir / "ERPC_DSM_Account_Week_35_of_2026.xlsx"
    before = marker.read_bytes()
    ensure_canonical_rpc_fixtures(fixture_dir)
    assert marker.read_bytes() == before


def test_canonical_rpc_fixtures_promote_settlement_facts(tmp_path: Path) -> None:
    """DSM and REA workbooks leave discovery/staging and land in FactRPC* tables."""

    fixture_dir = tmp_path / "rpc"
    write_canonical_rpc_fixtures(fixture_dir)
    db_path = tmp_path / "rpc.sqlite"
    result = ingest_rpc_fixture_reports(db_path, fixture_dir=fixture_dir)

    assert result["reports_persisted"] == 6
    assert result["rpc_fact_row_count"] >= 8
    assert result["fact_table_counts"]["FactRPCWeeklyDSMEntity"] >= 5
    assert result["fact_table_counts"]["FactRPCWeeklyDSMAncillary"] >= 1
    assert result["fact_table_counts"]["FactRPCMonthlyREAStation"] >= 1
    assert result["fact_table_counts"]["FactRPCMonthlyREAAllocation"] >= 1

    coverage = evaluate_coverage_manifest(db_path, profile_name="corpus")
    verdict = assess_coverage_completeness(
        coverage["corpus"],
        db_path=str(db_path),
        fact_table_counts=result["fact_table_counts"],
    )
    assert verdict.rpc_status == "full"
    assert verdict.rpc_fact_row_count >= 8
    assert verdict.full_psp_and_rpc_coverage is False
    assert verdict.full_cell_coverage is True
    assert set(verdict.accounted_cell_pct_by_source) >= {
        "erpc",
        "nrpc",
        "srpc",
        "wrpc",
        "nerpc",
    }
    assert all(
        pct >= 100.0
        for source, pct in verdict.accounted_cell_pct_by_source.items()
        if source in {"erpc", "nrpc", "srpc", "wrpc", "nerpc"}
    )


def test_coverage_stage_openlineage_facet_shows_demonstrated_rpc(tmp_path: Path) -> None:
    """DAG coverage XCom stamps RPC full cell coverage into the OpenLineage dataset facet."""

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
    assert facet["rpc_status"] == "full"
    assert facet["rpc_fact_row_count"] >= 8
    assert facet["full_psp_and_rpc_coverage"] is False
    assert assertions["rpc_status"]["actual"] == "full"
    assert assertions["rpc_status"]["success"] is True
    assert set(facet["accounted_cell_pct_by_source"]) >= {"erpc", "nrpc", "srpc", "wrpc", "nerpc"}
    assert all(
        pct >= 100.0
        for source, pct in facet["accounted_cell_pct_by_source"].items()
        if source in {"erpc", "nrpc", "srpc", "wrpc", "nerpc"}
    )
