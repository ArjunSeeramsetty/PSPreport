-- Keep valid-date current truth separate from the ingestion-time hypertable.
-- See sql/timescale_current_truth_views.sql for the compatibility rationale.
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
