"""Tests for guarded RLDC PDF table extraction."""

from __future__ import annotations

from typing import Any

from psp_pipeline.parsing.rldc.pdf_tables import extract_page_tables


class _DensePage:
    """Minimal page double that fails if native geometry extraction is used."""

    rects = [object()] * 10_000
    chars = [object()] * 500

    def extract_tables(self, table_settings: dict[str, Any] | None = None) -> list[list[list[str]]]:
        """Return a text-boundary table and reject the native table path."""

        if table_settings is None:
            raise AssertionError("native rect-based extraction should be skipped")
        return [[[
            "station", "capacity", "generation", "average",
        ], ["A", "1", "2", "3"], ["B", "4", "5", "6"]]]


def test_dense_rect_page_skips_native_geometry_extraction() -> None:
    """Use text boundaries before native extraction for vector-heavy pages."""

    tables = extract_page_tables(_DensePage())

    assert len(tables) == 1
    assert tables[0][1] == ["A", "1", "2", "3"]
