from __future__ import annotations

from typing import Optional

from neo4j import GraphDatabase


class Neo4jRepository:
    def __init__(self, uri: str, user: str, password: str):
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


def _split_entity_key(entity_key: str) -> tuple[str, str]:
    if ":" not in entity_key:
        return "NATIONAL", entity_key
    region, entity = entity_key.split(":", 1)
    return region or "NATIONAL", entity or entity_key
