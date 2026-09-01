CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS ingest_lineage (
    lineage_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    parser_version TEXT NOT NULL,
    extraction_confidence DOUBLE PRECISION NOT NULL,
    report_type TEXT NOT NULL,
    source_region TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NULL,
    version_no INTEGER NOT NULL,
    raw_object_key TEXT NOT NULL,
    UNIQUE (run_id, source_id, content_hash, version_no)
);

CREATE TABLE IF NOT EXISTS fact_observation (
    observation_id BIGSERIAL,
    entity_key TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_id TEXT NULL,
    time_block TEXT NULL,
    operational_value DOUBLE PRECISION NULL,
    settlement_value DOUBLE PRECISION NULL,
    variance_pct DOUBLE PRECISION NULL,
    report_type TEXT NOT NULL,
    source_region TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NULL,
    version_no INTEGER NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    sys_to TIMESTAMPTZ NOT NULL DEFAULT 'infinity',
    series_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    report_document_id BIGINT NULL,
    timeseries_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
    canonical_entity_id UUID NULL,
    PRIMARY KEY (observation_id, ingested_at),
    UNIQUE (entity_key, metric_name, time_block, valid_from, version_no, ingested_at)
);

-- This ordinary table provides global UUID idempotency. A Timescale hypertable
-- cannot enforce a unique key unless it includes its partitioning time column.
CREATE TABLE IF NOT EXISTS fact_observation_dedup (
    timeseries_uuid UUID PRIMARY KEY,
    series_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_id TEXT NULL,
    time_block TEXT NULL,
    report_type TEXT NOT NULL,
    source_region TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NULL,
    first_ingested_at TIMESTAMPTZ NOT NULL,
    canonical_entity_id UUID NULL
);

-- Global current-truth enforcement belongs in an ordinary PostgreSQL table.
-- A Timescale hypertable cannot enforce a unique key without its partition time.
CREATE TABLE IF NOT EXISTS fact_observation_current (
    series_key TEXT PRIMARY KEY,
    timeseries_uuid UUID NOT NULL,
    system_from TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_observation_lineage (
    lineage_key UUID PRIMARY KEY,
    timeseries_uuid UUID NOT NULL,
    source_id TEXT NOT NULL,
    report_document_id BIGINT NOT NULL,
    content_hash TEXT NOT NULL,
    destination_table TEXT NOT NULL,
    destination_key TEXT NOT NULL,
    destination_column TEXT NOT NULL,
    raw_kind TEXT NOT NULL CHECK (raw_kind IN ('cell', 'text_item', 'line')),
    raw_item_id BIGINT NOT NULL,
    page_no INTEGER NULL,
    table_no INTEGER NULL,
    row_no INTEGER NULL,
    col_no INTEGER NULL,
    confidence DOUBLE PRECISION NOT NULL,
    extraction_method TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS fact_observation_lineage_timeseries_idx
    ON fact_observation_lineage (timeseries_uuid);

SELECT create_hypertable('fact_observation', by_range('ingested_at'), if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS fact_observation_series_history_idx
    ON fact_observation (series_key, ingested_at DESC);

ALTER TABLE fact_observation
    SET (
        timescaledb.compress = true,
        timescaledb.compress_orderby = 'ingested_at DESC',
        timescaledb.compress_segmentby = 'entity_key,metric_name'
    );

SELECT add_compression_policy('fact_observation', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('fact_observation', INTERVAL '5 years', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS reconciliation_result (
    reconciliation_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    time_block TEXT NULL,
    variance_pct DOUBLE PRECISION NULL,
    source_region TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL,
    UNIQUE (run_id, entity_key, metric_name, time_block)
);

CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id TEXT PRIMARY KEY,
    dag_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
    sources_requested INTEGER NOT NULL,
    sources_completed INTEGER NOT NULL,
    sources_failed INTEGER NOT NULL,
    observations_exported INTEGER NOT NULL,
    observations_inserted INTEGER NOT NULL,
    observations_deduplicated INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS pipeline_run_completed_at_idx
    ON pipeline_run (completed_at DESC);

CREATE TABLE IF NOT EXISTS canonical_entity (
    entity_id UUID PRIMARY KEY,
    entity_code TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    region_code TEXT NULL,
    state_code TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS canonical_entity_type_name_region_idx
    ON canonical_entity (entity_type, canonical_name, region_code, state_code);

CREATE TABLE IF NOT EXISTS canonical_entity_alias (
    alias_id BIGSERIAL PRIMARY KEY,
    entity_id UUID NOT NULL REFERENCES canonical_entity (entity_id),
    source_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    raw_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    observation_entity_key TEXT NULL,
    match_method TEXT NOT NULL,
    match_confidence DOUBLE PRECISION NOT NULL,
    approval_status TEXT NOT NULL
        CHECK (approval_status IN ('approved', 'auto_exact', 'pending', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_id, entity_type, normalized_name)
);

CREATE INDEX IF NOT EXISTS canonical_entity_alias_entity_idx
    ON canonical_entity_alias (entity_id);

CREATE INDEX IF NOT EXISTS canonical_entity_alias_observation_key_idx
    ON canonical_entity_alias (observation_entity_key);

CREATE TABLE IF NOT EXISTS canonical_entity_adjudication (
    issue_id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    raw_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    candidate_entity_id UUID NULL REFERENCES canonical_entity (entity_id),
    candidate_score DOUBLE PRECISION NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMPTZ NULL,
    decided_by TEXT NULL,
    UNIQUE (source_id, entity_type, normalized_name, reason)
);

CREATE TABLE IF NOT EXISTS fact_wide_daily (
    wide_fact_key TEXT PRIMARY KEY,
    grain_key TEXT NOT NULL,
    source_id TEXT NOT NULL,
    destination_table TEXT NOT NULL,
    destination_key TEXT NULL,
    report_document_id BIGINT NULL,
    content_hash TEXT NOT NULL,
    valid_date DATE NOT NULL,
    entity_key TEXT NOT NULL,
    canonical_entity_id UUID NULL,
    report_type TEXT NOT NULL,
    source_region TEXT NOT NULL,
    metrics JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_to TIMESTAMPTZ NOT NULL DEFAULT 'infinity'
);

CREATE INDEX IF NOT EXISTS fact_wide_daily_grain_history_idx
    ON fact_wide_daily (grain_key, ingested_at DESC);

CREATE TABLE IF NOT EXISTS fact_wide_daily_current (
    grain_key TEXT PRIMARY KEY,
    wide_fact_key TEXT NOT NULL,
    canonical_entity_id UUID NULL,
    system_from TIMESTAMPTZ NOT NULL
);

CREATE MATERIALIZED VIEW IF NOT EXISTS daily_regional_current_summary AS
SELECT
    observation.valid_from::date AS valid_date,
    observation.source_region,
    observation.entity_key,
    observation.metric_name,
    observation.time_block,
    observation.operational_value,
    observation.settlement_value,
    observation.variance_pct,
    observation.timeseries_uuid,
    observation.version_no,
    observation.ingested_at
FROM fact_observation AS observation
JOIN fact_observation_current AS current_truth
  ON current_truth.timeseries_uuid = observation.timeseries_uuid
WHERE observation.entity_key LIKE '%:region:%'
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS daily_regional_current_summary_grain_idx
    ON daily_regional_current_summary (
        valid_date, source_region, entity_key, metric_name, time_block
    );

CREATE OR REPLACE VIEW gold_wide_fact_current AS
SELECT
    fact.valid_date,
    fact.source_id,
    fact.source_region,
    fact.destination_table,
    fact.entity_key,
    COALESCE(fact.canonical_entity_id, current_truth.canonical_entity_id) AS canonical_entity_id,
    entity.entity_code,
    entity.entity_type,
    entity.canonical_name,
    entity.region_code AS entity_region_code,
    entity.state_code,
    fact.metrics,
    fact.wide_fact_key,
    current_truth.system_from
FROM fact_wide_daily AS fact
JOIN fact_wide_daily_current AS current_truth
  ON current_truth.wide_fact_key = fact.wide_fact_key
LEFT JOIN canonical_entity AS entity
  ON entity.entity_id = COALESCE(fact.canonical_entity_id, current_truth.canonical_entity_id);

CREATE OR REPLACE VIEW gold_canonical_daily_current AS
SELECT
    fact.valid_date,
    COALESCE(fact.canonical_entity_id, current_truth.canonical_entity_id) AS canonical_entity_id,
    entity.entity_code,
    entity.entity_type,
    entity.canonical_name,
    COALESCE(entity.region_code, fact.source_region) AS region_code,
    entity.state_code,
    fact.source_id,
    fact.source_region,
    fact.destination_table,
    fact.entity_key,
    COALESCE(
        (fact.metrics ->> 'DayEnergyMetMU')::double precision,
        (fact.metrics ->> 'EnergyMetMU')::double precision,
        (fact.metrics ->> 'EnergyMet')::double precision
    ) AS energy_met_mu,
    COALESCE(
        (fact.metrics ->> 'EveningPeakDemandMetMW')::double precision,
        (fact.metrics ->> 'PeakDemandMetMW')::double precision
    ) AS evening_peak_demand_met_mw,
    fact.metrics,
    fact.wide_fact_key,
    current_truth.system_from
FROM fact_wide_daily AS fact
JOIN fact_wide_daily_current AS current_truth
  ON current_truth.wide_fact_key = fact.wide_fact_key
LEFT JOIN canonical_entity AS entity
  ON entity.entity_id = COALESCE(fact.canonical_entity_id, current_truth.canonical_entity_id);

