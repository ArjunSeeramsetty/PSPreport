from __future__ import annotations

from neo4j import GraphDatabase


class Neo4jRepository:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    def merge_entity(self, *, entity_key: str, entity_type: str, timeseries_uuid: str) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MERGE (e:GridEntity {entity_key: $entity_key})
                SET e.entity_type = $entity_type,
                    e.timeseries_uuid = $timeseries_uuid
                """,
                {
                    "entity_key": entity_key,
                    "entity_type": entity_type,
                    "timeseries_uuid": timeseries_uuid,
                },
            )

