"""Raw-cell extraction helpers for Grid-India NLDC Daily PSP reports."""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from psp_pipeline.parsing.rldc.pdf_tables import extract_page_tables
from psp_pipeline.pipelines.rldc_daily_psp import RawCell


# The control-area drawal matrix moved to Page 1 in an April 2025 layout,
# while later pages contain market and 15-minute grid snapshots. Persist all
# available pages so promotion remains section-driven and raw coverage stays
# auditable when a later section is not yet curated.
NLDC_PROMOTION_PAGES = (1, 2, 3, 4, 5)


def extract_nldc_raw_cells(pdf_path: Path) -> list[RawCell]:
    """Extract NLDC promotion pages as coordinate-preserving raw cells.

    The caller persists these cells through the normal PSP raw-storage path.
    This function performs no semantic promotion and raises ``FileNotFoundError``
    when the requested local PDF is absent.
    """

    cells: list[RawCell] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no in NLDC_PROMOTION_PAGES:
            if page_no > len(pdf.pages):
                continue
            for table_no, table in enumerate(
                extract_page_tables(pdf.pages[page_no - 1]),
                start=1,
            ):
                for row_no, row in enumerate(table, start=1):
                    for col_no, value in enumerate(row, start=1):
                        cells.append(
                            RawCell(
                                page_no=page_no,
                                table_no=table_no,
                                row_no=row_no,
                                col_no=col_no,
                                cell_text=str(value or ""),
                                extraction_method="pdfplumber",
                            )
                        )
    return cells
