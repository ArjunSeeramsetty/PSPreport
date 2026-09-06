"""Controlled location metadata for NERLDC curated dimensions.

The registry deliberately uses exact normalized names observed in the NERLDC
PSP corpus. Unknown assets remain unverified rather than receiving a guessed
state assignment.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class LocationRef:
    """Canonical state and region names with provenance for a grid asset."""

    state_name: str | None = None
    region_name: str | None = None
    evidence: str = "unverified"
    country_name: str | None = None


@dataclass(frozen=True)
class TransmissionLocation:
    """Resolved endpoint metadata for a NERLDC transmission element."""

    element_type: str
    nominal_voltage_kv: float | None
    from_location: LocationRef = LocationRef()
    to_location: LocationRef = LocationRef()
    evidence: str = "unverified"


# State assignments are taken from POWERGRID's North Eastern Region substation
# listing and retained as explicit registry records for reproducible backfills.
VOLTAGE_NODE_STATE_REGISTRY: dict[str, LocationRef] = {
    "AIZWAL 132KV": LocationRef("Mizoram", "North Eastern Region", "grid_india_registry"),
    "AZARA 400KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "BADARPUR 132KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "BALIPARA 400KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "BISWANATH CHARIALI 400KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "BONGAIGAON 400KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "BYRNIHAT KILLING 400KV": LocationRef("Meghalaya", "North Eastern Region", "grid_india_registry"),
    "BGTPP 400KV": LocationRef("Assam", "North Eastern Region", "nerldc_psp_verified"),
    "DIMAPUR PG 220KV": LocationRef("Nagaland", "North Eastern Region", "grid_india_registry"),
    "HAFLONG 132KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "IMPHAL PG 132KV": LocationRef("Manipur", "North Eastern Region", "grid_india_registry"),
    "IMPHAL PG 400KV": LocationRef("Manipur", "North Eastern Region", "grid_india_registry"),
    "JIRIBAM PG 132KV": LocationRef("Manipur", "North Eastern Region", "grid_india_registry"),
    "KAHILIPARA 132KV": LocationRef("Assam", "North Eastern Region", "nerldc_psp_verified"),
    "KHELIEHRIAT 132KV": LocationRef("Meghalaya", "North Eastern Region", "grid_india_registry"),
    "KUMARGHAT 132KV": LocationRef("Tripura", "North Eastern Region", "grid_india_registry"),
    "MARIANI PG 220KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "MARIANI PG 400KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "MISA 220KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "MISA 400KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "NEW KOHIMA 400KV": LocationRef("Nagaland", "North Eastern Region", "grid_india_registry"),
    "NIRJULI 132KV": LocationRef("Arunachal Pradesh", "North Eastern Region", "grid_india_registry"),
    "PALATANA 400KV": LocationRef("Tripura", "North Eastern Region", "nerldc_psp_verified"),
    "PK BARI STERLITE 400KV": LocationRef("Tripura", "North Eastern Region", "nerldc_psp_verified"),
    "RANGANADI 400KV": LocationRef("Arunachal Pradesh", "North Eastern Region", "nerldc_psp_verified"),
    "SALAKATI 220KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "SILCHAR 400KV": LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
    "SURAJMANINAGAR STERLITE 400KV": LocationRef("Tripura", "North Eastern Region", "nerldc_psp_verified"),
}


TRANSMISSION_ELEMENT_REGISTRY: dict[str, TransmissionLocation] = {
    "132KV RANGIA DEOTHANG": TransmissionLocation(
        "line", 132.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef(evidence="grid_india_registry", country_name="Bhutan"),
        "grid_india_registry",
    ),
    "132KV RANGIA MOTONGA": TransmissionLocation(
        "line", 132.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef(evidence="nerldc_psp_verified", country_name="Bhutan"),
        "nerldc_psp_verified",
    ),
    "132KV SALAKATI GELEPHU": TransmissionLocation(
        "line", 132.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef(evidence="grid_india_registry", country_name="Bhutan"),
        "grid_india_registry",
    ),
    "220KV SALAKATI ALIPURDUAR 1": TransmissionLocation(
        "line", 220.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "220KV SALAKATI ALIPURDUAR 2": TransmissionLocation(
        "line", 220.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV BONGAIGAON ALIPURDUAR 1": TransmissionLocation(
        "line", 400.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV BONGAIGAON ALIPURDUAR 2": TransmissionLocation(
        "line", 400.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV BONGAIGAON NEW SILIGURI 1": TransmissionLocation(
        "line", 400.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV BONGAIGAON NEW SILIGURI 2": TransmissionLocation(
        "line", 400.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "HVDC800KV BISWANATH CHARIALI AGRA": TransmissionLocation(
        "hvdc", 800.0,
        LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        LocationRef("UP", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "132KV SM NAGAR COMILLA": TransmissionLocation(
        "line", 132.0,
        LocationRef("Tripura", "North Eastern Region", "grid_india_registry"),
        LocationRef(evidence="grid_india_registry", country_name="Bangladesh"),
        "grid_india_registry",
    ),
    "132KV SURAJMANINAGAR COMILLA": TransmissionLocation(
        "line", 132.0,
        LocationRef("Tripura", "North Eastern Region", "grid_india_registry"),
        LocationRef(evidence="grid_india_registry", country_name="Bangladesh"),
        "grid_india_registry",
    ),
    "400KV SURAJMANINAGAR COMILLA": TransmissionLocation(
        "line", 400.0,
        LocationRef("Tripura", "North Eastern Region", "grid_india_registry"),
        LocationRef(evidence="grid_india_registry", country_name="Bangladesh"),
        "grid_india_registry",
    ),
}


# These are reviewed NERLDC station aliases. They intentionally replace
# capacity formatting and case variants only for known publisher labels.
GENERATION_ENTITY_CANONICAL_NAMES: dict[str, str] = {
    "Agartala GT": "Agartala GT",
    "Agartala Gas Turbine CCPP": "Agartala GT",
    "Ganol HEP": "Ganol HEP",
    "Karbi Langpi HEP": "Karbi Langpi HEP",
    "Lakwa Replacement PP": "Lakwa Replacement PP",
    "Lakwa TPS": "Lakwa TPS",
    "Monarchak CCGT": "Monarchak CCGT",
    "Myntreng HEP": "Myntreng HEP",
    "Myntdu Leshka HEP": "Myntdu Leshka HEP",
    "Myndtu Leshka": "Myntdu Leshka HEP",
    "Namrup Replacement PP": "Namrup Replacement PP",
    "Namrup TPS": "Namrup TPS",
    "New Umtru HEP": "New Umtru HEP",
    "New Umtru": "New Umtru HEP",
    "Lakroh": "Lakroh HEP",
    "Other Hydel": "Other Hydel",
    "Private Generators": "Private Generators",
    "Ranganadi HEP": "Ranganadi HEP",
    "Serlui B": "Serlui-B HEP",
    "Sonapani HEP": "Sonapani HEP",
    "Solar": "Solar",
    "Umiam St I": "Umiam St I HEP",
    "Umiam St II": "Umiam St II HEP",
    "Umiam St III": "Umiam St III HEP",
    "Umiam St IV": "Umiam St IV HEP",
    "OTPC Palatana": "OTPC Palatana",
    "Palatana": "OTPC Palatana",
    "Palatana GBPP": "OTPC Palatana",
}


def _normalize_key(name: str) -> str:
    """Normalize a publisher label without inferring an asset identity."""

    return re.sub(r"[^A-Z0-9]", "", str(name or "").upper())


def voltage_node_location(node_name: str) -> LocationRef:
    """Return the verified location for an observed NERLDC voltage node."""

    normalized = _normalize_key(node_name)
    for key, location in VOLTAGE_NODE_STATE_REGISTRY.items():
        if _normalize_key(key) == normalized:
            return location
    return LocationRef(region_name="North Eastern Region", evidence="unverified")


def transmission_location(element_name: str) -> TransmissionLocation:
    """Return verified endpoint metadata, or parsed unverified metadata."""

    normalized = _normalize_key(element_name)
    for key, location in TRANSMISSION_ELEMENT_REGISTRY.items():
        if _normalize_key(key) == normalized:
            return location

    voltage = re.search(r"(\d{3,4})\s*KV", element_name, re.IGNORECASE)
    return TransmissionLocation(
        "hvdc" if "HVDC" in str(element_name).upper() else "line",
        float(voltage.group(1)) if voltage else None,
    )


def generation_entity_canonical_name(entity_name: str) -> str:
    """Return a reviewed station identity while preserving unknown labels."""

    base_name = re.sub(r"\([^)]*\)", "", str(entity_name or ""))
    normalized = _normalize_key(base_name)
    for known_name, canonical_name in GENERATION_ENTITY_CANONICAL_NAMES.items():
        if _normalize_key(known_name) == normalized:
            return canonical_name
    return str(entity_name or "").strip()
