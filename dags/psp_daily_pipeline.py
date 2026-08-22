from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path

from airflow.decorators import dag, task

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.core.settings import load_settings
from psp_pipeline.pipelines.serde import (
    deserialize_artifacts,
    deserialize_facts,
    deserialize_lineage,
    deserialize_reconciliation,
    deserialize_sources,
    serialize_artifacts,
    serialize_facts,
    serialize_lineage,
    serialize_reconciliation,
    serialize_sources,
)
from psp_pipeline.pipelines.staging import read_stage_payload, write_stage_payload
from psp_pipeline.pipelines.stages import (
    deduplicate_artifacts,
    detect_schema_drift,
    collect_srldc_daily_psp,
    discover_sources,
    evaluate_dq,
    fetch_artifacts,
    make_run_id,
    parse_artifacts,
    persist_raw,
    persist_sql,
    reconcile_facts,
    repromote_srldc_curated,
    summarize_run,
    export_srldc_curated_to_timescale,
    sync_graph,
    sync_srldc_curated_to_graph,
)


DEFAULT_ARGS = {
    "owner": "psp",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="psp_daily_public_ingestion",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["power", "psp", "bronze", "decomposed"],
)
def psp_daily_public_ingestion():
    @task
    def init_run() -> dict:
        configure_logging("INFO")
        run_id = make_run_id()
        return {
            "run_id": run_id,
            "target_date": datetime.now(timezone.utc).date().isoformat(),
        }

    @task
    def discover_sources_task(run_meta: dict) -> list[dict]:
        _ = run_meta
        settings = load_settings()
        sources = discover_sources(settings, include_controlled=False)
        return serialize_sources(sources)

    @task
    def fetch_artifacts_task(source_payload: list[dict]) -> list[dict]:
        settings = load_settings()
        sources = deserialize_sources(source_payload)
        artifacts = fetch_artifacts(settings, sources)
        return serialize_artifacts(artifacts)

    @task
    def dedup_artifacts_task(artifact_payload: list[dict]) -> dict:
        settings = load_settings()
        artifacts = deserialize_artifacts(artifact_payload)
        deduped, skipped = deduplicate_artifacts(settings, artifacts)
        return {
            "artifacts": serialize_artifacts(deduped),
            "dedup_skipped": skipped,
        }

    @task
    def parse_task(run_meta: dict, dedup_payload: dict) -> dict:
        settings = load_settings()
        run_id = run_meta["run_id"]
        artifacts = deserialize_artifacts(dedup_payload["artifacts"])
        lineage, facts = parse_artifacts(run_id, artifacts)
        return write_stage_payload(settings.project_root, run_id, "parsed", {
            "lineage": serialize_lineage(lineage),
            "facts": serialize_facts(facts),
            "dedup_skipped": dedup_payload["dedup_skipped"],
            "artifacts": dedup_payload["artifacts"],
        })

    @task
    def drift_task(artifact_payload: list[dict]) -> dict:
        artifacts = deserialize_artifacts(artifact_payload)
        return detect_schema_drift(artifacts)

    @task
    def reconcile_task(run_meta: dict, parse_reference: dict) -> dict:
        settings = load_settings()
        parse_payload = read_stage_payload(parse_reference)
        run_id = run_meta["run_id"]
        facts = deserialize_facts(parse_payload["facts"])
        reconciled_facts, reconciliation = reconcile_facts(run_id, facts)
        return write_stage_payload(settings.project_root, run_id, "reconciled", {
            "lineage": parse_payload["lineage"],
            "facts": serialize_facts(reconciled_facts),
            "reconciliation": serialize_reconciliation(reconciliation),
            "dedup_skipped": parse_payload["dedup_skipped"],
            "artifacts": parse_payload["artifacts"],
        })

    @task
    def persist_raw_task(reconcile_reference: dict) -> None:
        settings = load_settings()
        reconcile_payload = read_stage_payload(reconcile_reference)
        lineage = deserialize_lineage(reconcile_payload["lineage"])
        persist_raw(settings, lineage)

    @task
    def persist_sql_task(reconcile_reference: dict) -> None:
        settings = load_settings()
        reconcile_payload = read_stage_payload(reconcile_reference)
        lineage = deserialize_lineage(reconcile_payload["lineage"])
        facts = deserialize_facts(reconcile_payload["facts"])
        reconciliation = deserialize_reconciliation(reconcile_payload["reconciliation"])
        persist_sql(settings, lineage, facts, reconciliation)

    @task
    def sync_graph_task(reconcile_reference: dict) -> None:
        settings = load_settings()
        reconcile_payload = read_stage_payload(reconcile_reference)
        facts = deserialize_facts(reconcile_payload["facts"])
        sync_graph(settings, facts)

    @task
    def collect_srldc_task(run_meta: dict) -> dict:
        """Collect the deterministic daily SRLDC PSP source independently."""

        settings = load_settings()
        return collect_srldc_daily_psp(
            settings,
            date.fromisoformat(run_meta["target_date"]),
        )

    @task
    def curated_promotion_task(collection: dict) -> dict:
        """Refresh local SRLDC curated facts when explicitly enabled."""

        if os.getenv("ENABLE_SRLDC_CURATED_PROMOTION", "false").lower() != "true":
            return {"reports_total": 0, "promoted": 0, "skipped": 0}
        if not collection["reports_persisted"]:
            return {"reports_total": 0, "promoted": 0, "skipped": 0}
        settings = load_settings()
        database = Path(os.getenv(
            "SRLDC_CURATED_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "srldc_daily.sqlite",
        ))
        return repromote_srldc_curated(database)

    @task
    def curated_timescale_task(promotion: dict) -> int:
        """Append the approved local SRLDC curated slice to TimescaleDB."""

        if not promotion["promoted"]:
            return 0
        settings = load_settings()
        database = Path(os.getenv(
            "SRLDC_CURATED_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "srldc_daily.sqlite",
        ))
        return export_srldc_curated_to_timescale(settings, database)

    @task
    def curated_graph_task(promoted_observations: int) -> int:
        """Synchronize the approved local SRLDC curated slice to Neo4j."""

        if not promoted_observations:
            return 0
        settings = load_settings()
        database = Path(os.getenv(
            "SRLDC_CURATED_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "srldc_daily.sqlite",
        ))
        return sync_srldc_curated_to_graph(settings, database)

    @task
    def dq_task(
        source_payload: list[dict],
        reconcile_reference: dict,
        drift_payload: dict,
        run_meta: dict,
    ) -> dict:
        reconcile_payload = read_stage_payload(reconcile_reference)
        sources = deserialize_sources(source_payload)
        artifacts = deserialize_artifacts(reconcile_payload["artifacts"])
        lineage = deserialize_lineage(reconcile_payload["lineage"])
        facts = deserialize_facts(reconcile_payload["facts"])
        reconciliation = deserialize_reconciliation(reconcile_payload["reconciliation"])
        dq_alerts = evaluate_dq(sources, artifacts, drift_payload)

        return summarize_run(
            run_id=run_meta["run_id"],
            sources=sources,
            artifacts=artifacts,
            dedup_skipped=int(reconcile_payload["dedup_skipped"]),
            lineage=lineage,
            facts=facts,
            reconciliation=reconciliation,
            dq_alerts=dq_alerts,
        )

    run_meta = init_run()
    sources = discover_sources_task(run_meta)
    fetched = fetch_artifacts_task(sources)
    deduped = dedup_artifacts_task(fetched)
    parsed = parse_task(run_meta, deduped)
    drift = drift_task(fetched)
    reconciled = reconcile_task(run_meta, parsed)

    raw_done = persist_raw_task(reconciled)
    sql_done = persist_sql_task(reconciled)
    graph_done = sync_graph_task(reconciled)
    summary = dq_task(sources, reconciled, drift, run_meta)
    srldc_collection = collect_srldc_task(run_meta)
    curated_promotion = curated_promotion_task(srldc_collection)
    curated_timescale = curated_timescale_task(curated_promotion)
    curated_graph = curated_graph_task(curated_timescale)

    raw_done >> sql_done >> graph_done >> summary
    curated_graph >> summary


dag = psp_daily_public_ingestion()
