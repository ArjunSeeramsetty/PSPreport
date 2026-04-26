from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from uuid import uuid4

from psp_pipeline.agents.dq_alert_agent import DQAlertAgent
from psp_pipeline.agents.graph_sync_agent import GraphSyncAgent
from psp_pipeline.agents.parser_agent import ParserAgent
from psp_pipeline.agents.recon_agent import ReconAgent
from psp_pipeline.agents.report_fetch_agent import ReportFetchAgent
from psp_pipeline.agents.schema_drift_agent import SchemaDriftAgent
from psp_pipeline.agents.source_discovery_agent import SourceDiscoveryAgent
from psp_pipeline.core.settings import AppSettings
from psp_pipeline.models.contracts import FactObservation, FetchArtifact, ReconciliationResult
from psp_pipeline.storage.minio_store import MinioRawStore
from psp_pipeline.storage.neo4j_repo import Neo4jRepository
from psp_pipeline.storage.postgres_repo import PostgresRepository


def run_bronze(settings: AppSettings, *, include_controlled: bool = False) -> Dict[str, int]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + str(uuid4())[:8]
    source_agent = SourceDiscoveryAgent(settings.project_root / "config" / "sources.yaml")
    fetch_agent = ReportFetchAgent(
        raw_dir=settings.project_root / "data" / "raw",
        max_attempts=settings.http_max_attempts,
        base_delay_seconds=settings.http_base_delay_seconds,
        max_delay_seconds=settings.http_max_delay_seconds,
        jitter_seconds=settings.http_jitter_seconds,
    )
    parser_agent = ParserAgent()
    recon_agent = ReconAgent()
    drift_agent = SchemaDriftAgent()
    dq_agent = DQAlertAgent()
    repo = PostgresRepository(settings.postgres_dsn)

    sources = source_agent.run(include_controlled=include_controlled)
    artifacts = fetch_agent.run(sources)
    artifacts, dedup_skipped = _deduplicate_artifacts(repo, artifacts)
    drift = drift_agent.run(artifacts)
    lineage, facts = parser_agent.run(run_id, artifacts)
    facts, reconciliation_results = _reconcile_facts(run_id, facts, recon_agent)

    raw_store = MinioRawStore(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    raw_store.ensure_bucket(settings.raw_bucket)
    for item in lineage:
        local_file = settings.project_root / "data" / "raw" / item.raw_object_key
        if local_file.exists():
            raw_store.upload_file(
                bucket_name=settings.raw_bucket,
                object_name=item.raw_object_key,
                local_path=str(local_file),
            )

    repo.run_in_transaction(lineage, facts, reconciliation_results)

    neo4j_repo = Neo4jRepository(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        graph_agent = GraphSyncAgent(neo4j_repo)
        graph_agent.run(facts)
    finally:
        neo4j_repo.close()

    dq_alerts = dq_agent.run(
        drift_result=drift,
        min_expected_sources=max(1, len(sources) // 3),
        actual_sources=len({x.source_id for x in artifacts}),
    )

    return {
        "run_id_length": len(run_id),
        "sources_discovered": len(sources),
        "artifacts_fetched": len(artifacts),
        "artifacts_failed": len(sources) - len(artifacts),
        "artifacts_dedup_skipped": dedup_skipped,
        "lineage_rows": len(lineage),
        "facts_rows": len(facts),
        "reconciliation_rows": len(reconciliation_results),
        "dq_alerts": len(dq_alerts),
    }


def _deduplicate_artifacts(
    repo: PostgresRepository,
    artifacts: list[FetchArtifact],
) -> tuple[list[FetchArtifact], int]:
    unique: list[FetchArtifact] = []
    skipped = 0

    for artifact in artifacts:
        latest_hash = repo.fetch_existing_hash(artifact.source_id)
        already_seen = latest_hash == artifact.content_hash or repo.content_hash_exists(
            artifact.source_id, artifact.content_hash
        )
        if already_seen:
            skipped += 1
            local_path = Path(artifact.local_path)
            if local_path.exists():
                local_path.unlink(missing_ok=True)
            continue
        unique.append(artifact)

    return unique, skipped


def _reconcile_facts(
    run_id: str,
    facts: list[FactObservation],
    recon_agent: ReconAgent,
) -> tuple[list[FactObservation], list[ReconciliationResult]]:
    computed_at = datetime.now(timezone.utc)
    out_facts: list[FactObservation] = []
    out_reconciliation: list[ReconciliationResult] = []

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
