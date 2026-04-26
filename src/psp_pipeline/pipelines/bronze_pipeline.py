from __future__ import annotations

from typing import Dict

from psp_pipeline.core.settings import AppSettings
from psp_pipeline.models.contracts import FactObservation, FetchArtifact
from psp_pipeline.pipelines.stages import (
    deduplicate_artifacts,
    detect_schema_drift,
    discover_sources,
    evaluate_dq,
    fetch_artifacts,
    make_run_id,
    parse_artifacts,
    persist_raw,
    persist_sql,
    reconcile_facts,
    summarize_run,
    sync_graph,
)
from psp_pipeline.storage.postgres_repo import PostgresRepository


def run_bronze(settings: AppSettings, *, include_controlled: bool = False) -> Dict[str, int]:
    run_id = make_run_id()
    sources = discover_sources(settings, include_controlled=include_controlled)
    artifacts = fetch_artifacts(settings, sources)
    artifacts, dedup_skipped = deduplicate_artifacts(settings, artifacts)
    drift = detect_schema_drift(artifacts)
    lineage, facts = parse_artifacts(run_id, artifacts)
    facts, reconciliation_results = reconcile_facts(run_id, facts)

    persist_raw(settings, lineage)
    persist_sql(settings, lineage, facts, reconciliation_results)
    sync_graph(settings, facts)
    dq_alerts = evaluate_dq(sources, artifacts, drift)

    return summarize_run(
        run_id=run_id,
        sources=sources,
        artifacts=artifacts,
        dedup_skipped=dedup_skipped,
        lineage=lineage,
        facts=facts,
        reconciliation=reconciliation_results,
        dq_alerts=dq_alerts,
    )


# Backward-compatible wrappers for existing tests/imports.
def _deduplicate_artifacts(repo: PostgresRepository, artifacts: list[FetchArtifact]):
    unique: list[FetchArtifact] = []
    skipped = 0
    for artifact in artifacts:
        latest_hash = repo.fetch_existing_hash(artifact.source_id)
        already_seen = latest_hash == artifact.content_hash or repo.content_hash_exists(
            artifact.source_id, artifact.content_hash
        )
        if already_seen:
            skipped += 1
            from pathlib import Path

            local_path = Path(artifact.local_path)
            if local_path.exists():
                local_path.unlink(missing_ok=True)
            continue
        unique.append(artifact)
    return unique, skipped


def _reconcile_facts(run_id: str, facts: list[FactObservation], recon_agent):
    from datetime import datetime, timezone
    from dataclasses import replace
    from psp_pipeline.models.contracts import ReconciliationResult

    computed_at = datetime.now(timezone.utc)
    out_facts = []
    out_reconciliation = []
    for fact in facts:
        variance = recon_agent.run(
            operational_value=fact.operational_value,
            settlement_value=fact.settlement_value,
        )
        out_facts.append(replace(fact, variance_pct=variance))
        out_reconciliation.append(
            ReconciliationResult(
                run_id=run_id,
                entity_key=fact.entity_key,
                metric_name=fact.metric_name,
                time_block=fact.time_block,
                variance_pct=variance,
                source_region=fact.source_region,
                computed_at=computed_at,
            )
        )
    return out_facts, out_reconciliation

