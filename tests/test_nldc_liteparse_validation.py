"""Optional LiteParse spatial validation for the NLDC parser fixture."""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

import pytest

from psp_pipeline.pipelines.rldc_daily_psp import _extract_liteparse_content


@pytest.mark.integration
def test_nldc_liteparse_spatial_validation() -> None:
    """Validate page-two spatial text without replacing deterministic parsing.

    The Node.js invocation is opt-in because it can populate an npm cache. The
    normal NLDC promoter remains based on persisted pdfplumber raw cells.
    """

    if os.environ.get("PSP_RUN_LITEPARSE_INTEGRATION") != "1":
        pytest.skip("set PSP_RUN_LITEPARSE_INTEGRATION=1 to invoke LiteParse")
    fixture = Path("downloads/NLDC_PSP/25-08-2026-nldc-psp.pdf")
    if not fixture.exists():
        pytest.skip(f"Fixture {fixture} not found")

    started_at = monotonic()
    text, items = _extract_liteparse_content(
        fixture,
        target_pages="2",
        timeout_seconds=60,
    )

    assert "Power Supply Position" in text
    assert items
    assert any(
        item.x is not None
        and item.y is not None
        and item.width is not None
        and item.height is not None
        for item in items
    )
    assert monotonic() - started_at < 60
