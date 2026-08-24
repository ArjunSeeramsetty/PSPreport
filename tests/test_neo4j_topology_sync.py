"""Tests for curated-dimension Neo4j topology projection and batch sync."""

from __future__ import annotations

import sqlite3

from psp_pipeline.storage.neo4j_repo import Neo4jRepository
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema
from psp_pipeline.storage.sqlite_topology_export import export_curated_topology


def test_topology_export_retains_indian_and_cross_border_endpoints() -> None:
    """The SQLite projection preserves state and country endpoints separately."""

    conn = sqlite3.connect(":memory:")
    ensure_curated_sqlite_schema(conn)
    assam = conn.execute("SELECT StateID FROM DimStates WHERE StateName = 'Assam'").fetchone()[0]
    ner = conn.execute("SELECT RegionID FROM DimRegions WHERE RegionName = 'North Eastern Region'").fetchone()[0]
    bhutan = conn.execute("SELECT CountryID FROM DimCountries WHERE CountryName = 'Bhutan'").fetchone()[0]
    conn.execute(
        "INSERT INTO DimTransmissionElements("
        "ElementName, ElementType, NominalVoltageKV, FromRegionID, FromStateID, ToCountryID"
        ") VALUES (?, ?, ?, ?, ?, ?)",
        ("132KV-RANGIA-DEOTHANG", "line", 132.0, ner, assam, bhutan),
    )
    topology = export_curated_topology(conn)

    line = topology["transmission_lines"][0]
    assert line["from_region_code"] == "NER"
    assert line["from_state_code"] == f"STATE-{assam}"
    assert line["to_country_code"] == f"COUNTRY-{bhutan}"
    assert line["to_state_code"] is None


def test_repository_runs_bounded_topology_batches_without_per_row_queries() -> None:
    """The graph repository uses parameterized UNWIND batches for topology."""

    class Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def run(
            self,
            query: str,
            params: dict[str, object] | None = None,
        ) -> None:
            self.calls.append((query, params or {}))

        def __enter__(self) -> "Session":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class Driver:
        def __init__(self) -> None:
            self.session_instance = Session()

        def session(self) -> Session:
            return self.session_instance

    repository = object.__new__(Neo4jRepository)
    repository.driver = Driver()
    repository.merge_grid_topology({
        "regions": [{"code": "SR", "name": "Southern Region"}],
        "countries": [],
        "states": [],
        "stations": [],
        "units": [],
        "grid_entities": [],
        "voltage_nodes": [],
        "transmission_lines": [],
    })

    assert len(repository.driver.session_instance.calls) == 1
    query, payload = repository.driver.session_instance.calls[0]
    assert "UNWIND $rows" in query
    assert payload == {"rows": [{"code": "SR", "name": "Southern Region"}]}


def test_repository_applies_each_idempotent_constraint_statement() -> None:
    """Constraint setup uses one session and preserves statement ordering."""

    class Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def run(
            self,
            query: str,
            params: dict[str, object] | None = None,
        ) -> None:
            self.calls.append((query, params or {}))

        def __enter__(self) -> "Session":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class Driver:
        def __init__(self) -> None:
            self.session_instance = Session()

        def session(self) -> Session:
            return self.session_instance

    repository = object.__new__(Neo4jRepository)
    repository.driver = Driver()
    repository.ensure_constraints(["CREATE CONSTRAINT one", "CREATE CONSTRAINT two"])

    assert repository.driver.session_instance.calls == [
        ("CREATE CONSTRAINT one", {}),
        ("CREATE CONSTRAINT two", {}),
    ]
