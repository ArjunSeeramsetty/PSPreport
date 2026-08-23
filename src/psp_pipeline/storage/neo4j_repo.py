from __future__ import annotations

from typing import Iterable, Mapping, Optional

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
                MERGE (ts:TimeSeries {uuid: $timeseries_uuid})

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
                    "timeseries_uuid": timeseries_uuid,
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
                    "timeseries_uuid": str(observation["timeseries_uuid"]),
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
                MERGE (ts:TimeSeries {uuid: row.timeseries_uuid})
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


def _split_entity_key(entity_key: str) -> tuple[str, str]:
    if ":" not in entity_key:
        return "NATIONAL", entity_key
    region, entity = entity_key.split(":", 1)
    return region or "NATIONAL", entity or entity_key
