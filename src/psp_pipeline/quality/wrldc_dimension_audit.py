"""Audit dimensions referenced by curated WRLDC facts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterable


LOGGER = logging.getLogger(__name__)


def audit_wrldc_dimensions(sqlite_path: Path) -> dict[str, Any]:
    """Return a read-only quality audit for WRLDC-referenced dimensions.

    The audit considers only dimensions reached through ``FactWRLDC*`` rows
    whose report document belongs to WRLDC.  This keeps mixed-RLDC SQLite
    staging databases from contributing unrelated findings.

    Args:
        sqlite_path: Existing curated SQLite database.

    Raises:
        FileNotFoundError: If ``sqlite_path`` does not exist.
        ValueError: If the database contains no WRLDC report documents.
    """

    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found at {sqlite_path}")

    with sqlite3.connect(
        f"file:{sqlite_path.resolve()}?mode=ro", uri=True
    ) as conn:
        conn.row_factory = sqlite3.Row
        report_count = _wrldc_report_count(conn)
        if report_count == 0:
            raise ValueError(
                f"Database at {sqlite_path} contains 0 WRLDC report documents; "
                "cannot audit WRLDC dimensions."
            )

        audits = {
            "states": _audit_states(conn),
            "grid_entities": _audit_grid_entities(conn),
            "voltage_nodes": _audit_voltage_nodes(conn),
            "reservoirs": _audit_reservoirs(conn),
            "transmission_elements": _audit_transmission_elements(conn),
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
        "Completed WRLDC dimension audit for %s report documents", report_count
    )
    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "database": str(sqlite_path),
        "wrldc_reports_found": report_count,
        "summary": summary,
        **audits,
    }


def _wrldc_report_count(conn: sqlite3.Connection) -> int:
    """Return the number of WRLDC report documents in ``conn``."""

    row = conn.execute(
        "SELECT COUNT(*) FROM psp_report_document WHERE rldc = 'wrldc'"
    ).fetchone()
    return int(row[0]) if row else 0


def _audit_states(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit states used by WRLDC state and generation facts."""

    rows = conn.execute(
        """
        SELECT DISTINCT state.StateID, state.StateName, state.StateCode, state.RegionID
        FROM DimStates AS state
        JOIN (
            SELECT fact.StateID
            FROM FactWRLDCStateDaily AS fact
            JOIN psp_report_document AS document
              ON document.id = fact.ReportDocumentID
            WHERE document.rldc = 'wrldc'
            UNION
            SELECT fact.StateID
            FROM FactWRLDCGenerationDaily AS fact
            JOIN psp_report_document AS document
              ON document.id = fact.ReportDocumentID
            WHERE document.rldc = 'wrldc' AND fact.StateID IS NOT NULL
        ) AS referenced ON referenced.StateID = state.StateID
        ORDER BY state.StateID
        """
    ).fetchall()
    return _audit_named_rows(
        rows,
        id_column="StateID",
        name_column="StateName",
        malformed=lambda row: not str(row["StateName"] or "").strip(),
    )


def _audit_grid_entities(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit grid entities used by WRLDC generation facts."""

    rows = conn.execute(
        """
        SELECT DISTINCT entity.EntityID, entity.EntityName, entity.EntityType,
               entity.StateID, entity.RegionID
        FROM DimGridEntities AS entity
        JOIN FactWRLDCGenerationDaily AS fact ON fact.EntityID = entity.EntityID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'wrldc'
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
    """Audit voltage nodes used by WRLDC voltage-profile facts."""

    rows = conn.execute(
        """
        SELECT DISTINCT node.VoltageNodeID, node.NodeName, node.NominalVoltageKV,
               node.StateID, node.RegionID
        FROM DimVoltageNodes AS node
        JOIN FactWRLDCVoltageProfile AS fact
          ON fact.VoltageNodeID = node.VoltageNodeID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'wrldc'
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
    """Audit reservoirs used by WRLDC reservoir facts."""

    rows = conn.execute(
        """
        SELECT DISTINCT reservoir.ReservoirID, reservoir.ReservoirName,
               reservoir.StateID, reservoir.RegionID
        FROM DimReservoirs AS reservoir
        JOIN FactWRLDCReservoirDaily AS fact
          ON fact.ReservoirID = reservoir.ReservoirID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'wrldc'
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
    """Audit transmission elements used by WRLDC exchange facts."""

    rows = conn.execute(
        """
        SELECT DISTINCT element.ElementID, element.ElementName, element.ElementType,
               element.NominalVoltageKV, element.FromRegionID, element.ToRegionID,
               element.FromStateID, element.ToStateID
        FROM DimTransmissionElements AS element
        JOIN FactWRLDCInterRegionalExchange AS fact
          ON fact.ElementID = element.ElementID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'wrldc'
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
