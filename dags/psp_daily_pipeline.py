from __future__ import annotations

from datetime import datetime, timedelta

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
        return {"run_id": run_id}

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
        run_id = run_meta["run_id"]
        artifacts = deserialize_artifacts(dedup_payload["artifacts"])
        lineage, facts = parse_artifacts(run_id, artifacts)
        return {
            "lineage": serialize_lineage(lineage),
            "facts": serialize_facts(facts),
            "dedup_skipped": dedup_payload["dedup_skipped"],
            "artifacts": dedup_payload["artifacts"],
        }

    @task
    def drift_task(artifact_payload: list[dict]) -> dict:
        artifacts = deserialize_artifacts(artifact_payload)
        return detect_schema_drift(artifacts)

    @task
    def reconcile_task(run_meta: dict, parse_payload: dict) -> dict:
        run_id = run_meta["run_id"]
        facts = deserialize_facts(parse_payload["facts"])
        reconciled_facts, reconciliation = reconcile_facts(run_id, facts)
        return {
            "lineage": parse_payload["lineage"],
            "facts": serialize_facts(reconciled_facts),
            "reconciliation": serialize_reconciliation(reconciliation),
            "dedup_skipped": parse_payload["dedup_skipped"],
            "artifacts": parse_payload["artifacts"],
        }

    @task
    def persist_raw_task(reconcile_payload: dict) -> None:
        settings = load_settings()
        lineage = deserialize_lineage(reconcile_payload["lineage"])
        persist_raw(settings, lineage)

    @task
    def persist_sql_task(reconcile_payload: dict) -> None:
        settings = load_settings()
        lineage = deserialize_lineage(reconcile_payload["lineage"])
        facts = deserialize_facts(reconcile_payload["facts"])
        reconciliation = deserialize_reconciliation(reconcile_payload["reconciliation"])
        persist_sql(settings, lineage, facts, reconciliation)

    @task
    def sync_graph_task(reconcile_payload: dict) -> None:
        settings = load_settings()
        facts = deserialize_facts(reconcile_payload["facts"])
        sync_graph(settings, facts)

    @task
    def dq_task(source_payload: list[dict], reconcile_payload: dict, drift_payload: dict, run_meta: dict) -> dict:
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

    raw_done >> sql_done >> graph_done >> summary


dag = psp_daily_public_ingestion()

