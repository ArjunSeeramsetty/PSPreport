"""Cross-source canonical entity identity, aliases, and fuzzy adjudication."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
import logging
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from psp_pipeline.storage.sqlite_dimensions import normalize_dimension_name
from psp_pipeline.storage.sqlite_topology_export import (
    _REGION_CODES,
    _observation_entity_key,
    _state_observation_entity_keys,
)


FUZZY_ADJUDICATION_FLOOR = 0.88
IDENTITY_SOURCE = "canonical_index"

LOGGER = logging.getLogger(__name__)

_STATE_CODES = {
    "Andhra Pradesh": "IN-AP",
    "AP": "IN-AP",
    "Telangana": "IN-TS",
    "TS": "IN-TS",
    "TG": "IN-TS",
    "Karnataka": "IN-KA",
    "KA": "IN-KA",
    "Kerala": "IN-KL",
    "KL": "IN-KL",
    "Tamil Nadu": "IN-TN",
    "TN": "IN-TN",
    "Puducherry": "IN-PY",
    "PY": "IN-PY",
    "Punjab": "IN-PB",
    "Haryana": "IN-HR",
    "Rajasthan": "IN-RJ",
    "Delhi": "IN-DL",
    "UP": "IN-UP",
    "Uttar Pradesh": "IN-UP",
    "Uttarakhand": "IN-UK",
    "HP": "IN-HP",
    "Himachal Pradesh": "IN-HP",
    "J&K(UT) & Ladakh(UT)": "IN-JK",
    "Chandigarh": "IN-CH",
    "Chhattisgarh": "IN-CT",
    "Gujarat": "IN-GJ",
    "MP": "IN-MP",
    "Madhya Pradesh": "IN-MP",
    "Maharashtra": "IN-MH",
    "Goa": "IN-GA",
    "Bihar": "IN-BR",
    "Jharkhand": "IN-JH",
    "Odisha": "IN-OR",
    "West Bengal": "IN-WB",
    "Sikkim": "IN-SK",
    "Arunachal Pradesh": "IN-AR",
    "Assam": "IN-AS",
    "Manipur": "IN-MN",
    "Meghalaya": "IN-ML",
    "Mizoram": "IN-MZ",
    "Nagaland": "IN-NL",
    "Tripura": "IN-TR",
}

_STATE_ALIAS_SEEDS = {
    "IN-AP": ("Andhra Pradesh", "AP"),
    "IN-TS": ("Telangana", "TS", "TG"),
    "IN-KA": ("Karnataka", "KA"),
    "IN-KL": ("Kerala", "KL"),
    "IN-TN": ("Tamil Nadu", "Tamilnadu", "TN"),
    "IN-PY": ("Puducherry", "Pondicherry", "PY"),
    "IN-UP": ("UP", "Uttar Pradesh", "UttarPradesh"),
    "IN-HP": ("HP", "Himachal Pradesh", "HimachalPradesh"),
    "IN-MH": ("Maharashtra", "MH"),
    "IN-GJ": ("Gujarat", "GUJ", "GJ"),
    "IN-WB": ("West Bengal", "WB"),
    "IN-OR": ("Odisha", "Orissa", "OD"),
    "IN-CT": ("Chhattisgarh", "CG"),
    "IN-DL": ("Delhi", "NCT Delhi"),
}


@dataclass(frozen=True)
class CanonicalEntity:
    """One durable grid object identity shared across public sources."""

    entity_id: str
    entity_code: str
    entity_type: str
    canonical_name: str
    region_code: str | None = None
    state_code: str | None = None


@dataclass(frozen=True)
class CanonicalAlias:
    """A source-published name that identifies a canonical entity."""

    entity_id: str
    source_id: str
    entity_type: str
    raw_name: str
    normalized_name: str
    observation_entity_key: str | None
    match_method: str
    match_confidence: float
    approval_status: str


@dataclass(frozen=True)
class CanonicalAdjudication:
    """A fuzzy or conflicting identity that a human must accept or reject."""

    source_id: str
    entity_type: str
    raw_name: str
    normalized_name: str
    candidate_entity_id: str | None
    candidate_score: float | None
    reason: str
    status: str = "pending"


@dataclass
class CanonicalCatalog:
    """In-memory identity index for one curated replay."""

    entities: dict[str, CanonicalEntity] = field(default_factory=dict)
    aliases: list[CanonicalAlias] = field(default_factory=list)
    adjudications: list[CanonicalAdjudication] = field(default_factory=list)

    def entity_by_id(self, entity_id: str) -> CanonicalEntity | None:
        """Return a catalog entity when the UUID is known."""

        return self.entities.get(entity_id)


def build_entity_id(entity_code: str) -> str:
    """Return a deterministic UUID for a stable entity code."""

    return str(uuid5(NAMESPACE_URL, f"psp-canonical:{entity_code}"))


def name_similarity(left: str, right: str) -> float:
    """Return a 0-1 similarity on punctuation-insensitive labels."""

    first = normalize_dimension_name(left)
    second = normalize_dimension_name(right)
    if not first or not second:
        return 0.0
    return SequenceMatcher(None, first, second).ratio()


def build_canonical_catalog(
    conn: sqlite3.Connection,
    *,
    now: str | None = None,
) -> CanonicalCatalog:
    """Project SQLite dimensions into a cross-source canonical identity index.

    Exact normalized matches become auto-approved aliases. Fuzzy near-matches
    are queued for adjudication and never auto-merged.
    """

    recorded_at = now or datetime.now(timezone.utc).isoformat()
    from psp_pipeline.storage.sqlite_curated_schema import _ensure_canonical_identity_tables

    _ensure_canonical_identity_tables(conn)
    catalog = CanonicalCatalog()
    region_codes = _region_code_map(conn)
    _add_regions(conn, catalog)
    _add_states(conn, catalog, region_codes)
    _add_countries(conn, catalog)
    _add_stations(conn, catalog, region_codes)
    _add_units(conn, catalog)
    _add_grid_entities(conn, catalog, region_codes)
    _add_voltage_nodes(conn, catalog, region_codes)
    _add_reservoirs(conn, catalog, region_codes)
    _add_lines(conn, catalog, region_codes)
    _add_dimension_aliases(conn, catalog, region_codes)
    catalog.adjudications.extend(_fuzzy_duplicate_issues(catalog))
    persist_canonical_catalog(conn, catalog, recorded_at=recorded_at)
    LOGGER.info(
        "canonical_catalog_built entities=%s aliases=%s adjudications=%s",
        len(catalog.entities),
        len(catalog.aliases),
        len(catalog.adjudications),
    )
    return catalog


def resolve_observation_entity_id(
    catalog: CanonicalCatalog,
    entity_key: str,
) -> str | None:
    """Map an exported observation entity_key to a canonical UUID when known."""

    for alias in catalog.aliases:
        if alias.observation_entity_key == entity_key and alias.approval_status in {
            "approved",
            "auto_exact",
        }:
            return alias.entity_id
    return None


def propose_source_label(
    catalog: CanonicalCatalog,
    *,
    source_id: str,
    entity_type: str,
    raw_name: str,
    region_code: str | None = None,
) -> CanonicalAlias | CanonicalAdjudication:
    """Resolve a source label or queue it when only a fuzzy match exists."""

    normalized = normalize_dimension_name(raw_name)
    exact = _approved_alias(catalog, source_id, entity_type, normalized)
    if exact is not None:
        if exact.source_id == source_id:
            return exact
        return CanonicalAlias(
            entity_id=exact.entity_id,
            source_id=source_id,
            entity_type=entity_type,
            raw_name=raw_name,
            normalized_name=normalized,
            observation_entity_key=None,
            match_method="cross_source_exact_alias",
            match_confidence=1.0,
            approval_status="auto_exact",
        )
    candidates = [
        entity
        for entity in catalog.entities.values()
        if entity.entity_type == entity_type
        and (region_code is None or entity.region_code == region_code)
    ]
    exact_name = next(
        (
            entity
            for entity in candidates
            if normalize_dimension_name(entity.canonical_name) == normalized
        ),
        None,
    )
    if exact_name is not None:
        return CanonicalAlias(
            entity_id=exact_name.entity_id,
            source_id=source_id,
            entity_type=entity_type,
            raw_name=raw_name,
            normalized_name=normalized,
            observation_entity_key=None,
            match_method="deterministic_normalization",
            match_confidence=1.0,
            approval_status="auto_exact",
        )
    scored = sorted(
        (
            (name_similarity(raw_name, entity.canonical_name), entity)
            for entity in candidates
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if scored and scored[0][0] >= FUZZY_ADJUDICATION_FLOOR:
        score, entity = scored[0]
        return CanonicalAdjudication(
            source_id=source_id,
            entity_type=entity_type,
            raw_name=raw_name,
            normalized_name=normalized,
            candidate_entity_id=entity.entity_id,
            candidate_score=round(score, 4),
            reason="fuzzy_candidate",
        )
    return CanonicalAdjudication(
        source_id=source_id,
        entity_type=entity_type,
        raw_name=raw_name,
        normalized_name=normalized,
        candidate_entity_id=None,
        candidate_score=None,
        reason="unmatched_label",
    )


def persist_canonical_catalog(
    conn: sqlite3.Connection,
    catalog: CanonicalCatalog,
    *,
    recorded_at: str,
) -> None:
    """Write the identity index into the local SQLite replay."""

    for entity in catalog.entities.values():
        conn.execute(
            """
            INSERT INTO canonical_entity(
                EntityID, EntityCode, EntityType, CanonicalName,
                RegionCode, StateCode, CreatedAt
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(EntityID) DO UPDATE SET
                CanonicalName = excluded.CanonicalName,
                RegionCode = excluded.RegionCode,
                StateCode = excluded.StateCode
            """,
            (
                entity.entity_id,
                entity.entity_code,
                entity.entity_type,
                entity.canonical_name,
                entity.region_code,
                entity.state_code,
                recorded_at,
            ),
        )
    for alias in catalog.aliases:
        conn.execute(
            """
            INSERT INTO canonical_entity_alias(
                EntityID, SourceID, EntityType, RawName, NormalizedName,
                ObservationEntityKey, MatchMethod, MatchConfidence,
                ApprovalStatus, CreatedAt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(SourceID, EntityType, NormalizedName) DO UPDATE SET
                EntityID = excluded.EntityID,
                RawName = excluded.RawName,
                ObservationEntityKey = excluded.ObservationEntityKey,
                MatchMethod = excluded.MatchMethod,
                MatchConfidence = excluded.MatchConfidence
            WHERE canonical_entity_alias.ApprovalStatus IN ('approved', 'auto_exact')
            """,
            (
                alias.entity_id,
                alias.source_id,
                alias.entity_type,
                alias.raw_name,
                alias.normalized_name,
                alias.observation_entity_key,
                alias.match_method,
                alias.match_confidence,
                alias.approval_status,
                recorded_at,
            ),
        )
    for issue in catalog.adjudications:
        conn.execute(
            """
            INSERT OR IGNORE INTO canonical_entity_adjudication(
                SourceID, EntityType, RawName, NormalizedName,
                CandidateEntityID, CandidateScore, Reason, Status, CreatedAt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue.source_id,
                issue.entity_type,
                issue.raw_name,
                issue.normalized_name,
                issue.candidate_entity_id,
                issue.candidate_score,
                issue.reason,
                issue.status,
                recorded_at,
            ),
        )


def catalog_as_postgres_rows(
    catalog: CanonicalCatalog,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Return JSON-ready identity rows for the Postgres primary store."""

    entities = [
        {
            "entity_id": entity.entity_id,
            "entity_code": entity.entity_code,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "region_code": entity.region_code,
            "state_code": entity.state_code,
        }
        for entity in catalog.entities.values()
    ]
    aliases = [
        {
            "entity_id": alias.entity_id,
            "source_id": alias.source_id,
            "entity_type": alias.entity_type,
            "raw_name": alias.raw_name,
            "normalized_name": alias.normalized_name,
            "observation_entity_key": alias.observation_entity_key,
            "match_method": alias.match_method,
            "match_confidence": alias.match_confidence,
            "approval_status": alias.approval_status,
        }
        for alias in catalog.aliases
    ]
    issues = [
        {
            "source_id": issue.source_id,
            "entity_type": issue.entity_type,
            "raw_name": issue.raw_name,
            "normalized_name": issue.normalized_name,
            "candidate_entity_id": issue.candidate_entity_id,
            "candidate_score": issue.candidate_score,
            "reason": issue.reason,
            "status": issue.status,
        }
        for issue in catalog.adjudications
    ]
    return entities, aliases, issues


def annotate_topology_with_canonical_ids(
    topology: dict[str, list[dict[str, object]]],
    catalog: CanonicalCatalog,
) -> dict[str, list[dict[str, object]]]:
    """Attach deterministic canonical UUIDs to topology batches."""

    annotated: dict[str, list[dict[str, object]]] = {}
    for collection, rows in topology.items():
        annotated_rows: list[dict[str, object]] = []
        for row in rows:
            payload = dict(row)
            entity_id = _canonical_id_for_topology_row(collection, row, catalog)
            if entity_id:
                payload["canonical_entity_id"] = entity_id
            annotated_rows.append(payload)
        annotated[collection] = annotated_rows
    annotated["canonical_entities"] = [
        {
            "entity_id": entity.entity_id,
            "entity_code": entity.entity_code,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "region_code": entity.region_code,
            "state_code": entity.state_code,
        }
        for entity in catalog.entities.values()
    ]
    return annotated


def _add_entity(catalog: CanonicalCatalog, entity: CanonicalEntity) -> CanonicalEntity:
    catalog.entities[entity.entity_id] = entity
    return entity


def _add_alias(
    catalog: CanonicalCatalog,
    *,
    entity: CanonicalEntity,
    source_id: str,
    raw_name: str,
    observation_entity_key: str | None = None,
    match_method: str = "deterministic_normalization",
    match_confidence: float = 1.0,
    approval_status: str = "auto_exact",
) -> None:
    normalized = normalize_dimension_name(raw_name)
    if not normalized:
        return
    catalog.aliases.append(
        CanonicalAlias(
            entity_id=entity.entity_id,
            source_id=source_id,
            entity_type=entity.entity_type,
            raw_name=raw_name,
            normalized_name=normalized,
            observation_entity_key=observation_entity_key,
            match_method=match_method,
            match_confidence=match_confidence,
            approval_status=approval_status,
        )
    )


def _region_code_map(conn: sqlite3.Connection) -> dict[int, str]:
    return {
        int(region_id): _REGION_CODES.get(str(name), f"REGION-{region_id}")
        for region_id, name in conn.execute("SELECT RegionID, RegionName FROM DimRegions")
    }


def _add_regions(conn: sqlite3.Connection, catalog: CanonicalCatalog) -> None:
    for region_id, name in conn.execute("SELECT RegionID, RegionName FROM DimRegions"):
        code = _REGION_CODES.get(str(name), f"REGION-{region_id}")
        entity = _add_entity(
            catalog,
            CanonicalEntity(
                entity_id=build_entity_id(f"region:{code}"),
                entity_code=f"region:{code}",
                entity_type="region",
                canonical_name=str(name),
                region_code=code,
            ),
        )
        _add_alias(
            catalog,
            entity=entity,
            source_id=IDENTITY_SOURCE,
            raw_name=str(name),
            observation_entity_key=f"{code}:region:{name}",
        )


def _add_states(
    conn: sqlite3.Connection,
    catalog: CanonicalCatalog,
    region_codes: dict[int, str],
) -> None:
    if not _table_exists(conn, "DimStates"):
        return
    columns = _columns(conn, "DimStates")
    state_code_sql = "StateCode" if "StateCode" in columns else "NULL"
    for state_id, name, region_id, stored_code in conn.execute(
        f"SELECT StateID, StateName, RegionID, {state_code_sql} FROM DimStates"
    ):
        region_code = region_codes.get(int(region_id)) if region_id is not None else None
        state_code = (
            _STATE_CODES.get(str(name))
            or _STATE_CODES.get(str(stored_code or ""))
            or stored_code
        )
        entity_code = f"state:{state_code}" if state_code else f"state:name:{normalize_dimension_name(str(name))}"
        entity = _add_entity(
            catalog,
            CanonicalEntity(
                entity_id=build_entity_id(entity_code),
                entity_code=entity_code,
                entity_type="state",
                canonical_name=str(name),
                region_code=region_code,
                state_code=state_code,
            ),
        )
        for key in _state_observation_entity_keys(region_code, str(name), state_code):
            _add_alias(
                catalog,
                entity=entity,
                source_id=IDENTITY_SOURCE,
                raw_name=str(name),
                observation_entity_key=key,
            )
        for alias_name in _STATE_ALIAS_SEEDS.get(str(state_code or ""), ()):
            _add_alias(
                catalog,
                entity=entity,
                source_id=IDENTITY_SOURCE,
                raw_name=alias_name,
            )


def _add_countries(conn: sqlite3.Connection, catalog: CanonicalCatalog) -> None:
    if not _table_exists(conn, "DimCountries"):
        return
    for country_id, name in conn.execute("SELECT CountryID, CountryName FROM DimCountries"):
        entity_code = f"country:{normalize_dimension_name(str(name))}"
        entity = _add_entity(
            catalog,
            CanonicalEntity(
                entity_id=build_entity_id(entity_code),
                entity_code=entity_code,
                entity_type="country",
                canonical_name=str(name),
            ),
        )
        _add_alias(
            catalog,
            entity=entity,
            source_id=IDENTITY_SOURCE,
            raw_name=str(name),
            observation_entity_key=f"COUNTRY:{name}",
        )
        _ = country_id


def _add_stations(
    conn: sqlite3.Connection,
    catalog: CanonicalCatalog,
    region_codes: dict[int, str],
) -> None:
    if not _table_exists(conn, "DimPowerStations"):
        return
    for station_id, code, name, state_id, region_id in conn.execute(
        """
        SELECT StationID, StationCode, CanonicalStationName, StateID, RegionID
        FROM DimPowerStations
        """
    ):
        region_code = region_codes.get(int(region_id)) if region_id is not None else None
        entity_code = f"station:{code}"
        entity = _add_entity(
            catalog,
            CanonicalEntity(
                entity_id=build_entity_id(entity_code),
                entity_code=entity_code,
                entity_type="power_station",
                canonical_name=str(name),
                region_code=region_code,
                state_code=f"STATE-{state_id}" if state_id is not None else None,
            ),
        )
        _add_alias(
            catalog,
            entity=entity,
            source_id=IDENTITY_SOURCE,
            raw_name=str(name),
            observation_entity_key=_observation_entity_key(region_code, "generation", str(name)),
        )
        _ = station_id


def _add_units(conn: sqlite3.Connection, catalog: CanonicalCatalog) -> None:
    if not _table_exists(conn, "DimGeneratingUnits"):
        return
    for unit_id, code, name in conn.execute(
        "SELECT GeneratingUnitID, UnitCode, CanonicalUnitName FROM DimGeneratingUnits"
    ):
        entity_code = f"unit:{code}"
        entity = _add_entity(
            catalog,
            CanonicalEntity(
                entity_id=build_entity_id(entity_code),
                entity_code=entity_code,
                entity_type="generating_unit",
                canonical_name=str(name),
            ),
        )
        _add_alias(catalog, entity=entity, source_id=IDENTITY_SOURCE, raw_name=str(name))
        _ = unit_id


def _add_grid_entities(
    conn: sqlite3.Connection,
    catalog: CanonicalCatalog,
    region_codes: dict[int, str],
) -> None:
    if not _table_exists(conn, "DimGridEntities"):
        return
    for entity_id, name, entity_type, state_id, region_id in conn.execute(
        """
        SELECT EntityID, EntityName, EntityType, StateID, RegionID
        FROM DimGridEntities
        """
    ):
        region_code = region_codes.get(int(region_id)) if region_id is not None else None
        entity_code = (
            f"grid:{entity_type}:{normalize_dimension_name(str(name))}:"
            f"{region_code or '-'}:{state_id or '-'}"
        )
        entity = _add_entity(
            catalog,
            CanonicalEntity(
                entity_id=build_entity_id(entity_code),
                entity_code=entity_code,
                entity_type=str(entity_type),
                canonical_name=str(name),
                region_code=region_code,
                state_code=f"STATE-{state_id}" if state_id is not None else None,
            ),
        )
        _add_alias(
            catalog,
            entity=entity,
            source_id=IDENTITY_SOURCE,
            raw_name=str(name),
            observation_entity_key=_observation_entity_key(region_code, "generation", str(name)),
        )
        _ = entity_id


def _add_voltage_nodes(
    conn: sqlite3.Connection,
    catalog: CanonicalCatalog,
    region_codes: dict[int, str],
) -> None:
    if not _table_exists(conn, "DimVoltageNodes"):
        return
    for node_id, name, region_id in conn.execute(
        "SELECT VoltageNodeID, NodeName, RegionID FROM DimVoltageNodes"
    ):
        region_code = region_codes.get(int(region_id)) if region_id is not None else None
        entity_code = f"voltage:{normalize_dimension_name(str(name))}:{region_code or '-'}"
        entity = _add_entity(
            catalog,
            CanonicalEntity(
                entity_id=build_entity_id(entity_code),
                entity_code=entity_code,
                entity_type="voltage_node",
                canonical_name=str(name),
                region_code=region_code,
            ),
        )
        _add_alias(
            catalog,
            entity=entity,
            source_id=IDENTITY_SOURCE,
            raw_name=str(name),
            observation_entity_key=_observation_entity_key(region_code, "voltage", str(name)),
        )
        _ = node_id


def _add_reservoirs(
    conn: sqlite3.Connection,
    catalog: CanonicalCatalog,
    region_codes: dict[int, str],
) -> None:
    if not _table_exists(conn, "DimReservoirs"):
        return
    for reservoir_id, name, region_id in conn.execute(
        "SELECT ReservoirID, ReservoirName, RegionID FROM DimReservoirs"
    ):
        region_code = region_codes.get(int(region_id)) if region_id is not None else None
        entity_code = f"reservoir:{normalize_dimension_name(str(name))}:{region_code or '-'}"
        entity = _add_entity(
            catalog,
            CanonicalEntity(
                entity_id=build_entity_id(entity_code),
                entity_code=entity_code,
                entity_type="reservoir",
                canonical_name=str(name),
                region_code=region_code,
            ),
        )
        _add_alias(
            catalog,
            entity=entity,
            source_id=IDENTITY_SOURCE,
            raw_name=str(name),
            observation_entity_key=_observation_entity_key(region_code, "reservoir", str(name)),
        )
        _ = reservoir_id


def _add_lines(
    conn: sqlite3.Connection,
    catalog: CanonicalCatalog,
    region_codes: dict[int, str],
) -> None:
    if not _table_exists(conn, "DimTransmissionElements"):
        return
    for element_id, name, from_region_id, to_region_id in conn.execute(
        """
        SELECT ElementID, ElementName, FromRegionID, ToRegionID
        FROM DimTransmissionElements
        """
    ):
        region_code = region_codes.get(int(from_region_id or 0)) or region_codes.get(
            int(to_region_id or 0)
        )
        entity_code = f"line:{normalize_dimension_name(str(name))}"
        entity = _add_entity(
            catalog,
            CanonicalEntity(
                entity_id=build_entity_id(entity_code),
                entity_code=entity_code,
                entity_type="transmission_line",
                canonical_name=str(name),
                region_code=region_code,
            ),
        )
        _add_alias(
            catalog,
            entity=entity,
            source_id=IDENTITY_SOURCE,
            raw_name=str(name),
            observation_entity_key=_observation_entity_key(region_code, "line", str(name)),
        )
        _ = element_id


def _add_dimension_aliases(
    conn: sqlite3.Connection,
    catalog: CanonicalCatalog,
    region_codes: dict[int, str],
) -> None:
    if not _table_exists(conn, "DimStateAliases"):
        return
    name_to_entity = {
        entity.canonical_name: entity
        for entity in catalog.entities.values()
        if entity.entity_type == "state"
    }
    by_state_id: dict[int, CanonicalEntity] = {}
    for state_id, name in conn.execute("SELECT StateID, StateName FROM DimStates"):
        entity = name_to_entity.get(str(name))
        if entity is not None:
            by_state_id[int(state_id)] = entity
    for source_id, raw_name, state_id, status in conn.execute(
        """
        SELECT SourceID, RawName, StateID, ApprovalStatus
        FROM DimStateAliases
        WHERE ApprovalStatus IN ('approved', 'auto_exact')
        """
    ):
        entity = by_state_id.get(int(state_id))
        if entity is None:
            continue
        _add_alias(
            catalog,
            entity=entity,
            source_id=str(source_id),
            raw_name=str(raw_name),
            approval_status=str(status),
            match_method="approved_dimension_alias",
        )
    _ = region_codes


def _fuzzy_duplicate_issues(catalog: CanonicalCatalog) -> list[CanonicalAdjudication]:
    issues: list[CanonicalAdjudication] = []
    entities = list(catalog.entities.values())
    for index, left in enumerate(entities):
        for right in entities[index + 1 :]:
            if left.entity_type != right.entity_type:
                continue
            if left.region_code and right.region_code and left.region_code != right.region_code:
                continue
            score = name_similarity(left.canonical_name, right.canonical_name)
            if score < FUZZY_ADJUDICATION_FLOOR or left.entity_id == right.entity_id:
                continue
            issues.append(
                CanonicalAdjudication(
                    source_id=IDENTITY_SOURCE,
                    entity_type=left.entity_type,
                    raw_name=left.canonical_name,
                    normalized_name=normalize_dimension_name(left.canonical_name),
                    candidate_entity_id=right.entity_id,
                    candidate_score=round(score, 4),
                    reason="possible_duplicate",
                )
            )
    return issues


def _approved_alias(
    catalog: CanonicalCatalog,
    source_id: str,
    entity_type: str,
    normalized_name: str,
) -> CanonicalAlias | None:
    same_source: CanonicalAlias | None = None
    any_match: CanonicalAlias | None = None
    for alias in catalog.aliases:
        if (
            alias.entity_type != entity_type
            or alias.normalized_name != normalized_name
            or alias.approval_status not in {"approved", "auto_exact"}
        ):
            continue
        if alias.source_id == source_id:
            same_source = alias
            break
        any_match = alias
    return same_source or any_match


def _canonical_id_for_topology_row(
    collection: str,
    row: dict[str, object],
    catalog: CanonicalCatalog,
) -> str | None:
    keys: list[str] = []
    extra = row.get("observation_entity_keys")
    if isinstance(extra, list):
        keys.extend(str(item) for item in extra)
    single = row.get("observation_entity_key")
    if isinstance(single, str) and single:
        keys.append(single)
    for entity_key in keys:
        entity_id = resolve_observation_entity_id(catalog, entity_key)
        if entity_id:
            return entity_id
    if collection == "regions" and row.get("code"):
        return build_entity_id(f"region:{row['code']}")
    if collection == "states":
        name = str(row.get("name") or "")
        mapped = _STATE_CODES.get(name)
        if mapped:
            return build_entity_id(f"state:{mapped}")
    return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}
