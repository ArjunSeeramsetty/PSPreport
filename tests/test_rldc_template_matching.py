from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import (
    _extract_liteparse_content,
    _should_try_liteparse,
)
from psp_pipeline.parsing.rldc.templates import (
    COMPACT_SRLDCP_TEMPLATE,
    DEFAULT_SRLDCP_TEMPLATE,
    FLAT_8_SRLDCP_TEMPLATE,
    FLAT_8_2025_SRLDCP_TEMPLATE,
    FLAT_6_2023_SRLDCP_TEMPLATE,
    FLAT_6_2024_SRLDCP_TEMPLATE,
    FLAT_7_2023_SRLDCP_TEMPLATE,
    NRLDC_2024_TEMPLATE,
    NRLDC_2025_TEMPLATE,
    NRLDC_2026_TEMPLATE,
    NRLDC_STANDARD_FAMILY_ID,
    ReportStructure,
    SRLDC_FLAT_FAMILY_ID,
    SRLDC_SPLIT_FAMILY_ID,
    TableShape,
    infer_structural_family,
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

    result = match_report_template("wrldc", structure)

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
