"""Regression coverage for controlled NERLDC topology enrichment."""

from __future__ import annotations

from psp_pipeline.storage.sqlite_nerldc_enrichment import (
    TRANSMISSION_ELEMENT_REGISTRY,
    VOLTAGE_NODE_STATE_REGISTRY,
    generation_entity_canonical_name,
    transmission_location,
    voltage_node_location,
)


def test_registered_nerldc_voltage_nodes_have_verified_locations() -> None:
    """Every registry node carries a canonical North Eastern state and evidence."""

    assert len(VOLTAGE_NODE_STATE_REGISTRY) == 28
    for location in VOLTAGE_NODE_STATE_REGISTRY.values():
        assert location.state_name is not None
        assert location.region_name == "North Eastern Region"
        assert location.evidence in {"grid_india_registry", "nerldc_psp_verified"}


def test_voltage_node_lookup_normalizes_publisher_punctuation() -> None:
    """Publisher spacing and punctuation do not affect an exact canonical lookup."""

    location = voltage_node_location("SURajmaninagar (Sterlite) - 400KV")
    assert location.state_name == "Tripura"
    assert location.evidence == "nerldc_psp_verified"


def test_transmission_lookup_resolves_known_and_unknown_elements() -> None:
    """Known tie lines resolve endpoints; unknown labels remain explicitly unverified."""

    assert len(TRANSMISSION_ELEMENT_REGISTRY) == 10
    known = transmission_location("400KV-BONGAIGAON-ALIPURDUAR-1")
    assert known.from_location.state_name == "Assam"
    assert known.to_location.state_name == "West Bengal"
    assert known.evidence == "grid_india_registry"

    bhutan_tie = transmission_location("132KV-RANGIA-MOTONGA")
    assert bhutan_tie.from_location.state_name == "Assam"
    assert bhutan_tie.to_location.country_name == "Bhutan"
    assert bhutan_tie.to_location.region_name is None

    unknown = transmission_location("400KV-UNKNOWN-TEST")
    assert unknown.nominal_voltage_kv == 400.0
    assert unknown.evidence == "unverified"


def test_generation_aliases_only_normalize_reviewed_station_labels() -> None:
    """Known capacity and case variants share a controlled station identity."""

    assert generation_entity_canonical_name("MYNDTU LESHKA (3*42)") == "Myntdu Leshka HEP"
    assert generation_entity_canonical_name("SOLAR (1*5+1*25)") == "Solar"
    assert generation_entity_canonical_name("Unreviewed Station (2*100)") == (
        "Unreviewed Station (2*100)"
    )
