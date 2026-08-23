"""Unit tests for WRLDC location and topology enrichment registry."""

from __future__ import annotations

import pytest

from psp_pipeline.storage.sqlite_wrldc_enrichment import (
    TRANSMISSION_ELEMENT_REGISTRY,
    VOLTAGE_NODE_STATE_REGISTRY,
    transmission_location,
    voltage_node_state_name,
)

WR_STATES = {
    "Maharashtra",
    "Gujarat",
    "Madhya Pradesh",
    "Chhattisgarh",
    "Goa",
    "Dadra and Nagar Haveli and Daman and Diu",
}


def test_all_audited_voltage_nodes_resolve_to_western_region_state() -> None:
    assert len(VOLTAGE_NODE_STATE_REGISTRY) == 33
    for node_name, loc in VOLTAGE_NODE_STATE_REGISTRY.items():
        state = voltage_node_state_name(node_name)
        assert state is not None, f"Node {node_name} failed to resolve state"
        assert state in WR_STATES, f"Node {node_name} resolved to non-WR state: {state}"
        assert loc.region_name == "Western Region"
        assert loc.evidence == "grid_india_registry"


def test_all_audited_transmission_elements_resolve_endpoints() -> None:
    assert len(TRANSMISSION_ELEMENT_REGISTRY) == 41
    for elem_name, trans_loc in TRANSMISSION_ELEMENT_REGISTRY.items():
        loc = transmission_location(elem_name)
        assert loc.from_location.region_name == "Western Region"
        assert loc.from_location.state_name in WR_STATES
        assert loc.to_location.region_name in {"Northern Region", "Eastern Region", "Southern Region"}
        assert loc.to_location.state_name is not None
        assert loc.nominal_voltage_kv in {132.0, 205.0, 220.0, 400.0, 500.0, 765.0, 800.0}
        assert loc.element_type in {"line", "hvdc"}
        assert loc.evidence == "grid_india_registry"


def test_unknown_voltage_node_returns_none() -> None:
    assert voltage_node_state_name("UNKNOWN_SUBSTATION_400KV") is None
    assert voltage_node_state_name("") is None


def test_unknown_transmission_element_returns_unverified_metadata() -> None:
    loc = transmission_location("400KV-UNKNOWN_STATION-ANOTHER_STATION")
    assert loc.nominal_voltage_kv == 400.0
    assert loc.element_type == "line"
    assert loc.from_location.state_name is None
    assert loc.from_location.region_name is None
    assert loc.from_location.evidence == "unverified"
    assert loc.to_location.state_name is None
    assert loc.to_location.region_name is None
    assert loc.to_location.evidence == "unverified"
    assert loc.evidence == "unverified"


def test_unknown_hvdc_transmission_element_metadata() -> None:
    loc = transmission_location("HVDC800KV-UNKNOWN_A-UNKNOWN_B")
    assert loc.nominal_voltage_kv == 800.0
    assert loc.element_type == "hvdc"
    assert loc.from_location.state_name is None
    assert loc.to_location.state_name is None
    assert loc.evidence == "unverified"
