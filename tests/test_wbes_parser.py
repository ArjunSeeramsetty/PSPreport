"""Canonical JSON and XLSX parsers for synthetic WBES drop files."""

from pathlib import Path

import pytest

from psp_pipeline.wbes.parser import WbesParseError, parse_wbes_path
from wbes_support import synthetic_document, write_json, write_xlsx


def test_json_parser_accepts_96_block_canonical_document(tmp_path: Path) -> None:
    path = write_json(tmp_path / "r0.json", synthetic_document())
    document = parse_wbes_path(
        path,
        source_id="wbes_national",
        source_region="WR",
        block_count=96,
        block_minutes=15,
        allow_five_minute=False,
    )
    assert document.revision_label == "R0"
    assert document.block_count == 96
    assert len(document.matrices) == 6
    assert len(document.matrices[0].rows[0].values_mw) == 96
    assert document.content_hash


def test_json_parser_rejects_wrong_block_count(tmp_path: Path) -> None:
    payload = synthetic_document()
    payload["matrices"][0]["rows"][0]["values_mw"] = [1.0, 2.0]
    path = write_json(tmp_path / "bad.json", payload)
    with pytest.raises(WbesParseError, match="expected 96"):
        parse_wbes_path(
            path,
            source_id="wbes_national",
            source_region="WR",
            block_count=96,
            block_minutes=15,
            allow_five_minute=False,
        )


def test_entitlement_requires_counterparty(tmp_path: Path) -> None:
    payload = synthetic_document()
    payload["matrices"][0]["rows"][0]["counterparty_id"] = None
    path = write_json(tmp_path / "pair.json", payload)
    with pytest.raises(WbesParseError, match="counterparty_id"):
        parse_wbes_path(
            path,
            source_id="wbes_national",
            source_region="WR",
            block_count=96,
            block_minutes=15,
            allow_five_minute=False,
        )


def test_xlsx_parser_reads_wide_block_columns(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "r0.xlsx", synthetic_document())
    document = parse_wbes_path(
        path,
        source_id="wbes_national",
        source_region="WR",
        block_count=96,
        block_minutes=15,
        allow_five_minute=False,
    )
    assert document.schedule_date.isoformat() == "2026-09-01"
    entitlement = next(matrix for matrix in document.matrices if matrix.kind.value == "entitlement")
    assert len(entitlement.rows) == 2
    assert len(entitlement.rows[0].values_mw) == 96
