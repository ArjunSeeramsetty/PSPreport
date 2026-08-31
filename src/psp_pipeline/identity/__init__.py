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
    propose_source_label,
    resolve_observation_entity_id,
)

__all__ = [
    "CanonicalAdjudication",
    "CanonicalAlias",
    "CanonicalCatalog",
    "CanonicalEntity",
    "annotate_topology_with_canonical_ids",
    "build_canonical_catalog",
    "build_entity_id",
    "catalog_as_postgres_rows",
    "name_similarity",
    "propose_source_label",
    "resolve_observation_entity_id",
]
