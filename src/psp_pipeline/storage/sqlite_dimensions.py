"""Resolve source names to verified canonical SQLite dimensions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import sqlite3


class DimensionResolutionError(ValueError):
    """Raised when a source entity cannot be resolved to a valid dimension."""


@dataclass(frozen=True)
class GenerationIdentity:
    """Canonical station, unit, or aggregate keys for one generation row."""

    entity_type: str
    station_id: int | None = None
    generating_unit_id: int | None = None
    aggregate_id: int | None = None


def normalize_dimension_name(value: str) -> str:
    """Normalize a source label for deterministic alias matching."""

    return re.sub(r"[^a-z0-9]", "", value.lower())


def resolve_state_id(
    conn: sqlite3.Connection,
    source_id: str,
    raw_name: str,
) -> int:
    """Resolve an approved source-specific state alias and verify its target."""

    normalized = normalize_dimension_name(raw_name)
    row = conn.execute(
        """
        SELECT a.StateID
        FROM DimStateAliases AS a
        JOIN DimStates AS s ON s.StateID = a.StateID
        WHERE a.SourceID = ? AND a.NormalizedName = ?
          AND a.ApprovalStatus = 'approved'
        """,
        (source_id, normalized),
    ).fetchone()
    if not row:
        raise DimensionResolutionError(f"unapproved state alias: {raw_name}")
    return int(row[0])


def resolve_generation_identity(
    conn: sqlite3.Connection,
    source_id: str,
    raw_name: str,
    state_id: int | None,
    region_id: int,
    generation_source_id: int | None,
    installed_capacity_mw: float,
    is_total: bool,
) -> GenerationIdentity:
    """Resolve and verify the canonical identity for a generation row."""

    if not raw_name.strip():
        raise DimensionResolutionError("empty generation entity name")
    if is_total:
        aggregate_id = _resolve_aggregate(
            conn, source_id, raw_name, state_id, region_id, generation_source_id
        )
        return GenerationIdentity("aggregate", aggregate_id=aggregate_id)

    unit_match = re.search(r"\bunit[\s_-]*(\d+[a-z]?)\b", raw_name, re.IGNORECASE)
    if unit_match:
        station_name = re.sub(
            r"\bunit[\s_-]*\d+[a-z]?\b", "", raw_name,
            flags=re.IGNORECASE,
        )
        station_id = _resolve_station(
            conn, source_id, station_name, state_id, region_id,
            generation_source_id, installed_capacity_mw,
        )
        unit_id = _resolve_unit(
            conn, source_id, raw_name, station_id, unit_match.group(1),
            installed_capacity_mw,
        )
        return GenerationIdentity(
            "generating_unit", station_id=station_id, generating_unit_id=unit_id
        )

    station_id = _resolve_station(
        conn, source_id, raw_name, state_id, region_id,
        generation_source_id, installed_capacity_mw,
    )
    return GenerationIdentity("power_station", station_id=station_id)


def record_resolution_issue(
    conn: sqlite3.Connection,
    report_id: int,
    source_id: str,
    entity_type: str,
    raw_name: str,
    reason: str,
) -> None:
    """Persist an unresolved dimension value for human adjudication."""

    conn.execute(
        """
        INSERT OR IGNORE INTO dimension_resolution_issue(
            ReportDocumentID, SourceID, EntityType, RawName,
            NormalizedName, Reason, CreatedAt
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id, source_id, entity_type, raw_name,
            normalize_dimension_name(raw_name), reason,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def _canonical_station_name(raw_name: str) -> str:
    """Remove trailing capacity notation without discarding station identity."""

    value = re.sub(r"\s+", " ", raw_name).strip()
    capacity_suffix = re.compile(
        r"\s*\(\s*[\d.]+(?:\s*[*xX+]\s*[\d.]+|\s*MW|\s*)+\s*\)\s*$"
    )
    previous = None
    while previous != value:
        previous = value
        value = capacity_suffix.sub("", value).strip(" -")
    return value or raw_name.strip()


def _alias_key(raw_name: str) -> str:
    """Create a stable alias key insensitive to capacity-format punctuation."""

    return normalize_dimension_name(_canonical_station_name(raw_name))


def _stable_code(prefix: str, *parts: object) -> str:
    """Build a reproducible compact master-data code."""

    payload = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"


def _approved_alias_id(
    conn: sqlite3.Connection,
    source_id: str,
    entity_type: str,
    normalized_name: str,
) -> int | None:
    row = conn.execute(
        """
        SELECT CanonicalEntityID FROM DimEntityAliases
        WHERE SourceID = ? AND EntityType = ? AND NormalizedName = ?
          AND ApprovalStatus IN ('approved', 'auto_exact')
        """,
        (source_id, entity_type, normalized_name),
    ).fetchone()
    return int(row[0]) if row else None


def _insert_alias(
    conn: sqlite3.Connection,
    source_id: str,
    entity_type: str,
    raw_name: str,
    normalized_name: str,
    canonical_id: int,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO DimEntityAliases(
            SourceID, EntityType, RawName, NormalizedName, CanonicalEntityID,
            MatchMethod, MatchConfidence, ApprovalStatus
        ) VALUES (?, ?, ?, ?, ?, 'deterministic_normalization', 1.0, 'auto_exact')
        """,
        (source_id, entity_type, raw_name, normalized_name, canonical_id),
    )


def _resolve_station(
    conn: sqlite3.Connection,
    source_id: str,
    raw_name: str,
    state_id: int | None,
    region_id: int,
    generation_source_id: int | None,
    capacity_mw: float,
) -> int:
    canonical_name = _canonical_station_name(raw_name)
    normalized = _alias_key(raw_name)
    station_id = _approved_alias_id(conn, source_id, "power_station", normalized)
    if station_id is None:
        row = conn.execute(
            """
            SELECT StationID FROM DimPowerStations
            WHERE CanonicalStationName = ? AND StateID IS ? AND RegionID = ?
            """,
            (canonical_name, state_id, region_id),
        ).fetchone()
        if row:
            station_id = int(row[0])
        else:
            cursor = conn.execute(
                """
                INSERT INTO DimPowerStations(
                    StationCode, CanonicalStationName, StateID, RegionID,
                    GenerationSourceID, InstalledCapacityMW
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    _stable_code("STN", normalized, state_id, region_id),
                    canonical_name, state_id, region_id,
                    generation_source_id, capacity_mw,
                ),
            )
            station_id = int(cursor.lastrowid)
        _insert_alias(
            conn, source_id, "power_station", raw_name, normalized, station_id
        )
    exists = conn.execute(
        "SELECT 1 FROM DimPowerStations WHERE StationID = ?", (station_id,)
    ).fetchone()
    if not exists:
        raise DimensionResolutionError(f"station alias has invalid target: {raw_name}")
    return station_id


def _resolve_unit(
    conn: sqlite3.Connection,
    source_id: str,
    raw_name: str,
    station_id: int,
    unit_number: str,
    capacity_mw: float,
) -> int:
    normalized = normalize_dimension_name(raw_name)
    unit_id = _approved_alias_id(conn, source_id, "generating_unit", normalized)
    if unit_id is None:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO DimGeneratingUnits(
                UnitCode, StationID, CanonicalUnitName, UnitNumber, CapacityMW
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                _stable_code("UNIT", station_id, unit_number), station_id,
                raw_name.strip(), unit_number, capacity_mw,
            ),
        )
        if cursor.lastrowid:
            unit_id = int(cursor.lastrowid)
        else:
            unit_id = int(conn.execute(
                """
                SELECT GeneratingUnitID FROM DimGeneratingUnits
                WHERE StationID = ? AND CanonicalUnitName = ?
                """,
                (station_id, raw_name.strip()),
            ).fetchone()[0])
        _insert_alias(
            conn, source_id, "generating_unit", raw_name, normalized, unit_id
        )
    exists = conn.execute(
        "SELECT 1 FROM DimGeneratingUnits WHERE GeneratingUnitID = ?", (unit_id,)
    ).fetchone()
    if not exists:
        raise DimensionResolutionError(f"unit alias has invalid target: {raw_name}")
    return unit_id


def _resolve_aggregate(
    conn: sqlite3.Connection,
    source_id: str,
    raw_name: str,
    state_id: int | None,
    region_id: int,
    generation_source_id: int | None,
) -> int:
    canonical_name = re.sub(r"\s+", " ", raw_name).strip()
    normalized = normalize_dimension_name(canonical_name)
    aggregate_id = _approved_alias_id(
        conn, source_id, "generation_aggregate", normalized
    )
    if aggregate_id is None:
        row = conn.execute(
            """
            SELECT AggregateID FROM DimGenerationAggregates
            WHERE CanonicalAggregateName = ? AND StateID IS ? AND RegionID = ?
            """,
            (canonical_name, state_id, region_id),
        ).fetchone()
        if row:
            aggregate_id = int(row[0])
        else:
            cursor = conn.execute(
                """
                INSERT INTO DimGenerationAggregates(
                    AggregateCode, CanonicalAggregateName, StateID,
                    RegionID, GenerationSourceID
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _stable_code("AGG", normalized, state_id, region_id),
                    canonical_name, state_id, region_id, generation_source_id,
                ),
            )
            aggregate_id = int(cursor.lastrowid)
        _insert_alias(
            conn, source_id, "generation_aggregate", raw_name,
            normalized, aggregate_id,
        )
    exists = conn.execute(
        "SELECT 1 FROM DimGenerationAggregates WHERE AggregateID = ?",
        (aggregate_id,),
    ).fetchone()
    if not exists:
        raise DimensionResolutionError(
            f"aggregate alias has invalid target: {raw_name}"
        )
    return aggregate_id
