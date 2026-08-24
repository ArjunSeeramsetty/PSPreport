"""National multi-regional dimension quality audit across all 5 Indian RLDCs."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any

from psp_pipeline.quality.erldc_dimension_audit import audit_erldc_dimensions
from psp_pipeline.quality.nerldc_dimension_audit import audit_nerldc_dimensions
from psp_pipeline.quality.nrldc_dimension_audit import audit_nrldc_dimensions
from psp_pipeline.quality.wrldc_dimension_audit import audit_wrldc_dimensions

LOGGER = logging.getLogger(__name__)

SUPPORTED_RLDCS = ("srldc", "nrldc", "wrldc", "erldc", "nerldc")


def audit_national_dimensions(sqlite_path: Path | str) -> dict[str, Any]:
    """Execute a comprehensive dimension quality audit across all active RLDCs.

    Args:
        sqlite_path: Path to the curated SQLite database containing facts for one or more RLDCs.

    Returns:
        A dictionary containing national summary metrics and per-region breakdowns.

    Raises:
        FileNotFoundError: If `sqlite_path` does not exist.
        ValueError: If no report documents from any recognized RLDC are found.
    """
    db_path = Path(sqlite_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_report_document'"
        ).fetchone()
        if not table_exists:
            raise ValueError(f"No psp_report_document table in {db_path}")

        rldc_counts = {
            row["rldc"].lower(): row["cnt"]
            for row in conn.execute(
                "SELECT rldc, COUNT(*) AS cnt FROM psp_report_document WHERE rldc IS NOT NULL GROUP BY rldc"
            ).fetchall()
        }

    active_rldcs = [r for r in SUPPORTED_RLDCS if rldc_counts.get(r, 0) > 0]
    if not active_rldcs:
        raise ValueError(f"No supported RLDC reports found in {db_path}")

    regional_audits: dict[str, Any] = {}

    # Run specialized regional audits where available
    if "nrldc" in active_rldcs:
        try:
            regional_audits["nrldc"] = audit_nrldc_dimensions(db_path)
        except Exception as exc:
            LOGGER.warning("NRLDC audit failed: %s", exc)

    if "wrldc" in active_rldcs:
        try:
            regional_audits["wrldc"] = audit_wrldc_dimensions(db_path)
        except Exception as exc:
            LOGGER.warning("WRLDC audit failed: %s", exc)

    if "erldc" in active_rldcs:
        try:
            regional_audits["erldc"] = audit_erldc_dimensions(db_path)
        except Exception as exc:
            LOGGER.warning("ERLDC audit failed: %s", exc)

    if "nerldc" in active_rldcs:
        try:
            regional_audits["nerldc"] = audit_nerldc_dimensions(db_path)
        except Exception as exc:
            LOGGER.warning("NERLDC audit failed: %s", exc)

    if "srldc" in active_rldcs:
        regional_audits["srldc"] = _audit_srldc_dimensions(db_path)

    # Compute national rolled-up totals
    national_summary = {
        "active_rldcs": active_rldcs,
        "total_reports_found": sum(rldc_counts.get(r, 0) for r in active_rldcs),
        "total_states_count": 0,
        "total_grid_entities_count": 0,
        "total_voltage_nodes_count": 0,
        "total_reservoirs_count": 0,
        "total_transmission_elements_count": 0,
        "total_countries_count": 0,
        "total_unresolved_regions_count": 0,
        "total_unresolved_states_count": 0,
        "total_duplicate_entity_groups": 0,
        "total_topology_enrichment_pending_count": 0,
    }

    seen_states: set[str] = set()
    seen_entities: set[str] = set()
    seen_nodes: set[str] = set()
    seen_reservoirs: set[str] = set()
    seen_elements: set[str] = set()
    seen_countries: set[str] = set()

    for rldc, audit in regional_audits.items():
        summary = audit.get("summary", {})
        national_summary["total_unresolved_regions_count"] += sum(
            summary.get(k, 0) for k in summary if k.endswith("_unresolved_region_count")
        )
        national_summary["total_unresolved_states_count"] += sum(
            summary.get(k, 0) for k in summary if k.endswith("_unresolved_state_count")
        )
        national_summary["total_duplicate_entity_groups"] += sum(
            summary.get(k, 0) for k in summary if k.endswith("_duplicate_normalized_count")
        )
        national_summary["total_topology_enrichment_pending_count"] += sum(
            summary.get(k, 0)
            for k in summary
            if k.endswith("_topology_enrichment_pending_count")
        )

    national_summary["total_states_count"] = sum(
        a.get("summary", {}).get("dim_states_count", 0) for a in regional_audits.values()
    )
    national_summary["total_grid_entities_count"] = sum(
        a.get("summary", {}).get("dim_grid_entities_count", 0) for a in regional_audits.values()
    )
    national_summary["total_voltage_nodes_count"] = sum(
        a.get("summary", {}).get("dim_voltage_nodes_count", 0) for a in regional_audits.values()
    )
    national_summary["total_reservoirs_count"] = sum(
        a.get("summary", {}).get("dim_reservoirs_count", 0) for a in regional_audits.values()
    )
    national_summary["total_transmission_elements_count"] = sum(
        a.get("summary", {}).get("dim_transmission_elements_count", 0) for a in regional_audits.values()
    )
    national_summary["total_countries_count"] = sum(
        a.get("summary", {}).get("dim_countries_count", 0) for a in regional_audits.values()
    )

    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "database": str(db_path),
        "national_summary": national_summary,
        "regional_breakdowns": regional_audits,
    }


def _audit_srldc_dimensions(sqlite_path: Path) -> dict[str, Any]:
    """Read-only SRLDC dimension quality audit."""
    with sqlite3.connect(f"file:{sqlite_path.resolve()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        states = [
            dict(row)
            for row in conn.execute(
                """
                SELECT DISTINCT s.StateID, s.StateName, s.StateCode, s.RegionID, r.RegionName
                FROM DimStates AS s
                LEFT JOIN DimRegions AS r ON r.RegionID = s.RegionID
                JOIN FactSRLDCStateDaily AS f ON f.StateID = s.StateID
                """
            ).fetchall()
        ]
        entities = [
            dict(row)
            for row in conn.execute(
                """
                SELECT DISTINCT e.EntityID, e.EntityName, e.EntityType, e.StateID, e.RegionID
                FROM DimGridEntities AS e
                JOIN FactSRLDCGenerationDaily AS f ON f.EntityID = e.EntityID
                """
            ).fetchall()
        ]

    unresolved_state_regions = [
        s["StateName"] for s in states if s["RegionID"] is None or s["RegionName"] is None
    ]
    unresolved_entity_states = [e["EntityName"] for e in entities if e["StateID"] is None]

    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "database": str(sqlite_path),
        "srldc_reports_found": len(states),
        "summary": {
            "dim_states_count": len(states),
            "dim_grid_entities_count": len(entities),
            "dim_voltage_nodes_count": 0,
            "dim_reservoirs_count": 0,
            "dim_transmission_elements_count": 0,
            "dim_countries_count": 0,
            "states_unresolved_region_count": len(unresolved_state_regions),
            "grid_entities_unresolved_region_count": 0,
            "grid_entities_unresolved_state_count": len(unresolved_entity_states),
        },
        "states": {
            "count": len(states),
            "unresolved_region": unresolved_state_regions,
            "names": [s["StateName"] for s in states],
        },
        "grid_entities": {
            "count": len(entities),
            "unresolved_state": unresolved_entity_states,
            "names": [e["EntityName"] for e in entities],
        },
    }
