# Autonomous Indian Power-System KG Pipeline

This repository now includes a local/open-source-first build for:
- RLDC/NLDC/RPC public report ingestion (Phase A)
- Bitemporal Bronze/Silver/Gold data model
- Hybrid Graph + Time-Series architecture (Neo4j + TimescaleDB)
- WBES controlled-access onboarding path (Phase B+)

## Implemented Components
- Autonomous agents:
  - `source_discovery_agent`
  - `report_fetch_agent`
  - `parser_agent`
  - `schema_drift_agent`
  - `recon_agent`
  - `graph_sync_agent`
  - `dq_alert_agent`
- RPC settlement layer:
  - weekly DSM entity charges, sustained deviation penalties, and ancillary payments
  - monthly REA station PAFM / deemed generation and peak/off-peak allocations
  - header-driven table location, malformed-pair skip, unsupported-family quarantine
- Data contracts and source registry (`src/psp_pipeline/models/`)
- Pipeline flow (`src/psp_pipeline/pipelines/bronze_pipeline.py`)
- Stage decomposition (`src/psp_pipeline/pipelines/stages.py`)
- Airflow DAG (`dags/psp_daily_pipeline.py`)
- Timescale schema (`sql/timescale_schema.sql`)
- Neo4j constraints (`sql/neo4j_constraints.cypher`)
- Local infra stack (`docker-compose.yml`)
- Isolated WBES schedule pipeline (`src/psp_pipeline/wbes/`, `scripts/run_wbes_schedule.py`)

## Operational Defaults
- Retry policy: 3 attempts, exponential backoff with jitter (configurable via `.env`).
- Preflight: HEAD check before GET; validates status and rejects explicit `Content-Length: 0`.
- Dedup: content-hash dedup against `ingest_lineage` (no separate dedup table).
- Failure policy: source-level fail-soft (continue with others), tracked via `artifacts_failed`.
- Reconciliation: variance persisted to `reconciliation_result` and mirrored into `fact_observation.variance_pct`.

## Source Targets Included
RLDC: SRLDC, NRLDC, NERLDC, WRLDC, ERLDC  
RPC: ERPC, NRPC, SRPC, WRPC, NERPC  
NLDC/GRID-INDIA: national reports and inter-regional families  
WBES: `newwbes.grid-india.in` marked as controlled-access source

## Quick Start
1. Create and activate a virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Copy env template:
   - `copy .env.example .env`
4. Start infrastructure:
   - `powershell -ExecutionPolicy Bypass -File scripts/bootstrap_local.ps1`
5. Recreate Timescale from `sql/timescale_schema.sql` and backfill curated SQLite:
   - `set PYTHONPATH=src`
   - `python scripts/bootstrap_timescale_from_sqlite.py --db data/sqlite/all_rldc_daily.sqlite --recreate-schema`
6. Publish canonical identities and Postgres-primary wide facts without dropping schema:
   - `python scripts/publish_curated_postgres.py --db data/sqlite/all_rldc_daily.sqlite`
7. Run public ingestion:
   - `python scripts/run_public_ingestion.py`
8. Collect public RPC DSM/REA settlement accounts:
   - `python scripts/run_rpc_settlement.py`

## Airflow
- UI: `http://localhost:8080`
- DAG: `psp_daily_public_ingestion`
- Task-level stages: discover -> fetch -> dedup -> parse -> reconcile -> persist_raw -> persist_sql -> sync_graph -> dq_summary

## WBES Rollout
- Phase A: public sources live. The daily DAG never calls WBES.
- Isolated pipeline (disabled by default): `scripts/run_wbes_schedule.py`
  - Drop canonical JSON/XLSX into `data/wbes/drop/` and run with `WBES_ENABLED=true`.
  - Live portal probe/fetch also requires `WBES_ALLOW_LIVE_NETWORK=true`.
  - Block facts persist to `data/wbes/wbes_schedule.sqlite`, not the PSP SQLite DB.
  - Timescale publish is opt-in via `WBES_WRITE_TIMESCALE=true` (`sql/wbes_schema.sql`).
  - Neo4j is not updated.
- Airflow DAG `wbes_schedule_ingestion` is created paused and is not wired into `psp_daily_public_ingestion`.
- Probe only: `WBES_ENABLED=true WBES_ALLOW_LIVE_NETWORK=true python scripts/run_wbes_probe.py`

See [`docs/BLOCKERS_AND_SOLUTIONS.md`](docs/BLOCKERS_AND_SOLUTIONS.md) for known risks and mitigations.

## Neo4j Model
Neo4j now stores relationship topology for observations:
- `Region` -> `SourceEntity` -> `TimeSeries` -> `Metric`
- `SourceEntity` -> `Observation` -> `Metric`
- `Observation` -> `Region`
- `SourceEntity`/`Region`/`State` -> `IDENTIFIES` -> `CanonicalEntity`

Postgres is the published system of record for canonical aliases and wide daily facts (`fact_wide_daily`). Fuzzy name matches are queued in `canonical_entity_adjudication` and never auto-merged.
