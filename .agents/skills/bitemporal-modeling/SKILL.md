---
name: bitemporal-modeling
description: Use when modifying TimescaleDB/PostgreSQL schemas, fact tables, reconciliation persistence, 15-minute block telemetry, Bronze/Silver/Gold promotion, valid-time/system-time semantics, or correction/versioning logic.
---

# Bitemporal Modeling

## Temporal Semantics
- Keep valid time separate from system/ingestion time.
- Do not overwrite historical observations when corrections arrive.
- Insert a new version with the same valid time and newer system time or version number.
- Preserve Bronze raw artifacts even when Silver/Gold values supersede them.

## TimescaleDB Rules
- Any unique constraint on a hypertable must include the partitioning time column.
- Do not assume PostgreSQL 18 features such as `WITHOUT OVERLAPS` unless the runtime image is explicitly upgraded.
- For current compatibility, prefer conventional primary keys and unique indexes that include the hypertable time dimension.
- Use `time_bucket()` for aggregation and latest-system-time filtering for current-state queries.

## Observation Tables
- Keep `operational_value`, `settlement_value`, and `variance_pct` available for reconciliation.
- Store 15-minute or 5-minute telemetry in Timescale/Postgres, not Neo4j.
- Graph nodes should point to time-series UUIDs rather than storing high-volume blocks as graph nodes.

## Done Criteria
- Migration works on the configured local PostgreSQL/Timescale version.
- Unique constraints satisfy Timescale hypertable requirements.
- Revisions can be queried without losing original reported values.
