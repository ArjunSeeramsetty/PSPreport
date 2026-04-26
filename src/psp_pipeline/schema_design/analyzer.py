"""Deterministic report fingerprinting and schema-candidate inference."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
from typing import Iterable

from psp_pipeline.parsing.rldc.templates import ReportStructure, infer_structural_family
from psp_pipeline.schema_design.models import (
    ReportStructureFingerprint,
    SchemaProposal,
    SourceFieldCandidate,
)


UNIT_PATTERNS = (
    (re.compile(r"\bmu\b", re.IGNORECASE), "MU"),
    (re.compile(r"\bmw\b", re.IGNORECASE), "MW"),
    (re.compile(r"\bhz\b", re.IGNORECASE), "Hz"),
    (re.compile(r"\bkv\b", re.IGNORECASE), "kV"),
    (re.compile(r"%|percent", re.IGNORECASE), "%"),
    (re.compile(r"\bhrs?\b|time", re.IGNORECASE), "HH:MM:SS"),
)


def normalize_label(value: str) -> str:
    """Normalize a report label for stable matching across layout eras."""

    text = value.replace("\n", " ").strip().lower()
    text = re.sub(r"[^a-z0-9%]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_structure_fingerprint(
    source_id: str,
    structure: ReportStructure,
) -> ReportStructureFingerprint:
    """Build a content-addressed fingerprint from report geometry and headings."""

    structural_family = infer_structural_family(source_id, structure)
    shapes = tuple(
        f"p{shape.page_no}:t{shape.table_no}:{shape.min_rows}x{shape.min_cols}"
        for shape in structure.table_shapes
    )
    headings = tuple(sorted({normalize_label(value) for value in structure.headings if value.strip()}))
    normalized_shapes = tuple(
        f"p{shape.page_no}:t{shape.table_no}:c{shape.min_cols}"
        for shape in structure.table_shapes
    )
    payload = {
        "source_id": source_id.lower(),
        "family": structural_family,
        "pages": structure.page_count,
        "tables": structure.table_count,
        "shapes": normalized_shapes,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ReportStructureFingerprint(
        source_id=source_id.lower(),
        fingerprint=digest,
        structural_family=structural_family,
        page_count=structure.page_count,
        table_count=structure.table_count,
        table_shapes=shapes,
        normalized_headings=headings,
    )


def analyze_report_schema(
    raw_cells: Iterable[object],
    section_names: dict[tuple[int, int], str] | None = None,
) -> tuple[list[SourceFieldCandidate], list[SchemaProposal]]:
    """Infer table-column candidates and approval-gated proposals from raw cells."""

    sections = section_names or {}
    tables: dict[tuple[int, int], dict[int, dict[int, str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for cell in raw_cells:
        page_no = int(getattr(cell, "page_no"))
        table_no = int(getattr(cell, "table_no"))
        row_no = int(getattr(cell, "row_no"))
        col_no = int(getattr(cell, "col_no"))
        tables[(page_no, table_no)][row_no][col_no] = str(
            getattr(cell, "cell_text", "") or ""
        ).strip()

    candidates: list[SourceFieldCandidate] = []
    proposals: list[SchemaProposal] = []
    for (page_no, table_no), rows in sorted(tables.items()):
        section = sections.get((page_no, table_no), f"unclassified_p{page_no}_t{table_no}")
        max_col = max((max(row, default=0) for row in rows.values()), default=0)
        for col_no in range(1, max_col + 1):
            header_parts = _header_parts(rows, col_no)
            values = _data_values(rows, col_no)
            if not header_parts or not values:
                continue
            header_path = " / ".join(header_parts)
            candidate = SourceFieldCandidate(
                source_reference=f"p{page_no}:t{table_no}:c{col_no}",
                section_name=section,
                header_path=header_path,
                row_role=_infer_row_role(rows),
                inferred_data_type=_infer_data_type(values),
                inferred_unit=_infer_unit(header_path),
                grain_dimensions=_infer_grain(section, rows),
                sample_values=tuple(values[:5]),
                confidence=_candidate_confidence(section, header_parts, values),
            )
            candidates.append(candidate)
            if section.startswith("unclassified_") or candidate.confidence < 0.8:
                proposals.append(_proposal_for_candidate(candidate))
    return candidates, proposals


def _header_parts(rows: dict[int, dict[int, str]], col_no: int) -> list[str]:
    """Collect the leading textual header hierarchy for a table column."""

    parts: list[str] = []
    for row_no in sorted(rows)[:4]:
        value = rows[row_no].get(col_no, "")
        if not value or _looks_numeric(value):
            continue
        normalized = normalize_label(value)
        if normalized and normalized not in parts:
            parts.append(normalized)
    return parts


def _data_values(rows: dict[int, dict[int, str]], col_no: int) -> list[str]:
    """Return nonempty values below the likely header rows."""

    values: list[str] = []
    for row_no in sorted(rows)[2:]:
        value = rows[row_no].get(col_no, "").strip()
        if value:
            values.append(value)
    return values


def _looks_numeric(value: str) -> bool:
    text = value.replace(",", "").strip()
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text))


def _infer_data_type(values: list[str]) -> str:
    if all(_looks_numeric(value) or value.lower() in {"nil", "-", "--"} for value in values):
        return "REAL"
    if all(re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", value) for value in values):
        return "TIME"
    return "TEXT"


def _infer_unit(header_path: str) -> str | None:
    for pattern, unit in UNIT_PATTERNS:
        if pattern.search(header_path):
            return unit
    return None


def _infer_row_role(rows: dict[int, dict[int, str]]) -> str:
    labels = " ".join(normalize_label(value) for row in rows.values() for value in row.values())
    if "total" in labels:
        return "detail_with_total"
    return "detail"


def _infer_grain(section: str, rows: dict[int, dict[int, str]]) -> tuple[str, ...]:
    labels = " ".join(normalize_label(value) for row in rows.values() for value in row.values())
    base = ["report_document", "date"]
    if "state" in section or any(name in labels for name in ("karnataka", "kerala", "telangana")):
        base.append("state")
    elif "voltage" in section:
        base.append("voltage_node")
    elif "reservoir" in section:
        base.append("reservoir")
    elif "generation" in section:
        base.append("grid_entity")
    elif "exchange" in section:
        base.append("transmission_element")
    else:
        base.append("region")
    return tuple(base)


def _candidate_confidence(section: str, headers: list[str], values: list[str]) -> float:
    score = 0.4
    if not section.startswith("unclassified_"):
        score += 0.25
    if headers:
        score += 0.2
    if values:
        score += 0.15
    return round(min(score, 1.0), 2)


def _proposal_for_candidate(candidate: SourceFieldCandidate) -> SchemaProposal:
    proposal_type = "new_section" if candidate.section_name.startswith("unclassified_") else "ambiguous_field"
    key = f"{candidate.section_name}:{normalize_label(candidate.header_path)}"
    evidence = {
        "source_reference": candidate.source_reference,
        "header_path": candidate.header_path,
        "sample_values": list(candidate.sample_values),
        "inferred_type": candidate.inferred_data_type,
        "inferred_unit": candidate.inferred_unit,
        "grain": list(candidate.grain_dimensions),
        "confidence": candidate.confidence,
    }
    return SchemaProposal(
        proposal_type=proposal_type,
        candidate_key=key,
        evidence=evidence,
        proposed_contract=None,
        proposed_ddl=None,
        compatibility_result="manual_review_required",
    )
