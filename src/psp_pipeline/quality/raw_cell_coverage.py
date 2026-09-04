"""Report auditable raw-cell coverage for curated PSP promotions.

The report deliberately treats unmapped non-empty cells as unresolved unless
there is lineage or an approved coverage disposition.  It is therefore a
quality gate, not a best-effort estimate of parsing completeness.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any


_EXCLUDED_DISPOSITIONS = {
    "dimension",
    "header",
    "derived",
    "duplicate",
    "decorative",
    "intentionally_excluded",
}
_HEADER_TERMS = (
    "station",
    "constituent",
    "state",
    "region",
    "frequency",
    "voltage",
    "reservoir",
    "element",
    "line details",
    "capacity",
    "generation",
    "schedule",
    "drawal",
    "demand",
    "energy",
    "import",
    "export",
    "maximum",
    "minimum",
    "average",
        "peak",
        "off peak",
        "time",
        "shortage",
        "actual",
        "requirement",
        "gross",
        "net",
        "total",
        "sl. no",
        "dsm",
        "deviation",
        "pafm",
        "deemed",
        "allocation",
        "ancillary",
        "payable",
        "receivable",
        "scheduled",
        "constituent",
        "utility",
        "beneficiary",
    )
_UNIT_VALUES = {"mw", "mu", "hz", "kv", "%", "hrs", "m", "mcm", "ft"}
_STRUCTURAL_VALUES = {"-", "--", "nil", "n/a", "na", "none"}


def generate_raw_cell_coverage_report(
    db_path: Path | str,
    *,
    rldc: str | None = None,
    report_id: int | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate a conservative lineage-based coverage report from SQLite.

    Args:
        db_path: SQLite database containing raw PSP cells and curated lineage.
        rldc: Optional source identifier used to restrict documents.
        report_id: Optional raw document identifier used to restrict documents.
        output_path: Optional JSON output location.

    Returns:
        A JSON-serializable report with counts, template summaries, and the
        highest-frequency unresolved page/table/column groups.

    Raises:
        FileNotFoundError: If ``db_path`` does not exist.
        ValueError: If the database has no raw-cell persistence contract.
    """

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "psp_raw_cell") or not _table_exists(
            conn, "psp_report_document"
        ):
            raise ValueError("SQLite database does not contain persisted raw PSP cells")

        clauses = ["TRIM(COALESCE(cell.cell_text, '')) <> ''"]
        params: list[object] = []
        if rldc is not None:
            clauses.append("document.rldc = ?")
            params.append(rldc)
        if report_id is not None:
            clauses.append("document.id = ?")
            params.append(report_id)
        where = f"WHERE {' AND '.join(clauses)}"

        cells = conn.execute(
            f"""
            SELECT cell.id, cell.report_document_id, cell.page_no, cell.table_no,
                   cell.row_no, cell.col_no, cell.cell_text, document.rldc,
                   document.template_id
            FROM psp_raw_cell AS cell
            JOIN psp_report_document AS document
              ON document.id = cell.report_document_id
            {where}
            ORDER BY cell.report_document_id, cell.page_no, cell.table_no,
                     cell.row_no, cell.col_no
            """,
            params,
        ).fetchall()

        report_ids = sorted({int(cell["report_document_id"]) for cell in cells})
        mapped_ids = _mapped_raw_cell_ids(conn, report_ids)
        approved = _approved_dispositions(conn, report_ids)
        mapped_rows = {
            (int(cell["report_document_id"]), int(cell["page_no"]),
             int(cell["table_no"]), int(cell["row_no"]))
            for cell in cells
            if int(cell["id"]) in mapped_ids
        }

        totals: Counter[str] = Counter()
        templates: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        unresolved: dict[tuple[str, str, int, int, int], list[dict[str, object]]] = defaultdict(list)

        for cell in cells:
            disposition, reason = _classify_cell(
                cell,
                mapped_ids=mapped_ids,
                approved=approved,
                mapped_rows=mapped_rows,
            )
            totals[disposition] += 1
            template_key = (str(cell["rldc"]), str(cell["template_id"] or "unassigned"))
            templates[template_key][disposition] += 1
            if disposition == "unresolved":
                key = (
                    str(cell["rldc"]),
                    str(cell["template_id"] or "unassigned"),
                    int(cell["page_no"]),
                    int(cell["table_no"]),
                    int(cell["col_no"]),
                )
                unresolved[key].append(
                    {
                        "raw_cell_id": int(cell["id"]),
                        "row_no": int(cell["row_no"]),
                        "value": str(cell["cell_text"])[:200],
                        "reason": reason,
                    }
                )

        raw_cell_count = len(cells)
        accounted_count = raw_cell_count - totals["unresolved"]
        report = {
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "database_path": str(path),
            "scope": {"rldc": rldc, "report_id": report_id},
            "raw_nonempty_cell_count": raw_cell_count,
            "mapped_cell_count": totals["mapped"],
            "approved_exclusion_count": totals["approved_exclusion"],
            "unresolved_cell_count": totals["unresolved"],
            "accounted_cell_count": accounted_count,
            "accounted_cell_pct": _pct(accounted_count, raw_cell_count),
            "lineage_rate_pct": _pct(totals["mapped"], raw_cell_count),
            "null_rate_pct": _pct(totals["unresolved"], raw_cell_count),
            "lineage_cell_count": len(mapped_ids),
            "templates": [
                {
                    "rldc": source,
                    "template_id": template_id,
                    "raw_nonempty_cell_count": sum(counts.values()),
                    "mapped_cell_count": counts["mapped"],
                    "approved_exclusion_count": counts["approved_exclusion"],
                    "unresolved_cell_count": counts["unresolved"],
                    "accounted_cell_pct": _pct(
                        sum(counts.values()) - counts["unresolved"], sum(counts.values())
                    ),
                    "lineage_rate_pct": _pct(counts["mapped"], sum(counts.values())),
                    "null_rate_pct": _pct(counts["unresolved"], sum(counts.values())),
                }
                for (source, template_id), counts in sorted(templates.items())
            ],
            "unresolved_groups": [
                {
                    "rldc": source,
                    "template_id": template_id,
                    "page_no": page_no,
                    "table_no": table_no,
                    "col_no": col_no,
                    "count": len(items),
                    "examples": items[:10],
                }
                for (source, template_id, page_no, table_no, col_no), items in sorted(
                    unresolved.items(), key=lambda item: (-len(item[1]), item[0])
                )
            ],
            "tables": _destination_table_coverage(conn, report_ids, rldc),
        }
        if output_path is not None:
            destination = Path(output_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return whether a SQLite table exists."""

    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
    ).fetchone() is not None


def _destination_table_coverage(
    conn: sqlite3.Connection,
    report_ids: list[int],
    rldc: str | None,
) -> list[dict[str, Any]]:
    """Summarize lineage completeness per curated destination table."""

    if not report_ids or not _table_exists(conn, "curated_field_lineage"):
        return []
    placeholders = ",".join("?" for _ in report_ids)
    params: list[object] = list(report_ids)
    rldc_clause = ""
    if rldc is not None:
        rldc_clause = " AND document.rldc = ?"
        params.append(rldc)
    rows = conn.execute(
        f"""
        SELECT document.rldc, lineage.DestinationTable,
               COUNT(*) AS lineage_count,
               SUM(CASE WHEN lineage.RawCellID IS NOT NULL THEN 1 ELSE 0 END)
                 AS mapped_count
        FROM curated_field_lineage AS lineage
        JOIN psp_report_document AS document
          ON document.id = lineage.ReportDocumentID
        WHERE lineage.ReportDocumentID IN ({placeholders}){rldc_clause}
        GROUP BY document.rldc, lineage.DestinationTable
        ORDER BY document.rldc, lineage.DestinationTable
        """,
        params,
    ).fetchall()
    summaries = []
    for source, table_name, lineage_count, mapped_count in rows:
        mapped = int(mapped_count or 0)
        total = int(lineage_count or 0)
        missing = total - mapped
        summaries.append(
            {
                "rldc": str(source),
                "destination_table": str(table_name),
                "lineage_row_count": total,
                "mapped_cell_count": mapped,
                "accounted_cell_pct": _pct(mapped, total),
                "lineage_rate_pct": _pct(mapped, total),
                "null_rate_pct": _pct(missing, total),
            }
        )
    return summaries


def _mapped_raw_cell_ids(conn: sqlite3.Connection, report_ids: list[int]) -> set[int]:
    """Return raw cells with at least one curated lineage destination."""

    if not report_ids or not _table_exists(conn, "curated_field_lineage"):
        return set()
    placeholders = ",".join("?" for _ in report_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT RawCellID
        FROM curated_field_lineage
        WHERE ReportDocumentID IN ({placeholders}) AND RawCellID IS NOT NULL
        """,
        report_ids,
    ).fetchall()
    return {int(row[0]) for row in rows}


def _approved_dispositions(
    conn: sqlite3.Connection, report_ids: list[int]
) -> dict[int, str]:
    """Load existing source-specific coverage decisions when available."""

    if not report_ids or not _table_exists(conn, "schema_coverage_item"):
        return {}
    placeholders = ",".join("?" for _ in report_ids)
    rows = conn.execute(
        f"""
        SELECT item.RawCellID, item.Disposition
        FROM schema_coverage_item AS item
        JOIN schema_coverage_run AS run ON run.CoverageRunID = item.CoverageRunID
        WHERE run.ReportDocumentID IN ({placeholders}) AND item.RawCellID IS NOT NULL
        """,
        report_ids,
    ).fetchall()
    return {int(row[0]): str(row[1]) for row in rows}


def _classify_cell(
    cell: sqlite3.Row,
    *,
    mapped_ids: set[int],
    approved: dict[int, str],
    mapped_rows: set[tuple[int, int, int, int]],
) -> tuple[str, str]:
    """Classify one non-empty raw cell without inferring a fact mapping."""

    cell_id = int(cell["id"])
    if cell_id in mapped_ids:
        return "mapped", "curated_field_lineage"
    coverage_disposition = approved.get(cell_id)
    if coverage_disposition == "mapped_value":
        return "mapped", "approved_schema_coverage"
    if coverage_disposition in _EXCLUDED_DISPOSITIONS:
        return "approved_exclusion", f"approved_{coverage_disposition}"

    text = str(cell["cell_text"]).strip()
    normalized = re.sub(r"\s+", " ", text).lower()
    if normalized in _STRUCTURAL_VALUES:
        return "approved_exclusion", "published_empty_indicator"
    if normalized in _UNIT_VALUES or _is_header_text(normalized):
        return "approved_exclusion", "recognized_header_or_unit"
    row_key = (
        int(cell["report_document_id"]),
        int(cell["page_no"]),
        int(cell["table_no"]),
        int(cell["row_no"]),
    )
    if int(cell["col_no"]) == 1 and row_key in mapped_rows:
        return "approved_exclusion", "dimension_label_for_mapped_row"
    return "unresolved", "nonempty_cell_without_lineage_or_approved_exclusion"


def _is_header_text(normalized: str) -> bool:
    """Return whether text is a conservative, recognizable table heading."""

    if normalized in {"s.no", "s.no.", "sl.no", "sl.no.", "total", "avg", "hrs"}:
        return True
    if any(term in normalized for term in _HEADER_TERMS):
        return True
    return bool(re.fullmatch(r"(?:[0-9]+\s*)?(?:mw|mu|hz|kv|%|hrs)", normalized))


def _pct(numerator: int, denominator: int) -> float:
    """Return a rounded percentage while handling empty scopes."""

    return round(100.0 * numerator / denominator, 2) if denominator else 0.0
