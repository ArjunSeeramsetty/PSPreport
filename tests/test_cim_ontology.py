"""Tests for IEC 61970/61968 CIM annotations and native Cypher batching."""

from __future__ import annotations

from psp_pipeline.storage.cim_ontology import (
    CIM_AC_LINE_SEGMENT,
    CIM_ENERGY_SCHEDULING_COORDINATOR,
    CIM_PLANT,
    annotate_grid_entity,
    annotate_station,
    annotate_transmission_line,
    annotate_unit,
    cim_class_for_grid_entity,
)
from psp_pipeline.storage.neo4j_repo import (
    _STATION_QUERY,
    _TRANSMISSION_LINE_QUERY,
    _UNIT_QUERY,
    _run_batches,
)


def test_cim_class_mapping_for_commercial_and_plant_entities() -> None:
    """Proprietary entity types project onto CIM base classes."""

    assert cim_class_for_grid_entity("market_participant") == CIM_ENERGY_SCHEDULING_COORDINATOR
    assert annotate_station({"key": "station:1", "name": "Ramagundam"})["cim_class"] == CIM_PLANT
    assert annotate_unit({"key": "unit:1", "station_key": "station:1"})["mrid"] == "unit:1"
    line = annotate_transmission_line({"key": "line:9", "name": "RANGIA-DEOTHANG"})
    assert line["cim_class"] == CIM_AC_LINE_SEGMENT
    assert annotate_grid_entity(
        {"key": "entity:2", "entity_type": "market_participant"}
    )["cim_label"] == "EnergySchedulingCoordinator"


def test_topology_queries_add_cim_labels_without_apoc() -> None:
    """Batch MERGE stays on native UNWIND and adds CIM labels beside existing ones."""

    assert "UNWIND $rows AS row" in _STATION_QUERY
    assert "SET station:Plant" in _STATION_QUERY
    assert "apoc.periodic" not in _STATION_QUERY
    assert "SET unit:SynchronousMachine" in _UNIT_QUERY
    assert "SET line:ACLineSegment" in _TRANSMISSION_LINE_QUERY
    assert "line.timescale_uuid" in _TRANSMISSION_LINE_QUERY
    assert "apoc." not in _TRANSMISSION_LINE_QUERY


def test_run_batches_chunks_without_per_row_queries() -> None:
    """Native batching remains memory-bounded at 500 rows."""

    class Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def run(self, query: str, params: dict[str, object] | None = None) -> None:
            self.calls.append((query, params or {}))

    session = Session()
    rows = [{"key": str(index)} for index in range(501)]
    _run_batches(session, "UNWIND $rows AS row RETURN row", rows)
    assert len(session.calls) == 2
    assert len(session.calls[0][1]["rows"]) == 500
    assert len(session.calls[1][1]["rows"]) == 1
