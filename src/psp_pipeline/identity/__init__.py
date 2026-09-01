"""Canonical entity identity for the Indian power-system knowledge graph."""

from psp_pipeline.identity.canonical import (
    CanonicalAdjudication,
    CanonicalAlias,
    CanonicalCatalog,
    CanonicalEntity,
    annotate_topology_with_canonical_ids,
    build_canonical_catalog,
    build_entity_id,
    catalog_as_postgres_rows,
    name_similarity,
    observation_keys_for_label,
    propose_source_label,
    resolve_observation_entity_id,
)
from psp_pipeline.identity.adjudication import (
    AdjudicationApplyResult,
    AdjudicationError,
    apply_adjudication,
    identity_adjudication_summary,
    list_identity_adjudications,
    queue_source_label,
    republish_identity_after_adjudication,
)

__all__ = [
    "AdjudicationApplyResult",
    "AdjudicationError",
    "CanonicalAdjudication",
    "CanonicalAlias",
    "CanonicalCatalog",
    "CanonicalEntity",
    "annotate_topology_with_canonical_ids",
    "apply_adjudication",
    "build_canonical_catalog",
    "build_entity_id",
    "catalog_as_postgres_rows",
    "identity_adjudication_summary",
    "list_identity_adjudications",
    "name_similarity",
    "observation_keys_for_label",
    "propose_source_label",
    "queue_source_label",
    "republish_identity_after_adjudication",
    "resolve_observation_entity_id",
]
