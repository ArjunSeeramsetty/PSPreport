"""Diagnostic coverage analysis of curated NERLDC facts by template and section."""

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
class NERLDCCuratedCoverageReport:
    """Comprehensive curated coverage diagnostic across the NERLDC corpus."""

    audited_at: str
    database_path: str
    total_raw_reports: int
    total_curated_reports: int
    overall_promotion_rate_pct: float
    total_lineage_records: int
    sections: list[SectionCoverage]
    templates: list[TemplateCoverage]


_FACT_TABLES = (
    "FactNERLDCRegionalDaily",
    "FactNERLDCStateDaily",
    "FactNERLDCGenerationDaily",
    "FactNERLDCFrequencyDaily",
    "FactNERLDCVoltageProfile",
    "FactNERLDCInterRegionalExchange",
    "FactNERLDCInternationalExchange",
)


def generate_nerldc_coverage_report(
    db_path: Path | str,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate a diagnostic coverage report across NERLDC curated fact tables.

    Computes:
    1. Overall promotion rate (curated vs raw reports).
    2. Section-level fact row counts and report coverage percentages.
    3. Template-level promotion rates and fact yield breakdown.
    4. Curated lineage record counts.

    Args:
        db_path: Path to the curated SQLite database.
        output_path: Optional path to write the resulting JSON report.

    Returns:
        A dictionary representation of `NERLDCCuratedCoverageReport`.
    """
    db_path_obj = Path(db_path)
    if not db_path_obj.exists():
        raise FileNotFoundError(f"Database not found at {db_path_obj}")

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
                "SELECT id, template_id, semantic_pass_required FROM psp_report_document WHERE rldc = 'nerldc'"
            ).fetchall()
        total_raw = len(raw_reports_query)

        if total_raw == 0:
            empty_report = NERLDCCuratedCoverageReport(
                audited_at=datetime.now(timezone.utc).isoformat(),
                database_path=str(db_path_obj),
                total_raw_reports=0,
                total_curated_reports=0,
                overall_promotion_rate_pct=0.0,
                total_lineage_records=0,
                sections=[],
                templates=[],
            )
            return asdict(empty_report)

        # Raw document breakdown by template
        templates_raw: dict[str, list[tuple[int, int]]] = {}
        for r_id, template_id, semantic_pass in raw_reports_query:
            t_id = template_id or "unmatched"
            templates_raw.setdefault(t_id, []).append((r_id, semantic_pass or 0))

        # Check section-level coverage across all fact tables
        sections: list[SectionCoverage] = []
        all_promoted_report_ids: set[int] = set()

        for table in _FACT_TABLES:
            t_exists = conn.execute(
                f"SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '{table}'"
            ).fetchone()
            if not t_exists:
                sections.append(
                    SectionCoverage(
                        fact_table=table,
                        total_rows=0,
                        distinct_reports=0,
                        report_coverage_pct=0.0,
                    )
                )
                continue

            row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            distinct_reports_rows = conn.execute(
                f"SELECT DISTINCT ReportDocumentID FROM {table}"
            ).fetchall()
            distinct_reports = len(distinct_reports_rows)
            for (r_id,) in distinct_reports_rows:
                all_promoted_report_ids.add(r_id)

            coverage_pct = round(
                (distinct_reports / total_raw * 100.0) if total_raw > 0 else 0.0, 2
            )
            sections.append(
                SectionCoverage(
                    fact_table=table,
                    total_rows=row_count,
                    distinct_reports=distinct_reports,
                    report_coverage_pct=coverage_pct,
                )
            )

        # Lineage record count
        has_lineage = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'curated_field_lineage'"
        ).fetchone()
        total_lineage = (
            conn.execute("SELECT COUNT(*) FROM curated_field_lineage").fetchone()[0]
            if has_lineage
            else 0
        )

        total_curated = len(all_promoted_report_ids)
        overall_promotion_rate = round(
            (total_curated / total_raw * 100.0) if total_raw > 0 else 0.0, 2
        )

        # Template-level breakdown
        templates: list[TemplateCoverage] = []
        for t_id, reports in sorted(templates_raw.items()):
            t_report_ids = {r[0] for r in reports}
            gated_count = sum(1 for r in reports if r[1] == 1)
            promoted_in_template = len(t_report_ids.intersection(all_promoted_report_ids))
            t_prom_rate = round(
                (promoted_in_template / len(reports) * 100.0) if reports else 0.0, 2
            )

            # Fact counts for this template
            fact_counts: dict[str, int] = {}
            for table in _FACT_TABLES:
                t_exists = conn.execute(
                    f"SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '{table}'"
                ).fetchone()
                if not t_exists:
                    fact_counts[table] = 0
                    continue
                q_marks = ",".join("?" for _ in t_report_ids)
                if not q_marks:
                    fact_counts[table] = 0
                    continue
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE ReportDocumentID IN ({q_marks})",
                    list(t_report_ids),
                ).fetchone()[0]
                fact_counts[table] = cnt

            templates.append(
                TemplateCoverage(
                    template_id=t_id,
                    total_reports=len(reports),
                    promoted_reports=promoted_in_template,
                    gated_reports=gated_count,
                    promotion_rate_pct=t_prom_rate,
                    fact_counts=fact_counts,
                )
            )

        report = NERLDCCuratedCoverageReport(
            audited_at=datetime.now(timezone.utc).isoformat(),
            database_path=str(db_path_obj),
            total_raw_reports=total_raw,
            total_curated_reports=total_curated,
            overall_promotion_rate_pct=overall_promotion_rate,
            total_lineage_records=total_lineage,
            sections=sections,
            templates=templates,
        )
        report_dict = asdict(report)

        if output_path is not None:
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(report_dict, f, indent=2)

        return report_dict

    finally:
        conn.close()
