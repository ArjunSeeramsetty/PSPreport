-- Add bitemporal revision state without rebuilding the Timescale hypertable.
ALTER TABLE fact_observation
    ADD COLUMN IF NOT EXISTS sys_to TIMESTAMPTZ NOT NULL DEFAULT 'infinity';

ALTER TABLE fact_observation
    ADD COLUMN IF NOT EXISTS series_key TEXT;

ALTER TABLE fact_observation
    ADD COLUMN IF NOT EXISTS content_hash TEXT;

ALTER TABLE fact_observation
    ADD COLUMN IF NOT EXISTS report_document_id BIGINT;

UPDATE fact_observation
SET series_key = jsonb_build_object(
    'entity_key', entity_key,
    'metric_name', metric_name,
    'report_type', report_type,
    'source_region', source_region,
    'time_block', time_block,
    'valid_from', valid_from,
    'valid_to', valid_to
)::text
WHERE series_key IS NULL;

UPDATE fact_observation
SET content_hash = 'legacy:' || timeseries_uuid::text
WHERE content_hash IS NULL;

-- Existing revisions become a valid system-time history before current-state
-- tracking is enabled. The latest row for each logical series stays open.
WITH ordered_versions AS (
    SELECT
        observation_id,
        ingested_at,
        lead(ingested_at, 1, 'infinity'::timestamptz) OVER (
            PARTITION BY series_key
            ORDER BY ingested_at, version_no, observation_id
        ) AS next_system_from
    FROM fact_observation
)
UPDATE fact_observation AS observation
SET sys_to = ordered_versions.next_system_from
FROM ordered_versions
WHERE observation.observation_id = ordered_versions.observation_id;

CREATE TABLE IF NOT EXISTS fact_observation_current (
    series_key TEXT PRIMARY KEY,
    timeseries_uuid UUID NOT NULL,
    system_from TIMESTAMPTZ NOT NULL
);

INSERT INTO fact_observation_current(series_key, timeseries_uuid, system_from)
SELECT DISTINCT ON (series_key)
    series_key,
    timeseries_uuid,
    ingested_at
FROM fact_observation
WHERE sys_to = 'infinity'
ORDER BY series_key, ingested_at DESC, version_no DESC, observation_id DESC
ON CONFLICT (series_key) DO UPDATE SET
    timeseries_uuid = EXCLUDED.timeseries_uuid,
    system_from = EXCLUDED.system_from;

CREATE INDEX IF NOT EXISTS fact_observation_series_history_idx
    ON fact_observation (series_key, ingested_at DESC);

ALTER TABLE fact_observation_dedup
    ADD COLUMN IF NOT EXISTS series_key TEXT;

ALTER TABLE fact_observation_dedup
    ADD COLUMN IF NOT EXISTS content_hash TEXT;
