"""Tests for header-first exclusive layout resolution."""

from __future__ import annotations

from psp_pipeline.parsing.layout_resolution import (
    LayoutResolution,
    resolve_exclusive_layouts,
    resolve_header_layout,
)


def test_header_layout_wins_when_every_required_field_binds() -> None:
    """Published labels are a resolved mapping, not a width heuristic."""

    rows = [
        {1: "Evening Peak Demand Met", 6: "Off Peak Demand Met", 12: "Day Energy Met"},
    ]
    result = resolve_header_layout(
        rows,
        {
            "EveningPeakDemandMetMW": ("evening", "peak", "demand", "met"),
            "OffPeakDemandMetMW": ("off", "peak", "demand", "met"),
            "DayEnergyMetMU": ("day", "energy", "met"),
        },
    )
    assert result.resolved is True
    assert result.layout_id == "header"
    assert result.mapping == {
        "EveningPeakDemandMetMW": 1,
        "OffPeakDemandMetMW": 6,
        "DayEnergyMetMU": 12,
    }


def test_exclusive_numeric_layouts_quarantine_when_both_signatures_hit() -> None:
    """Competing compact and wide occupancy is ambiguous, never guessed."""

    populated = {1, 2, 3, 6, 12}

    result = resolve_exclusive_layouts(
        layouts={
            "compact": {"a": 1, "b": 2, "c": 3},
            "wide": {"a": 1, "b": 6, "c": 12},
        },
        exclusive_columns={"compact": frozenset({2, 3}), "wide": frozenset({6, 12})},
        populated=lambda column: column in populated,
    )
    assert result.status == "ambiguous"
    assert result.quarantine_reason == "ambiguous_layout"
    assert set(result.evidence["candidates"]) == {"compact", "wide"}


def test_exclusive_numeric_layouts_keep_compact_when_wide_exclusive_empty() -> None:
    """Decorative trailing cells do not select the wide signature."""

    populated = {1, 2, 3, 20}

    result = resolve_exclusive_layouts(
        layouts={
            "compact": {"a": 1, "b": 2, "c": 3},
            "wide": {"a": 1, "b": 6, "c": 12},
        },
        exclusive_columns={"compact": frozenset({2, 3}), "wide": frozenset({6, 12})},
        populated=lambda column: column in populated,
    )
    assert result == LayoutResolution.from_mapping(
        "compact",
        {"a": 1, "b": 2, "c": 3},
        exclusive_hits={"compact": (2, 3), "wide": ()},
    )
