from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import (
    RawCell,
    RawTextItem,
    _extract_liteparse_content,
    _spatial_fallback_reasons,
    _should_try_liteparse,
    extract_psp_content,
)
from psp_pipeline.parsing.rldc.templates import (
    COMPACT_SRLDCP_TEMPLATE,
    DEFAULT_SRLDCP_TEMPLATE,
    ERLDC_2023_TEMPLATE,
    ERLDC_2024_FLAT_TEMPLATE,
    ERLDC_2024_SPLIT_TEMPLATE,
    ERLDC_2025_FLAT_TEMPLATE,
    ERLDC_2025_SPLIT_TEMPLATE,
    ERLDC_STANDARD_FAMILY_ID,
    FLAT_8_SRLDCP_TEMPLATE,
    FLAT_8_2025_SRLDCP_TEMPLATE,
    FLAT_6_2023_SRLDCP_TEMPLATE,
    FLAT_6_2024_SRLDCP_TEMPLATE,
    FLAT_7_2023_SRLDCP_TEMPLATE,
    NRLDC_2024_TEMPLATE,
    NRLDC_2025_TEMPLATE,
    NRLDC_2026_TEMPLATE,
    NRLDC_STANDARD_FAMILY_ID,
    NERLDC_STANDARD_FAMILY_ID,
    ReportStructure,
    SRLDC_FLAT_FAMILY_ID,
    SRLDC_SPLIT_FAMILY_ID,
    TableShape,
    WRLDC_2023_TEMPLATE,
    WRLDC_2023_REVISED_TEMPLATE,
    WRLDC_2024_TEMPLATE,
    WRLDC_2024_REVISED_TEMPLATE,
    WRLDC_2024_TRANSITION_TEMPLATE,
    WRLDC_2025_TEMPLATE,
    WRLDC_2025_REVISED_TEMPLATE,
    WRLDC_2026_TEMPLATE,
    WRLDC_2026_EARLY_TEMPLATE,
    WRLDC_STANDARD_FAMILY_ID,
    infer_structural_family,
    inspect_report_structure,
    match_report_template,
)


def test_srldc_template_match_accepts_expected_structure() -> None:
    structure = ReportStructure(
        page_count=10,
        table_count=41,
        headings=DEFAULT_SRLDCP_TEMPLATE.required_headings,
        table_shapes=(
            TableShape(1, 1, 3, 3, 10, 10, "observed"),
            TableShape(1, 2, 9, 9, 13, 13, "observed"),
            TableShape(1, 3, 9, 9, 10, 10, "observed"),
            TableShape(1, 4, 9, 9, 13, 13, "observed"),
            TableShape(8, 2, 4, 4, 10, 10, "observed"),
            TableShape(9, 2, 11, 11, 12, 12, "observed"),
            TableShape(10, 3, 8, 8, 9, 9, "observed"),
            TableShape(10, 4, 8, 8, 13, 13, "observed"),
        ),
    )

    result = match_report_template("srldc", structure)

    assert result.template_id == "srldc_daily_psp_v2026_05"
    assert result.semantic_pass_required is False
    assert result.confidence == 1.0


def test_srldc_compact_template_match_accepts_expected_structure() -> None:
    structure = ReportStructure(
        page_count=9,
        table_count=38,
        headings=COMPACT_SRLDCP_TEMPLATE.required_headings,
        table_shapes=(
            TableShape(1, 1, 3, 3, 10, 10, "observed"),
            TableShape(1, 2, 9, 9, 13, 13, "observed"),
            TableShape(1, 3, 9, 9, 10, 10, "observed"),
            TableShape(1, 4, 9, 9, 13, 13, "observed"),
            TableShape(7, 1, 4, 4, 10, 10, "observed"),
            TableShape(7, 4, 6, 6, 9, 9, "observed"),
            TableShape(7, 7, 4, 4, 12, 12, "observed"),
            TableShape(8, 2, 9, 9, 14, 14, "observed"),
            TableShape(8, 4, 9, 9, 8, 8, "observed"),
            TableShape(9, 2, 8, 8, 9, 9, "observed"),
            TableShape(9, 3, 8, 8, 13, 13, "observed"),
        ),
    )

    result = match_report_template("srldc", structure)

    assert result.template_id == "srldc_daily_psp_v2026_01"
    assert result.semantic_pass_required is False
    assert result.confidence == 1.0


def test_template_match_requires_semantic_pass_for_unknown_rldc() -> None:
    structure = ReportStructure(page_count=10, table_count=41, headings=(), table_shapes=())

    result = match_report_template("unknown-rldc", structure)

    assert result.template_id is None
    assert result.semantic_pass_required is True
    assert result.reasons == ("no_template_for_rldc",)


def test_structural_family_groups_compact_and_expanded_split_reports() -> None:
    compact = ReportStructure(
        page_count=9,
        table_count=38,
        headings=COMPACT_SRLDCP_TEMPLATE.required_headings,
        table_shapes=tuple(
            TableShape(page_no, 1, 5, 5, 10, 10, "observed")
            for page_no in range(1, 10)
        ),
    )
    expanded = ReportStructure(
        page_count=10,
        table_count=41,
        headings=DEFAULT_SRLDCP_TEMPLATE.required_headings,
        table_shapes=tuple(
            TableShape(page_no, 1, 5, 5, 10, 10, "observed")
            for page_no in range(1, 11)
        ),
    )

    assert infer_structural_family("srldc", compact) == SRLDC_SPLIT_FAMILY_ID
    assert infer_structural_family("srldc", expanded) == SRLDC_SPLIT_FAMILY_ID


def test_structural_family_detects_flattened_historical_exports() -> None:
    structure = ReportStructure(
        page_count=8,
        table_count=8,
        headings=DEFAULT_SRLDCP_TEMPLATE.required_headings,
        table_shapes=tuple(
            TableShape(page_no, 1, 30, 30, 12, 12, "observed")
            for page_no in range(1, 9)
        ),
    )

    assert infer_structural_family("srldc", structure) == SRLDC_FLAT_FAMILY_ID


def test_srldc_flat_8_template_match_accepts_expected_structure() -> None:
    structure = ReportStructure(
        page_count=8,
        table_count=8,
        headings=(),
        table_shapes=(
            TableShape(1, 1, 60, 60, 40, 40, "observed"),
            TableShape(6, 1, 70, 70, 41, 41, "observed"),
            TableShape(7, 1, 65, 65, 51, 51, "observed"),
            TableShape(8, 1, 4, 4, 1, 1, "observed"),
        ),
    )

    result = match_report_template("srldc", structure)

    assert result.template_id == FLAT_8_SRLDCP_TEMPLATE.template_id
    assert result.semantic_pass_required is False
    assert result.confidence == 1.0


def test_srldc_flat_8_2025_template_match_accepts_expected_structure() -> None:
    structure = ReportStructure(
        page_count=8,
        table_count=8,
        headings=(),
        table_shapes=(
            TableShape(1, 1, 60, 60, 40, 40, "observed"),
            TableShape(6, 1, 63, 63, 37, 37, "observed"),
            TableShape(7, 1, 57, 57, 35, 35, "observed"),
            TableShape(8, 1, 23, 23, 21, 21, "observed"),
        ),
    )

    result = match_report_template("srldc", structure)

    assert result.template_id == FLAT_8_2025_SRLDCP_TEMPLATE.template_id
    assert result.semantic_pass_required is False
    assert result.confidence == 1.0


def test_srldc_flat_6_2023_template_match_accepts_sparse_structure() -> None:
    structure = ReportStructure(
        page_count=6,
        table_count=6,
        headings=(),
        table_shapes=(
            TableShape(1, 1, 61, 61, 35, 35, "observed"),
            TableShape(5, 1, 67, 67, 37, 37, "observed"),
            TableShape(6, 1, 43, 43, 36, 36, "observed"),
        ),
    )

    result = match_report_template("srldc", structure)

    assert result.template_id == FLAT_6_2023_SRLDCP_TEMPLATE.template_id
    assert result.semantic_pass_required is False
    assert result.confidence == 1.0


def test_srldc_flat_7_2023_template_match_accepts_generation_continuation() -> None:
    structure = ReportStructure(
        page_count=7,
        table_count=7,
        headings=(),
        table_shapes=(
            TableShape(1, 1, 61, 61, 40, 40, "observed"),
            TableShape(5, 1, 75, 75, 31, 31, "observed"),
            TableShape(6, 1, 68, 68, 50, 50, "observed"),
            TableShape(7, 1, 11, 11, 9, 9, "observed"),
        ),
    )

    result = match_report_template("srldc", structure)

    assert result.template_id == FLAT_7_2023_SRLDCP_TEMPLATE.template_id
    assert result.semantic_pass_required is False
    assert result.confidence == 1.0


def test_srldc_flat_7_2023_template_accepts_shorter_market_rows() -> None:
    """Accept the verified 53-row market section variation from 2023-24."""

    structure = ReportStructure(
        page_count=7,
        table_count=7,
        headings=(),
        table_shapes=(
            TableShape(1, 1, 61, 61, 40, 40, "observed"),
            TableShape(5, 1, 75, 75, 31, 31, "observed"),
            TableShape(6, 1, 53, 53, 35, 35, "observed"),
            TableShape(7, 1, 11, 11, 9, 9, "observed"),
        ),
    )

    result = match_report_template("srldc", structure)

    assert result.template_id == FLAT_7_2023_SRLDCP_TEMPLATE.template_id
    assert result.semantic_pass_required is False
    assert result.confidence == 1.0


def test_srldc_flat_6_2024_template_matches_wide_operations_layout() -> None:
    """Recognize the verified April 2024 layout without a semantic pass."""

    structure = ReportStructure(
        page_count=6,
        table_count=6,
        headings=(),
        table_shapes=(
            TableShape(1, 1, 61, 61, 40, 40, "observed"),
            TableShape(5, 1, 69, 69, 47, 47, "observed"),
            TableShape(6, 1, 53, 53, 41, 41, "observed"),
        ),
    )

    result = match_report_template("srldc", structure)

    assert result.template_id == FLAT_6_2024_SRLDCP_TEMPLATE.template_id
    assert result.semantic_pass_required is False
    assert result.confidence == 1.0


def test_nrldc_2024_template_matches_nine_column_state_generation() -> None:
    """Keep the verified 2024 NRLDC state-generation layout deterministic."""
    structure = ReportStructure(
        page_count=12,
        table_count=13,
        headings=NRLDC_2024_TEMPLATE.required_headings,
        table_shapes=(
            TableShape(1, 1, 54, 54, 38, 38, "observed"),
            TableShape(2, 1, 63, 63, 9, 9, "observed"),
            TableShape(5, 1, 60, 60, 13, 13, "observed"),
            TableShape(9, 1, 62, 62, 25, 25, "observed"),
            TableShape(11, 1, 69, 69, 33, 33, "observed"),
            TableShape(12, 1, 25, 25, 16, 16, "observed"),
        ),
    )

    result = match_report_template("nrldc", structure)

    assert result.template_id == NRLDC_2024_TEMPLATE.template_id
    assert result.semantic_pass_required is False
    assert infer_structural_family("nrldc", structure) == NRLDC_STANDARD_FAMILY_ID


def test_nrldc_2025_and_2026_templates_preserve_known_expansions() -> None:
    """Recognize the 11-column and storage-page NRLDC report families."""
    cases = (
        (
            NRLDC_2025_TEMPLATE,
            12,
            16,
            (
                TableShape(1, 1, 54, 54, 40, 40, "observed"),
                TableShape(2, 1, 65, 65, 11, 11, "observed"),
                TableShape(5, 1, 61, 61, 15, 15, "observed"),
                TableShape(9, 1, 67, 67, 23, 23, "observed"),
                TableShape(10, 1, 61, 61, 25, 25, "observed"),
                TableShape(11, 1, 69, 69, 33, 33, "observed"),
                TableShape(12, 5, 19, 19, 16, 16, "observed"),
            ),
        ),
        (
            NRLDC_2026_TEMPLATE,
            13,
            17,
            (
                TableShape(1, 1, 54, 54, 40, 40, "observed"),
                TableShape(2, 1, 65, 65, 11, 11, "observed"),
                TableShape(5, 1, 62, 62, 15, 15, "observed"),
                TableShape(9, 1, 70, 70, 23, 23, "observed"),
                TableShape(10, 1, 59, 59, 25, 25, "observed"),
                TableShape(12, 1, 64, 64, 34, 34, "observed"),
                TableShape(13, 4, 22, 22, 16, 16, "observed"),
            ),
        ),
    )
    for template, page_count, table_count, shapes in cases:
        structure = ReportStructure(
            page_count=page_count,
            table_count=table_count,
            headings=template.required_headings,
            table_shapes=shapes,
        )

        result = match_report_template("nrldc", structure)

        assert result.template_id == template.template_id
        assert result.semantic_pass_required is False


def test_wrldc_templates_preserve_observed_2023_to_2026_layouts() -> None:
    """Recognize the verified WRLDC annual layout families deterministically."""

    cases = (
        (
            WRLDC_2023_TEMPLATE,
            7,
            8,
            (
                TableShape(1, 1, 55, 55, 36, 36, "observed"),
                TableShape(2, 1, 65, 65, 9, 9, "observed"),
                TableShape(3, 1, 72, 72, 18, 18, "observed"),
                TableShape(5, 1, 53, 53, 25, 25, "observed"),
                TableShape(5, 2, 18, 18, 12, 12, "observed"),
                TableShape(6, 1, 67, 67, 31, 31, "observed"),
                TableShape(7, 1, 11, 11, 9, 9, "observed"),
            ),
        ),
        (
            WRLDC_2024_TEMPLATE,
            8,
            9,
            (
                TableShape(1, 1, 59, 59, 40, 40, "observed"),
                TableShape(2, 1, 65, 65, 9, 9, "observed"),
                TableShape(3, 1, 73, 73, 18, 18, "observed"),
                TableShape(5, 1, 66, 66, 32, 32, "observed"),
                TableShape(5, 2, 4, 4, 9, 9, "observed"),
                TableShape(6, 1, 58, 58, 20, 20, "observed"),
                TableShape(7, 1, 51, 51, 40, 40, "observed"),
                TableShape(8, 1, 13, 13, 9, 9, "observed"),
            ),
        ),
        (
            WRLDC_2023_REVISED_TEMPLATE,
            7,
            8,
            (
                TableShape(1, 1, 59, 59, 40, 40, "observed"),
                TableShape(2, 1, 66, 66, 9, 9, "observed"),
                TableShape(3, 1, 73, 73, 18, 18, "observed"),
                TableShape(4, 1, 71, 71, 17, 17, "observed"),
                TableShape(5, 1, 59, 59, 26, 26, "observed"),
                TableShape(5, 2, 11, 11, 12, 12, "observed"),
                TableShape(6, 1, 63, 63, 20, 20, "observed"),
                TableShape(7, 1, 57, 57, 36, 36, "observed"),
            ),
        ),
        (
            WRLDC_2025_TEMPLATE,
            9,
            10,
            (
                TableShape(1, 1, 62, 62, 43, 43, "observed"),
                TableShape(2, 1, 65, 65, 11, 11, "observed"),
                TableShape(3, 1, 73, 73, 20, 20, "observed"),
                TableShape(4, 1, 28, 28, 12, 12, "observed"),
                TableShape(5, 1, 72, 72, 23, 23, "observed"),
                TableShape(6, 1, 57, 57, 26, 26, "observed"),
                TableShape(6, 2, 14, 14, 12, 12, "observed"),
                TableShape(8, 1, 48, 48, 30, 30, "observed"),
                TableShape(9, 1, 14, 14, 9, 9, "observed"),
            ),
        ),
        (
            WRLDC_2024_REVISED_TEMPLATE,
            8,
            9,
            (
                TableShape(1, 1, 59, 59, 43, 43, "observed"),
                TableShape(2, 1, 65, 65, 11, 11, "observed"),
                TableShape(3, 1, 73, 73, 20, 20, "observed"),
                TableShape(4, 1, 28, 28, 12, 12, "observed"),
                TableShape(5, 1, 72, 72, 24, 24, "observed"),
                TableShape(6, 1, 48, 48, 26, 26, "observed"),
                TableShape(6, 2, 23, 23, 12, 12, "observed"),
                TableShape(7, 1, 64, 64, 26, 26, "observed"),
                TableShape(8, 1, 46, 46, 29, 29, "observed"),
            ),
        ),
        (
            WRLDC_2025_REVISED_TEMPLATE,
            9,
            10,
            (
                TableShape(1, 1, 62, 62, 43, 43, "observed"),
                TableShape(2, 1, 65, 65, 11, 11, "observed"),
                TableShape(3, 1, 73, 73, 20, 20, "observed"),
                TableShape(4, 1, 29, 29, 12, 12, "observed"),
                TableShape(5, 1, 73, 73, 20, 20, "observed"),
                TableShape(6, 1, 61, 61, 32, 32, "observed"),
                TableShape(6, 2, 9, 9, 12, 12, "observed"),
                TableShape(7, 1, 55, 55, 20, 20, "observed"),
                TableShape(8, 1, 61, 61, 39, 39, "observed"),
                TableShape(9, 1, 15, 15, 9, 9, "observed"),
            ),
        ),
        (
            WRLDC_2024_TRANSITION_TEMPLATE,
            8,
            9,
            (
                TableShape(1, 1, 62, 62, 43, 43, "observed"),
                TableShape(2, 1, 65, 65, 11, 11, "observed"),
                TableShape(3, 1, 73, 73, 20, 20, "observed"),
                TableShape(4, 1, 28, 28, 12, 12, "observed"),
                TableShape(5, 1, 72, 72, 23, 23, "observed"),
                TableShape(6, 1, 48, 48, 26, 26, "observed"),
                TableShape(6, 2, 23, 23, 12, 12, "observed"),
                TableShape(7, 1, 54, 54, 20, 20, "observed"),
                TableShape(8, 1, 56, 56, 35, 35, "observed"),
            ),
        ),
        (
            WRLDC_2026_TEMPLATE,
            9,
            10,
            (
                TableShape(1, 1, 62, 62, 43, 43, "observed"),
                TableShape(2, 1, 65, 65, 11, 11, "observed"),
                TableShape(3, 1, 73, 73, 20, 20, "observed"),
                TableShape(4, 1, 29, 29, 12, 12, "observed"),
                TableShape(5, 1, 73, 73, 12, 12, "observed"),
                TableShape(6, 1, 72, 72, 23, 23, "observed"),
                TableShape(7, 1, 39, 39, 26, 26, "observed"),
                TableShape(7, 2, 32, 32, 12, 12, "observed"),
                TableShape(8, 1, 57, 57, 26, 26, "observed"),
                TableShape(9, 1, 49, 49, 29, 29, "observed"),
            ),
        ),
        (
            WRLDC_2026_EARLY_TEMPLATE,
            9,
            10,
            (
                TableShape(1, 1, 62, 62, 43, 43, "observed"),
                TableShape(2, 1, 65, 65, 11, 11, "observed"),
                TableShape(3, 1, 73, 73, 20, 20, "observed"),
                TableShape(4, 1, 29, 29, 12, 12, "observed"),
                TableShape(5, 1, 73, 73, 12, 12, "observed"),
                TableShape(6, 1, 73, 73, 23, 23, "observed"),
                TableShape(7, 1, 12, 12, 25, 25, "observed"),
                TableShape(7, 2, 50, 50, 12, 12, "observed"),
                TableShape(8, 1, 64, 64, 30, 30, "observed"),
                TableShape(9, 1, 31, 31, 17, 17, "observed"),
            ),
        ),
    )
    for template, page_count, table_count, shapes in cases:
        structure = ReportStructure(
            page_count=page_count,
            table_count=table_count,
            headings=template.required_headings,
            table_shapes=shapes,
        )

        result = match_report_template("wrldc", structure)

        assert result.template_id == template.template_id
        assert result.confidence == 1.0
        assert result.semantic_pass_required is False
        assert infer_structural_family("wrldc", structure) == WRLDC_STANDARD_FAMILY_ID


def test_erldc_templates_preserve_observed_flat_and_split_geometries() -> None:
    """Recognize local ERLDC report layouts without relying on report dates."""

    cases = (
        (
            ERLDC_2023_TEMPLATE,
            6,
            10,
            (
                TableShape(1, 1, 49, 49, 15, 15, "observed"),
                TableShape(1, 2, 9, 9, 5, 5, "observed"),
                TableShape(2, 1, 65, 65, 9, 9, "observed"),
                TableShape(3, 1, 72, 72, 13, 13, "observed"),
                TableShape(4, 1, 67, 67, 12, 12, "observed"),
                TableShape(5, 1, 56, 56, 17, 17, "observed"),
                TableShape(6, 1, 23, 23, 11, 11, "observed"),
            ),
        ),
        (
            ERLDC_2024_FLAT_TEMPLATE,
            7,
            10,
            (
                TableShape(1, 1, 61, 61, 18, 18, "observed"),
                TableShape(2, 1, 73, 73, 9, 9, "observed"),
                TableShape(3, 1, 71, 71, 13, 13, "observed"),
                TableShape(4, 1, 63, 63, 16, 16, "observed"),
                TableShape(5, 1, 49, 49, 27, 27, "observed"),
                TableShape(6, 1, 57, 57, 40, 40, "observed"),
                TableShape(7, 1, 11, 11, 11, 11, "observed"),
            ),
        ),
        (
            ERLDC_2024_SPLIT_TEMPLATE,
            11,
            40,
            (
                TableShape(1, 1, 3, 3, 10, 10, "observed"),
                TableShape(1, 2, 10, 10, 15, 15, "observed"),
                TableShape(2, 2, 11, 11, 11, 11, "observed"),
                TableShape(3, 2, 24, 24, 11, 11, "observed"),
                TableShape(5, 1, 39, 39, 12, 12, "observed"),
                TableShape(6, 3, 20, 20, 9, 9, "observed"),
                TableShape(8, 5, 17, 17, 8, 8, "observed"),
                TableShape(9, 2, 10, 10, 14, 14, "observed"),
                TableShape(11, 2, 9, 9, 11, 11, "observed"),
            ),
        ),
        (
            ERLDC_2025_SPLIT_TEMPLATE,
            7,
            33,
            (
                TableShape(1, 1, 3, 3, 10, 10, "observed"),
                TableShape(1, 2, 10, 10, 15, 15, "observed"),
                TableShape(1, 4, 10, 10, 7, 7, "observed"),
                TableShape(2, 2, 16, 16, 11, 11, "observed"),
                TableShape(3, 2, 63, 63, 12, 12, "observed"),
                TableShape(4, 3, 46, 46, 9, 9, "observed"),
                TableShape(5, 5, 17, 17, 8, 8, "observed"),
                TableShape(6, 2, 10, 10, 9, 9, "observed"),
            ),
        ),
        (
            ERLDC_2025_FLAT_TEMPLATE,
            7,
            10,
            (
                TableShape(1, 1, 61, 61, 23, 23, "observed"),
                TableShape(2, 1, 72, 72, 11, 11, "observed"),
                TableShape(3, 1, 71, 71, 21, 21, "observed"),
                TableShape(4, 1, 70, 70, 25, 25, "observed"),
                TableShape(5, 1, 51, 51, 32, 32, "observed"),
                TableShape(6, 1, 57, 57, 40, 40, "observed"),
                TableShape(7, 1, 11, 11, 11, 11, "observed"),
            ),
        ),
    )

    for template, page_count, table_count, shapes in cases:
        structure = ReportStructure(
            page_count=page_count,
            table_count=table_count,
            headings=template.required_headings,
            table_shapes=shapes,
        )

        result = match_report_template("erldc", structure)

        assert result.template_id == template.template_id
        assert result.confidence == 1.0
        assert result.semantic_pass_required is False
        assert infer_structural_family("erldc", structure) == ERLDC_STANDARD_FAMILY_ID


def test_erldc_unknown_geometry_remains_gated_for_semantic_review() -> None:
    """Avoid assigning a near-match template to an unverified ERLDC layout."""

    structure = ReportStructure(page_count=10, table_count=41, headings=(), table_shapes=())

    result = match_report_template("erldc", structure)

    assert result.template_id is None
    assert result.semantic_pass_required is True
    assert result.reasons == ("no_template_match",)


@pytest.mark.parametrize(
    ("filename", "template_id"),
    (
        ("NER-PSP-REPORT-DATED-01-04-2023.pdf", "nerldc_daily_psp_v2023_standard_09_column_generation"),
        ("NER-PSP-REPORT-DATED-01-01-2024.pdf", "nerldc_daily_psp_v2024_standard_09_column_generation"),
        ("NER-PSP-REPORT-DATED-01-01-2025.pdf", "nerldc_daily_psp_v2025_standard_10_column_generation"),
        ("NER-PSP-REPORT-DATED-01-01-2026.pdf", "nerldc_daily_psp_v2026_standard_09_column_generation"),
    ),
)
def test_nerldc_local_fixtures_match_yearly_template_contracts(
    filename: str,
    template_id: str,
) -> None:
    """Known NERLDC fixtures select their conservative discovery template."""
    fixture = Path("downloads/NERLDC_PSP") / filename
    if not fixture.exists():
        pytest.skip(f"local NERLDC fixture missing: {fixture}")

    structure = inspect_report_structure(fixture)
    result = match_report_template("nerldc", structure)

    assert result.template_id == template_id
    assert result.semantic_pass_required is False
    assert infer_structural_family("nerldc", structure) == NERLDC_STANDARD_FAMILY_ID


@pytest.mark.integration
def test_liteparse_fallback_requires_native_extraction_failure() -> None:
    """Do not invoke LiteParse merely because a template needs semantic review."""

    assert not _should_try_liteparse(
        True,
        None,
        {"field": 1.0},
        "x" * 1200,
        [object()],
    )
    assert _should_try_liteparse(True, None, {}, "x" * 1200, [object()])
    assert _should_try_liteparse(True, None, {"field": 1.0}, "x" * 1200, [])


def test_liteparse_accepts_current_snake_case_spatial_items(monkeypatch) -> None:
    """LiteParse 2.x spatial JSON remains consumable by the local parser."""

    def fake_run(*_args, **_kwargs):
        return {
            "pages": [
                {
                    "page": 6,
                    "text": "IPP/JV",
                    "text_items": [
                        {
                            "text": "TEST STATION",
                            "x": 15.0,
                            "y": 42.0,
                            "width": 40.0,
                            "height": 8.0,
                            "confidence": 1.0,
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr("psp_pipeline.pipelines.rldc_daily_psp._run_liteparse", fake_run)
    text, items = _extract_liteparse_content(Path("fixture.pdf"))

    assert text == "IPP/JV"
    assert len(items) == 1
    assert items[0].text == "TEST STATION"
    assert items[0].page_no == 6
    assert items[0].x == 15.0


def test_erldc_extrema_fallback_requests_page_six_spatial_items(monkeypatch) -> None:
    """A collapsed Section 8(B) grid must not be skipped before LiteParse."""

    cells = [
        RawCell(6, 1, 1, 1, "8(B). Short Term Open Access", "pdfplumber"),
        RawCell(
            6,
            1,
            2,
            1,
            "WEST BENGAL\n0 0 0 0 0 0 0 0 255.99 -991.28",
            "pdfplumber",
        ),
    ]
    calls: list[object] = []
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp.inspect_report_structure",
        lambda _path: object(),
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp.match_report_template",
        lambda _rldc, _structure: object(),
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._extract_pdfplumber_raw",
        lambda _path: ("native text" * 200, [], cells),
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._extract_numeric_fields",
        lambda _text: {},
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._extract_table_fallback_fields",
        lambda _cells: {},
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._liteparse_available",
        lambda: True,
    )

    def fake_liteparse(_path, *, target_pages=None, **_kwargs):
        calls.append(target_pages)
        return "spatial text", [RawTextItem(6, 1, "WEST BENGAL", 1, 1, 1, 1, 1, "liteparse")]

    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._extract_liteparse_content",
        fake_liteparse,
    )

    parsed = extract_psp_content(Path("fixture.pdf"), "erldc")

    assert _spatial_fallback_reasons("erldc", cells) == ("erldc_market_extrema",)
    assert calls == ["6"]
    assert parsed.raw_text_items[0].extraction_method == "liteparse"


def test_erldc_extrema_fallback_requests_non_page_six_spatial_items(monkeypatch) -> None:
    """Collapsed Section 8(B) rows on a later page still request LiteParse."""

    cells = [
        RawCell(7, 1, 1, 1, "8(B). Short Term Open Access", "pdfplumber"),
        RawCell(
            7,
            1,
            2,
            1,
            "WEST BENGAL\n0 0 0 0 0 0 0 0 255.99 -991.28",
            "pdfplumber",
        ),
    ]
    calls: list[object] = []
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp.inspect_report_structure",
        lambda _path: object(),
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp.match_report_template",
        lambda _rldc, _structure: object(),
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._extract_pdfplumber_raw",
        lambda _path: ("native text" * 200, [], cells),
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._extract_numeric_fields",
        lambda _text: {},
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._extract_table_fallback_fields",
        lambda _cells: {},
    )
    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._liteparse_available",
        lambda: True,
    )

    def fake_liteparse(_path, *, target_pages=None, **_kwargs):
        calls.append(target_pages)
        return "spatial text", [RawTextItem(7, 1, "WEST BENGAL", 1, 1, 1, 1, 1, "liteparse")]

    monkeypatch.setattr(
        "psp_pipeline.pipelines.rldc_daily_psp._extract_liteparse_content",
        fake_liteparse,
    )

    parsed = extract_psp_content(Path("fixture.pdf"), "erldc")

    assert _spatial_fallback_reasons("erldc", cells) == ("erldc_market_extrema",)
    assert calls == ["7"]
    assert parsed.raw_text_items[0].page_no == 7


def test_liteparse_extracts_spatial_items_for_rect_heavy_srldc_fixture() -> None:
    """Verify the local LiteParse fallback on the known rect-heavy SRLDC report.

    This intentionally runs only when ``PSP_RUN_LITEPARSE_INTEGRATION=1`` is
    set because it invokes the local Node.js CLI and may need an npm cache.
    """

    if os.environ.get("PSP_RUN_LITEPARSE_INTEGRATION") != "1":
        pytest.skip("set PSP_RUN_LITEPARSE_INTEGRATION=1 to invoke LiteParse")

    project_root = Path(__file__).resolve().parents[1]
    fixture = project_root / "downloads" / "SRLDC_PSP" / "01-10-2023-psp.pdf"
    assert fixture.exists(), f"missing LiteParse fixture: {fixture}"

    started_at = monotonic()
    text, text_items = _extract_liteparse_content(
        fixture,
        target_pages="1",
        timeout_seconds=30,
    )
    elapsed_seconds = monotonic() - started_at

    assert text.strip()
    assert text_items
    assert any(
        item.x is not None
        and item.y is not None
        and item.width is not None
        and item.height is not None
        for item in text_items
    )
    assert elapsed_seconds < 30
