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


_ERLDC_REGIONAL_TOKENS = {
    "EveningPeakDemandMetMW": ("evening", "peak", "demand", "met"),
    "OffPeakDemandMetMW": ("off", "peak", "demand", "met"),
    "DayEnergyMetMU": ("day", "energy", "met"),
}


def test_stacked_two_row_headers_bind_compact_regional_columns() -> None:
    """Super-header plus sub-header in the same column is one published label."""

    rows = [
        {1: "Evening Peak (20:00) MW", 2: "Off Peak (03:00) MW", 3: "Day Energy (MU)"},
        {1: "Demand Met", 2: "Demand Met", 3: "Met"},
    ]
    result = resolve_header_layout(rows, _ERLDC_REGIONAL_TOKENS)
    assert result.resolved is True
    assert result.evidence["source"] == "stacked_header"
    assert result.mapping == {
        "EveningPeakDemandMetMW": 1,
        "OffPeakDemandMetMW": 2,
        "DayEnergyMetMU": 3,
    }


def test_stacked_two_row_headers_bind_wide_regional_columns() -> None:
    """Stacked labels still win when measure columns are sparse."""

    rows = [
        {1: "Evening Peak (20:00) MW", 6: "Off Peak (03:00) MW", 12: "Day Energy (MU)"},
        {1: "Demand Met", 6: "Demand Met", 12: "Met"},
    ]
    result = resolve_header_layout(rows, _ERLDC_REGIONAL_TOKENS)
    assert result.resolved is True
    assert result.evidence["source"] == "stacked_header"
    assert result.mapping == {
        "EveningPeakDemandMetMW": 1,
        "OffPeakDemandMetMW": 6,
        "DayEnergyMetMU": 12,
    }


def test_stacked_headers_bind_demand_met_not_shortage_columns() -> None:
    """Shortage siblings share a super-header but lack Demand Met tokens."""

    rows = [
        {
            1: "Evening Peak (20:00) MW",
            2: "Evening Peak (20:00) MW",
            3: "Off Peak (03:00) MW",
            4: "Off Peak (03:00) MW",
            5: "Day Energy (MU)",
            6: "Day Energy (MU)",
        },
        {
            1: "Demand Met",
            2: "Shortage",
            3: "Demand Met",
            4: "Shortage",
            5: "Energy Met",
            6: "Shortage",
        },
    ]
    result = resolve_header_layout(rows, _ERLDC_REGIONAL_TOKENS)
    assert result.resolved is True
    assert result.mapping == {
        "EveningPeakDemandMetMW": 1,
        "OffPeakDemandMetMW": 3,
        "DayEnergyMetMU": 5,
    }


def test_stacked_headers_do_not_bind_day_energy_from_demand_substring() -> None:
    """``day`` inside ``Demand`` is not enough without an energy token."""

    rows = [
        {1: "Evening Peak (20:00) MW", 2: "Off Peak (03:00) MW"},
        {1: "Demand Met", 2: "Demand Met"},
    ]
    result = resolve_header_layout(rows, _ERLDC_REGIONAL_TOKENS)
    assert result.resolved is False
    assert result.quarantine_reason == "incomplete_header_layout"
    assert "DayEnergyMetMU" in result.evidence["missing_fields"]


def test_stacked_headers_stay_incomplete_when_two_columns_match_one_field() -> None:
    """Duplicate stacked Demand Met columns are not guessed."""

    rows = [
        {1: "Evening Peak (20:00) MW", 2: "Evening Peak (20:00) MW", 3: "Day Energy (MU)"},
        {1: "Demand Met", 2: "Demand Met", 3: "Met"},
    ]
    result = resolve_header_layout(rows, _ERLDC_REGIONAL_TOKENS)
    assert result.resolved is False
    assert "EveningPeakDemandMetMW" in result.evidence["stacked_ambiguous_fields"]


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
