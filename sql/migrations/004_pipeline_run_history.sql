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
