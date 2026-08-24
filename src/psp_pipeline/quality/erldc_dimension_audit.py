"""Audit dimensions referenced by curated ERLDC facts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterable

LOGGER = logging.getLogger(__name__)


def audit_erldc_dimensions(sqlite_path: Path) -> dict[str, Any]:
    """Return a read-only quality audit for ERLDC-referenced dimensions.

    The audit considers only dimensions reached through ``FactERLDC*`` rows
    whose report document belongs to ERLDC.  This keeps mixed-RLDC SQLite
    staging databases from contributing unrelated findings.

    Args:
        sqlite_path: Existing curated SQLite database.

    Raises:
        FileNotFoundError: If ``sqlite_path`` does not exist.
        ValueError: If the database contains no ERLDC report documents.
    """
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found at {sqlite_path}")

    with sqlite3.connect(
        f"file:{sqlite_path.resolve()}?mode=ro", uri=True
    ) as conn:
        conn.row_factory = sqlite3.Row
        report_count = _erldc_report_count(conn)
        if report_count == 0:
            raise ValueError(
                f"Database at {sqlite_path} contains 0 ERLDC report documents; "
                "cannot audit ERLDC dimensions."
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
    summary.update(
        {
            f"{name}_topology_enrichment_pending_count": len(
                value["topology_enrichment_pending"]
            )
            for name, value in audits.items()
            if "topology_enrichment_pending" in value
        }
    )

    LOGGER.info(
        "Completed ERLDC dimension audit for %s report documents", report_count
    )
    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "database": str(sqlite_path),
        "erldc_reports_found": report_count,
        "summary": summary,
        **audits,
    }


def _erldc_report_count(conn: sqlite3.Connection) -> int:
    """Return the number of ERLDC report documents in ``conn``."""
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_report_document'"
    ).fetchone()
    if not has_table:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) FROM psp_report_document WHERE rldc = 'erldc'"
    ).fetchone()
    return int(row[0]) if row else 0


def _has_table(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _audit_states(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit states used by ERLDC state and generation facts."""
    if not _has_table(conn, "FactERLDCStateDaily"):
        return _empty_audit("StateID", "StateName")

    rows = conn.execute(
        """
        SELECT DISTINCT state.StateID, state.StateName, state.StateCode, state.RegionID
        FROM DimStates AS state
        JOIN (
            SELECT fact.StateID
            FROM FactERLDCStateDaily AS fact
            JOIN psp_report_document AS document
              ON document.id = fact.ReportDocumentID
            WHERE document.rldc = 'erldc'
            UNION
            SELECT fact.StateID
            FROM FactERLDCGenerationDaily AS fact
            JOIN psp_report_document AS document
              ON document.id = fact.ReportDocumentID
            WHERE document.rldc = 'erldc'
        ) AS active
          ON active.StateID = state.StateID
        ORDER BY state.StateID
        """
    ).fetchall()
    return _audit_named_rows(
        rows,
        id_column="StateID",
        name_column="StateName",
        malformed=lambda row: not str(row["StateName"] or "").strip(),
        state_columns=(),
    )


def _audit_grid_entities(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit power stations and generating units used by ERLDC generation facts."""
    if not _has_table(conn, "FactERLDCGenerationDaily"):
        return _empty_audit("EntityID", "EntityName")

    rows = conn.execute(
        """
        SELECT DISTINCT entity.EntityID, entity.EntityName, entity.EntityType,
               entity.StateID, entity.RegionID
        FROM DimGridEntities AS entity
        JOIN FactERLDCGenerationDaily AS fact ON fact.EntityID = entity.EntityID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'erldc'
        ORDER BY entity.EntityID
        """
    ).fetchall()
    audit = _audit_named_rows(
        rows,
        id_column="EntityID",
        name_column="EntityName",
        malformed=lambda row: (
            not str(row["EntityName"] or "").strip()
            or not str(row["EntityType"] or "").strip()
        ),
    )
    audit["duplicates"] = _scoped_duplicates(
        rows,
        id_column="EntityID",
        name_column="EntityName",
        scope_columns=("StateID", "EntityType"),
    )
    return audit


def _audit_voltage_nodes(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit voltage nodes used by ERLDC voltage-profile facts."""
    if not _has_table(conn, "FactERLDCVoltageProfile"):
        return _empty_audit("VoltageNodeID", "NodeName")

    rows = conn.execute(
        """
        SELECT DISTINCT node.VoltageNodeID, node.NodeName, node.NominalVoltageKV,
               node.StateID, node.RegionID
        FROM DimVoltageNodes AS node
        JOIN FactERLDCVoltageProfile AS fact
          ON fact.VoltageNodeID = node.VoltageNodeID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'erldc'
        ORDER BY node.VoltageNodeID
        """
    ).fetchall()
    audit = _audit_named_rows(
        rows,
        id_column="VoltageNodeID",
        name_column="NodeName",
        malformed=lambda row: (
            row["NominalVoltageKV"] is None or row["NominalVoltageKV"] <= 0
        ),
        state_columns=(),
    )
    audit["topology_enrichment_pending"] = [
        {
            **dict(row),
            "reason": "state is not inferable from a PSP voltage-profile label",
        }
        for row in rows
        if row["StateID"] is None
    ]
    return audit


def _audit_reservoirs(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit reservoirs used by ERLDC reservoir facts."""
    if not _has_table(conn, "FactERLDCReservoirDaily"):
        return _empty_audit("ReservoirID", "ReservoirName")

    rows = conn.execute(
        """
        SELECT DISTINCT reservoir.ReservoirID, reservoir.ReservoirName,
               reservoir.StateID, reservoir.RegionID
        FROM DimReservoirs AS reservoir
        JOIN FactERLDCReservoirDaily AS fact
          ON fact.ReservoirID = reservoir.ReservoirID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'erldc'
        ORDER BY reservoir.ReservoirID
        """
    ).fetchall()
    return _audit_named_rows(
        rows,
        id_column="ReservoirID",
        name_column="ReservoirName",
        malformed=lambda row: not str(row["ReservoirName"] or "").strip(),
    )


def _audit_transmission_elements(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit transmission elements used by ERLDC exchange facts."""
    if not _has_table(conn, "FactERLDCInterRegionalExchange"):
        return _empty_audit("ElementID", "ElementName")

    rows = conn.execute(
        """
        SELECT DISTINCT element.ElementID, element.ElementName, element.ElementType,
               element.NominalVoltageKV, element.FromRegionID, element.ToRegionID,
               element.FromStateID, element.ToStateID
        FROM DimTransmissionElements AS element
        JOIN FactERLDCInterRegionalExchange AS fact
          ON fact.ElementID = element.ElementID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'erldc'
        ORDER BY element.ElementID
        """
    ).fetchall()
    audit = _audit_named_rows(
        rows,
        id_column="ElementID",
        name_column="ElementName",
        malformed=lambda row: (
            not str(row["ElementName"] or "").strip()
            or not str(row["ElementType"] or "").strip()
        ),
        region_columns=(),
        state_columns=(),
    )
    audit["topology_enrichment_pending"] = [
        {
            **dict(row),
            "reason": "PSP exchange sections do not authoritatively identify both endpoints",
        }
        for row in rows
        if any(
            row[column] is None
            for column in ("FromRegionID", "ToRegionID", "FromStateID", "ToStateID")
        )
    ]
    return audit


def _audit_countries(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit international countries referenced by ERLDC international exchange facts."""
    if not _has_table(conn, "FactERLDCInternationalExchange"):
        return _empty_audit("CountryID", "CountryName")

    rows = conn.execute(
        """
        SELECT DISTINCT country.CountryID, country.CountryName
        FROM DimCountries AS country
        JOIN FactERLDCInternationalExchange AS fact
          ON fact.CountryID = country.CountryID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'erldc'
        ORDER BY country.CountryID
        """
    ).fetchall()
    return _audit_named_rows(
        rows,
        id_column="CountryID",
        name_column="CountryName",
        malformed=lambda row: not str(row["CountryName"] or "").strip(),
        region_columns=(),
        state_columns=(),
    )


def _empty_audit(id_column: str, name_column: str) -> dict[str, Any]:
    return {
        "count": 0,
        "unresolved_region": [],
        "unresolved_state": [],
        "duplicates": [],
        "malformed": [],
        "ids": [],
    }


def _audit_named_rows(
    rows: Iterable[sqlite3.Row],
    *,
    id_column: str,
    name_column: str,
    malformed: Callable[[dict[str, Any]], bool],
    region_columns: tuple[str, ...] = ("RegionID",),
    state_columns: tuple[str, ...] = ("StateID",),
) -> dict[str, Any]:
    """Build a normalized-name audit record for a dimension query result."""
    records = [dict(row) for row in rows]
    normalized_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        normalized_name = re.sub(
            r"[^a-z0-9]", "", str(record[name_column] or "").lower()
        )
        normalized_groups[normalized_name].append(record)

    return {
        "count": len(records),
        "unresolved_region": [
            record
            for record in records
            if any(record.get(column) is None for column in region_columns)
        ],
        "unresolved_state": [
            record
            for record in records
            if any(record.get(column) is None for column in state_columns)
        ],
        "duplicates": [
            {
                "normalized_name": name,
                "count": len(group),
                "instances": group,
            }
            for name, group in normalized_groups.items()
            if name and len(group) > 1
        ],
        "malformed": [record for record in records if malformed(record)],
        "ids": [record[id_column] for record in records],
    }


def _scoped_duplicates(
    rows: Iterable[sqlite3.Row],
    *,
    id_column: str,
    name_column: str,
    scope_columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Find collisions only where a dimension's declared identity scope matches."""
    groups: dict[tuple[str, tuple[object, ...]], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        record = dict(row)
        normalized_name = re.sub(
            r"[^a-z0-9]", "", str(record[name_column] or "").lower()
        )
        groups[(normalized_name, tuple(record.get(column) for column in scope_columns))].append(record)
    return [
        {
            "normalized_name": normalized_name,
            "scope": dict(zip(scope_columns, scope, strict=True)),
            "count": len(group),
            "instances": group,
        }
        for (normalized_name, scope), group in groups.items()
        if normalized_name and len(group) > 1
    ]
