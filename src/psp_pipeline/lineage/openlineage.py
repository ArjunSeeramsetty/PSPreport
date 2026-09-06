"""Emit OpenLineage ColumnLineageDatasetFacet payloads from curated SQLite."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4


OPENLINEAGE_PRODUCER = "https://github.com/ArjunSeeramsetty/PSPreport"


def build_column_lineage_event(
    db_path: Path | str,
    *,
    run_id: str,
    job_name: str = "psp.parse_artifacts",
    namespace: str = "psp://downloads",
    event_time: datetime | None = None,
) -> dict[str, Any]:
    """Translate ``curated_field_lineage`` rows into an OpenLineage RunEvent.

    Numeric values are never re-derived. The facet only declares that an
    output column depends on a specific raw cell or text item, including the
    geometric coordinates stored on ``psp_raw_text_item``.
    """

    occurred = event_time or datetime.now(timezone.utc)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        fields = _column_lineage_fields(conn, namespace)
        inputs = _unique_inputs(fields)
    finally:
        conn.close()
    return {
        "eventType": "COMPLETE",
        "eventTime": occurred.isoformat(),
        "run": {"runId": run_id or str(uuid4())},
        "job": {"namespace": namespace, "name": job_name},
        "inputs": inputs,
        "outputs": [
            {
                "namespace": namespace,
                "name": "timescale.fact_observation",
                "facets": {
                    "columnLineage": {
                        "_producer": OPENLINEAGE_PRODUCER,
                        "_schemaURL": (
                            "https://openlineage.io/spec/facets/1-2-0/"
                            "ColumnLineageDatasetFacet.json"
                        ),
                        "fields": fields,
                    }
                },
            }
        ],
        "producer": OPENLINEAGE_PRODUCER,
        "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
    }


def _column_lineage_fields(
    conn: sqlite3.Connection,
    namespace: str,
) -> dict[str, Any]:
    required = (
        "curated_field_lineage",
        "psp_report_document",
    )
    present = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?)",
            required,
        )
    }
    if set(required) - present:
        return {}
    has_cells = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_raw_cell'"
    ).fetchone()
    has_items = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_raw_text_item'"
    ).fetchone()
    cell_join = (
        "LEFT JOIN psp_raw_cell AS cell ON cell.id = lineage.RawCellID"
        if has_cells
        else ""
    )
    item_join = (
        "LEFT JOIN psp_raw_text_item AS text_item ON text_item.id = lineage.RawTextItemID"
        if has_items
        else ""
    )
    cell_cols = (
        "cell.page_no AS cell_page, cell.table_no AS table_no, "
        "cell.row_no AS row_no, cell.col_no AS col_no,"
        if has_cells
        else "NULL AS cell_page, NULL AS table_no, NULL AS row_no, NULL AS col_no,"
    )
    item_cols = (
        "text_item.page_no AS item_page, text_item.x AS x, text_item.y AS y, "
        "text_item.width AS width, text_item.height AS height,"
        if has_items
        else "NULL AS item_page, NULL AS x, NULL AS y, NULL AS width, NULL AS height,"
    )
    rows = conn.execute(
        f"""
        SELECT
            lineage.DestinationTable AS destination_table,
            lineage.DestinationColumn AS destination_column,
            lineage.RawCellID AS raw_cell_id,
            lineage.RawTextItemID AS raw_text_item_id,
            lineage.ExtractionMethod AS extraction_method,
            lineage.Confidence AS confidence,
            report.rldc AS rldc,
            report.local_path AS local_path,
            {cell_cols}
            {item_cols}
            1 AS _pad
        FROM curated_field_lineage AS lineage
        JOIN psp_report_document AS report
          ON report.id = lineage.ReportDocumentID
        {cell_join}
        {item_join}
        ORDER BY lineage.DestinationTable, lineage.DestinationColumn,
                 lineage.RawCellID, lineage.RawTextItemID
        """
    ).fetchall()
    fields: dict[str, Any] = {}
    for row in rows:
        output_name = f"{row['destination_table']}.{row['destination_column']}"
        field = fields.setdefault(output_name, {"inputFields": []})
        if row["cell_page"] is not None:
            source_field = (
                f"p{row['cell_page']}_t{row['table_no']}_r{row['row_no']}_c{row['col_no']}"
            )
        elif row["raw_text_item_id"] is not None:
            source_field = f"text-item-{row['raw_text_item_id']}"
        else:
            source_field = f"raw-cell-{row['raw_cell_id']}"
        entry: dict[str, Any] = {
            "namespace": f"{namespace}/{row['rldc']}",
            "name": Path(str(row["local_path"] or "unknown.pdf")).name,
            "field": source_field,
            "transformations": [
                {
                    "type": "DIRECT",
                    "subtype": "IDENTITY",
                    "description": str(row["extraction_method"] or "pdfplumber"),
                    "confidence": row["confidence"],
                }
            ],
        }
        if row["x"] is not None and row["y"] is not None:
            width = row["width"] or 0.0
            height = row["height"] or 0.0
            entry["boundingBox"] = {
                "x0": row["x"],
                "y0": row["y"],
                "x1": row["x"] + width,
                "y1": row["y"] + height,
                "page_no": row["item_page"],
            }
        field["inputFields"].append(entry)
    return fields


def _unique_inputs(fields: dict[str, Any]) -> list[dict[str, str]]:
    seen: dict[tuple[str, str], None] = {}
    for payload in fields.values():
        for item in payload.get("inputFields", []):
            key = (str(item.get("namespace")), str(item.get("name")))
            seen[key] = None
    return [{"namespace": namespace, "name": name} for namespace, name in seen]
