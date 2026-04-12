from neo4j import GraphDatabase

NEO4J_URI = "neo4j://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "powerflow"

EXPECTED_LABELS = [
    "Report", "Metric", "MetricObservation", "GenerationSource", "GenerationObservation",
    "ExchangeMechanism", "ExchangeObservation", "State", "Region", "Country", "PowerLine", "TimeBlock"
]
EXPECTED_REL_TYPES = [
    "HAS_OBSERVATION", "IS_METRIC", "APPLIES_TO", "HAS_GENERATION", "OF_SOURCE", "IN_REPORT",
    "HAS_EXCHANGE", "USES_MECHANISM", "WITH", "EXCHANGED_POWER_WITH", "IN_REGION", "CONNECTS_TO",
    "REPORTS_POWERLINE", "FOR_DAY", "HAS_DATA_FOR_BLOCK", "NEXT", "NEXT_DAY"
]

SUPER_NODE_LABELS = ["Metric", "GenerationSource", "ExchangeMechanism", "PowerLine"]
SUPER_NODE_THRESHOLD = 10000

def test_connection(session):
    try:
        result = session.run("RETURN 1 AS test")
        assert result.single()["test"] == 1
        print("[PASS] Connection to Neo4j successful.")
    except Exception as e:
        print(f"[FAIL] Connection test failed: {e}")

def test_node_and_rel_counts(session):
    node_count = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
    rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
    print(f"[INFO] Node count: {node_count}")
    print(f"[INFO] Relationship count: {rel_count}")
    if node_count == 0:
        print("[FAIL] No nodes found in the graph.")
    if rel_count == 0:
        print("[FAIL] No relationships found in the graph.")

def test_labels_exist(session):
    labels = set(record["label"] for record in session.run("CALL db.labels() YIELD label"))
    missing = [l for l in EXPECTED_LABELS if l not in labels]
    for l in EXPECTED_LABELS:
        count = session.run(f"MATCH (n:{l}) RETURN count(n) AS count").single()["count"]
        print(f"[INFO] {l}: {count} nodes")
    if missing:
        print(f"[FAIL] Missing expected labels: {missing}")

def test_rel_types_exist(session):
    rel_types = set(record[0] for record in session.run("CALL db.relationshipTypes()"))
    missing = [r for r in EXPECTED_REL_TYPES if r not in rel_types]
    for r in EXPECTED_REL_TYPES:
        count = session.run(f"MATCH ()-[:{r}]->() RETURN count(*) AS count").single()["count"]
        print(f"[INFO] {r}: {count} relationships")
    if missing:
        print(f"[FAIL] Missing expected relationship types: {missing}")

def test_orphaned_observations(session):
    # MetricObservation
    mo_orphan = session.run("""
        MATCH (mo:MetricObservation)
        WHERE NOT (mo)<-[:HAS_OBSERVATION]-(:Report)
           OR NOT (mo)-[:IS_METRIC]->(:Metric)
           OR NOT (mo)-[:APPLIES_TO]->()
        RETURN count(mo) AS count
    """).single()["count"]
    # GenerationObservation
    go_orphan = session.run("""
        MATCH (go:GenerationObservation)
        WHERE NOT (go)<-[:HAS_GENERATION]-(:Region)
           OR NOT (go)-[:OF_SOURCE]->(:GenerationSource)
           OR NOT (go)-[:IN_REPORT]->(:Report)
        RETURN count(go) AS count
    """).single()["count"]
    # ExchangeObservation
    eo_orphan = session.run("""
        MATCH (eo:ExchangeObservation)
        WHERE NOT (eo)<-[:HAS_EXCHANGE]-(:Country)
           OR NOT (eo)-[:USES_MECHANISM]->(:ExchangeMechanism)
           OR NOT (eo)-[:WITH]->(:Country)
        RETURN count(eo) AS count
    """).single()["count"]
    if mo_orphan == 0:
        print("[PASS] No orphaned MetricObservation nodes.")
    else:
        print(f"[FAIL] {mo_orphan} orphaned MetricObservation nodes found.")
    if go_orphan == 0:
        print("[PASS] No orphaned GenerationObservation nodes.")
    else:
        print(f"[FAIL] {go_orphan} orphaned GenerationObservation nodes found.")
    if eo_orphan == 0:
        print("[PASS] No orphaned ExchangeObservation nodes.")
    else:
        print(f"[FAIL] {eo_orphan} orphaned ExchangeObservation nodes found.")

def test_supernodes(session):
    for label in SUPER_NODE_LABELS:
        result = session.run(f"""
            MATCH (n:{label})
            WITH n, COUNT {{ (n)--() }} AS degree
            WHERE degree > $threshold
            RETURN n.name AS name, degree
            ORDER BY degree DESC
            LIMIT 5
        """, threshold=SUPER_NODE_THRESHOLD)
        found = False
        for record in result:
            found = True
            print(f"[FAIL] Supernode detected: {label} '{record['name']}' with degree {record['degree']}")
        if not found:
            print(f"[PASS] No supernodes detected for label {label} (threshold {SUPER_NODE_THRESHOLD}).")

def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session(database="neo4j") as session:
        print("\n--- Neo4j Graph DB Test ---\n")
        test_connection(session)
        test_node_and_rel_counts(session)
        test_labels_exist(session)
        test_rel_types_exist(session)
        test_orphaned_observations(session)
        test_supernodes(session)
    driver.close()
    print("\n--- Test Complete ---\n")

if __name__ == "__main__":
    main() 