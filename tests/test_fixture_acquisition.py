"""Tests for checksum-pinned external corpus fixture declarations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from psp_pipeline.quality.fixture_acquisition import load_fixture_artifacts


def test_default_fixture_manifest_requires_no_unverified_network_downloads() -> None:
    """The committed baseline does not invent public corpus artifacts."""

    manifest = Path(__file__).parent / "fixtures" / "manifest.json"
    assert load_fixture_artifacts(manifest) == ()


def test_fixture_manifest_rejects_non_https_or_unpinned_artifacts(tmp_path: Path) -> None:
    """Corpus reports must be declared with an immutable transport contract."""

    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "id": "bad",
                        "source_url": "http://example.test/report.pdf",
                        "sha256": "a" * 64,
                        "filename": "report.pdf",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="HTTPS"):
        load_fixture_artifacts(path)
