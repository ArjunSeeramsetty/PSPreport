-- Exported observation provenance remains in an ordinary table because source
-- cells are sparse metadata, not time-partitioned telemetry.
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
