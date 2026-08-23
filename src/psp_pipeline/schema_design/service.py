"""Services for clustering SRLDC report layouts and selecting fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

from psp_pipeline.parsing.rldc.templates import (
    TemplateMatch,
    inspect_report_structure,
    match_report_template,
)
from psp_pipeline.schema_design.analyzer import analyze_report_schema, build_structure_fingerprint
from psp_pipeline.schema_design.models import ReportStructureFingerprint


@dataclass(frozen=True)
class TemplateCluster:
    """A group of reports sharing one deterministic structure fingerprint."""

    fingerprint: str
    report_paths: tuple[Path, ...]
    representative_paths: tuple[Path, ...]
    structure: ReportStructureFingerprint


@dataclass(frozen=True)
class StoredRawCell:
    """Minimal raw-cell shape consumed by the schema analyzer."""

    page_no: int
    table_no: int
    row_no: int
    col_no: int
    cell_text: str


@dataclass(frozen=True)
class TemplateInventoryRecord:
    """Observed template metadata for one local PSP PDF."""

    pdf_path: Path
    report_date: str | None
    fingerprint: str
    structure: ReportStructureFingerprint
    template_match: TemplateMatch


@dataclass(frozen=True)
class TemplateInventoryCluster:
    """A fingerprint cluster with current-template coverage metadata."""

    fingerprint: str
    structure: ReportStructureFingerprint
    report_paths: tuple[Path, ...]
    representative_paths: tuple[Path, ...]
    matched_template_ids: tuple[str, ...]
    semantic_pass_required_count: int


@dataclass(frozen=True)
class MonthlyAnchorSample:
    """One chosen representative PDF for a given month-anchor role."""

    month_key: str
    anchor: str
    pdf_path: Path
    report_date: str
    exact_day_match: bool


def cluster_report_structures(
    pdf_paths: list[Path],
    source_id: str = "srldc",
    representatives_per_cluster: int = 3,
) -> list[TemplateCluster]:
    """Cluster local PDFs and choose evenly distributed representatives."""

    grouped: dict[str, tuple[ReportStructureFingerprint, list[Path]]] = {}
    for pdf_path in sorted(pdf_paths):
        structure = inspect_report_structure(pdf_path)
        fingerprint = build_structure_fingerprint(source_id, structure)
        if fingerprint.fingerprint not in grouped:
            grouped[fingerprint.fingerprint] = (fingerprint, [])
        grouped[fingerprint.fingerprint][1].append(pdf_path)

    clusters: list[TemplateCluster] = []
    for digest, (structure, paths) in grouped.items():
        clusters.append(
            TemplateCluster(
                fingerprint=digest,
                report_paths=tuple(paths),
                representative_paths=_select_representatives(paths, representatives_per_cluster),
                structure=structure,
            )
        )
    return sorted(clusters, key=lambda cluster: cluster.report_paths[0].name)


def build_template_inventory(
    pdf_paths: list[Path],
    source_id: str = "srldc",
) -> list[TemplateInventoryRecord]:
    """Inspect local PDFs and return one template-inventory row per report."""

    records: list[TemplateInventoryRecord] = []
    for pdf_path in sorted(pdf_paths):
        structure = inspect_report_structure(pdf_path)
        fingerprint = build_structure_fingerprint(source_id, structure)
        template_match = match_report_template(source_id, structure)
        records.append(
            TemplateInventoryRecord(
                pdf_path=pdf_path,
                report_date=_infer_report_date(pdf_path),
                fingerprint=fingerprint.fingerprint,
                structure=fingerprint,
                template_match=template_match,
            )
        )
    return records


def cluster_template_inventory(
    records: list[TemplateInventoryRecord],
    representatives_per_cluster: int = 3,
) -> list[TemplateInventoryCluster]:
    """Group inventory rows by structure fingerprint and summarize template coverage."""

    grouped: dict[str, list[TemplateInventoryRecord]] = {}
    for record in records:
        grouped.setdefault(record.fingerprint, []).append(record)
    clusters: list[TemplateInventoryCluster] = []
    for fingerprint, cluster_records in grouped.items():
        sorted_records = sorted(cluster_records, key=lambda record: record.pdf_path.name)
        matched_template_ids = tuple(sorted({
            record.template_match.template_id
            for record in sorted_records
            if record.template_match.template_id
        }))
        clusters.append(
            TemplateInventoryCluster(
                fingerprint=fingerprint,
                structure=sorted_records[0].structure,
                report_paths=tuple(record.pdf_path for record in sorted_records),
                representative_paths=_select_representatives(
                    [record.pdf_path for record in sorted_records],
                    representatives_per_cluster,
                ),
                matched_template_ids=matched_template_ids,
                semantic_pass_required_count=sum(
                    1 for record in sorted_records
                    if record.template_match.semantic_pass_required
                ),
            )
        )
    return sorted(clusters, key=lambda cluster: cluster.report_paths[0].name)


def summarize_template_inventory(
    records: list[TemplateInventoryRecord],
) -> dict[str, object]:
    """Return high-level coverage totals for a historical template inventory."""

    matched = [record for record in records if record.template_match.template_id]
    semantic_required = [
        record for record in records if record.template_match.semantic_pass_required
    ]
    template_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    for record in matched:
        template_id = str(record.template_match.template_id)
        template_counts[template_id] = template_counts.get(template_id, 0) + 1
    for record in records:
        family = record.structure.structural_family
        family_counts[family] = family_counts.get(family, 0) + 1
    return {
        "report_count": len(records),
        "matched_report_count": len(matched),
        "semantic_pass_required_count": len(semantic_required),
        "matched_pct": round(100.0 * len(matched) / len(records), 2) if records else 0.0,
        "semantic_pass_required_pct": (
            round(100.0 * len(semantic_required) / len(records), 2) if records else 0.0
        ),
        "family_counts": dict(sorted(family_counts.items())),
        "template_counts": dict(sorted(template_counts.items())),
    }


def select_monthly_anchor_paths(
    pdf_paths: list[Path],
    source_id: str = "srldc",
) -> list[MonthlyAnchorSample]:
    """Pick first, fifteenth, and last available report from each source month."""

    grouped: dict[str, list[tuple[str, Path]]] = {}
    for pdf_path in sorted(pdf_paths):
        report_date = _infer_report_date(pdf_path, source_id)
        if not report_date:
            continue
        month_key = report_date[:7]
        grouped.setdefault(month_key, []).append((report_date, pdf_path))

    samples: list[MonthlyAnchorSample] = []
    for month_key, entries in sorted(grouped.items()):
        sorted_entries = sorted(entries, key=lambda item: item[0])
        first_date, first_path = sorted_entries[0]
        last_date, last_path = sorted_entries[-1]
        samples.append(
            MonthlyAnchorSample(month_key, "first", first_path, first_date, True)
        )
        mid_date, mid_path, exact = _pick_midmonth_anchor(sorted_entries)
        samples.append(
            MonthlyAnchorSample(month_key, "fifteenth", mid_path, mid_date, exact)
        )
        if last_path != first_path:
            samples.append(
                MonthlyAnchorSample(month_key, "last", last_path, last_date, True)
            )
    return samples


def _select_representatives(paths: list[Path], limit: int) -> tuple[Path, ...]:
    """Select first, middle, and last fixtures without duplicate paths."""

    if len(paths) <= limit:
        return tuple(paths)
    indexes = {0, len(paths) // 2, len(paths) - 1}
    if limit > 3:
        step = (len(paths) - 1) / (limit - 1)
        indexes.update(round(position * step) for position in range(limit))
    return tuple(paths[index] for index in sorted(indexes)[:limit])


def _infer_report_date(pdf_path: Path, source_id: str = "srldc") -> str | None:
    """Infer a report date from an approved source-specific filename pattern."""

    filename = pdf_path.name.lower()
    source = source_id.lower()
    if source == "srldc":
        match = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})-psp\.pdf", filename)
        if not match:
            return None
        day, month, year = match.groups()
        return _to_iso_date(day, month, year)

    if source == "nrldc":
        match = re.search(r"daily(\d{6}|\d{8})\.pdf$", filename)
        if not match:
            return None
        digits = match.group(1)
        if len(digits) == 6:
            day, month, short_year = digits[:2], digits[2:4], digits[4:]
            return _to_iso_date(day, month, f"20{short_year}")
        day, month, year = digits[:2], digits[2:4], digits[4:]
        return _to_iso_date(day, month, year)
    return None


def _to_iso_date(day: str, month: str, year: str) -> str | None:
    """Validate separated filename components and return an ISO calendar date."""

    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return None


def _pick_midmonth_anchor(entries: list[tuple[str, Path]]) -> tuple[str, Path, bool]:
    """Return the 15th if present, otherwise the nearest available report date."""

    for report_date, pdf_path in entries:
        if report_date.endswith("-15"):
            return report_date, pdf_path, True
    nearest = min(
        entries,
        key=lambda item: (abs(int(item[0][-2:]) - 15), item[0]),
    )
    return nearest[0], nearest[1], False


def persist_report_schema_proposals(
    conn: sqlite3.Connection,
    report_document_id: int,
    section_names: dict[tuple[int, int], str] | None = None,
) -> int:
    """Analyze stored raw cells and persist approval-gated proposals."""

    raw_cells = [
        StoredRawCell(
            page_no=int(row[0]),
            table_no=int(row[1]),
            row_no=int(row[2]),
            col_no=int(row[3]),
            cell_text=str(row[4] or ""),
        )
        for row in conn.execute(
            """
            SELECT page_no, table_no, row_no, col_no, cell_text
            FROM psp_raw_cell WHERE report_document_id = ?
            ORDER BY page_no, table_no, row_no, col_no
            """,
            (report_document_id,),
        )
    ]
    _, proposals = analyze_report_schema(raw_cells, section_names)
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for proposal in proposals:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO schema_proposal(
                ReportDocumentID, ProposalType, CandidateKey, EvidenceJson,
                ProposedContractJson, ProposedDDL, CompatibilityResult,
                Status, CreatedAt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                report_document_id,
                proposal.proposal_type,
                proposal.candidate_key,
                json.dumps(proposal.evidence, sort_keys=True),
                json.dumps(proposal.proposed_contract, sort_keys=True)
                if proposal.proposed_contract else None,
                proposal.proposed_ddl,
                proposal.compatibility_result,
                now,
            ),
        )
        inserted += cursor.rowcount
    return inserted
