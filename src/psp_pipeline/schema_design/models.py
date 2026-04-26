"""Data contracts for deterministic PSP schema analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportStructureFingerprint:
    """Stable signature of a report's physical layout."""

    source_id: str
    fingerprint: str
    structural_family: str
    page_count: int
    table_count: int
    table_shapes: tuple[str, ...]
    normalized_headings: tuple[str, ...]


@dataclass(frozen=True)
class SourceFieldCandidate:
    """Potential business field inferred from a source table column."""

    source_reference: str
    section_name: str
    header_path: str
    row_role: str
    inferred_data_type: str
    inferred_unit: str | None
    grain_dimensions: tuple[str, ...]
    sample_values: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class SchemaProposal:
    """Approval-gated schema or mapping change proposed by analysis."""

    proposal_type: str
    candidate_key: str
    evidence: dict[str, object]
    proposed_contract: dict[str, object] | None
    proposed_ddl: str | None
    compatibility_result: str


@dataclass(frozen=True)
class CoverageResult:
    """Coverage totals for one report after mapping and validation."""

    expected_fields: int
    mapped_fields: int
    excluded_fields: int
    ambiguous_fields: int
    missing_required_fields: int
    lineage_complete_fields: int
    validation_failures: int

    @property
    def coverage_pct(self) -> float:
        """Return mapped coverage over expected fields."""

        if self.expected_fields == 0:
            return 0.0
        return round(100.0 * self.mapped_fields / self.expected_fields, 2)

    @property
    def status(self) -> str:
        """Return the governed promotion status for this coverage result."""

        if self.missing_required_fields or self.ambiguous_fields or self.validation_failures:
            return "review_required"
        return "passed"
