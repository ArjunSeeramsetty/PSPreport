from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
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
    PipelineRun,
    ReconciliationResult,
    SourceDefinition,
)
from psp_pipeline.quality.coverage_contract import (
    default_coverage_manifest_path,
    enforce_coverage_manifest,
    evaluate_coverage_manifest,
)
from psp_pipeline.quality.timescale_mirror_reconciliation import (
    CurrentRowFetcher,
    verify_exported_current_mirror,
)
from psp_pipeline.storage.minio_store import MinioRawStore
from psp_pipeline.storage.neo4j_repo import Neo4jRepository
from psp_pipeline.storage.postgres_publish import (
    prepare_curated_postgres_publish,
    publish_wide_facts_to_repository,
)
from psp_pipeline.storage.postgres_repo import PostgresRepository
from psp_pipeline.storage.sqlite_curated_export import (
    export_observation_lineage,
    export_srldc_daily_observations,
)
from psp_pipeline.storage.sqlite_curated_promoter import repromote_srldc_reports
from psp_pipeline.storage.sqlite_topology_export import export_curated_topology
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
) -> int:
    """Persist legacy-path facts only when they are non-placeholder measures.

    The unified curated pipeline owns production PSP observations. This guard
    keeps the opt-in bootstrap branch useful for lineage migration while
    preventing synthetic smoke-test counters from entering Timescale.
    """

    fact_rows = list(facts)
    placeholder_metrics = [
        fact.metric_name for fact in fact_rows if fact.metric_name == "raw_artifact_count"
    ]
    if placeholder_metrics:
        raise ValueError(
            "Legacy bootstrap observations are not eligible for production SQL persistence"
        )

    repo = PostgresRepository(settings.postgres_dsn)
    return repo.run_in_transaction(lineage, fact_rows, reconciliation)


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
    *,
    verify_current_mirror: bool = True,
    current_row_fetcher: CurrentRowFetcher | None = None,
) -> int:
    """Append curated SRLDC regional and state facts to TimescaleDB."""

    if not sqlite_db_path.exists():
        return 0
    import sqlite3

    with sqlite3.connect(sqlite_db_path) as conn:
        facts = export_srldc_daily_observations(conn)
        if facts:
            observation_lineage = export_observation_lineage(conn, facts)
            repository = PostgresRepository(settings.postgres_dsn)
            facts, catalog, identity_summary = prepare_curated_postgres_publish(
                conn,
                facts,
                repository,
            )
            repository.upsert_curated_observations(
                facts,
                observation_lineage,
            )
            publish_wide_facts_to_repository(
                facts,
                catalog,
                repository,
                verify_current_mirror=verify_current_mirror,
            )
            repository.refresh_current_truth_views()
            if verify_current_mirror:
                verify_exported_current_mirror(
                    facts,
                    settings.postgres_dsn,
                    current_row_fetcher=current_row_fetcher,
                )
            logger.info(
                "srldc_curated_postgres_publish observations=%s identity=%s",
                len(facts),
                identity_summary,
            )
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


def collect_all_rldc_daily_psp(
    settings: AppSettings,
    target_date: date | None = None,
    target_rldcs: set[str] | None = None,
    max_reports_per_rldc: int = 1,
) -> Dict[str, Any]:
    """Coordinate fail-soft daily ingestion across all 5 Indian RLDCs."""
    from psp_pipeline.pipelines.all_rldc_daily_psp import run_all_rldc_daily_psp

    try:
        return run_all_rldc_daily_psp(
            config_path=settings.project_root / "config" / "rldc_report_sources.yaml",
            sqlite_db_path=settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
            download_root=settings.project_root / "downloads",
            target_date=target_date,
            max_reports_per_rldc=max_reports_per_rldc,
            target_rldcs=target_rldcs,
        )
    except Exception:
        logger.exception("All-RLDC daily PSP collection failed")
        return {
            "aggregate": {
                "sources_requested": len(target_rldcs) if target_rldcs else 5,
                "sources_completed": 0,
                "sources_failed": len(target_rldcs) if target_rldcs else 5,
                "pdf_links_found": 0,
                "reports_downloaded": 0,
                "reports_persisted": 0,
                "ocr_recommended": 0,
                "report_family_rejected": 0,
            },
            "sources": {},
            "source_failures": {"all": "Critical failure in coordinator"},
        }


def collect_rpc_settlement(
    settings: AppSettings,
    target_date: date | None = None,
    target_rpcs: set[str] | None = None,
    max_reports_per_rpc: int = 4,
) -> Dict[str, Any]:
    """Collect weekly DSM and monthly REA accounts from public RPC listings."""

    from psp_pipeline.pipelines.rpc_settlement import run_rpc_settlement_collection

    try:
        return run_rpc_settlement_collection(
            config_path=settings.project_root / "config" / "rpc_report_sources.yaml",
            sqlite_db_path=settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
            download_root=settings.project_root / "downloads" / "rpc",
            target_date=target_date,
            target_rpcs=target_rpcs,
            max_reports_per_rpc=max_reports_per_rpc,
        )
    except Exception:
        logger.exception("RPC settlement collection failed")
        return {
            "aggregate": {
                "sources_requested": len(target_rpcs) if target_rpcs else 5,
                "sources_completed": 0,
                "sources_failed": len(target_rpcs) if target_rpcs else 5,
                "links_found": 0,
                "reports_downloaded": 0,
                "reports_persisted": 0,
                "unsupported_family": 0,
            },
            "sources": {},
            "failures": {"all": "Critical failure in RPC coordinator"},
        }


def catch_up_missing_public_dates(
    settings: AppSettings,
    target_date: date,
    *,
    lookback_days: int = 2,
) -> Dict[str, Any]:
    """Fill recent holes left by a failed or partial public collection day."""

    from psp_pipeline.pipelines.all_rldc_daily_psp import catch_up_missing_rldc_dates

    try:
        return catch_up_missing_rldc_dates(
            config_path=settings.project_root / "config" / "rldc_report_sources.yaml",
            sqlite_db_path=settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
            download_root=settings.project_root / "downloads",
            target_date=target_date,
            lookback_days=lookback_days,
        )
    except Exception:
        logger.exception("Public RLDC catch-up failed for %s", target_date.isoformat())
        return {
            "lookback_days": lookback_days,
            "anchor_date": target_date.isoformat(),
            "dates": [],
            "error": "catch_up_failed",
        }


def retry_curated_promotion_quarantine(
    sqlite_db_path: Path,
) -> Dict[str, Any]:
    """Retry pending spatial and OCR holds before coverage is evaluated."""

    if not sqlite_db_path.exists():
        return {
            "holds_seen": 0,
            "resolved": 0,
            "skipped_semantic": 0,
            "reports_missing_local_file": 0,
            "reports_without_spatial_items": 0,
            "liteparse_unavailable": 0,
            "unknown_reason": 0,
            "retry_failed": 0,
            "skipped": True,
        }
    from psp_pipeline.pipelines.quarantine_retry import retry_pending_promotion_quarantine

    return retry_pending_promotion_quarantine(sqlite_db_path)


def audit_curated_source_freshness(
    sqlite_db_path: Path,
    target_date: date,
) -> Dict[str, Any]:
    """Return public sources missing a persisted report for the target date."""

    from psp_pipeline.pipelines.all_rldc_daily_psp import missing_sources_for_date

    missing = sorted(missing_sources_for_date(sqlite_db_path, target_date))
    return {
        "target_date": target_date.isoformat(),
        "stale_or_missing_sources": missing,
        "passed": not missing,
        "skipped": not sqlite_db_path.exists(),
    }


def export_all_curated_to_timescale(
    settings: AppSettings,
    sqlite_db_path: Path,
    rldcs: list[str] | None = None,
    target_date: date | None = None,
    report_document_ids: Iterable[int] | None = None,
    *,
    verify_current_mirror: bool = True,
    current_row_fetcher: CurrentRowFetcher | None = None,
) -> int:
    """Export a date-scoped curated multi-RLDC slice into TimescaleDB.

    Historical replay belongs in ``bootstrap_timescale_from_sqlite`` against a
    greenfield schema. This stage only publishes the orchestration date, then
    upserts canonical identity and Postgres-primary wide facts when the
    repository implements those APIs.
    """
    if not sqlite_db_path.exists():
        return 0
    import sqlite3

    with sqlite3.connect(sqlite_db_path) as conn:
        facts = _export_curated_observations_for_date(
            conn,
            rldcs,
            target_date,
            report_document_ids=report_document_ids,
        )
        observation_lineage = export_observation_lineage(conn, facts)
        if facts:
            repository = PostgresRepository(settings.postgres_dsn)
            facts, catalog, identity_summary = prepare_curated_postgres_publish(
                conn,
                facts,
                repository,
            )
            inserted = repository.upsert_curated_observations(
                facts,
                observation_lineage,
            )
            wide_summary = publish_wide_facts_to_repository(
                facts,
                catalog,
                repository,
                verify_current_mirror=verify_current_mirror,
            )
            repository.refresh_current_truth_views()
            if verify_current_mirror:
                verify_exported_current_mirror(
                    facts,
                    settings.postgres_dsn,
                    current_row_fetcher=current_row_fetcher,
                )
            logger.info(
                "curated_postgres_publish inserted=%s identity=%s wide=%s",
                inserted,
                identity_summary,
                wide_summary,
            )
            return inserted
    return 0


def sync_all_curated_to_graph(
    settings: AppSettings,
    sqlite_db_path: Path,
    rldcs: list[str] | None = None,
    target_date: date | None = None,
    report_document_ids: Iterable[int] | None = None,
) -> int:
    """Synchronize curated topology and a date-scoped observation slice to Neo4j."""
    if not sqlite_db_path.exists():
        return 0
    import sqlite3
    from psp_pipeline.identity.canonical import (
        annotate_topology_with_canonical_ids,
        build_canonical_catalog,
    )
    from psp_pipeline.storage.postgres_publish import dimension_catalog_available
    from psp_pipeline.storage.wide_facts import attach_canonical_entity_ids

    with sqlite3.connect(sqlite_db_path) as conn:
        topology = export_curated_topology(conn)
        facts = _export_curated_observations_for_date(
            conn,
            rldcs,
            target_date,
            report_document_ids=report_document_ids,
        )
        catalog = None
        if dimension_catalog_available(conn):
            catalog = build_canonical_catalog(conn)
            topology = annotate_topology_with_canonical_ids(topology, catalog)
            facts = attach_canonical_entity_ids(facts, catalog)
            conn.commit()
    neo4j_repo = Neo4jRepository(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
    )
    try:
        neo4j_repo.ensure_constraints(_neo4j_constraint_statements())
        merge_canonical = getattr(neo4j_repo, "merge_canonical_entities", None)
        if callable(merge_canonical):
            merge_canonical(topology.get("canonical_entities", []))
        neo4j_repo.merge_grid_topology(topology)
        link_identifies = getattr(neo4j_repo, "link_identifies_relationships", None)
        if callable(link_identifies):
            link_identifies()
        GraphSyncAgent(neo4j_repo).run(facts)
    finally:
        neo4j_repo.close()
    return len(facts)


def reconcile_national_daily_balance(
    sqlite_db_path: Path,
    date_id: int | None = None,
    target_date: date | None = None,
) -> Dict[str, Any]:
    """Synthesize national balance for an explicit valid date or date key."""
    if not sqlite_db_path.exists():
        return {}
    import sqlite3
    from psp_pipeline.reconciliation.all_india_balance import synthesize_all_india_daily_balance

    with sqlite3.connect(sqlite_db_path) as conn:
        resolved_date_id = _resolve_date_id(conn, date_id, target_date)
        if resolved_date_id is None:
            return {}
        balance = synthesize_all_india_daily_balance(conn, date_id=resolved_date_id)
    return balance.as_dict()


def _export_curated_observations_for_date(
    conn: Any,
    rldcs: list[str] | None,
    target_date: date | None,
    *,
    report_document_ids: Iterable[int] | None = None,
) -> list[FactObservation]:
    """Return target-date observations plus explicitly collected reports."""

    from psp_pipeline.storage.sqlite_curated_export import export_all_daily_observations

    if target_date is None and report_document_ids is None:
        return export_all_daily_observations(conn, rldcs=rldcs)
    report_ids = {int(report_id) for report_id in report_document_ids or ()}
    if target_date is not None:
        placeholders = ", ".join("?" for _ in rldcs) if rldcs else ""
        query = "SELECT id FROM psp_report_document WHERE report_date = ?"
        params: list[Any] = [target_date.isoformat()]
        if rldcs:
            query += f" AND rldc IN ({placeholders})"
            params.extend(rldcs)
        report_ids.update(int(row[0]) for row in conn.execute(query, params))
    observations: list[FactObservation] = []
    for report_document_id in sorted(report_ids):
        observations.extend(
            export_all_daily_observations(
                conn,
                rldcs=rldcs,
                report_document_id=report_document_id,
            )
        )
    return observations


def _resolve_date_id(
    conn: Any,
    date_id: int | None,
    target_date: date | None,
) -> int | None:
    """Resolve a supplied valid date to the canonical SQLite date key."""

    if date_id is not None:
        return date_id
    if target_date is None:
        return None
    row = conn.execute(
        "SELECT DateID FROM DimDates WHERE ActualDate = ?",
        (target_date.isoformat(),),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _neo4j_constraint_statements() -> list[str]:
    """Load repository-owned idempotent graph constraints for DAG execution."""

    constraints_path = (
        Path(__file__).resolve().parents[3] / "sql" / "neo4j_constraints.cypher"
    )
    return [
        statement.strip()
        for statement in constraints_path.read_text(encoding="utf-8").split(";")
        if statement.strip()
    ]


def audit_pending_identity_adjudications(
    sqlite_db_path: Path,
) -> Dict[str, Any]:
    """Count pending canonical identity issues without auto-approving them.

    Daily orchestration treats this as fail-soft observability. A non-zero
    pending count is recorded in XCom; humans apply decisions through
    ``apply_canonical_identity_adjudication``.
    """

    if not sqlite_db_path.exists():
        return {
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "total": 0,
            "skipped": True,
            "passed": True,
            "issues": [],
        }
    import sqlite3
    from psp_pipeline.identity.adjudication import (
        identity_adjudication_summary,
        list_identity_adjudications,
    )

    with sqlite3.connect(sqlite_db_path) as conn:
        summary = identity_adjudication_summary(conn)
        issues = list_identity_adjudications(conn, status="pending")
    logger.info(
        "identity_adjudication_audit pending=%s approved=%s rejected=%s",
        summary["pending"],
        summary["approved"],
        summary["rejected"],
    )
    return {
        **summary,
        "skipped": False,
        "passed": True,
        "issues": issues,
    }


def apply_canonical_identity_adjudication(
    sqlite_db_path: Path,
    *,
    issue_id: int,
    decision: str,
    decided_by: str = "operator",
    entity_id: str | None = None,
    observation_entity_key: str | None = None,
    postgres_dsn: str | None = None,
    repository: object | None = None,
) -> Dict[str, Any]:
    """Apply one human identity decision and optionally republish to Postgres."""

    import sqlite3
    from psp_pipeline.identity.adjudication import (
        apply_adjudication,
        republish_identity_after_adjudication,
    )

    with sqlite3.connect(sqlite_db_path) as conn:
        result = apply_adjudication(
            conn,
            issue_id=issue_id,
            decision=decision,
            decided_by=decided_by,
            entity_id=entity_id,
            observation_entity_key=observation_entity_key,
        )
        repo = repository
        if repo is None and postgres_dsn:
            repo = PostgresRepository(postgres_dsn)
        if repo is None:
            return {
                "apply": result.as_dict(),
                "postgres": {"skipped": True},
                "decision": {"skipped": True},
                "backfill": {"skipped": True},
            }
        published = republish_identity_after_adjudication(conn, repo, result)
    logger.info(
        "canonical_identity_adjudication_applied issue_id=%s decision=%s",
        issue_id,
        decision,
    )
    return published


def audit_national_curated_dimensions(
    sqlite_db_path: Path,
) -> Dict[str, Any]:
    """Execute national dimension quality audit across all active RLDC tables."""
    if not sqlite_db_path.exists():
        return {}
    from psp_pipeline.quality.national_dimension_audit import audit_national_dimensions

    return audit_national_dimensions(sqlite_db_path)


def evaluate_curated_coverage_contract(
    sqlite_db_path: Path,
    *,
    manifest_path: Path | None = None,
    profile_name: str = "corpus",
    require_sources: Iterable[str] | None = None,
    fail_hard: bool = False,
) -> Dict[str, Any]:
    """Evaluate or enforce the committed coverage floors against one SQLite replay.

    Daily orchestration uses ``fail_hard=False`` so a coverage regression is
    visible in XCom without blocking Timescale or graph publication. Replay and
    CI callers pass ``fail_hard=True`` for the profile they intend to gate.
    """

    if not sqlite_db_path.exists():
        return {
            "database_path": str(sqlite_db_path),
            "profile_name": profile_name,
            "passed": True,
            "skipped": True,
            "profiles": {},
        }
    resolved_manifest = manifest_path or default_coverage_manifest_path()
    evaluator = enforce_coverage_manifest if fail_hard else evaluate_coverage_manifest
    results = evaluator(
        sqlite_db_path,
        resolved_manifest,
        profile_name=profile_name,
        require_sources=require_sources,
    )
    selected = results[profile_name]
    return {
        "database_path": str(sqlite_db_path),
        "profile_name": profile_name,
        "passed": selected.passed,
        "skipped": False,
        "profiles": {name: result.as_dict() for name, result in results.items()},
    }


def record_pipeline_run(
    settings: AppSettings,
    *,
    run_id: str,
    started_at: datetime,
    collection: Dict[str, Any],
    observations_inserted: int,
    graph_observations: int,
) -> Dict[str, object]:
    """Persist a fail-soft summary of one unified public PSP orchestration run."""

    aggregate = collection.get("aggregate", {})
    requested = int(aggregate.get("sources_requested", 0))
    completed = int(aggregate.get("sources_completed", 0))
    failed = int(aggregate.get("sources_failed", max(requested - completed, 0)))
    exported = max(int(graph_observations), int(observations_inserted))
    status = "success" if failed == 0 else "partial"
    record = PipelineRun(
        run_id=run_id,
        dag_id="psp_daily_public_ingestion",
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        status=status,
        sources_requested=requested,
        sources_completed=completed,
        sources_failed=failed,
        observations_exported=exported,
        observations_inserted=int(observations_inserted),
        observations_deduplicated=max(exported - int(observations_inserted), 0),
    )
    try:
        PostgresRepository(settings.postgres_dsn).upsert_pipeline_run(record)
    except Exception:
        logger.exception("Pipeline run history persistence failed for run_id=%s", run_id)
        return {"run_id": run_id, "status": "history_write_failed"}
    return {"run_id": run_id, "status": status}


def combine_collection_summaries(*collections: Dict[str, Any]) -> Dict[str, Any]:
    """Combine fail-soft source counters for one orchestration history record."""

    counters = ("sources_requested", "sources_completed", "sources_failed")
    aggregate = {
        counter: sum(
            int(collection.get("aggregate", {}).get(counter, 0))
            for collection in collections
        )
        for counter in counters
    }
    return {"aggregate": aggregate}


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
