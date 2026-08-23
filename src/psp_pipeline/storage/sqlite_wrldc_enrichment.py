"""Deterministic WRLDC location and topology enrichment for dimensions."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class LocationRef:
    """Canonical state and region names with authoritative evidence for an asset endpoint."""

    state_name: str | None = None
    region_name: str | None = None
    evidence: str = "unverified"


@dataclass(frozen=True)
class TransmissionLocation:
    """Resolved endpoint metadata for a transmission element."""

    element_type: str
    nominal_voltage_kv: float | None
    from_location: LocationRef = LocationRef()
    to_location: LocationRef = LocationRef()
    evidence: str = "unverified"


# Authoritative state mappings for observed WRLDC 400 kV and 765 kV voltage profile substations.
# Each entry is sourced from Grid-India / CEA Western Regional Power System records.
VOLTAGE_NODE_STATE_REGISTRY: dict[str, LocationRef] = {
    "KARAD-400KV": LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
    "KASOR-400KV": LocationRef("Gujarat", "Western Region", "grid_india_registry"),
    "KHANDWA-400KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "MAGARWADA-400KV": LocationRef("Dadra and Nagar Haveli and Daman and Diu", "Western Region", "grid_india_registry"),
    "MAPUSA-400KV": LocationRef("Goa", "Western Region", "grid_india_registry"),
    "NAGDA-400KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "NEWKOYNA-400KV": LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
    "PARLI-400KV": LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
    "RAIPUR-400KV": LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
    "RAIGARH-400KV": LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
    "VAPI-400KV": LocationRef("Gujarat", "Western Region", "grid_india_registry"),
    "WARDHA-400KV": LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
    "BINA-765KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "DURG-765KV": LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
    "GWALIOR-765KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "INDORE-765KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "KOTRA-765KV": LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
    "SASAN-765KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "SATNA-765KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "SEONI-765KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "SIPAT-765KV": LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
    "TAMNAR-765KV": LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
    "VADODARA-765KV": LocationRef("Gujarat", "Western Region", "grid_india_registry"),
    "WARDHA-765KV": LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
    "DAMOH-400KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "GPEC-400KV": LocationRef("Gujarat", "Western Region", "grid_india_registry"),
    "GWALIOR-400KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "HAZIRA-400KV": LocationRef("Gujarat", "Western Region", "grid_india_registry"),
    "INDORE-400KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "ITARSI-400KV": LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
    "JETPUR-400KV": LocationRef("Gujarat", "Western Region", "grid_india_registry"),
    "KALA-400KV": LocationRef("Dadra and Nagar Haveli and Daman and Diu", "Western Region", "grid_india_registry"),
    "KALWA-400KV": LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
}


# Authoritative endpoint mappings for Western Region transmission lines and inter-regional links.
TRANSMISSION_ELEMENT_REGISTRY: dict[str, TransmissionLocation] = {
    # WR - ER Inter-Regional Lines
    "220KV-KORBA-BUDIPADAR": TransmissionLocation(
        "line", 220.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "220KV-RAIGARH-BUDIPADAR": TransmissionLocation(
        "line", 220.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-RAIGARH-JHARSUGUDA": TransmissionLocation(
        "line", 400.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-RAIGARH-ROURKELA": TransmissionLocation(
        "line", 400.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-RAIGARH-STERLITE": TransmissionLocation(
        "line", 400.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-SIPAT-RANCHI": TransmissionLocation(
        "line", 400.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-DHARJAYGARH-JHARSUGUDA": TransmissionLocation(
        "line", 765.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-DHARJAYGARH-RANCHI": TransmissionLocation(
        "line", 765.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-RAIPUR-PS(DURG)-JHARSUGUDA": TransmissionLocation(
        "line", 765.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
        "grid_india_registry",
    ),

    # WR - NR Inter-Regional Lines
    "132KV-GWALIOR-SAWAIMADHOPUR": TransmissionLocation(
        "line", 132.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Rajasthan", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "132KV-RAJGHAT-LALITPUR": TransmissionLocation(
        "line", 132.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "220KV-BHANPURA-MODAK": TransmissionLocation(
        "line", 220.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Rajasthan", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "220KV-BHANPURA-RANPUR": TransmissionLocation(
        "line", 220.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Rajasthan", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "220KV-MALANPUR-AURIYA": TransmissionLocation(
        "line", 220.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "220KV-MEHGAON-AURIYA": TransmissionLocation(
        "line", 220.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-KANSARI-KANKROLI": TransmissionLocation(
        "line", 400.0,
        LocationRef("Gujarat", "Western Region", "grid_india_registry"),
        LocationRef("Rajasthan", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-KANSARI-KANKROLI2(BYPASSAT BHINMAL)": TransmissionLocation(
        "line", 400.0,
        LocationRef("Gujarat", "Western Region", "grid_india_registry"),
        LocationRef("Rajasthan", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-NEEMUCH-CHITTORGARH": TransmissionLocation(
        "line", 400.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Rajasthan", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-SUJALPUR-RAPP": TransmissionLocation(
        "line", 400.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Rajasthan", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-VINDHYACHALPS-RIHAND(III)": TransmissionLocation(
        "line", 400.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-BANASKANTHA-CHITTORGARH": TransmissionLocation(
        "line", 765.0,
        LocationRef("Gujarat", "Western Region", "grid_india_registry"),
        LocationRef("Rajasthan", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-GWALIOR-AGRA": TransmissionLocation(
        "line", 765.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-GWALIOR-JAIPUR": TransmissionLocation(
        "line", 765.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Rajasthan", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-GWALIOR-ORAI": TransmissionLocation(
        "line", 765.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-JABALPUR-ORAI": TransmissionLocation(
        "line", 765.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-SATNA-ORAI": TransmissionLocation(
        "line", 765.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-VINDHYACHAL(PS)-VARANASI": TransmissionLocation(
        "line", 765.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "HVDC400KV-VINDYACHAL(PS)-RIHAND": TransmissionLocation(
        "hvdc", 400.0,
        LocationRef("Madhya Pradesh", "Western Region", "grid_india_registry"),
        LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "HVDC500KV-MUNDRA-MOHINDARGARH": TransmissionLocation(
        "hvdc", 500.0,
        LocationRef("Gujarat", "Western Region", "grid_india_registry"),
        LocationRef("Haryana", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "HVDC800KV-CHAMPA-KURUKSHETRA": TransmissionLocation(
        "hvdc", 800.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Haryana", "Northern Region", "grid_india_registry"),
        "grid_india_registry",
    ),

    # WR - SR Inter-Regional Lines
    "220KV-KOLHAPUR-CHIKKODI-II": TransmissionLocation(
        "line", 220.0,
        LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
        LocationRef("Karnataka", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "220KV-PONDA-AMBEWADI": TransmissionLocation(
        "line", 220.0,
        LocationRef("Goa", "Western Region", "grid_india_registry"),
        LocationRef("Karnataka", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "220KV-TALANGADE(MS)-CHIKKODI-II": TransmissionLocation(
        "line", 220.0,
        LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
        LocationRef("Karnataka", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "220KV-XELDEM-AMBEWADI": TransmissionLocation(
        "line", 220.0,
        LocationRef("Goa", "Western Region", "grid_india_registry"),
        LocationRef("Karnataka", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "400KV-KOLHAPURGIS-NARENDRAKUDGI": TransmissionLocation(
        "line", 400.0,
        LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
        LocationRef("Karnataka", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-SOLAPUR-RAICHUR": TransmissionLocation(
        "line", 765.0,
        LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
        LocationRef("Karnataka", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-WARDHA-NIZAMABAD": TransmissionLocation(
        "line", 765.0,
        LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
        LocationRef("Telangana", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "765KV-WARORA-PG-WARANGAL": TransmissionLocation(
        "line", 765.0,
        LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
        LocationRef("Telangana", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "HVDC205KV-BHADRAWATI-RAMAGUNDAM": TransmissionLocation(
        "hvdc", 205.0,
        LocationRef("Maharashtra", "Western Region", "grid_india_registry"),
        LocationRef("Telangana", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "HVDC400KV-BARSUR-L.SILERU": TransmissionLocation(
        "hvdc", 400.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Andhra Pradesh", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
    "HVDC800KV-RAIGARH-GIS-HVDC-PUGALUR": TransmissionLocation(
        "hvdc", 800.0,
        LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        LocationRef("Tamil Nadu", "Southern Region", "grid_india_registry"),
        "grid_india_registry",
    ),
}


def voltage_node_location(node_name: str) -> LocationRef:
    """Return canonical LocationRef for a Western Region voltage node."""
    norm = str(node_name).strip().upper()
    ref = VOLTAGE_NODE_STATE_REGISTRY.get(norm)
    if ref is not None:
        return ref
    return LocationRef(region_name="Western Region", evidence="unverified")


def voltage_node_state_name(node_name: str) -> str | None:
    """Return the canonical Western Region state for a known voltage node."""
    loc = voltage_node_location(node_name)
    return loc.state_name


def transmission_location(element_name: str) -> TransmissionLocation:
    """Return authoritative endpoint metadata for a Western Region transmission element.

    Nominal voltage extraction is performed only as metadata, never endpoint inference.
    If the element is not in the authoritative registry, returns an unverified LocationRef.
    """
    clean_name = re.sub(r"\s+", " ", str(element_name).strip().upper())
    if clean_name in TRANSMISSION_ELEMENT_REGISTRY:
        return TRANSMISSION_ELEMENT_REGISTRY[clean_name]

    # Deterministic metadata extraction for unknown lines
    voltage_match = re.search(r"(\d+)\s*KV", clean_name)
    nominal_kv = float(voltage_match.group(1)) if voltage_match else None
    element_type = "hvdc" if "HVDC" in clean_name else "line"

    return TransmissionLocation(
        element_type=element_type,
        nominal_voltage_kv=nominal_kv,
        from_location=LocationRef(evidence="unverified"),
        to_location=LocationRef(evidence="unverified"),
        evidence="unverified",
    )
