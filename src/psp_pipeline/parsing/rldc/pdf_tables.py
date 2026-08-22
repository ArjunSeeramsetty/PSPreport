"""Guarded table extraction helpers for structurally varied RLDC PDFs."""

from __future__ import annotations

from typing import Any


RECT_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "snap_tolerance": 3,
}
MAX_RECT_TO_CHAR_RATIO = 4.0
DENSE_RECT_THRESHOLD = 10_000


def extract_page_tables(page: Any) -> list[list[list[str | None]]]:
    """Extract tables, retrying text boundaries for dense rect-delimited pages.

    The fallback is deliberately narrow: it only runs when native line extraction
    found no tables, the page has abundant rectangle geometry and readable text,
    and the fallback result has enough populated cells to resemble a table.
    """

    if len(page.rects) >= DENSE_RECT_THRESHOLD:
        return _extract_text_tables(page)

    tables = page.extract_tables() or []
    if tables:
        return tables
    if len(page.rects) < 100 or len(page.chars) < 200:
        return []
    rect_to_char_ratio = len(page.rects) / max(len(page.chars), 1)
    if rect_to_char_ratio > MAX_RECT_TO_CHAR_RATIO:
        return []
    return _extract_text_tables(page)


def _extract_text_tables(page: Any) -> list[list[list[str | None]]]:
    """Extract credible tables with text boundaries, avoiding rect intersections."""

    candidates = page.extract_tables(table_settings=RECT_TABLE_SETTINGS) or []
    return [table for table in candidates if _is_credible_table(table)]


def _is_credible_table(table: list[list[str | None]]) -> bool:
    """Return whether a text-strategy result is large enough to be table-like."""

    rows = len(table)
    columns = max((len(row) for row in table), default=0)
    populated = sum(
        1
        for row in table
        for cell in row
        if cell is not None and str(cell).strip()
    )
    return rows >= 3 and columns >= 4 and populated >= 12
