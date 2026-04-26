---
name: neo4j-graph-sync
description: Use when modifying Neo4j constraints, graph synchronization, Cypher MERGE logic, batch UNWIND ingestion, topology mapping, time-series UUID links, or graph idempotency for the Indian power-system knowledge graph.
---

# Neo4j Graph Sync

## Graph Principles
- Neo4j stores topology, hierarchy, metadata, and links to time-series UUIDs.
- Do not store high-volume 15-minute telemetry as graph nodes or relationships.
- Model relationships explicitly: Region, SourceEntity, ReportType, Metric, TimeSeries, Observation.

## Cypher Rules
- Use `MERGE` for idempotent ingestion.
- Use `ON CREATE SET` for immutable creation metadata.
- Use `ON MATCH SET` for `last_seen_at` and refresh metadata.
- Prefer parameterized `UNWIND` batch queries over per-row Python loops.
- Create constraints before graph sync jobs run.

## Lock-Safety
- Avoid parallel batches that repeatedly merge relationships into the same high-level node.
- Merge static nodes once per batch when possible.
- Keep batch payloads bounded and retry transient lock failures where appropriate.

## Done Criteria
- Re-running graph sync does not duplicate nodes.
- Required uniqueness constraints exist in `sql/neo4j_constraints.cypher`.
- Graph entities can be traced back to Timescale/relational identifiers.
