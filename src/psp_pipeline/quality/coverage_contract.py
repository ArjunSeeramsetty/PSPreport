"""Enforce explicit raw-cell coverage floors for replayable PSP fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from psp_pipeline.quality.raw_cell_coverage import generate_raw_cell_coverage_report


def load_coverage_manifest(path: Path | str) -> dict[str, Any]:
    """Load and minimally validate a coverage manifest.

    The manifest separates always-available synthetic contracts from optional
    checksum-pinned corpus checks. It intentionally stores no report content;
    public PDFs remain local artifacts or controlled downloads.

    Raises:
        ValueError: If the manifest lacks a usable version or coverage profile.
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Coverage manifest must declare version 1")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("Coverage manifest must declare at least one profile")
    for name, profile in profiles.items():
        if not isinstance(profile, dict) or not isinstance(
            profile.get("coverage_floors"), dict
        ):
            raise ValueError(f"Coverage profile {name!r} lacks coverage_floors")
    return payload


def assert_coverage_floors(
    db_path: Path | str,
    floors: Mapping[str, float],
) -> dict[str, float]:
    """Assert that each source present in a replay meets its approved floor.

    Sources without raw cells are not interpreted as passing. Callers decide
    whether a fixture must contain every configured source before invoking this
    gate, which keeps bounded source fixtures useful and honest.
    """

    results: dict[str, float] = {}
    failures: list[str] = []
    for source, floor in sorted(floors.items()):
        report = generate_raw_cell_coverage_report(db_path, rldc=source)
        if report["raw_nonempty_cell_count"] == 0:
            continue
        actual = float(report["accounted_cell_pct"])
        results[source] = actual
        if actual < float(floor):
            failures.append(f"{source}: {actual:.2f}% < {float(floor):.2f}%")
    if failures:
        raise AssertionError("Raw-cell coverage floors failed: " + "; ".join(failures))
    return results
