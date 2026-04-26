from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.core.settings import load_settings
from psp_pipeline.pipelines.bronze_pipeline import run_bronze


def run_public_pipeline() -> None:
    configure_logging("INFO")
    settings = load_settings()
    result = run_bronze(settings, include_controlled=False)
    print(result)


with DAG(
    dag_id="psp_daily_public_ingestion",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["power", "psp", "bronze"],
) as dag:
    ingest = PythonOperator(
        task_id="run_public_ingestion",
        python_callable=run_public_pipeline,
    )

    ingest

