from __future__ import annotations

from pathlib import Path

from psp_pipeline.parsing.rldc.templates import TemplateMatch
from psp_pipeline.schema_design.models import ReportStructureFingerprint
from psp_pipeline.schema_design.service import (
    TemplateInventoryRecord,
    _infer_report_date,
    _select_representatives,
    cluster_template_inventory,
    select_monthly_anchor_paths,
    summarize_template_inventory,
)


def test_representative_selection_spans_cluster_history() -> None:
    paths = [Path(f"report-{index:02d}.pdf") for index in range(9)]

    selected = _select_representatives(paths, 3)

    assert selected == (paths[0], paths[4], paths[8])


import pytest


@pytest.mark.parametrize(
    ("filename", "source_id", "expected_date"),
    [
        # SRLDC cases
        ("01-02-2026-psp.pdf", "srldc", "2026-02-01"),
        ("15-05-2024-psp.pdf", "srldc", "2024-05-15"),
        ("31-12-2023-psp.pdf", "srldc", "2023-12-31"),
        ("01-02-26-psp.pdf", "srldc", None),
        ("not-a-standard-name.pdf", "srldc", None),
        ("32-01-2024-psp.pdf", "srldc", None),
        # NRLDC cases
        ("daily010424.pdf", "nrldc", "2024-04-01"),
        ("daily15052026.pdf", "nrldc", "2026-05-15"),
        ("daily311225.pdf", "nrldc", "2025-12-31"),
        ("daily123.pdf", "nrldc", None),
        ("not_daily.pdf", "nrldc", None),
        # WRLDC cases
        ("WRLDC_PSP_Report_01-04-2023.pdf", "wrldc", "2023-04-01"),
        ("WRLDC_PSP_Report_15-11-2024.pdf", "wrldc", "2024-11-15"),
        ("wrldc_psp_report_31-12-2025.pdf", "wrldc", "2025-12-31"),
        ("WRLDC_PSP_Report_01-04-23.pdf", "wrldc", None),
        ("WRLDC_Tripping_01-04-2023.pdf", "wrldc", None),
        ("WRLDC_PSP_Report_32-01-2024.pdf", "wrldc", None),
        # ERLDC cases
        ("PSP_15-05-2024.pdf", "erldc", "2024-05-15"),
        ("psp_01-01-2025.pdf", "erldc", "2025-01-01"),
        ("PSP_15-05-24.pdf", "erldc", None),
        ("other_15-05-2024.pdf", "erldc", None),
        # NERLDC cases
        ("PSP_20-06-2024.pdf", "nerldc", "2024-06-20"),
        ("psp_01-10-2025.pdf", "nerldc", "2025-10-01"),
        ("PSP_20-06-24.pdf", "nerldc", None),
        ("tripping_20-06-2024.pdf", "nerldc", None),
    ],
)
def test_infer_report_date_across_all_rldcs(
    filename: str, source_id: str, expected_date: str | None
) -> None:
    assert _infer_report_date(Path(filename), source_id=source_id) == expected_date


def test_template_inventory_cluster_and_summary_are_stable() -> None:
    structure = ReportStructureFingerprint(
        source_id="srldc",
        fingerprint="fp-1",
        structural_family="srldc_daily_psp_split_sections",
        page_count=9,
        table_count=38,
        table_shapes=("p1:t1:c10",),
        normalized_headings=("regional availability demand",),
    )
    records = [
        TemplateInventoryRecord(
            pdf_path=Path("01-01-2026-psp.pdf"),
            report_date="2026-01-01",
            fingerprint="fp-1",
            structure=structure,
            template_match=TemplateMatch(
                "srldc_daily_psp_v2026_01", "2026.01", 1.0, False, ()
            ),
        ),
        TemplateInventoryRecord(
            pdf_path=Path("15-01-2026-psp.pdf"),
            report_date="2026-01-15",
            fingerprint="fp-1",
            structure=structure,
            template_match=TemplateMatch(
                "srldc_daily_psp_v2026_01", "2026.01", 0.98, False, ()
            ),
        ),
        TemplateInventoryRecord(
            pdf_path=Path("01-02-2026-psp.pdf"),
            report_date="2026-02-01",
            fingerprint="fp-2",
            structure=ReportStructureFingerprint(
                source_id="srldc",
                fingerprint="fp-2",
                structural_family="srldc_daily_psp_split_sections",
                page_count=10,
                table_count=41,
                table_shapes=("p1:t1:c10",),
                normalized_headings=("regional availability demand",),
            ),
            template_match=TemplateMatch(
                "srldc_daily_psp_v2026_05", "2026.05", 1.0, False, ()
            ),
        ),
    ]

    clusters = cluster_template_inventory(records)
    summary = summarize_template_inventory(records)

    assert len(clusters) == 2
    assert clusters[0].representative_paths == (
        Path("01-01-2026-psp.pdf"),
        Path("15-01-2026-psp.pdf"),
    )
    assert clusters[0].matched_template_ids == ("srldc_daily_psp_v2026_01",)
    assert summary == {
        "report_count": 3,
        "matched_report_count": 3,
        "semantic_pass_required_count": 0,
        "matched_pct": 100.0,
        "semantic_pass_required_pct": 0.0,
        "family_counts": {
            "srldc_daily_psp_split_sections": 3,
        },
        "template_counts": {
            "srldc_daily_psp_v2026_01": 2,
            "srldc_daily_psp_v2026_05": 1,
        },
    }


def test_select_monthly_anchor_paths_prefers_exact_fifteenth() -> None:
    paths = [
        Path("01-01-2026-psp.pdf"),
        Path("15-01-2026-psp.pdf"),
        Path("31-01-2026-psp.pdf"),
    ]

    samples = select_monthly_anchor_paths(paths)

    assert [(sample.anchor, sample.pdf_path.name, sample.exact_day_match) for sample in samples] == [
        ("first", "01-01-2026-psp.pdf", True),
        ("fifteenth", "15-01-2026-psp.pdf", True),
        ("last", "31-01-2026-psp.pdf", True),
    ]


def test_select_monthly_anchor_paths_falls_back_to_nearest_fifteenth() -> None:
    paths = [
        Path("01-02-2026-psp.pdf"),
        Path("14-02-2026-psp.pdf"),
        Path("28-02-2026-psp.pdf"),
    ]

    samples = select_monthly_anchor_paths(paths)

    assert [(sample.anchor, sample.pdf_path.name, sample.exact_day_match) for sample in samples] == [
        ("first", "01-02-2026-psp.pdf", True),
        ("fifteenth", "14-02-2026-psp.pdf", False),
        ("last", "28-02-2026-psp.pdf", True),
    ]
