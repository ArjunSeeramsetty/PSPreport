-- Add a stable curated metric identity while retaining metric_name as the
-- source-prefixed compatibility alias used by existing clients.
ALTER TABLE fact_observation
    ADD COLUMN IF NOT EXISTS metric_id TEXT;

ALTER TABLE fact_observation_dedup
    ADD COLUMN IF NOT EXISTS metric_id TEXT;

UPDATE fact_observation
SET metric_id = regexp_replace(metric_name, '^[^.]+\.', '')
WHERE metric_id IS NULL;

UPDATE fact_observation_dedup
SET metric_id = regexp_replace(metric_name, '^[^.]+\.', '')
WHERE metric_id IS NULL;

CREATE INDEX IF NOT EXISTS fact_observation_metric_id_idx
    ON fact_observation (metric_id, valid_from DESC);
