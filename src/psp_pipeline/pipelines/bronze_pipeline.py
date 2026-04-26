from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict
from uuid import uuid4

from psp_pipeline.agents.dq_alert_agent import DQAlertAgent
from psp_pipeline.agents.graph_sync_agent import GraphSyncAgent
from psp_pipeline.agents.parser_agent import ParserAgent
from psp_pipeline.agents.report_fetch_agent import ReportFetchAgent
from psp_pipeline.agents.schema_drift_agent import SchemaDriftAgent
from psp_pipeline.agents.source_discovery_agent import SourceDiscoveryAgent
from psp_pipeline.core.settings import AppSettings
from psp_pipeline.storage.minio_store import MinioRawStore
from psp_pipeline.storage.neo4j_repo import Neo4jRepository
from psp_pipeline.storage.postgres_repo import PostgresRepository


def run_bronze(settings: AppSettings, *, include_controlled: bool = False) -> Dict[str, int]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + str(uuid4())[:8]
    source_agent = SourceDiscoveryAgent(settings.project_root / "config" / "sources.yaml")
    fetch_agent = ReportFetchAgent(raw_dir=settings.project_root / "data" / "raw")
    parser_agent = ParserAgent()
    drift_agent = SchemaDriftAgent()
    dq_agent = DQAlertAgent()

    sources = source_agent.run(include_controlled=include_controlled)
    artifacts = fetch_agent.run(sources)
    drift = drift_agent.run(artifacts)
    lineage, facts = parser_agent.run(run_id, artifacts)

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

    repo = PostgresRepository(settings.postgres_dsn)
    repo.run_in_transaction(lineage, facts)

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
        "lineage_rows": len(lineage),
        "facts_rows": len(facts),
        "dq_alerts": len(dq_alerts),
    }
