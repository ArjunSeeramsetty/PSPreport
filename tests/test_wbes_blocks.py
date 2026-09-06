"""Tests for isolated WBES 96-block schedule matrix helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from psp_pipeline.storage.timescale_bootstrap import (
    default_greenfield_schema_path,
    split_sql_statements,
)
from psp_pipeline.storage.wbes_blocks import (
    ADD_WBES_HASH_DIMENSION_SQL,
    BITEMPORAL_WBES_UPSERT_SQL,
    CREATE_WBES_HYPERTABLE_SQL,
    WBES_BLOCKS_PER_DAY,
    WbesBlockError,
    block_window,
    validate_daily_blocks,
    wbes_schema_statements,
)


def test_greenfield_schema_declares_wbes_hash_partitioning() -> None:
    """The WBES hypertable is present but not part of public PSP readiness."""

    script = default_greenfield_schema_path().read_text(encoding="utf-8")
    assert "fact_wbes_block" in script
    assert "by_range('valid_from', INTERVAL '7 days')" in script
    assert "by_hash('grain_key', 4)" in script
    statements = split_sql_statements(script)
    assert any("create_hypertable" in item.lower() and "fact_wbes_block" in item for item in statements)


def test_wbes_schema_statements_match_the_isolated_ddl() -> None:
    """Python helpers stay aligned with the migration SQL."""

    statements = wbes_schema_statements()
    assert CREATE_WBES_HYPERTABLE_SQL.strip() in statements
    assert ADD_WBES_HASH_DIMENSION_SQL.strip() in statements


def test_block_window_is_fifteen_minutes() -> None:
    """Block 1 is 00:00-00:15 UTC; block 96 ends at the next midnight."""

    day = datetime(2026, 4, 1, tzinfo=timezone.utc)
    start, end = block_window(day, 1)
    assert start.isoformat() == "2026-04-01T00:00:00+00:00"
    assert end.isoformat() == "2026-04-01T00:15:00+00:00"
    last_start, last_end = block_window(day, WBES_BLOCKS_PER_DAY)
    assert last_start.isoformat() == "2026-04-01T23:45:00+00:00"
    assert last_end.isoformat() == "2026-04-02T00:00:00+00:00"


def test_validate_daily_blocks_rejects_duplicates_and_out_of_range() -> None:
    """The 96-block grain is fail-closed."""

    assert validate_daily_blocks([{"block_no": 1}, {"block_no": 2}]) == (1, 2)
    with pytest.raises(WbesBlockError, match="outside"):
        validate_daily_blocks([{"block_no": 97}])
    with pytest.raises(WbesBlockError, match="duplicate"):
        validate_daily_blocks([{"block_no": 1}, {"block_no": 1}])


def test_bitemporal_upsert_closes_infinity_not_null() -> None:
    """WBES revisions must match the existing Timescale sys_to='infinity' convention."""

    assert "sys_to = 'infinity'" in BITEMPORAL_WBES_UPSERT_SQL
    assert "sys_to IS NULL" not in BITEMPORAL_WBES_UPSERT_SQL
    assert "apoc." not in BITEMPORAL_WBES_UPSERT_SQL.lower()
