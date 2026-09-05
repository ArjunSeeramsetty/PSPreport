"""Unit tests for ERLDC location and topology enrichment registry."""

from __future__ import annotations

import pytest

from psp_pipeline.storage.sqlite_erldc_enrichment import (
    GENERATION_ENTITY_STATE_REGISTRY,
    RESERVOIR_STATE_REGISTRY,
    TRANSMISSION_ELEMENT_REGISTRY,
    VOLTAGE_NODE_STATE_REGISTRY,
    generation_entity_state_name,
    reservoir_location,
    reservoir_state_name,
    transmission_location,
    voltage_node_location,
    voltage_node_state_name,
)

ER_STATES = {
    "West Bengal",
    "Bihar",
    "Jharkhand",
    "Odisha",
    "Sikkim",
    "DVC",
}


def test_all_registered_voltage_nodes_resolve_to_eastern_region_state() -> None:
    assert len(VOLTAGE_NODE_STATE_REGISTRY) >= 25
    for node_name, loc in VOLTAGE_NODE_STATE_REGISTRY.items():
        state = voltage_node_state_name(node_name)
        assert state is not None, f"Node {node_name} failed to resolve state"
        assert state in ER_STATES, f"Node {node_name} resolved to non-ER state: {state}"
        assert loc.region_name == "Eastern Region"
        assert loc.evidence == "grid_india_registry"


def test_all_registered_transmission_elements_resolve_endpoints() -> None:
    assert len(TRANSMISSION_ELEMENT_REGISTRY) >= 8
    for elem_name, trans_loc in TRANSMISSION_ELEMENT_REGISTRY.items():
        loc = transmission_location(elem_name)
        assert loc.from_location.region_name == "Eastern Region"
        assert loc.to_location.region_name in {
            "Northern Region",
            "Western Region",
            "North Eastern Region",
            "Southern Region",
            "International",
        }
        assert loc.evidence == "grid_india_registry"
        if loc.element_type == "corridor":
            assert loc.nominal_voltage_kv is None
            continue
        assert loc.from_location.state_name in ER_STATES
        assert loc.nominal_voltage_kv in {220.0, 400.0, 765.0}
        assert loc.element_type in {"line", "hvdc"}


def test_registered_generation_entities_resolve_states() -> None:
    assert len(GENERATION_ENTITY_STATE_REGISTRY) >= 25
    assert generation_entity_state_name("FSTPS (4*210+2*500)") == "West Bengal"
    assert generation_entity_state_name("KAHALGAON STPS (4*210+3*500)") == "Bihar"
    assert generation_entity_state_name("MEJIA TPS (4*210+2*250)") == "DVC"
    assert generation_entity_state_name("OPGC (2*210+2*660)") == "Odisha"
    assert generation_entity_state_name("TEESTA-V HPS (3*170)") == "Sikkim"
    assert generation_entity_state_name("CESC") == "West Bengal"
    assert generation_entity_state_name("JUVNL TPS") == "Jharkhand"


def test_all_registered_reservoirs_resolve_states() -> None:
    assert len(RESERVOIR_STATE_REGISTRY) >= 12
    for res_name, loc in RESERVOIR_STATE_REGISTRY.items():
        state = reservoir_state_name(res_name)
        assert state is not None, f"Reservoir {res_name} failed to resolve state"
        assert state in ER_STATES, f"Reservoir {res_name} resolved to non-ER state: {state}"
        assert loc.region_name == "Eastern Region"
        assert loc.evidence == "grid_india_registry"


def test_unknown_voltage_node_returns_none() -> None:
    assert voltage_node_state_name("UNKNOWN_ER_SUBSTATION_400KV") is None
    assert voltage_node_state_name("") is None


def test_unknown_transmission_element_returns_unverified_metadata() -> None:
    loc = transmission_location("400KV_UNKNOWN_ER_STATION_A_TO_B")
    assert loc.nominal_voltage_kv == 400.0
    assert loc.element_type == "line"
    assert loc.from_location.state_name is None
    assert loc.from_location.region_name is None
    assert loc.from_location.evidence == "unverified"
    assert loc.to_location.state_name is None
    assert loc.to_location.region_name is None
    assert loc.to_location.evidence == "unverified"
    assert loc.evidence == "unverified"
