"""Tests for IEGC operating-band header and label-row binding."""

from __future__ import annotations

from psp_pipeline.parsing.frequency_operating_bands import (
    collect_frequency_operating_bands,
)


def test_header_columns_bind_three_operating_bands() -> None:
    """Super-header percentages bind only when every bucket is unique."""

    rows = [
        {1: "<49.90 Hz", 2: "49.90-50.05 Hz", 3: ">50.05 Hz"},
        {1: "2.10", 2: "95.40", 3: "2.50"},
    ]
    values, _sources = collect_frequency_operating_bands(rows)
    assert values == {
        "DurationBelow49_90Pct": 2.1,
        "Duration49_90To50_05Pct": 95.4,
        "DurationAbove50_05Pct": 2.5,
    }


def test_label_rows_bind_operating_bands() -> None:
    """A label in column 1 plus a later numeric cell is a complete band."""

    rows = [
        {1: "% time frequency remained below 49.90 Hz", 2: "1.8"},
        {1: "49.90-50.05 Hz", 2: "96.1"},
        {1: "% time frequency remained above 50.05 Hz", 2: "2.1"},
    ]
    values, _sources = collect_frequency_operating_bands(rows)
    assert values == {
        "DurationBelow49_90Pct": 1.8,
        "Duration49_90To50_05Pct": 96.1,
        "DurationAbove50_05Pct": 2.1,
    }


def test_incomplete_operating_bands_are_not_guessed() -> None:
    """Two of three buckets is not a mapping."""

    rows = [
        {1: "<49.90 Hz", 2: "3.0"},
        {1: ">50.05 Hz", 2: "1.0"},
    ]
    values, sources = collect_frequency_operating_bands(rows)
    assert values == {}
    assert sources == {}
