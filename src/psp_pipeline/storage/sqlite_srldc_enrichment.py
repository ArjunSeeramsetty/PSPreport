"""Deterministic SRLDC location enrichment for dimensions."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class LocationRef:
    """Canonical state and region names for a known SRLDC asset endpoint."""

    state_name: str | None = None
    region_name: str | None = None


@dataclass(frozen=True)
class TransmissionLocation:
    """Resolved endpoint metadata for a transmission element name."""

    element_type: str
    nominal_voltage_kv: float | None
    from_location: LocationRef = LocationRef()
    to_location: LocationRef = LocationRef()


VOLTAGE_NODE_STATE_MAP = {
    "GHANAPUR": "Telangana",
    "GOOTY": "Andhra Pradesh",
    "HIRIYUR": "Karnataka",
    "KAIGA": "Karnataka",
    "KOLAR_AC": "Karnataka",
    "KUDANKULAM": "Tamil Nadu",
    "KURNOOL": "Andhra Pradesh",
    "NIZAMABAD": "Telangana",
    "RAICHUR_PG": "Karnataka",
    "SHANKARAPALLY": "Telangana",
    "SOMANAHALLI": "Karnataka",
    "SRIKAKULAM": "Andhra Pradesh",
    "SRIPERUMBADUR": "Tamil Nadu",
    "TRICHY": "Tamil Nadu",
    "TRIVANDRUM": "Kerala",
    "VIJAYAWADA": "Andhra Pradesh",
}

RESERVOIR_STATE_MAP = {
    "IDUKKI": "Kerala",
    "JALAPUT": "Andhra Pradesh",
    "KAKKI": "Kerala",
    "LINGANAMAKKI": "Karnataka",
    "N.SAGAR": "Telangana",
    "NILAGIRIS": "Tamil Nadu",
    "SRISAILAM": "Andhra Pradesh",
    "SUPA": "Karnataka",
}

TRANSMISSION_ENDPOINT_MAP = {
    "AMBEWADI": LocationRef("Karnataka", "Southern Region"),
    "ANGUL": LocationRef("Odisha", "Eastern Region"),
    "BALIMELA": LocationRef("Odisha", "Eastern Region"),
    "BARSUR": LocationRef("Chhattisgarh", "Western Region"),
    "BHADRAVTAHI": LocationRef("Karnataka", "Southern Region"),
    "CHIKKODI": LocationRef("Karnataka", "Southern Region"),
    "GAZUWAKA": LocationRef("Andhra Pradesh", "Southern Region"),
    "JEYPORE": LocationRef("Odisha", "Eastern Region"),
    "KHOLAPUR_PG": LocationRef("Maharashtra", "Western Region"),
    "KOLAR_DC": LocationRef("Karnataka", "Southern Region"),
    "KUDGI_PG": LocationRef("Karnataka", "Southern Region"),
    "LOWER_SILERU": LocationRef("Andhra Pradesh", "Southern Region"),
    "MUDASANGI": LocationRef("Karnataka", "Southern Region"),
    "NIZAMABAD": LocationRef("Telangana", "Southern Region"),
    "PONDA": LocationRef("Goa", "Western Region"),
    "PUGALUR_HVDC": LocationRef("Tamil Nadu", "Southern Region"),
    "PUGALUR": LocationRef("Tamil Nadu", "Southern Region"),
    "RAICHUR_PG": LocationRef("Karnataka", "Southern Region"),
    "RAIGARH_HVDC": LocationRef("Chhattisgarh", "Western Region"),
    "RAIGARH": LocationRef("Chhattisgarh", "Western Region"),
    "RAMAGUNDAM": LocationRef("Telangana", "Southern Region"),
    "SHOLAPUR": LocationRef("Maharashtra", "Western Region"),
    "SRIKAKULAM": LocationRef("Andhra Pradesh", "Southern Region"),
    "TALANGADE": LocationRef("Maharashtra", "Western Region"),
    "TALCHER": LocationRef("Odisha", "Eastern Region"),
    "UPPER_SILERU": LocationRef("Andhra Pradesh", "Southern Region"),
    "WARDHA": LocationRef("Maharashtra", "Western Region"),
    "WARANGAL(NEW)": LocationRef("Telangana", "Southern Region"),
    "WARORA": LocationRef("Maharashtra", "Western Region"),
    "XELDEM": LocationRef("Goa", "Western Region"),
}

AGGREGATE_LINK_REGION_MAP = {
    "East-South": (
        LocationRef(region_name="Eastern Region"),
        LocationRef(region_name="Southern Region"),
    ),
    "West-South": (
        LocationRef(region_name="Western Region"),
        LocationRef(region_name="Southern Region"),
    ),
    "Sub-Total EAST REGION": (
        LocationRef(region_name="Eastern Region"),
        LocationRef(region_name="Southern Region"),
    ),
    "Sub-Total WEST REGION": (
        LocationRef(region_name="Western Region"),
        LocationRef(region_name="Southern Region"),
    ),
    "TOTAL IR EXCHANGE": (
        LocationRef(region_name="India"),
        LocationRef(region_name="Southern Region"),
    ),
    "Total": (
        LocationRef(region_name="India"),
        LocationRef(region_name="Southern Region"),
    ),
}


def voltage_node_state_name(node_name: str) -> str | None:
    """Return the canonical state for a known SRLDC voltage node."""

    key = node_name.split(" - ", 1)[0].strip().upper()
    return VOLTAGE_NODE_STATE_MAP.get(key)


def reservoir_state_name(reservoir_name: str) -> str | None:
    """Return the canonical state for a known SRLDC reservoir."""

    return RESERVOIR_STATE_MAP.get(reservoir_name.strip().upper())


def transmission_location(element_name: str) -> TransmissionLocation:
    """Resolve known endpoint state and region metadata for an SRLDC corridor."""

    element_name = element_name.strip()
    voltage_match = re.search(r"(?:HVDC)?(\d{3})KV", element_name.upper())
    voltage = float(voltage_match.group(1)) if voltage_match else None
    if element_name in AGGREGATE_LINK_REGION_MAP:
        from_location, to_location = AGGREGATE_LINK_REGION_MAP[element_name]
        return TransmissionLocation("aggregate_link", voltage, from_location, to_location)
    normalized = re.sub(r"^(?:HVDC\d+KV-|[0-9]+KV-)", "", element_name.upper())
    parts = [part for part in normalized.split("-") if part]
    if len(parts) >= 2:
        from_location = TRANSMISSION_ENDPOINT_MAP.get(parts[0], LocationRef())
        to_location = TRANSMISSION_ENDPOINT_MAP.get(parts[1], LocationRef())
        return TransmissionLocation(
            "transmission_corridor", voltage, from_location, to_location
        )
    element_type = (
        "aggregate_link"
        if element_name.lower().startswith(("sub-total", "total")) or "-south" in element_name.lower()
        else "transmission_corridor"
    )
    return TransmissionLocation(element_type, voltage)
