"""Diagnostic coverage analysis of curated ERLDC facts by template and section."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


@dataclass(frozen=True)
class SectionCoverage:
    """Coverage metrics for an individual curated fact table."""

    fact_table: str
    total_rows: int
    distinct_reports: int
    report_coverage_pct: float


@dataclass(frozen=True)
class TemplateCoverage:
    """Coverage metrics aggregated by structural template ID."""

    template_id: str
    total_reports: int
    promoted_reports: int
    gated_reports: int
    promotion_rate_pct: float
    fact_counts: dict[str, int]


@dataclass(frozen=True)
class ERLDCCuratedCoverageReport:
    """Comprehensive curated coverage diagnostic across the ERLDC corpus."""

    audited_at: str
    database_path: str
    total_raw_reports: int
    total_curated_reports: int
    overall_promotion_rate_pct: float
    total_lineage_records: int
    sections: list[SectionCoverage]
    templates: list[TemplateCoverage]


_FACT_TABLES = (
    "FactERLDCRegionalDaily",
    "FactERLDCStateDaily",
    "FactERLDCGenerationDaily",
    "FactERLDCFrequencyDaily",
    "FactERLDCReservoirDaily",
    "FactERLDCVoltageProfile",
    "FactERLDCInterRegionalExchange",
    "FactERLDCInternationalExchange",
)


def generate_erldc_coverage_report(db_path: Path | str) -> dict[str, Any]:
    """Analyze curated fact tables in ``db_path`` and return structured coverage metrics."""

    db_path_obj = Path(db_path)
    if not db_path_obj.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    conn = sqlite3.connect(db_path_obj)
    try:
        # Check raw report count
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_report_document'"
        ).fetchone()
        if not table_exists:
            raw_reports_query = []
        else:
            raw_reports_query = conn.execute(
                "SELECT id, template_id, semantic_pass_required FROM psp_report_document WHERE rldc = 'erldc'"
            ).fetchall()
        total_raw = len(raw_reports_query)

        if total_raw == 0:
            return asdict(
                ERLDCCuratedCoverageReport(
                    audited_at=datetime.now(timezone.utc).isoformat(),
                    database_path=str(db_path),
                    total_raw_reports=0,
                    total_curated_reports=0,
                    overall_promotion_rate_pct=0.0,
                    total_lineage_records=0,
                    sections=[],
                    templates=[],
                )
            )

        # Section-by-section coverage
        sections: list[SectionCoverage] = []
        reports_with_any_facts: set[int] = set()

        for table in _FACT_TABLES:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if not table_exists:
                sections.append(SectionCoverage(table, 0, 0, 0.0))
                continue

            row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            distinct_rep = conn.execute(f"SELECT COUNT(DISTINCT ReportDocumentID) FROM {table}").fetchone()[0]
            rep_ids = [r[0] for r in conn.execute(f"SELECT DISTINCT ReportDocumentID FROM {table}").fetchall()]
            reports_with_any_facts.update(rep_ids)

            coverage_pct = round((distinct_rep / total_raw) * 100.0, 2) if total_raw > 0 else 0.0
            sections.append(SectionCoverage(table, row_count, distinct_rep, coverage_pct))

        total_curated = len(reports_with_any_facts)
        overall_promotion_rate = round((total_curated / total_raw) * 100.0, 2) if total_raw > 0 else 0.0

        # Lineage record count
        lineage_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'curated_field_lineage'"
        ).fetchone()
        total_lineage = (
            conn.execute("SELECT COUNT(*) FROM curated_field_lineage").fetchone()[0]
            if lineage_exists
            else 0
        )

        # Template breakdown
        template_groups: dict[str, list[tuple[int, int]]] = {}
        for rep_id, template_id, sem_pass in raw_reports_query:
            tid = str(template_id or "unassigned")
            template_groups.setdefault(tid, []).append((rep_id, sem_pass))

        templates: list[TemplateCoverage] = []
        for tid, reps in sorted(template_groups.items()):
            tot = len(reps)
            gated = sum(1 for _, sem in reps if sem == 1)
            promoted = sum(1 for rid, _ in reps if rid in reports_with_any_facts)
            rate_pct = round((promoted / tot) * 100.0, 2) if tot > 0 else 0.0

            # Fact counts for this template
            rep_id_list = [r[0] for r in reps]
            placeholders = ",".join("?" for _ in rep_id_list)
            fact_counts: dict[str, int] = {}

            for table in _FACT_TABLES:
                table_exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                if not table_exists:
                    fact_counts[table] = 0
                else:
                    cnt = conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE ReportDocumentID IN ({placeholders})",
                        rep_id_list,
                    ).fetchone()[0]
                    fact_counts[table] = cnt

            templates.append(
                TemplateCoverage(
                    template_id=tid,
                    total_reports=tot,
                    promoted_reports=promoted,
                    gated_reports=gated,
                    promotion_rate_pct=rate_pct,
                    fact_counts=fact_counts,
                )
            )

        report = ERLDCCuratedCoverageReport(
            audited_at=datetime.now(timezone.utc).isoformat(),
            database_path=str(db_path),
            total_raw_reports=total_raw,
            total_curated_reports=total_curated,
            overall_promotion_rate_pct=overall_promotion_rate,
            total_lineage_records=total_lineage,
            sections=sections,
            templates=templates,
        )
        return asdict(report)
    finally:
        conn.close()
