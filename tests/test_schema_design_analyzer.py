from __future__ import annotations

from psp_pipeline.parsing.rldc.templates import ReportStructure, TableShape
from psp_pipeline.schema_design.analyzer import (
    analyze_report_schema,
    build_structure_fingerprint,
    normalize_label,
)


class Cell:
    def __init__(self, page: int, table: int, row: int, col: int, text: str) -> None:
        self.page_no = page
        self.table_no = table
        self.row_no = row
        self.col_no = col
        self.cell_text = text


def test_structure_fingerprint_is_stable() -> None:
    structure = ReportStructure(
        page_count=10,
        table_count=1,
        headings=("1. Regional Availability / Demand",),
        table_shapes=(TableShape(1, 1, 3, 3, 10, 10, "observed"),),
    )

    first = build_structure_fingerprint("SRLDC", structure)
    second = build_structure_fingerprint("srldc", structure)

    assert first.fingerprint == second.fingerprint
    assert first.source_id == "srldc"
    assert first.structural_family == second.structural_family


def test_schema_analysis_proposes_unclassified_columns() -> None:
    cells = [
        Cell(1, 1, 1, 1, "State"),
        Cell(1, 1, 1, 2, "Demand (MW)"),
        Cell(1, 1, 2, 1, "Name"),
        Cell(1, 1, 2, 2, "Value"),
        Cell(1, 1, 3, 1, "Karnataka"),
        Cell(1, 1, 3, 2, "12345"),
    ]

    candidates, proposals = analyze_report_schema(cells)

    assert candidates
    assert proposals
    demand = next(candidate for candidate in candidates if candidate.source_reference.endswith("c2"))
    assert demand.inferred_unit == "MW"
    assert demand.inferred_data_type == "REAL"
    assert "state" in demand.grain_dimensions
    assert normalize_label("Demand\n(MW)") == "demand mw"
