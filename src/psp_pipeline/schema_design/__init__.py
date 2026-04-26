"""Governed schema inference for regional PSP reports."""

from psp_pipeline.schema_design.analyzer import (
    analyze_report_schema,
    build_structure_fingerprint,
)
from psp_pipeline.schema_design.models import (
    CoverageResult,
    ReportStructureFingerprint,
    SchemaProposal,
    SourceFieldCandidate,
)

__all__ = [
    "CoverageResult",
    "ReportStructureFingerprint",
    "SchemaProposal",
    "SourceFieldCandidate",
    "analyze_report_schema",
    "build_structure_fingerprint",
]
