"""96-block calendar and revision-label helpers."""

from datetime import date

import pytest

from psp_pipeline.wbes.blocks import (
    DEFAULT_BLOCK_COUNT,
    FIVE_MINUTE_BLOCK_COUNT,
    IST,
    iter_schedule_blocks,
    require_standard_blocks,
)
from psp_pipeline.wbes.models import FINAL_REVISION_VERSION, parse_revision_label


def test_standard_day_has_96_ist_blocks() -> None:
    blocks = iter_schedule_blocks(date(2026, 9, 1))
    assert len(blocks) == DEFAULT_BLOCK_COUNT
    assert blocks[0].block_no == 1
    assert blocks[0].start_clock == "00:00"
    assert blocks[0].valid_from.tzinfo == IST
    assert blocks[-1].block_no == 96
    assert blocks[-1].start_clock == "23:45"
    assert (blocks[-1].valid_to - blocks[0].valid_from).total_seconds() == 24 * 60 * 60


def test_five_minute_generator_exists_but_pipeline_rejects_it_by_default() -> None:
    blocks = iter_schedule_blocks(
        date(2026, 9, 1),
        block_count=FIVE_MINUTE_BLOCK_COUNT,
        minutes=5,
    )
    assert len(blocks) == 288
    with pytest.raises(ValueError, match="96 15-minute"):
        require_standard_blocks(block_count=288, minutes=5, allow_five_minute=False)
    require_standard_blocks(block_count=288, minutes=5, allow_five_minute=True)


def test_revision_labels_map_to_sortable_versions() -> None:
    assert parse_revision_label("R0") == ("R0", 0)
    assert parse_revision_label("R12") == ("R12", 12)
    assert parse_revision_label("R_final") == ("Rfinal", FINAL_REVISION_VERSION)
