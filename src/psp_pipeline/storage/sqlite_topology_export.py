"""Project curated SQLite dimensions into canonical Neo4j topology batches."""

from __future__ import annotations

import sqlite3
from typing import Any


_REGION_CODES = {
    "Northern Region": "NR",
    "Western Region": "WR",
    "Southern Region": "SR",
    "Eastern Region": "ER",
    "North Eastern Region": "NER",
    "India": "IN",
}


def export_curated_topology(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """Return deterministic topology rows without reading high-volume facts."""

    regions = [
        {"code": _region_code(region_id, name), "name": name}
        for region_id, name in conn.execute(
            "SELECT RegionID, RegionName FROM DimRegions ORDER BY RegionID"
        )
    ]
    region_codes = {
        int(region_id): _region_code(int(region_id), str(name))
        for region_id, name in conn.execute(
            "SELECT RegionID, RegionName FROM DimRegions"
        )
    }
    states = [
        {
            "code": f"STATE-{state_id}",
            "name": state_name,
            "region_code": region_codes.get(region_id),
            "observation_entity_keys": _state_observation_entity_keys(
                region_codes.get(region_id),
                state_name,
                state_code,
            ),
        }
        for state_id, state_name, region_id, state_code in conn.execute(
            "SELECT StateID, StateName, RegionID, StateCode FROM DimStates ORDER BY StateID"
        )
    ]
    countries = [
        {"code": f"COUNTRY-{country_id}", "name": country_name}
        for country_id, country_name in conn.execute(
            "SELECT CountryID, CountryName FROM DimCountries ORDER BY CountryID"
        )
    ]
    stations = [
        {
            "key": f"station:{station_id}",
            "name": name,
            "state_code": _state_code(state_id),
            "region_code": region_codes.get(region_id),
            "capacity_mw": capacity,
        }
        for station_id, name, state_id, region_id, capacity in conn.execute(
            "SELECT StationID, CanonicalStationName, StateID, RegionID, InstalledCapacityMW "
            "FROM DimPowerStations ORDER BY StationID"
        )
    ]
    units = [
        {
            "key": f"unit:{unit_id}",
            "name": name,
            "station_key": f"station:{station_id}",
            "unit_number": unit_number,
            "capacity_mw": capacity,
        }
        for unit_id, station_id, name, unit_number, capacity in conn.execute(
            "SELECT GeneratingUnitID, StationID, CanonicalUnitName, UnitNumber, CapacityMW "
            "FROM DimGeneratingUnits ORDER BY GeneratingUnitID"
        )
    ]
    grid_entities = [
        {
            "key": f"entity:{entity_id}",
            "name": name,
            "entity_type": entity_type,
            "state_code": _state_code(state_id),
            "region_code": region_codes.get(region_id),
            "capacity_mw": capacity,
            "observation_entity_key": _observation_entity_key(
                region_codes.get(region_id), "generation", name
            ),
        }
        for entity_id, name, entity_type, state_id, region_id, capacity in conn.execute(
            "SELECT EntityID, EntityName, EntityType, StateID, RegionID, InstalledCapacityMW "
            "FROM DimGridEntities ORDER BY EntityID"
        )
    ]
    voltage_nodes = [
        {
            "key": f"voltage:{node_id}",
            "name": name,
            "nominal_voltage_kv": nominal_kv,
            "state_code": _state_code(state_id),
            "region_code": region_codes.get(region_id),
            "observation_entity_key": _observation_entity_key(
                region_codes.get(region_id), "voltage", name
            ),
        }
        for node_id, name, nominal_kv, state_id, region_id in conn.execute(
            "SELECT VoltageNodeID, NodeName, NominalVoltageKV, StateID, RegionID "
            "FROM DimVoltageNodes ORDER BY VoltageNodeID"
        )
    ]
    lines = _transmission_rows(conn, region_codes)
    return {
        "regions": regions,
        "states": states,
        "countries": countries,
        "stations": stations,
        "units": units,
        "grid_entities": grid_entities,
        "voltage_nodes": voltage_nodes,
        "transmission_lines": lines,
    }


def _transmission_rows(
    conn: sqlite3.Connection,
    region_codes: dict[int, str],
) -> list[dict[str, Any]]:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(DimTransmissionElements)")}
    from_country = "FromCountryID" if "FromCountryID" in columns else "NULL"
    to_country = "ToCountryID" if "ToCountryID" in columns else "NULL"
    rows = conn.execute(
        "SELECT ElementID, ElementName, ElementType, NominalVoltageKV, "
        "FromRegionID, ToRegionID, FromStateID, ToStateID, "
        f"{from_country}, {to_country} FROM DimTransmissionElements ORDER BY ElementID"
    )
    return [
        {
            "key": f"line:{element_id}",
            "name": name,
            "element_type": element_type,
            "nominal_voltage_kv": nominal_kv,
            "from_region_code": region_codes.get(from_region_id),
            "to_region_code": region_codes.get(to_region_id),
            "from_state_code": _state_code(from_state_id),
            "to_state_code": _state_code(to_state_id),
            "from_country_code": _country_code(from_country_id),
            "to_country_code": _country_code(to_country_id),
            "observation_entity_key": _observation_entity_key(
                region_codes.get(from_region_id) or region_codes.get(to_region_id),
                "line",
                name,
            ),
        }
        for (
            element_id,
            name,
            element_type,
            nominal_kv,
            from_region_id,
            to_region_id,
            from_state_id,
            to_state_id,
            from_country_id,
            to_country_id,
        ) in rows
    ]


def _region_code(region_id: int, region_name: str) -> str:
    """Return a stable regional graph key, including unknown future regions."""

    return _REGION_CODES.get(region_name, f"REGION-{region_id}")


def _state_code(state_id: int | None) -> str | None:
    """Return the stable graph state key for an available dimension identifier."""

    return f"STATE-{state_id}" if state_id is not None else None


def _country_code(country_id: int | None) -> str | None:
    """Return the stable graph country key for an available dimension identifier."""

    return f"COUNTRY-{country_id}" if country_id is not None else None


def _observation_entity_key(
    region_code: str | None,
    category: str,
    name: str,
) -> str | None:
    """Build the exporter-compatible entity key when a regional source is known."""

    return f"{region_code}:{category}:{name}" if region_code else None


def _state_observation_entity_keys(
    region_code: str | None,
    state_name: str,
    state_code: str | None,
) -> list[str]:
    """Return every current exporter-compatible key for one state dimension.

    Northern and Southern exporters use approved state codes, while the other
    regional exporters currently use the canonical display name. Retaining both
    formats during the transition prevents duplicate graph identities without
    rewriting existing Timescale series.
    """

    if not region_code:
        return []
    if region_code in {"NR", "SR"} and state_code:
        return [f"{region_code}:state:{state_code}"]
    return [f"{region_code}:state:{state_name}"]
