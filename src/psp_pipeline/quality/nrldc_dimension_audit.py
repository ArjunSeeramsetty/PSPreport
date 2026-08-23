"""Audit dimension quality for NRLDC voltage nodes, reservoirs, and transmission elements."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any


def audit_nrldc_dimensions(sqlite_path: Path) -> dict[str, Any]:
    """Inspect curated NRLDC-referenced dimension tables and report quality anomalies without mutating data.

    Args:
        sqlite_path: Path to the SQLite database to inspect.

    Returns:
        A dictionary containing counts and details of unresolved/duplicate/malformed dimensions.

    Raises:
        FileNotFoundError: If ``sqlite_path`` does not exist.
        ValueError: If the database contains no NRLDC report documents.
    """

    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found at {sqlite_path}")

    conn = sqlite3.connect(f"file:{sqlite_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # Verify NRLDC documents exist in the database
    nrldc_doc_count_row = conn.execute(
        "SELECT COUNT(*) FROM psp_report_document WHERE rldc = 'nrldc'"
    ).fetchone()
    nrldc_doc_count = nrldc_doc_count_row[0] if nrldc_doc_count_row else 0
    if nrldc_doc_count == 0:
        conn.close()
        raise ValueError(f"Database at {sqlite_path} contains 0 NRLDC report documents; cannot audit NRLDC dimensions.")

    # 1. Voltage Nodes referenced by FactNRLDCVoltageProfile
    voltage_nodes_rows = conn.execute(
        """
        SELECT DISTINCT node.VoltageNodeID, node.NodeName, node.NominalVoltageKV, node.StateID, node.RegionID
        FROM DimVoltageNodes AS node
        JOIN FactNRLDCVoltageProfile AS fact ON fact.VoltageNodeID = node.VoltageNodeID
        ORDER BY node.VoltageNodeID
        """
    ).fetchall()

    vn_unresolved_region: list[dict[str, Any]] = []
    vn_unresolved_state: list[dict[str, Any]] = []
    vn_malformed: list[dict[str, Any]] = []
    vn_normalized_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in voltage_nodes_rows:
        item = {
            "id": row["VoltageNodeID"],
            "name": row["NodeName"],
            "nominal_kv": row["NominalVoltageKV"],
            "state_id": row["StateID"],
            "region_id": row["RegionID"],
        }
        norm = re.sub(r"[^a-z0-9]", "", str(row["NodeName"]).lower())
        vn_normalized_groups[norm].append(item)

        if row["RegionID"] is None:
            vn_unresolved_region.append(item)
        if row["StateID"] is None:
            vn_unresolved_state.append(item)
        if row["NominalVoltageKV"] is None or row["NominalVoltageKV"] <= 0:
            vn_malformed.append(item)

    vn_duplicates = [
        {"normalized_name": k, "count": len(v), "instances": v}
        for k, v in vn_normalized_groups.items()
        if len(v) > 1
    ]

    # 2. Reservoirs referenced by FactNRLDCReservoirDaily
    reservoir_rows = conn.execute(
        """
        SELECT DISTINCT res.ReservoirID, res.ReservoirName, res.StateID, res.RegionID
        FROM DimReservoirs AS res
        JOIN FactNRLDCReservoirDaily AS fact ON fact.ReservoirID = res.ReservoirID
        ORDER BY res.ReservoirID
        """
    ).fetchall()

    res_unresolved_region: list[dict[str, Any]] = []
    res_unresolved_state: list[dict[str, Any]] = []
    res_normalized_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in reservoir_rows:
        item = {
            "id": row["ReservoirID"],
            "name": row["ReservoirName"],
            "state_id": row["StateID"],
            "region_id": row["RegionID"],
        }
        norm = re.sub(r"[^a-z0-9]", "", str(row["ReservoirName"]).lower())
        res_normalized_groups[norm].append(item)

        if row["RegionID"] is None:
            res_unresolved_region.append(item)
        if row["StateID"] is None:
            res_unresolved_state.append(item)

    res_duplicates = [
        {"normalized_name": k, "count": len(v), "instances": v}
        for k, v in res_normalized_groups.items()
        if len(v) > 1
    ]

    # 3. Transmission Elements referenced by FactNRLDCInterRegionalExchange or FactNRLDCInternationalExchange
    element_rows = conn.execute(
        """
        SELECT DISTINCT elem.ElementID, elem.ElementName, elem.ElementType, elem.NominalVoltageKV,
               elem.CircuitCount, elem.FromRegionID, elem.ToRegionID, elem.FromStateID, elem.ToStateID
        FROM DimTransmissionElements AS elem
        WHERE elem.ElementID IN (SELECT ElementID FROM FactNRLDCInterRegionalExchange)
           OR elem.ElementID IN (SELECT ElementID FROM FactNRLDCInternationalExchange)
        ORDER BY elem.ElementID
        """
    ).fetchall()

    elem_unresolved_region: list[dict[str, Any]] = []
    elem_unresolved_state: list[dict[str, Any]] = []
    elem_malformed: list[dict[str, Any]] = []
    elem_normalized_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in element_rows:
        item = {
            "id": row["ElementID"],
            "name": row["ElementName"],
            "type": row["ElementType"],
            "nominal_kv": row["NominalVoltageKV"],
            "from_region_id": row["FromRegionID"],
            "to_region_id": row["ToRegionID"],
            "from_state_id": row["FromStateID"],
            "to_state_id": row["ToStateID"],
        }
        norm = re.sub(r"[^a-z0-9]", "", str(row["ElementName"]).lower())
        elem_normalized_groups[norm].append(item)

        if row["FromRegionID"] is None or row["ToRegionID"] is None:
            elem_unresolved_region.append(item)
        if row["FromStateID"] is None or row["ToStateID"] is None:
            elem_unresolved_state.append(item)
        if not re.search(r"[a-zA-Z0-9]", str(row["ElementName"])):
            elem_malformed.append(item)

    elem_duplicates = [
        {"normalized_name": k, "count": len(v), "instances": v}
        for k, v in elem_normalized_groups.items()
        if len(v) > 1
    ]

    conn.close()

    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "database": str(sqlite_path),
        "nrldc_reports_found": nrldc_doc_count,
        "summary": {
            "dim_voltage_nodes_count": len(voltage_nodes_rows),
            "dim_reservoirs_count": len(reservoir_rows),
            "dim_transmission_elements_count": len(element_rows),
            "voltage_nodes_unresolved_region_count": len(vn_unresolved_region),
            "voltage_nodes_unresolved_state_count": len(vn_unresolved_state),
            "voltage_nodes_duplicate_normalized_count": len(vn_duplicates),
            "voltage_nodes_malformed_count": len(vn_malformed),
            "reservoirs_unresolved_region_count": len(res_unresolved_region),
            "reservoirs_unresolved_state_count": len(res_unresolved_state),
            "reservoirs_duplicate_normalized_count": len(res_duplicates),
            "transmission_elements_unresolved_region_count": len(elem_unresolved_region),
            "transmission_elements_unresolved_state_count": len(elem_unresolved_state),
            "transmission_elements_duplicate_normalized_count": len(elem_duplicates),
            "transmission_elements_malformed_count": len(elem_malformed),
        },
        "voltage_nodes": {
            "unresolved_region": vn_unresolved_region,
            "unresolved_state": vn_unresolved_state,
            "duplicates": vn_duplicates,
            "malformed": vn_malformed,
        },
        "reservoirs": {
            "unresolved_region": res_unresolved_region,
            "unresolved_state": res_unresolved_state,
            "duplicates": res_duplicates,
        },
        "transmission_elements": {
            "unresolved_region": elem_unresolved_region,
            "unresolved_state": elem_unresolved_state,
            "duplicates": elem_duplicates,
            "malformed": elem_malformed,
        },
    }
