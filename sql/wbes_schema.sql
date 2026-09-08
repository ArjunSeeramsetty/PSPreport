-- Isolated WBES schedule-matrix schema.
-- Not part of sql/timescale_schema.sql and not required by public PSP bootstrap.
CREATE TABLE IF NOT EXISTS fact_wbes_block (
    observation_id BIGSERIAL,
    revision_uuid UUID NOT NULL,
    series_key TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    counterparty_key TEXT NULL,
    archetype TEXT NOT NULL,
    matrix_kind TEXT NOT NULL,
    schedule_component TEXT NULL,
    metric_name TEXT NOT NULL,
    time_block TEXT NOT NULL,
    block_no INTEGER NOT NULL,
    operational_value DOUBLE PRECISION NOT NULL,
    source_region TEXT NOT NULL,
    source_id TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    version_no INTEGER NOT NULL,
    revision_label TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    sys_to TIMESTAMPTZ NOT NULL DEFAULT 'infinity',
    content_hash TEXT NOT NULL,
    PRIMARY KEY (observation_id, ingested_at),
    UNIQUE (revision_uuid, ingested_at)
);

CREATE TABLE IF NOT EXISTS fact_wbes_block_dedup (
    revision_uuid UUID PRIMARY KEY,
    series_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fact_wbes_block_current (
    series_key TEXT PRIMARY KEY,
    revision_uuid UUID NOT NULL,
    system_from TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS fact_wbes_block_series_history_idx
    ON fact_wbes_block (series_key, ingested_at DESC);

SELECT create_hypertable('fact_wbes_block', by_range('ingested_at'), if_not_exists => TRUE);

ALTER TABLE fact_wbes_block
    SET (
        timescaledb.compress = true,
        timescaledb.compress_orderby = 'ingested_at DESC',
        timescaledb.compress_segmentby = 'entity_key,metric_name'
    );

SELECT add_compression_policy('fact_wbes_block', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('fact_wbes_block', INTERVAL '5 years', if_not_exists => TRUE);
