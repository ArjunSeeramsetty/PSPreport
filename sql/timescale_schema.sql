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
    timeseries_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
    PRIMARY KEY (observation_id, ingested_at),
    UNIQUE (entity_key, metric_name, time_block, valid_from, version_no)
);

SELECT create_hypertable('fact_observation', by_range('ingested_at'), if_not_exists => TRUE);

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
