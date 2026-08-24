"""Audit dimensions referenced by curated NERLDC facts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterable

LOGGER = logging.getLogger(__name__)


def audit_nerldc_dimensions(sqlite_path: Path) -> dict[str, Any]:
    """Return a read-only quality audit for NERLDC-referenced dimensions.

    The audit considers dimensions reached through ``FactNERLDC*`` rows
    whose report document belongs to NERLDC.

    Args:
        sqlite_path: Existing curated SQLite database.

    Raises:
        FileNotFoundError: If ``sqlite_path`` does not exist.
        ValueError: If the database contains no NERLDC report documents.
    """
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found at {sqlite_path}")

    with sqlite3.connect(
        f"file:{sqlite_path.resolve()}?mode=ro", uri=True
    ) as conn:
        conn.row_factory = sqlite3.Row
        report_count = _nerldc_report_count(conn)
        if report_count == 0:
            raise ValueError(
                f"Database at {sqlite_path} contains 0 NERLDC report documents; "
                "cannot audit NERLDC dimensions."
            )

        audits = {
            "states": _audit_states(conn),
            "grid_entities": _audit_grid_entities(conn),
            "voltage_nodes": _audit_voltage_nodes(conn),
            "reservoirs": _audit_reservoirs(conn),
            "transmission_elements": _audit_transmission_elements(conn),
            "countries": _audit_countries(conn),
        }

    summary = {
        f"dim_{name}_count": value["count"] for name, value in audits.items()
    }
    summary.update(
        {
            f"{name}_unresolved_region_count": len(value["unresolved_region"])
            for name, value in audits.items()
            if "unresolved_region" in value
        }
    )
    summary.update(
        {
            f"{name}_unresolved_state_count": len(value["unresolved_state"])
            for name, value in audits.items()
            if "unresolved_state" in value
        }
    )
    summary.update(
        {
            f"{name}_duplicate_normalized_count": len(value["duplicates"])
            for name, value in audits.items()
        }
    )
    summary.update(
        {
            f"{name}_malformed_count": len(value["malformed"])
            for name, value in audits.items()
        }
    )
    if "topology_enrichment_pending" in audits["voltage_nodes"]:
        summary["voltage_nodes_topology_enrichment_pending_count"] = len(
            audits["voltage_nodes"]["topology_enrichment_pending"]
        )
    if "topology_enrichment_pending" in audits["transmission_elements"]:
        summary["transmission_elements_topology_enrichment_pending_count"] = len(
            audits["transmission_elements"]["topology_enrichment_pending"]
        )

    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "database": str(sqlite_path),
        "nerldc_reports_found": report_count,
        "summary": summary,
        **audits,
    }


def _nerldc_report_count(conn: sqlite3.Connection) -> int:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_report_document'"
    ).fetchone()
    if not table_exists:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) FROM psp_report_document WHERE rldc = 'nerldc'"
    ).fetchone()
    return int(row[0]) if row else 0


def _audit_states(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = _table_rows(
        conn,
        """
        SELECT DISTINCT s.StateID, s.StateName, s.StateCode, s.RegionID
        FROM DimStates AS s
        JOIN FactNERLDCStateDaily AS f ON f.StateID = s.StateID
        ORDER BY s.StateID
        """,
        fallback_query="""
        SELECT DISTINCT s.StateID, s.StateName, s.StateCode, s.RegionID
        FROM DimStates AS s
        JOIN DimRegions AS r ON r.RegionID = s.RegionID
        WHERE r.RegionCode = 'NER'
        ORDER BY s.StateID
        """,
    )
    return {
        "count": len(rows),
        "unresolved_region": [dict(r) for r in rows if r["RegionID"] is None],
        "unresolved_state": [],
        "duplicates": _find_duplicates(rows, lambda r: str(r["StateName"])),
        "malformed": [
            dict(r)
            for r in rows
            if not r["StateName"] or not str(r["StateName"]).strip()
        ],
        "ids": [int(r["StateID"]) for r in rows],
    }


def _audit_grid_entities(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = _table_rows(
        conn,
        """
        SELECT DISTINCT e.EntityID, e.EntityName, e.EntityType, e.StateID, e.RegionID
        FROM DimGridEntities AS e
        JOIN FactNERLDCGenerationDaily AS f ON f.EntityID = e.EntityID
        ORDER BY e.EntityID
        """,
    )
    return {
        "count": len(rows),
        "unresolved_region": [dict(r) for r in rows if r["RegionID"] is None],
        "unresolved_state": [dict(r) for r in rows if r["StateID"] is None],
        "duplicates": _find_duplicates(
            rows,
            lambda r: str(r["EntityName"]),
            scope_key=lambda r: (r["StateID"], r["EntityType"]),
        ),
        "malformed": [
            dict(r)
            for r in rows
            if not r["EntityName"]
            or not str(r["EntityName"]).strip()
            or len(str(r["EntityName"]).strip()) < 2
        ],
        "ids": [int(r["EntityID"]) for r in rows],
    }


def _audit_voltage_nodes(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = _table_rows(
        conn,
        """
        SELECT DISTINCT n.VoltageNodeID, n.NodeName, n.NominalVoltageKV, n.StateID, n.RegionID
        FROM DimVoltageNodes AS n
        JOIN FactNERLDCVoltageProfile AS f ON f.VoltageNodeID = n.VoltageNodeID
        ORDER BY n.VoltageNodeID
        """,
    )
    return {
        "count": len(rows),
        "unresolved_region": [dict(r) for r in rows if r["RegionID"] is None],
        "unresolved_state": [dict(r) for r in rows if r["StateID"] is None],
        "duplicates": _find_duplicates(rows, lambda r: str(r["NodeName"])),
        "malformed": [
            dict(r)
            for r in rows
            if not r["NodeName"] or not str(r["NodeName"]).strip()
        ],
        "ids": [int(r["VoltageNodeID"]) for r in rows],
        "topology_enrichment_pending": [
            dict(r) for r in rows if r["StateID"] is None or r["RegionID"] is None
        ],
    }


def _audit_reservoirs(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = _table_rows(
        conn,
        """
        SELECT DISTINCT r.ReservoirID, r.ReservoirName, r.StateID, r.RegionID
        FROM DimReservoirs AS r
        JOIN FactNERLDCReservoirDaily AS f ON f.ReservoirID = r.ReservoirID
        ORDER BY r.ReservoirID
        """,
    )
    return {
        "count": len(rows),
        "unresolved_region": [dict(r) for r in rows if r["RegionID"] is None],
        "unresolved_state": [dict(r) for r in rows if r["StateID"] is None],
        "duplicates": _find_duplicates(rows, lambda r: str(r["ReservoirName"])),
        "malformed": [
            dict(r)
            for r in rows
            if not r["ReservoirName"] or not str(r["ReservoirName"]).strip()
        ],
        "ids": [int(r["ReservoirID"]) for r in rows],
    }


def _audit_transmission_elements(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit NERLDC inter-regional elements using the canonical endpoint schema."""

    rows = _table_rows(
        conn,
        """
        SELECT DISTINCT
            e.ElementID,
            e.ElementName,
            e.ElementType,
            e.FromRegionID,
            e.ToRegionID,
            e.FromStateID,
            e.ToStateID,
            e.FromCountryID,
            e.ToCountryID
        FROM DimTransmissionElements AS e
        JOIN FactNERLDCInterRegionalExchange AS f ON f.ElementID = e.ElementID
        ORDER BY e.ElementID
        """,
    )
    return {
        "count": len(rows),
        "unresolved_region": [
            dict(r)
            for r in rows
            if (
                r["FromRegionID"] is None and r["FromCountryID"] is None
            ) or (
                r["ToRegionID"] is None and r["ToCountryID"] is None
            )
        ],
        "unresolved_state": [
            dict(r)
            for r in rows
            if (
                r["FromStateID"] is None and r["FromCountryID"] is None
            ) or (
                r["ToStateID"] is None and r["ToCountryID"] is None
            )
        ],
        "duplicates": _find_duplicates(rows, lambda r: str(r["ElementName"])),
        "malformed": [
            dict(r)
            for r in rows
            if not r["ElementName"] or not str(r["ElementName"]).strip()
        ],
        "ids": [int(r["ElementID"]) for r in rows],
        "topology_enrichment_pending": [
            dict(r)
            for r in rows
            if (
                r["FromRegionID"] is None and r["FromCountryID"] is None
            ) or (
                r["ToRegionID"] is None and r["ToCountryID"] is None
            )
        ],
    }


def _audit_countries(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit countries referenced by NERLDC international exchange facts."""

    rows = _table_rows(
        conn,
        """
        SELECT DISTINCT c.CountryID, c.CountryName
        FROM DimCountries AS c
        JOIN FactNERLDCInternationalExchange AS f ON f.CountryID = c.CountryID
        ORDER BY c.CountryID
        """,
    )
    return {
        "count": len(rows),
        "unresolved_region": [],
        "unresolved_state": [],
        "duplicates": _find_duplicates(rows, lambda r: str(r["CountryName"])),
        "malformed": [
            dict(r)
            for r in rows
            if not r["CountryName"] or not str(r["CountryName"]).strip()
        ],
        "ids": [int(r["CountryID"]) for r in rows],
    }


def _table_rows(
    conn: sqlite3.Connection,
    query: str,
    fallback_query: str | None = None,
) -> list[sqlite3.Row]:
    try:
        return conn.execute(query).fetchall()
    except sqlite3.OperationalError:
        if fallback_query is not None:
            try:
                return conn.execute(fallback_query).fetchall()
            except sqlite3.OperationalError:
                return []
        return []


def _find_duplicates(
    rows: Iterable[sqlite3.Row],
    name_getter: Callable[[sqlite3.Row], str],
    scope_key: Callable[[sqlite3.Row], Any] | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        name = name_getter(row)
        normalized = _normalize_name(name)
        if not normalized:
            continue
        scope = scope_key(row) if scope_key else None
        buckets[(scope, normalized)].append(dict(row))

    duplicates: list[dict[str, Any]] = []
    for (scope, norm), group in buckets.items():
        if len(group) > 1:
            record: dict[str, Any] = {
                "normalized_name": norm,
                "count": len(group),
                "instances": group,
            }
            if scope is not None:
                record["scope"] = scope
            duplicates.append(record)
    return duplicates


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"[\s\-_/]+", "", name)
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)
    return cleaned.strip().lower()
