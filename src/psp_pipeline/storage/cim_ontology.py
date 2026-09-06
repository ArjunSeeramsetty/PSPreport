"""IEC 61970/61968 CIM class mapping for curated Neo4j topology.

Existing proprietary labels are retained. CIM labels and ``mrid`` properties
are added alongside so EMS consumers can traverse the graph without a
breaking relabel.
"""

from __future__ import annotations

from typing import Any, Mapping

CIM_PLANT = "cim:Plant"
CIM_GENERATING_UNIT = "cim:GeneratingUnit"
CIM_SYNCHRONOUS_MACHINE = "cim:SynchronousMachine"
CIM_AC_LINE_SEGMENT = "cim:ACLineSegment"
CIM_VOLTAGE_LEVEL = "cim:VoltageLevel"
CIM_ENERGY_CONSUMER = "cim:EnergyConsumer"
CIM_ENERGY_SCHEDULING_COORDINATOR = "cim:EnergySchedulingCoordinator"
CIM_CONTROL_AREA = "cim:ControlArea"
CIM_GEOGRAPHICAL_REGION = "cim:GeographicalRegion"
CIM_SUB_GEOGRAPHICAL_REGION = "cim:SubGeographicalRegion"
CIM_IDENTIFIED_OBJECT = "cim:IdentifiedObject"

_GRID_ENTITY_CIM_CLASS = {
    "power_station": CIM_PLANT,
    "control_area": CIM_CONTROL_AREA,
    "market_participant": CIM_ENERGY_SCHEDULING_COORDINATOR,
    "beneficiary": CIM_ENERGY_CONSUMER,
    "state": CIM_ENERGY_CONSUMER,
}


def cim_class_for_grid_entity(entity_type: str | None) -> str:
    """Return the CIM base class for a curated ``DimGridEntities`` row."""

    if not entity_type:
        return CIM_IDENTIFIED_OBJECT
    return _GRID_ENTITY_CIM_CLASS.get(str(entity_type).lower(), CIM_IDENTIFIED_OBJECT)


def cim_label_for_class(cim_class: str) -> str:
    """Return the Neo4j extra label derived from a CIM class URI."""

    return cim_class.rsplit(":", 1)[-1]


def annotate_station(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a station topology row and attach CIM identifiers."""

    payload = dict(row)
    payload["mrid"] = payload.get("mrid") or payload["key"]
    payload["cim_class"] = CIM_PLANT
    payload["cim_label"] = cim_label_for_class(CIM_PLANT)
    return payload


def annotate_unit(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a generating-unit row and attach CIM identifiers."""

    payload = dict(row)
    payload["mrid"] = payload.get("mrid") or payload["key"]
    payload["cim_class"] = CIM_GENERATING_UNIT
    payload["cim_label"] = cim_label_for_class(CIM_GENERATING_UNIT)
    payload["equipment_cim_class"] = CIM_SYNCHRONOUS_MACHINE
    return payload


def annotate_voltage_node(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a voltage-node row and attach CIM identifiers."""

    payload = dict(row)
    payload["mrid"] = payload.get("mrid") or payload["key"]
    payload["cim_class"] = CIM_VOLTAGE_LEVEL
    payload["cim_label"] = cim_label_for_class(CIM_VOLTAGE_LEVEL)
    return payload


def annotate_transmission_line(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a transmission-line row and attach CIM identifiers."""

    payload = dict(row)
    payload["mrid"] = payload.get("mrid") or payload["key"]
    payload["cim_class"] = CIM_AC_LINE_SEGMENT
    payload["cim_label"] = cim_label_for_class(CIM_AC_LINE_SEGMENT)
    return payload


def annotate_grid_entity(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a commercial or control-area entity and attach CIM identifiers."""

    payload = dict(row)
    payload["mrid"] = payload.get("mrid") or payload["key"]
    payload["cim_class"] = cim_class_for_grid_entity(payload.get("entity_type"))
    payload["cim_label"] = cim_label_for_class(payload["cim_class"])
    return payload


def annotate_region(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a region row and attach CIM identifiers."""

    payload = dict(row)
    payload["mrid"] = payload.get("mrid") or payload.get("code")
    payload["cim_class"] = CIM_SUB_GEOGRAPHICAL_REGION
    payload["cim_label"] = cim_label_for_class(CIM_SUB_GEOGRAPHICAL_REGION)
    return payload


def annotate_state(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a state row and attach CIM identifiers."""

    payload = dict(row)
    payload["mrid"] = payload.get("mrid") or payload.get("code")
    payload["cim_class"] = CIM_GEOGRAPHICAL_REGION
    payload["cim_label"] = cim_label_for_class(CIM_GEOGRAPHICAL_REGION)
    return payload
