from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
import logging
from pathlib import Path
from typing import Dict, List, Tuple
from uuid import uuid4

from psp_pipeline.agents.dq_alert_agent import DQAlertAgent
from psp_pipeline.agents.graph_sync_agent import GraphSyncAgent
from psp_pipeline.agents.parser_agent import ParserAgent
from psp_pipeline.agents.recon_agent import ReconAgent
from psp_pipeline.agents.report_fetch_agent import ReportFetchAgent
from psp_pipeline.agents.schema_drift_agent import SchemaDriftAgent
from psp_pipeline.agents.source_discovery_agent import SourceDiscoveryAgent
from psp_pipeline.core.settings import AppSettings
from psp_pipeline.models.contracts import (
    FactObservation,
    FetchArtifact,
    LineageRecord,
    ReconciliationResult,
    SourceDefinition,
)
from psp_pipeline.storage.minio_store import MinioRawStore
from psp_pipeline.storage.neo4j_repo import Neo4jRepository
from psp_pipeline.storage.postgres_repo import PostgresRepository
from psp_pipeline.storage.sqlite_curated_export import export_srldc_daily_observations
from psp_pipeline.storage.sqlite_curated_promoter import repromote_srldc_reports
from psp_pipeline.pipelines.rldc_daily_psp import run_rldc_daily_psp_collection


logger = logging.getLogger(__name__)


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + str(uuid4())[:8]


def discover_sources(settings: AppSettings, *, include_controlled: bool = False) -> List[SourceDefinition]:
    source_agent = SourceDiscoveryAgent(settings.project_root / "config" / "sources.yaml")
    return source_agent.run(include_controlled=include_controlled)


def fetch_artifacts(settings: AppSettings, sources: List[SourceDefinition]) -> List[FetchArtifact]:
    fetch_agent = ReportFetchAgent(
        raw_dir=settings.project_root / "data" / "raw",
        max_attempts=settings.http_max_attempts,
        base_delay_seconds=settings.http_base_delay_seconds,
        max_delay_seconds=settings.http_max_delay_seconds,
        jitter_seconds=settings.http_jitter_seconds,
    )
    return fetch_agent.run(sources)


def deduplicate_artifacts(settings: AppSettings, artifacts: List[FetchArtifact]) -> Tuple[List[FetchArtifact], int]:
    repo = PostgresRepository(settings.postgres_dsn)
    unique: List[FetchArtifact] = []
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


def detect_schema_drift(artifacts: List[FetchArtifact]) -> Dict[str, List[str]]:
    return SchemaDriftAgent().run(artifacts)


def parse_artifacts(run_id: str, artifacts: List[FetchArtifact]) -> Tuple[List[LineageRecord], List[FactObservation]]:
    parser_agent = ParserAgent()
    return parser_agent.run(run_id, artifacts)


def reconcile_facts(
    run_id: str,
    facts: List[FactObservation],
) -> Tuple[List[FactObservation], List[ReconciliationResult]]:
    recon_agent = ReconAgent()
    computed_at = datetime.now(timezone.utc)
    out_facts: List[FactObservation] = []
    out_reconciliation: List[ReconciliationResult] = []

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


def persist_raw(settings: AppSettings, lineage: List[LineageRecord]) -> None:
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


def persist_sql(
    settings: AppSettings,
    lineage: List[LineageRecord],
    facts: List[FactObservation],
    reconciliation: List[ReconciliationResult],
) -> None:
    repo = PostgresRepository(settings.postgres_dsn)
    repo.run_in_transaction(lineage, facts, reconciliation)


def sync_graph(settings: AppSettings, facts: List[FactObservation]) -> None:
    neo4j_repo = Neo4jRepository(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        graph_agent = GraphSyncAgent(neo4j_repo)
        graph_agent.run(facts)
    finally:
        neo4j_repo.close()


def repromote_srldc_curated(sqlite_db_path: Path) -> Dict[str, int]:
    """Refresh approved SRLDC curated facts from local raw-cell lineage."""

    if not sqlite_db_path.exists():
        return {"reports_total": 0, "promoted": 0, "skipped": 0}
    import sqlite3

    with sqlite3.connect(sqlite_db_path) as conn:
        result = repromote_srldc_reports(conn)
        conn.commit()
    return result


def export_srldc_curated_to_timescale(
    settings: AppSettings,
    sqlite_db_path: Path,
) -> int:
    """Append curated SRLDC regional and state facts to TimescaleDB."""

    if not sqlite_db_path.exists():
        return 0
    import sqlite3

    with sqlite3.connect(sqlite_db_path) as conn:
        facts = export_srldc_daily_observations(conn)
    if facts:
        PostgresRepository(settings.postgres_dsn).upsert_fact_observations(facts)
    return len(facts)


def sync_srldc_curated_to_graph(settings: AppSettings, sqlite_db_path: Path) -> int:
    """Synchronize curated SRLDC regional and state observation topology."""

    if not sqlite_db_path.exists():
        return 0
    import sqlite3

    with sqlite3.connect(sqlite_db_path) as conn:
        facts = export_srldc_daily_observations(conn)
    if facts:
        sync_graph(settings, facts)
    return len(facts)


def collect_srldc_daily_psp(
    settings: AppSettings,
    target_date: date | None = None,
) -> Dict[str, int]:
    """Collect and curate public SRLDC daily PSP PDFs into local SQLite."""

    try:
        return run_rldc_daily_psp_collection(
            config_path=settings.project_root / "config" / "rldc_report_sources.yaml",
            sqlite_db_path=settings.project_root / "data" / "sqlite" / "srldc_daily.sqlite",
            download_root=settings.project_root / "downloads",
            target_rldcs={"srldc"},
            max_reports_per_rldc=1,
            target_date=target_date,
        )
    except Exception:
        logger.exception("SRLDC daily PSP collection failed")
        return {
            "sources_scanned": 1,
            "pdf_links_found": 0,
            "reports_downloaded": 0,
            "reports_persisted": 0,
            "ocr_recommended": 0,
            "report_family_rejected": 0,
        }


def evaluate_dq(
    sources: List[SourceDefinition],
    artifacts: List[FetchArtifact],
    drift: Dict[str, List[str]],
) -> List[str]:
    return DQAlertAgent().run(
        drift_result=drift,
        min_expected_sources=max(1, len(sources) // 3),
        actual_sources=len({x.source_id for x in artifacts}),
    )


def summarize_run(
    run_id: str,
    sources: List[SourceDefinition],
    artifacts: List[FetchArtifact],
    dedup_skipped: int,
    lineage: List[LineageRecord],
    facts: List[FactObservation],
    reconciliation: List[ReconciliationResult],
    dq_alerts: List[str],
) -> Dict[str, int]:
    return {
        "run_id_length": len(run_id),
        "sources_discovered": len(sources),
        "artifacts_fetched": len(artifacts),
        "artifacts_failed": len(sources) - len(artifacts),
        "artifacts_dedup_skipped": dedup_skipped,
        "lineage_rows": len(lineage),
        "facts_rows": len(facts),
        "reconciliation_rows": len(reconciliation),
        "dq_alerts": len(dq_alerts),
    }
