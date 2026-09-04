"""Paused, isolated WBES schedule DAG.

This DAG is created paused and is not referenced by the public daily ingestion DAG.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task


DEFAULT_ARGS = {
    "owner": "psp",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}


@dag(
    dag_id="wbes_schedule_ingestion",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    is_paused_upon_creation=True,
    default_args=DEFAULT_ARGS,
    tags=["wbes", "controlled", "isolated"],
)
def wbes_schedule_ingestion():
    @task
    def run_isolated_wbes_schedule() -> dict:
        from psp_pipeline.wbes.pipeline import run_wbes_schedule
        from psp_pipeline.wbes.settings import load_wbes_settings

        settings = load_wbes_settings()
        return run_wbes_schedule(settings).as_dict()

    run_isolated_wbes_schedule()


wbes_schedule_ingestion()
