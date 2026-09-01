"""Apply human decisions to pending canonical identity adjudications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import sqlite3

from psp_pipeline.identity.canonical import (
    CanonicalEntity,
    build_canonical_catalog,
    catalog_as_postgres_rows,
    observation_keys_for_label,
    persist_canonical_catalog,
)
from psp_pipeline.storage.sqlite_dimensions import normalize_dimension_name as _normalize


LOGGER = logging.getLogger(__name__)

_VALID_DECISIONS = {"approved", "rejected"}


class AdjudicationError(ValueError):
    """Raised when a pending identity issue cannot be applied."""


@dataclass(frozen=True)
class AdjudicationApplyResult:
    """Outcome of one approve/reject decision, including republish keys."""

    issue_id: int
    decision: str
    source_id: str
    entity_type: str
    raw_name: str
    normalized_name: str
    reason: str
    entity_id: str | None
    observation_entity_keys: tuple[str, ...]
    aliases_written: int
    decided_by: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready apply payload."""

        return {
            "issue_id": self.issue_id,
            "decision": self.decision,
            "source_id": self.source_id,
            "entity_type": self.entity_type,
            "raw_name": self.raw_name,
            "normalized_name": self.normalized_name,
            "reason": self.reason,
            "entity_id": self.entity_id,
            "observation_entity_keys": list(self.observation_entity_keys),
            "aliases_written": self.aliases_written,
            "decided_by": self.decided_by,
        }


def list_identity_adjudications(
    conn: sqlite3.Connection,
    *,
    status: str | None = "pending",
) -> list[dict[str, object]]:
    """Return queued identity issues, newest first."""

    from psp_pipeline.storage.sqlite_curated_schema import _ensure_canonical_identity_tables

    _ensure_canonical_identity_tables(conn)
    query = """
        SELECT IssueID, SourceID, EntityType, RawName, NormalizedName,
               CandidateEntityID, CandidateScore, Reason, Status, CreatedAt
        FROM canonical_entity_adjudication
    """
    params: list[object] = []
    if status:
        query += " WHERE Status = ?"
        params.append(status)
    query += " ORDER BY IssueID DESC"
    rows = conn.execute(query, params).fetchall()
    return [
        {
            "issue_id": int(issue_id),
            "source_id": str(source_id),
            "entity_type": str(entity_type),
            "raw_name": str(raw_name),
            "normalized_name": str(normalized),
            "candidate_entity_id": str(candidate) if candidate else None,
            "candidate_score": float(score) if score is not None else None,
            "reason": str(reason),
            "status": str(issue_status),
            "created_at": str(created_at),
        }
        for (
            issue_id,
            source_id,
            entity_type,
            raw_name,
            normalized,
            candidate,
            score,
            reason,
            issue_status,
            created_at,
        ) in rows
    ]


def identity_adjudication_summary(conn: sqlite3.Connection) -> dict[str, int]:
    """Return counts of pending, approved, and rejected identity issues."""

    from psp_pipeline.storage.sqlite_curated_schema import _ensure_canonical_identity_tables

    _ensure_canonical_identity_tables(conn)
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    for status, total in conn.execute(
        "SELECT Status, COUNT(*) FROM canonical_entity_adjudication GROUP BY Status"
    ):
        if str(status) in counts:
            counts[str(status)] = int(total)
    counts["total"] = sum(counts.values())
    return counts


def queue_source_label(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    entity_type: str,
    raw_name: str,
    region_code: str | None = None,
    catalog=None,
) -> object:
    """Resolve a label and persist it when the result is a pending issue."""

    from psp_pipeline.identity.canonical import propose_source_label

    resolved_catalog = catalog or build_canonical_catalog(conn)
    result = propose_source_label(
        resolved_catalog,
        source_id=source_id,
        entity_type=entity_type,
        raw_name=raw_name,
        region_code=region_code,
    )
    if hasattr(result, "reason"):
        recorded_at = datetime.now(timezone.utc).isoformat()
        persist_canonical_catalog(
            conn,
            resolved_catalog,
            recorded_at=recorded_at,
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO canonical_entity_adjudication(
                SourceID, EntityType, RawName, NormalizedName,
                CandidateEntityID, CandidateScore, Reason, Status, CreatedAt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.source_id,
                result.entity_type,
                result.raw_name,
                result.normalized_name,
                result.candidate_entity_id,
                result.candidate_score,
                result.reason,
                result.status,
                recorded_at,
            ),
        )
        conn.commit()
        LOGGER.info(
            "canonical_adjudication_queued source=%s type=%s name=%s reason=%s",
            source_id,
            entity_type,
            raw_name,
            result.reason,
        )
    return result


def apply_adjudication(
    conn: sqlite3.Connection,
    *,
    issue_id: int,
    decision: str,
    decided_by: str = "operator",
    entity_id: str | None = None,
    observation_entity_key: str | None = None,
) -> AdjudicationApplyResult:
    """Approve or reject one pending issue and persist the resulting alias.

    Approval writes `human_adjudication` aliases, including exporter entity
    keys, so a later catalog rebuild and Postgres republish can attach IDs.
    Rejection records the decision and never creates an alias.
    """

    from psp_pipeline.storage.sqlite_curated_schema import _ensure_canonical_identity_tables

    if decision not in _VALID_DECISIONS:
        raise AdjudicationError(f"decision must be approved or rejected, not {decision!r}")
    _ensure_canonical_identity_tables(conn)
    row = conn.execute(
        """
        SELECT IssueID, SourceID, EntityType, RawName, NormalizedName,
               CandidateEntityID, Reason, Status
        FROM canonical_entity_adjudication
        WHERE IssueID = ?
        """,
        (issue_id,),
    ).fetchone()
    if row is None:
        raise AdjudicationError(f"adjudication issue {issue_id} was not found")
    (
        stored_id,
        source_id,
        entity_type,
        raw_name,
        normalized,
        candidate_id,
        reason,
        status,
    ) = row
    if str(status) != "pending":
        raise AdjudicationError(
            f"adjudication issue {issue_id} is {status}, not pending"
        )
    resolved_entity_id = entity_id or (str(candidate_id) if candidate_id else None)
    if decision == "approved" and not resolved_entity_id:
        raise AdjudicationError(
            "approval requires a candidate_entity_id or explicit entity_id"
        )
    decided_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE canonical_entity_adjudication
        SET Status = ?, CandidateEntityID = COALESCE(?, CandidateEntityID),
            DecidedAt = ?, DecidedBy = ?
        WHERE IssueID = ?
        """,
        (decision, resolved_entity_id, decided_at, decided_by, stored_id),
    )
    aliases_written = 0
    observation_keys: tuple[str, ...] = ()
    if decision == "approved" and resolved_entity_id:
        entity = _entity_from_sqlite(conn, resolved_entity_id)
        if entity is None:
            raise AdjudicationError(
                f"canonical entity {resolved_entity_id} was not found"
            )
        keys = list(observation_keys_for_label(entity, str(raw_name)))
        if observation_entity_key:
            keys.insert(0, observation_entity_key)
        observation_keys = tuple(dict.fromkeys(keys))
        aliases_written = _write_approved_aliases(
            conn,
            entity=entity,
            source_id=str(source_id),
            raw_name=str(raw_name),
            normalized_name=str(normalized or _normalize(str(raw_name))),
            observation_keys=observation_keys,
            decided_at=decided_at,
        )
    conn.commit()
    LOGGER.info(
        "canonical_adjudication_applied issue_id=%s decision=%s entity_id=%s aliases=%s",
        stored_id,
        decision,
        resolved_entity_id,
        aliases_written,
    )
    return AdjudicationApplyResult(
        issue_id=int(stored_id),
        decision=decision,
        source_id=str(source_id),
        entity_type=str(entity_type),
        raw_name=str(raw_name),
        normalized_name=str(normalized or _normalize(str(raw_name))),
        reason=str(reason),
        entity_id=resolved_entity_id,
        observation_entity_keys=observation_keys,
        aliases_written=aliases_written,
        decided_by=decided_by,
    )


def republish_identity_after_adjudication(
    conn: sqlite3.Connection,
    repository: object,
    result: AdjudicationApplyResult,
) -> dict[str, object]:
    """Publish the updated identity index and backfill current fact IDs."""

    catalog = build_canonical_catalog(conn)
    entities, aliases, issues = catalog_as_postgres_rows(catalog)
    published: dict[str, object] = {"skipped": True}
    publisher = getattr(repository, "upsert_canonical_entities", None)
    if callable(publisher):
        published = dict(publisher(entities, aliases, issues))
        published["skipped"] = False
    decision_counts: dict[str, object] = {"skipped": True}
    apply_fn = getattr(repository, "apply_canonical_adjudication", None)
    if callable(apply_fn):
        payload = {
            "decision": result.decision,
            "entity_id": result.entity_id,
            "decided_by": result.decided_by,
            "source_id": result.source_id,
            "entity_type": result.entity_type,
            "raw_name": result.raw_name,
            "normalized_name": result.normalized_name,
            "reason": result.reason,
            "observation_entity_key": (
                result.observation_entity_keys[0] if result.observation_entity_keys else None
            ),
        }
        decision_counts = dict(apply_fn(payload))
        decision_counts["skipped"] = False
    backfill: dict[str, object] = {"skipped": True}
    backfill_fn = getattr(repository, "backfill_canonical_entity_ids", None)
    if (
        callable(backfill_fn)
        and result.decision == "approved"
        and result.entity_id
        and result.observation_entity_keys
    ):
        backfill = dict(
            backfill_fn(result.entity_id, result.observation_entity_keys)
        )
        backfill["skipped"] = False
    conn.commit()
    return {
        "apply": result.as_dict(),
        "postgres": published,
        "decision": decision_counts,
        "backfill": backfill,
        "catalog_aliases": len(catalog.aliases),
    }


def _entity_from_sqlite(
    conn: sqlite3.Connection,
    entity_id: str,
) -> CanonicalEntity | None:
    row = conn.execute(
        """
        SELECT EntityID, EntityCode, EntityType, CanonicalName, RegionCode, StateCode
        FROM canonical_entity
        WHERE EntityID = ?
        """,
        (entity_id,),
    ).fetchone()
    if row is None:
        return None
    return CanonicalEntity(
        entity_id=str(row[0]),
        entity_code=str(row[1]),
        entity_type=str(row[2]),
        canonical_name=str(row[3]),
        region_code=str(row[4]) if row[4] else None,
        state_code=str(row[5]) if row[5] else None,
    )


def _write_approved_aliases(
    conn: sqlite3.Connection,
    *,
    entity: CanonicalEntity,
    source_id: str,
    raw_name: str,
    normalized_name: str,
    observation_keys: tuple[str, ...],
    decided_at: str,
) -> int:
    """Insert or promote human-approved aliases for the decided label."""

    written = 0
    primary_key = observation_keys[0] if observation_keys else None
    conn.execute(
        """
        INSERT INTO canonical_entity_alias(
            EntityID, SourceID, EntityType, RawName, NormalizedName,
            ObservationEntityKey, MatchMethod, MatchConfidence,
            ApprovalStatus, CreatedAt
        ) VALUES (?, ?, ?, ?, ?, ?, 'human_adjudication', 1.0, 'approved', ?)
        ON CONFLICT(SourceID, EntityType, NormalizedName) DO UPDATE SET
            EntityID = excluded.EntityID,
            RawName = excluded.RawName,
            ObservationEntityKey = COALESCE(
                excluded.ObservationEntityKey,
                canonical_entity_alias.ObservationEntityKey
            ),
            MatchMethod = 'human_adjudication',
            MatchConfidence = 1.0,
            ApprovalStatus = 'approved'
        """,
        (
            entity.entity_id,
            source_id,
            entity.entity_type,
            raw_name,
            normalized_name,
            primary_key,
            decided_at,
        ),
    )
    written += 1
    for obs_key in observation_keys[1:]:
        conn.execute(
            """
            INSERT OR IGNORE INTO canonical_entity_alias(
                EntityID, SourceID, EntityType, RawName, NormalizedName,
                ObservationEntityKey, MatchMethod, MatchConfidence,
                ApprovalStatus, CreatedAt
            ) VALUES (?, ?, ?, ?, ?, ?, 'human_adjudication', 1.0, 'approved', ?)
            """,
            (
                entity.entity_id,
                f"{source_id}:key",
                entity.entity_type,
                raw_name,
                f"{normalized_name}:{obs_key}",
                obs_key,
                decided_at,
            ),
        )
        written += 1
    return written
