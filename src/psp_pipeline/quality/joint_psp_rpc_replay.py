"""Evaluate six daily PSP documents plus optional RPC fixtures as one replay.

PSP and RPC can share a SQLite database without sharing a calendar date. This
module stamps one OpenLineage coverage-completeness payload so a floor pass on
either family cannot be read as ``full_psp_and_rpc_coverage``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from psp_pipeline.lineage.openlineage import build_column_lineage_event
from psp_pipeline.quality.coverage_completeness import (
    PSP_DAILY_SOURCES,
    assess_coverage_completeness,
)
from psp_pipeline.quality.coverage_contract import (
    CoverageProfileResult,
    default_coverage_manifest_path,
    evaluate_coverage_manifest,
)


def build_replay_lineage_summary(
    sqlite_db_path: Path | str,
    coverage: Mapping[str, CoverageProfileResult],
    *,
    profile_name: str = "corpus",
    balance: Mapping[str, Any] | None = None,
    fact_table_counts: Mapping[str, int] | None = None,
    run_id: str | None = None,
    job_name: str = "psp.joint_psp_rpc_replay",
) -> dict[str, Any]:
    """Attach completeness and OpenLineage facets for one already-evaluated replay."""

    db_path = Path(sqlite_db_path)
    selected = coverage[profile_name]
    completeness = assess_coverage_completeness(
        selected,
        db_path=str(db_path),
        fact_table_counts=fact_table_counts,
        balance=balance,
    )
    lineage = build_column_lineage_event(
        db_path,
        run_id=run_id or f"joint-psp-rpc:{db_path.name}",
        job_name=job_name,
        completeness=completeness,
        event_time=datetime.now(timezone.utc),
    )
    return {
        "coverage_completeness": completeness.as_dict(),
        "full_psp_and_rpc_coverage": completeness.full_psp_and_rpc_coverage,
        "openlineage": lineage,
    }


def evaluate_joint_psp_rpc_replay(
    sqlite_db_path: Path | str,
    *,
    ingest_rpc_fixtures: bool = False,
    rpc_fixture_dir: Path | str | None = None,
    profile_name: str = "corpus",
    require_sources: Iterable[str] | None = None,
    balance: Mapping[str, Any] | None = None,
    fact_table_counts: Mapping[str, int] | None = None,
    run_id: str | None = None,
    job_name: str = "psp.joint_psp_rpc_replay",
) -> dict[str, Any]:
    """Optionally ingest RPC fixtures, then evaluate PSP+RPC completeness together.

    ``require_sources`` defaults to the six daily PSP identifiers so a joint
    replay cannot silently drop a missing RLDC or NLDC document. RPC sources
    remain optional unless the caller lists them.
    """

    db_path = Path(sqlite_db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Replay SQLite database not found at {db_path}")
    rpc_ingest: dict[str, Any] | None = None
    if ingest_rpc_fixtures:
        from psp_pipeline.quality.rpc_fixtures import ingest_rpc_fixture_reports

        rpc_ingest = ingest_rpc_fixture_reports(db_path, fixture_dir=rpc_fixture_dir)
    required = (
        tuple(require_sources) if require_sources is not None else PSP_DAILY_SOURCES
    )
    coverage = evaluate_coverage_manifest(
        db_path,
        default_coverage_manifest_path(),
        profile_name=profile_name,
        require_sources=required,
    )
    summary = build_replay_lineage_summary(
        db_path,
        coverage,
        profile_name=profile_name,
        balance=balance,
        fact_table_counts=fact_table_counts,
        run_id=run_id,
        job_name=job_name,
    )
    summary["coverage"] = {name: result.as_dict() for name, result in coverage.items()}
    summary["rpc_fixtures"] = rpc_ingest
    return summary
