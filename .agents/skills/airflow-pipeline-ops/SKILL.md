---
name: airflow-pipeline-ops
description: Use when modifying, testing, or debugging this repository's Airflow DAGs and pipeline stage orchestration, especially dags/psp_daily_pipeline.py, XCom payloads, task decomposition, local DAG execution, or fail-soft source handling.
---

# Airflow Pipeline Ops

## Workflow
- Keep DAG files thin: task functions should call reusable code from `src/psp_pipeline/pipelines/`.
- Prefer decomposed tasks over one large `PythonOperator`.
- Pass small serialized payloads through XCom; use object storage or database tables for large artifacts.
- Keep public ingestion fail-soft at source level: one failed source should be counted and logged, not halt unrelated sources.

## Local Validation
- Do not start the Airflow webserver or scheduler to debug pure Python changes.
- Test stage functions directly with pytest where possible.
- For DAG smoke testing, prefer Airflow's local `dag.test()` pattern or task-level invocation with mocked settings.
- Patch environment variables and external repositories in tests; do not require live TimescaleDB, Neo4j, MinIO, or Airflow metadata DB unless running explicit integration tests.

## Done Criteria
- DAG imports without side effects.
- Task boundaries remain clear: discover, fetch, dedup, parse, reconcile, persist raw, persist SQL, sync graph, summarize DQ.
- Retries/backoff are configured at source connector level, not only as Airflow task retries.
