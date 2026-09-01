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
    audit_curated_source_freshness,
    audit_national_curated_dimensions,
    audit_pending_identity_adjudications,
    catch_up_missing_public_dates,
    collect_all_rldc_daily_psp,
    collect_rpc_settlement,
    collect_srldc_daily_psp,
    combine_collection_summaries,
    deduplicate_artifacts,
    detect_schema_drift,
    discover_sources,
    evaluate_curated_coverage_contract,
    evaluate_dq,
    export_all_curated_to_timescale,
    export_srldc_curated_to_timescale,
    fetch_artifacts,
    make_run_id,
    parse_artifacts,
    persist_raw,
    persist_sql,
    reconcile_facts,
    reconcile_national_daily_balance,
    record_pipeline_run,
    repromote_srldc_curated,
    retry_curated_promotion_quarantine,
    summarize_run,
    sync_all_curated_to_graph,
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
            "started_at": datetime.now(timezone.utc).isoformat(),
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
    def collect_rpc_settlement_task(run_meta: dict) -> dict:
        """Collect public weekly DSM and monthly REA accounts fail-soft per RPC."""

        settings = load_settings()
        return collect_rpc_settlement(
            settings,
            date.fromisoformat(run_meta["target_date"]),
        )

    @task
    def collect_all_rldc_task(run_meta: dict) -> dict:
        """Collect and curate all 5 public RLDC daily PSP sources with isolated failures."""

        settings = load_settings()
        return collect_all_rldc_daily_psp(
            settings,
            date.fromisoformat(run_meta["target_date"]),
        )

    @task
    def catch_up_missing_dates_task(run_meta: dict, collection: dict) -> dict:
        """Re-collect recent dates that never persisted a public source report."""

        _ = collection
        lookback_days = int(os.getenv("PSP_CATCHUP_LOOKBACK_DAYS", "2"))
        return catch_up_missing_public_dates(
            load_settings(),
            date.fromisoformat(run_meta["target_date"]),
            lookback_days=lookback_days,
        )

    @task
    def quarantine_retry_task(catch_up: dict) -> dict:
        """Replay LiteParse for pending spatial and OCR promotion holds."""

        _ = catch_up
        settings = load_settings()
        database = Path(os.getenv(
            "ALL_RLDC_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
        ))
        return retry_curated_promotion_quarantine(database)

    @task
    def curated_freshness_task(run_meta: dict, catch_up: dict) -> dict:
        """Flag public sources still missing after today and catch-up."""

        _ = catch_up
        settings = load_settings()
        database = Path(os.getenv(
            "ALL_RLDC_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
        ))
        return audit_curated_source_freshness(
            database,
            date.fromisoformat(run_meta["target_date"]),
        )

    @task
    def national_balance_task(collection: dict, run_meta: dict, retry: dict) -> dict:
        """Synthesize daily All-India balance after spatial/OCR retries."""

        _ = retry
        settings = load_settings()
        database = Path(os.getenv(
            "ALL_RLDC_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
        ))
        return reconcile_national_daily_balance(
            database,
            target_date=date.fromisoformat(run_meta["target_date"]),
        )

    @task
    def national_dimension_audit_task(collection: dict, retry: dict) -> dict:
        """Audit national dimension quality after spatial/OCR retries."""

        _ = retry
        settings = load_settings()
        database = Path(os.getenv(
            "ALL_RLDC_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
        ))
        return audit_national_curated_dimensions(database)

    @task
    def identity_adjudication_audit_task(collection: dict, retry: dict) -> dict:
        """Count pending identity issues without auto-approving them."""

        _ = collection
        _ = retry
        settings = load_settings()
        database = Path(os.getenv(
            "ALL_RLDC_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
        ))
        return audit_pending_identity_adjudications(database)

    @task
    def coverage_contract_task(collection: dict, retry: dict) -> dict:
        """Evaluate corpus coverage floors after quarantine retries complete."""

        _ = retry
        settings = load_settings()
        database = Path(os.getenv(
            "ALL_RLDC_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
        ))
        completed = [
            source_id
            for source_id, payload in collection.get("sources", {}).items()
            if int(payload.get("reports_persisted", 0)) > 0
        ]
        return evaluate_curated_coverage_contract(
            database,
            profile_name="corpus",
            require_sources=completed or None,
            fail_hard=os.getenv("PSP_COVERAGE_FAIL_HARD", "false").lower() == "true",
        )

    @task
    def all_curated_timescale_task(
        collection: dict,
        rpc_collection: dict,
        run_meta: dict,
        retry: dict,
    ) -> int:
        """Append approved curated observations after catch-up and quarantine retry."""

        _ = collection
        _ = retry
        settings = load_settings()
        database = Path(os.getenv(
            "ALL_RLDC_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
        ))
        return export_all_curated_to_timescale(
            settings,
            database,
            target_date=date.fromisoformat(run_meta["target_date"]),
            report_document_ids=_rpc_report_ids(rpc_collection),
        )

    @task
    def all_curated_graph_task(
        collection: dict,
        rpc_collection: dict,
        run_meta: dict,
    ) -> int:
        """Synchronize approved 5-RLDC observations into Neo4j graph topology."""
        _ = collection
        settings = load_settings()
        database = Path(os.getenv(
            "ALL_RLDC_SQLITE_DB",
            settings.project_root / "data" / "sqlite" / "all_rldc_daily.sqlite",
        ))
        return sync_all_curated_to_graph(
            settings,
            database,
            target_date=date.fromisoformat(run_meta["target_date"]),
            report_document_ids=_rpc_report_ids(rpc_collection),
        )

    @task(trigger_rule="all_done")
    def pipeline_run_history_task(
        run_meta: dict,
        collection: dict,
        rpc_collection: dict,
        observations_inserted: int,
        graph_observations: int,
    ) -> dict:
        """Persist the run outcome even when an upstream source is partial."""

        return record_pipeline_run(
            load_settings(),
            run_id=run_meta["run_id"],
            started_at=datetime.fromisoformat(run_meta["started_at"]),
            collection=combine_collection_summaries(collection, rpc_collection),
            observations_inserted=observations_inserted,
            graph_observations=graph_observations,
        )

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

    # The unified branch owns daily public RLDC ingestion by default.  The
    # original generic/SRLDC paths remain available for controlled migration.
    if os.getenv("ENABLE_LEGACY_PSP_PIPELINES", "false").lower() == "true":
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

    all_rldc_collection = collect_all_rldc_task(run_meta)
    rpc_collection = collect_rpc_settlement_task(run_meta)
    catch_up = catch_up_missing_dates_task(run_meta, all_rldc_collection)
    quarantine_retry = quarantine_retry_task(catch_up)
    curated_freshness_task(run_meta, catch_up)
    national_balance_task(all_rldc_collection, run_meta, quarantine_retry)
    national_dimension_audit_task(all_rldc_collection, quarantine_retry)
    identity_adjudication_audit_task(all_rldc_collection, quarantine_retry)
    coverage_contract_task(all_rldc_collection, quarantine_retry)
    all_timescale = all_curated_timescale_task(
        all_rldc_collection, rpc_collection, run_meta, quarantine_retry
    )
    all_graph = all_curated_graph_task(all_rldc_collection, rpc_collection, run_meta)
    all_timescale >> all_graph
    pipeline_run_history_task(
        run_meta,
        all_rldc_collection,
        rpc_collection,
        all_timescale,
        all_graph,
    )


def _rpc_report_ids(collection: dict) -> list[int]:
    """Extract deduplicated persisted-report IDs from the RPC task payload."""

    return sorted(
        {
            int(report_id)
            for source in collection.get("sources", {}).values()
            for report_id in source.get("report_document_ids", [])
        }
    )


dag = psp_daily_public_ingestion()
