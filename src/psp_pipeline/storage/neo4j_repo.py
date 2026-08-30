from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None  # type: ignore[assignment]


class Neo4jRepository:
    def __init__(self, uri: str, user: str, password: str):
        if GraphDatabase is None:
            raise RuntimeError(
                "The 'neo4j' package is required to use Neo4jRepository. "
                "Install it with `pip install neo4j`."
            )
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    def merge_observation_topology(
        self,
        *,
        entity_key: str,
        report_type: str,
        metric_name: str,
        source_region: str,
        timeseries_uuid: str,
        time_block: Optional[str],
        series_key: str | None = None,
    ) -> None:
        region_code, source_entity_id = _split_entity_key(entity_key)
        observation_key = f"{entity_key}|{metric_name}|{time_block or 'NA'}"

        with self.driver.session() as session:
            session.run(
                """
                MERGE (r:Region {code: $region_code})

                MERGE (e:SourceEntity {entity_key: $entity_key})
                SET e.entity_id = $source_entity_id

                MERGE (rt:ReportType {name: $report_type})
                MERGE (m:Metric {name: $metric_name})
                MERGE (ts:TimeSeries {uuid: $series_key})

                MERGE (o:Observation {observation_key: $observation_key})
                SET o.time_block = $time_block

                MERGE (r)-[:HAS_ENTITY]->(e)
                MERGE (e)-[:IN_REPORT_TYPE]->(rt)
                MERGE (e)-[:HAS_TIMESERIES]->(ts)
                MERGE (ts)-[:FOR_METRIC]->(m)
                MERGE (e)-[:HAS_OBSERVATION]->(o)
                MERGE (o)-[:MEASURES]->(m)
                MERGE (o)-[:RECORDED_IN]->(r)
                """,
                {
                    "region_code": region_code,
                    "entity_key": entity_key,
                    "source_entity_id": source_entity_id,
                    "report_type": report_type,
                    "metric_name": metric_name,
                    "series_key": series_key or observation_key,
                    "observation_key": observation_key,
                    "time_block": time_block,
                },
            )

    def merge_observation_topologies(
        self,
        observations: Iterable[Mapping[str, object]],
    ) -> None:
        """Idempotently merge a bounded batch of observation topology links."""

        rows = []
        for observation in observations:
            entity_key = str(observation["entity_key"])
            region_code, source_entity_id = _split_entity_key(entity_key)
            metric_name = str(observation["metric_name"])
            time_block = observation.get("time_block")
            state_code = (
                source_entity_id.removeprefix("state:")
                if source_entity_id.startswith("state:")
                else None
            )
            rows.append(
                {
                    "region_code": region_code,
                    "entity_key": entity_key,
                    "source_entity_id": source_entity_id,
                    "state_code": state_code,
                    "report_type": str(observation["report_type"]),
                    "metric_name": metric_name,
                    "series_key": str(
                        observation.get("series_key")
                        or f"{entity_key}|{metric_name}|{time_block or 'NA'}"
                    ),
                    "observation_key": (
                        f"{entity_key}|{metric_name}|{time_block or 'NA'}"
                    ),
                    "time_block": time_block,
                }
            )
        if not rows:
            return
        with self.driver.session() as session:
            session.run(
                """
                UNWIND $rows AS row
                MERGE (r:Region {code: row.region_code})
                MERGE (e:SourceEntity {entity_key: row.entity_key})
                ON CREATE SET e.entity_id = row.source_entity_id,
                              e.created_at = datetime(),
                              e.last_seen_at = datetime()
                ON MATCH SET e.entity_id = row.source_entity_id,
                             e.last_seen_at = datetime()
                MERGE (rt:ReportType {name: row.report_type})
                MERGE (m:Metric {name: row.metric_name})
                MERGE (ts:TimeSeries {uuid: row.series_key})
                MERGE (o:Observation {observation_key: row.observation_key})
                ON CREATE SET o.time_block = row.time_block,
                              o.created_at = datetime(),
                              o.last_seen_at = datetime()
                ON MATCH SET o.time_block = row.time_block,
                             o.last_seen_at = datetime()
                FOREACH (_ IN CASE WHEN row.state_code IS NULL THEN [] ELSE [1] END |
                    MERGE (s:State {code: row.state_code})
                    MERGE (r)-[:CONTAINS_STATE]->(s)
                    MERGE (s)-[:HAS_ENTITY]->(e)
                )
                FOREACH (_ IN CASE WHEN row.state_code IS NULL THEN [1] ELSE [] END |
                    MERGE (r)-[:HAS_ENTITY]->(e)
                )
                MERGE (e)-[:IN_REPORT_TYPE]->(rt)
                MERGE (e)-[:HAS_TIMESERIES]->(ts)
                MERGE (ts)-[:FOR_METRIC]->(m)
                MERGE (e)-[:HAS_OBSERVATION]->(o)
                MERGE (o)-[:MEASURES]->(m)
                MERGE (o)-[:RECORDED_IN]->(r)
                """,
                {"rows": rows},
            )

    def merge_daily_observation_values(
        self,
        observations: Iterable[Mapping[str, object]],
    ) -> None:
        """Merge immutable, date-scoped measurement versions under a time series."""

        rows = []
        for observation in observations:
            entity_key = str(observation["entity_key"])
            metric_name = str(observation["metric_name"])
            time_block = observation.get("time_block")
            rows.append(
                {
                    "series_key": str(
                        observation.get("series_key")
                        or f"{entity_key}|{metric_name}|{time_block or 'NA'}"
                    ),
                    "timeseries_uuid": str(observation["timeseries_uuid"]),
                    "operational_value": observation.get("operational_value"),
                    "valid_from": _iso_datetime(observation["valid_from"]),
                    "valid_to": _iso_datetime(observation.get("valid_to")),
                    "ingested_at": _iso_datetime(observation["ingested_at"]),
                    "version_no": int(observation["version_no"]),
                    "report_type": str(observation["report_type"]),
                    "source_region": str(observation["source_region"]),
                }
            )
        if not rows:
            return
        with self.driver.session() as session:
            session.run(_OBSERVATION_VERSION_QUERY, {"rows": rows})

    def retire_observation_versions(
        self,
        timeseries_uuids: Iterable[str],
        retired_at: datetime,
    ) -> None:
        """Close graph measurement versions retired by a Timescale snapshot."""

        rows = [
            {"timeseries_uuid": str(timeseries_uuid), "retired_at": _iso_datetime(retired_at)}
            for timeseries_uuid in timeseries_uuids
        ]
        if not rows:
            return
        with self.driver.session() as session:
            session.run(_RETIRE_OBSERVATION_VERSION_QUERY, {"rows": rows})

    def merge_grid_topology(self, topology: Mapping[str, list[Mapping[str, Any]]]) -> None:
        """Idempotently merge curated dimension topology in bounded batches."""

        with self.driver.session() as session:
            _run_batches(session, _REGION_QUERY, topology.get("regions", []))
            _run_batches(session, _COUNTRY_QUERY, topology.get("countries", []))
            _run_batches(session, _STATE_QUERY, topology.get("states", []))
            _run_batches(session, _STATION_QUERY, topology.get("stations", []))
            _run_batches(session, _UNIT_QUERY, topology.get("units", []))
            _run_batches(session, _GRID_ENTITY_QUERY, topology.get("grid_entities", []))
            _run_batches(session, _VOLTAGE_NODE_QUERY, topology.get("voltage_nodes", []))
            _run_batches(
                session,
                _TRANSMISSION_LINE_QUERY,
                topology.get("transmission_lines", []),
            )

    def ensure_constraints(self, statements: Iterable[str]) -> None:
        """Apply idempotent Cypher constraints before a graph synchronization."""

        with self.driver.session() as session:
            for statement in statements:
                session.run(statement)


def _split_entity_key(entity_key: str) -> tuple[str, str]:
    if ":" not in entity_key:
        return "NATIONAL", entity_key
    region, entity = entity_key.split(":", 1)
    return region or "NATIONAL", entity or entity_key


def _iso_datetime(value: object | None) -> str | None:
    """Convert supported datetime inputs to the ISO form accepted by Cypher."""

    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _run_batches(session: Any, query: str, rows: list[Mapping[str, Any]]) -> None:
    """Run bounded parameterized batches to limit lock contention."""

    for start in range(0, len(rows), 500):
        session.run(query, {"rows": rows[start:start + 500]})


_REGION_QUERY = """
UNWIND $rows AS row
MERGE (region:Region {code: row.code})
ON CREATE SET region.name = row.name, region.created_at = datetime()
ON MATCH SET region.name = row.name, region.last_seen_at = datetime()
"""

_COUNTRY_QUERY = """
UNWIND $rows AS row
MERGE (country:Country {code: row.code})
ON CREATE SET country.name = row.name, country.created_at = datetime()
ON MATCH SET country.name = row.name, country.last_seen_at = datetime()
"""

_STATE_QUERY = """
UNWIND $rows AS row
MERGE (state:State {code: row.code})
ON CREATE SET state.name = row.name, state.created_at = datetime()
ON MATCH SET state.name = row.name, state.last_seen_at = datetime()
WITH row, state
FOREACH (_ IN CASE WHEN row.region_code IS NULL THEN [] ELSE [1] END |
  MERGE (region:Region {code: row.region_code})
  MERGE (state)-[:LOCATED_IN]->(region)
  MERGE (region)-[:CONTAINS_STATE]->(state)
)
"""

_STATION_QUERY = """
UNWIND $rows AS row
MERGE (station:GridEntity:PowerStation {key: row.key})
ON CREATE SET station.name = row.name, station.created_at = datetime()
ON MATCH SET station.name = row.name, station.last_seen_at = datetime()
SET station.capacity_mw = row.capacity_mw
WITH row, station
FOREACH (_ IN CASE WHEN row.state_code IS NULL THEN [] ELSE [1] END |
  MERGE (state:State {code: row.state_code})
  MERGE (station)-[:LOCATED_IN]->(state)
)
"""

_UNIT_QUERY = """
UNWIND $rows AS row
MERGE (unit:GridEntity:GeneratingUnit {key: row.key})
ON CREATE SET unit.name = row.name, unit.created_at = datetime()
ON MATCH SET unit.name = row.name, unit.last_seen_at = datetime()
SET unit.unit_number = row.unit_number, unit.capacity_mw = row.capacity_mw
WITH row, unit
MERGE (station:GridEntity:PowerStation {key: row.station_key})
MERGE (unit)-[:UNIT_OF]->(station)
"""

_GRID_ENTITY_QUERY = """
UNWIND $rows AS row
MERGE (entity:GridEntity {key: row.key})
ON CREATE SET entity.name = row.name, entity.entity_type = row.entity_type,
              entity.created_at = datetime()
ON MATCH SET entity.name = row.name, entity.entity_type = row.entity_type,
             entity.last_seen_at = datetime()
SET entity.capacity_mw = row.capacity_mw,
    entity.observation_entity_key = row.observation_entity_key
WITH row, entity
FOREACH (_ IN CASE WHEN row.state_code IS NULL THEN [] ELSE [1] END |
  MERGE (state:State {code: row.state_code})
  MERGE (entity)-[:LOCATED_IN]->(state)
)
FOREACH (_ IN CASE WHEN row.observation_entity_key IS NULL THEN [] ELSE [1] END |
  MERGE (source:SourceEntity {entity_key: row.observation_entity_key})
  MERGE (source)-[:DESCRIBES]->(entity)
)
"""

_VOLTAGE_NODE_QUERY = """
UNWIND $rows AS row
MERGE (node:VoltageNode {key: row.key})
ON CREATE SET node.name = row.name, node.created_at = datetime()
ON MATCH SET node.name = row.name, node.last_seen_at = datetime()
SET node.nominal_voltage_kv = row.nominal_voltage_kv,
    node.observation_entity_key = row.observation_entity_key
WITH row, node
FOREACH (_ IN CASE WHEN row.state_code IS NULL THEN [] ELSE [1] END |
  MERGE (state:State {code: row.state_code})
  MERGE (node)-[:LOCATED_IN]->(state)
)
FOREACH (_ IN CASE WHEN row.observation_entity_key IS NULL THEN [] ELSE [1] END |
  MERGE (source:SourceEntity {entity_key: row.observation_entity_key})
  MERGE (source)-[:DESCRIBES]->(node)
)
"""

_TRANSMISSION_LINE_QUERY = """
UNWIND $rows AS row
MERGE (line:TransmissionLine {key: row.key})
ON CREATE SET line.name = row.name, line.created_at = datetime()
ON MATCH SET line.name = row.name, line.last_seen_at = datetime()
SET line.element_type = row.element_type,
    line.nominal_voltage_kv = row.nominal_voltage_kv,
    line.observation_entity_key = row.observation_entity_key
WITH row, line
FOREACH (_ IN CASE WHEN row.from_state_code IS NULL THEN [] ELSE [1] END |
  MERGE (state:State {code: row.from_state_code})
  MERGE (line)-[:CONNECTS_TO {side: 'from'}]->(state)
)
FOREACH (_ IN CASE WHEN row.to_state_code IS NULL THEN [] ELSE [1] END |
  MERGE (state:State {code: row.to_state_code})
  MERGE (line)-[:CONNECTS_TO {side: 'to'}]->(state)
)
FOREACH (_ IN CASE WHEN row.from_country_code IS NULL THEN [] ELSE [1] END |
  MERGE (country:Country {code: row.from_country_code})
  MERGE (line)-[:TIE_BETWEEN {side: 'from'}]->(country)
)
FOREACH (_ IN CASE WHEN row.to_country_code IS NULL THEN [] ELSE [1] END |
  MERGE (country:Country {code: row.to_country_code})
  MERGE (line)-[:TIE_BETWEEN {side: 'to'}]->(country)
)
FOREACH (_ IN CASE WHEN row.observation_entity_key IS NULL THEN [] ELSE [1] END |
  MERGE (source:SourceEntity {entity_key: row.observation_entity_key})
  MERGE (source)-[:DESCRIBES]->(line)
)
"""

_OBSERVATION_VERSION_QUERY = """
UNWIND $rows AS row
MERGE (ts:TimeSeries {uuid: row.series_key})
SET ts.series_key = row.series_key,
    ts.last_seen_at = datetime()
WITH row, ts
OPTIONAL MATCH (ts)-[:HAS_VERSION]->(previous:ObservationVersion)
WHERE previous.sys_to = 'infinity'
  AND previous.timeseries_uuid <> row.timeseries_uuid
  AND previous.ingested_at < datetime(row.ingested_at)
FOREACH (_ IN CASE WHEN previous IS NULL THEN [] ELSE [1] END |
  SET previous.sys_to = row.ingested_at
)
WITH row, ts
MERGE (version:ObservationVersion {timeseries_uuid: row.timeseries_uuid})
ON CREATE SET version.created_at = datetime(),
              version.operational_value = row.operational_value,
              version.valid_from = datetime(row.valid_from),
              version.valid_to = CASE WHEN row.valid_to IS NULL THEN NULL ELSE datetime(row.valid_to) END,
              version.ingested_at = datetime(row.ingested_at),
              version.sys_to = 'infinity',
              version.version_no = row.version_no,
              version.report_type = row.report_type,
              version.source_region = row.source_region
ON MATCH SET version.last_seen_at = datetime()
MERGE (ts)-[:HAS_VERSION]->(version)
"""

_RETIRE_OBSERVATION_VERSION_QUERY = """
UNWIND $rows AS row
MATCH (version:ObservationVersion {timeseries_uuid: row.timeseries_uuid})
WHERE version.sys_to = 'infinity'
SET version.sys_to = datetime(row.retired_at),
    version.retired_at = datetime(row.retired_at)
"""
