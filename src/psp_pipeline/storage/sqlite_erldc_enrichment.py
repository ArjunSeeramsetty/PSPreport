"""Deterministic ERLDC location and topology enrichment for dimensions."""

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
    """Resolved endpoint metadata for an Eastern Region transmission element."""

    element_type: str
    nominal_voltage_kv: float | None
    from_location: LocationRef = LocationRef()
    to_location: LocationRef = LocationRef()
    evidence: str = "unverified"


# Authoritative state mappings for Eastern Region voltage nodes (400 kV / 765 kV / 220 kV)
VOLTAGE_NODE_STATE_REGISTRY: dict[str, LocationRef] = {
    "JEERAT-400KV": LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
    "SUBHASHGRAM-400KV": LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
    "BINAGURI-400KV": LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
    "FARAKKA-400KV": LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
    "BAKRESWAR-400KV": LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
    "KOLAGHAT-400KV": LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
    "SAGARDIGHI-400KV": LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
    "PURULIA-400KV": LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
    "KAHALGAON-400KV": LocationRef("Bihar", "Eastern Region", "grid_india_registry"),
    "BARH-400KV": LocationRef("Bihar", "Eastern Region", "grid_india_registry"),
    "PATNA-400KV": LocationRef("Bihar", "Eastern Region", "grid_india_registry"),
    "MUZAFFARPUR-400KV": LocationRef("Bihar", "Eastern Region", "grid_india_registry"),
    "BIHARSHARIFF-400KV": LocationRef("Bihar", "Eastern Region", "grid_india_registry"),
    "NABINAGAR-400KV": LocationRef("Bihar", "Eastern Region", "grid_india_registry"),
    "RANCHI-400KV": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "JAMSHEDPUR-400KV": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "CHAIBASA-400KV": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "PATRATU-400KV": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "KODERMA-400KV": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "MERAMUNDALI-400KV": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "NEWDUBURI-400KV": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "ANGUL-765KV": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "JHARSUGUDA-765KV": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "SUNDARGARH-765KV": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "BOLANGIR-400KV": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "MENDHASAL-400KV": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "PANDIABILI-400KV": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "RANGPO-400KV": LocationRef("Sikkim", "Eastern Region", "grid_india_registry"),
    "NEWMELLI-220KV": LocationRef("Sikkim", "Eastern Region", "grid_india_registry"),
}

# Authoritative endpoint mappings for Eastern Region inter-regional and cross-border tie lines
TRANSMISSION_ELEMENT_REGISTRY: dict[str, TransmissionLocation] = {
    "400KV_BINAGURI_BONGAIGAON_1": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=400.0,
        from_location=LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
    "400KV_BINAGURI_BONGAIGAON_2": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=400.0,
        from_location=LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
    "400KV_BINAGURI_BONGAIGAON": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=400.0,
        from_location=LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Assam", "North Eastern Region", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
    "765KV_RANCHI_DHARAMJAYGARH": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=765.0,
        from_location=LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
    "765KV_JHARSUGUDA_DHARAMJAYGARH": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=765.0,
        from_location=LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
    "765KV_JHARSUGUDA_DHARMAJAYAGARH": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=765.0,
        from_location=LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Chhattisgarh", "Western Region", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
    "400KV_SASARAM_VARANASI": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=400.0,
        from_location=LocationRef("Bihar", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
    "400KV_PATNA_BALLIA": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=400.0,
        from_location=LocationRef("Bihar", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Uttar Pradesh", "Northern Region", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
    "400KV_BAHARAMPUR_BHERAMARA": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=400.0,
        from_location=LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Bangladesh", "International", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
    "400KV_MUZAFFARPUR_DHALKEBAR": TransmissionLocation(
        element_type="line",
        nominal_voltage_kv=400.0,
        from_location=LocationRef("Bihar", "Eastern Region", "grid_india_registry"),
        to_location=LocationRef("Nepal", "International", "grid_india_registry"),
        evidence="grid_india_registry",
    ),
}

# Authoritative state and owner mapping for major Eastern Region generation entities
GENERATION_ENTITY_STATE_REGISTRY: dict[str, str] = {
    "BOKARO-A": "DVC",
    "CHANDRAPURA": "DVC",
    "DURGAPUR": "DVC",
    "KODERMA": "DVC",
    "MEJIA": "DVC",
    "RAGHUNATHPUR": "DVC",
    "RTPS": "DVC",
    "MAITHON": "DVC",
    "PANCHET": "DVC",
    "TILAIYA": "DVC",
    "IB.TPS": "Odisha",
    "OPGC": "Odisha",
    "VEDANTA": "Odisha",
    "GMRKAMALANGA": "Odisha",
    "JITPL": "Odisha",
    "FARAKKA": "West Bengal",
    "FSTPS": "West Bengal",
    "BAKRESWAR": "West Bengal",
    "BANDEL": "West Bengal",
    "KOLAGHAT": "West Bengal",
    "SAGARDIGHI": "West Bengal",
    "SANTALDIH": "West Bengal",
    "BUDGEBUDGE": "West Bengal",
    "PURULIA": "West Bengal",
    "KAHALGAON": "Bihar",
    "KHSTPP": "Bihar",
    "BARH": "Bihar",
    "BARAUNI": "Bihar",
    "KANTI": "Bihar",
    "KBUNL": "Bihar",
    "NABINAGAR": "Bihar",
    "BRBCL": "Bihar",
    "NPGCL": "Bihar",
    "TEESTA-V": "Sikkim",
    "RANGIT": "Sikkim",
    "DIKCHU": "Sikkim",
    "CHUZACHEN": "Sikkim",
    "JORETHANG": "Sikkim",
    "TASHIDING": "Sikkim",
}

# Authoritative state mapping for major Eastern Region hydro reservoirs
RESERVOIR_STATE_REGISTRY: dict[str, LocationRef] = {
    "MAITHON": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "PANCHET": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "TILAIYA": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "KONAR": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "TENUGHAT": LocationRef("Jharkhand", "Eastern Region", "grid_india_registry"),
    "RENGALI": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "BALIMELA": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "UPPERKOLAB": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "U.KOLAB": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "INDRAVATI": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "HIRAKUD": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "MACHKUND": LocationRef("Odisha", "Eastern Region", "grid_india_registry"),
    "TEESTA": LocationRef("Sikkim", "Eastern Region", "grid_india_registry"),
    "TEESTA-V": LocationRef("Sikkim", "Eastern Region", "grid_india_registry"),
    "RANGIT": LocationRef("Sikkim", "Eastern Region", "grid_india_registry"),
    "PURULIA": LocationRef("West Bengal", "Eastern Region", "grid_india_registry"),
}


def _normalize_key(name: str) -> str:
    """Normalize label for exact canonical matching."""
    return re.sub(r"[^A-Z0-9]", "", str(name or "").upper())


def voltage_node_location(node_name: str) -> LocationRef:
    """Return authoritative LocationRef for an Eastern Region voltage node."""
    norm = _normalize_key(node_name)
    for key, loc in VOLTAGE_NODE_STATE_REGISTRY.items():
        if _normalize_key(key) == norm:
            return loc
    return LocationRef(evidence="unverified")


def voltage_node_state_name(node_name: str) -> str | None:
    """Return canonical state name for an Eastern Region voltage node if verified."""
    return voltage_node_location(node_name).state_name


def transmission_location(element_name: str) -> TransmissionLocation:
    """Resolve endpoint metadata for an Eastern Region transmission element."""
    norm = _normalize_key(element_name)
    for key, loc in TRANSMISSION_ELEMENT_REGISTRY.items():
        if _normalize_key(key) == norm:
            return loc

    # Parse metadata without endpoint inference
    match = re.search(r"(?P<kv>\d{3,4})\s*KV", element_name, re.IGNORECASE)
    nominal_kv = float(match.group("kv")) if match else None
    element_type = "hvdc" if "hvdc" in element_name.lower() else "line"

    return TransmissionLocation(
        element_type=element_type,
        nominal_voltage_kv=nominal_kv,
        from_location=LocationRef(evidence="unverified"),
        to_location=LocationRef(evidence="unverified"),
        evidence="unverified",
    )


def generation_entity_state_name(entity_name: str) -> str | None:
    """Return canonical state name for an Eastern Region power station if verified."""
    norm = _normalize_key(entity_name)
    for prefix, state_name in GENERATION_ENTITY_STATE_REGISTRY.items():
        if _normalize_key(prefix) in norm:
            return state_name
    return None


def reservoir_location(reservoir_name: str) -> LocationRef:
    """Return authoritative LocationRef for an Eastern Region reservoir."""
    norm = _normalize_key(reservoir_name)
    for key, loc in RESERVOIR_STATE_REGISTRY.items():
        if _normalize_key(key) == norm or _normalize_key(key) in norm:
            return loc
    return LocationRef(evidence="unverified")


def reservoir_state_name(reservoir_name: str) -> str | None:
    """Return canonical state name for an Eastern Region reservoir if verified."""
    return reservoir_location(reservoir_name).state_name
