-- Isolated WBES 96-block schedule matrix. Disabled in the public DAG.
-- Chunk by valid_from (7 days) and hash-partition grain_key for dense I/O.
CREATE TABLE IF NOT EXISTS fact_wbes_block (
    grain_key TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    sys_from TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_to TIMESTAMPTZ NOT NULL DEFAULT 'infinity',
    version_no INTEGER NOT NULL,
    block_no INTEGER NOT NULL CHECK (block_no BETWEEN 1 AND 96),
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION NULL,
    content_hash TEXT NOT NULL,
    report_document_id BIGINT NULL,
    timeseries_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
    PRIMARY KEY (grain_key, valid_from, version_no, sys_from)
);

SELECT create_hypertable(
    'fact_wbes_block',
    by_range('valid_from', INTERVAL '7 days'),
    if_not_exists => TRUE
);

SELECT add_dimension(
    'fact_wbes_block',
    by_hash('grain_key', 4),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS fact_wbes_block_active_idx
    ON fact_wbes_block (grain_key, valid_from DESC)
    WHERE sys_to = 'infinity';
