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
- Data contracts and source registry (`src/psp_pipeline/models/`)
- Pipeline flow (`src/psp_pipeline/pipelines/bronze_pipeline.py`)
- Airflow DAG (`dags/psp_daily_pipeline.py`)
- Timescale schema (`sql/timescale_schema.sql`)
- Neo4j constraints (`sql/neo4j_constraints.cypher`)
- Local infra stack (`docker-compose.yml`)
- WBES probe stub (`scripts/run_wbes_probe.py`)

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
5. Run public ingestion:
   - `set PYTHONPATH=src`
   - `python scripts/run_public_ingestion.py`

## Airflow
- UI: `http://localhost:8080`
- DAG: `psp_daily_public_ingestion`

## WBES Rollout
- Phase A: public sources live.
- Phase B: credential and compliance onboarding.
- Phase C+: Playwright login + endpoint catalog + 96-block extraction.

See [`docs/BLOCKERS_AND_SOLUTIONS.md`](/C:/Users/arjun/Desktop/PSPreport/docs/BLOCKERS_AND_SOLUTIONS.md) for known risks and mitigations.

