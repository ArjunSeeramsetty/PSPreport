"""Fetch checksum-pinned PSP corpus fixtures declared in a manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from psp_pipeline.quality.fixture_acquisition import fetch_checksum_pinned_fixtures


def main() -> int:
    """Fetch approved regression artifacts and print their local paths."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/manifest.json"),
    )
    parser.add_argument("--destination", type=Path, default=Path("downloads/fixtures"))
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    for path in fetch_checksum_pinned_fixtures(
        args.manifest,
        args.destination,
        timeout_seconds=args.timeout_seconds,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
