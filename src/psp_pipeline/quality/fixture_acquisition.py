"""Acquire checksum-pinned PSP regression fixtures without trusting live state."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from urllib.request import urlopen


@dataclass(frozen=True)
class FixtureArtifact:
    """One externally stored, checksum-pinned PSP regression artifact."""

    fixture_id: str
    source_url: str
    sha256: str
    filename: str


def load_fixture_artifacts(manifest_path: Path | str) -> tuple[FixtureArtifact, ...]:
    """Load real-corpus artifacts declared in a coverage manifest.

    Raises:
        ValueError: If an artifact lacks an HTTPS URL, SHA-256, or safe name.
    """

    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    artifacts = payload.get("fixtures", [])
    if not isinstance(artifacts, list):
        raise ValueError("Fixture manifest field 'fixtures' must be a list")
    parsed: list[FixtureArtifact] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise ValueError("Fixture entries must be objects")
        fixture = FixtureArtifact(
            fixture_id=str(item.get("id", "")),
            source_url=str(item.get("source_url", "")),
            sha256=str(item.get("sha256", "")).lower(),
            filename=str(item.get("filename", "")),
        )
        _validate_fixture(fixture)
        parsed.append(fixture)
    return tuple(parsed)


def hash_local_fixtures(
    artifacts: Iterable[tuple[str, Path | str]],
) -> tuple[dict[str, str], ...]:
    """Return SHA-256 pins for local corpus files that already exist.

    Missing files are omitted rather than invented. This lets replay runners
    record an evidence manifest without requiring a public download URL.
    """

    pins: list[dict[str, str]] = []
    for fixture_id, raw_path in artifacts:
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            continue
        pins.append(
            {
                "id": fixture_id,
                "filename": path.name,
                "path": str(path),
                "sha256": _sha256(path),
            }
        )
    return tuple(pins)


def srldc_public_fixture_entry(report_date: date, sha256: str) -> dict[str, str]:
    """Return one checksum-pinned SRLDC corpus fixture for a public PDF URL.

    The URL is constructed deterministically. Callers must supply a SHA-256
    measured from bytes they actually downloaded; this helper never invents a
    digest.
    """

    from psp_pipeline.acquisition.downloaders.srldc import (
        srldc_psp_filename,
        srldc_psp_url,
    )

    return {
        "id": f"srldc-{report_date.isoformat()}",
        "source_url": srldc_psp_url(report_date),
        "sha256": sha256.lower(),
        "filename": srldc_psp_filename(report_date),
    }


def fetch_checksum_pinned_fixtures(
    manifest_path: Path | str,
    destination_dir: Path | str,
    *,
    timeout_seconds: float = 30.0,
) -> tuple[Path, ...]:
    """Fetch declared fixtures and reject bytes that miss their SHA-256.

    Existing matching files are reused. A mismatching local file is never
    overwritten, avoiding accidental replacement of a recorded corpus sample.
    """

    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    resolved: list[Path] = []
    for fixture in load_fixture_artifacts(manifest_path):
        target = destination / fixture.filename
        if target.exists():
            if _sha256(target) != fixture.sha256:
                raise ValueError(f"Existing fixture checksum mismatch: {target}")
            resolved.append(target)
            continue
        with urlopen(fixture.source_url, timeout=timeout_seconds) as response:
            payload = response.read()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != fixture.sha256:
            raise ValueError(f"Downloaded fixture checksum mismatch: {fixture.fixture_id}")
        target.write_bytes(payload)
        resolved.append(target)
    return tuple(resolved)


def _validate_fixture(fixture: FixtureArtifact) -> None:
    """Reject unsafe or unverifiable fixture declarations."""

    if not fixture.fixture_id:
        raise ValueError("Fixture entries require id")
    if urlparse(fixture.source_url).scheme != "https":
        raise ValueError(f"Fixture {fixture.fixture_id} must use HTTPS")
    if len(fixture.sha256) != 64 or any(
        character not in "0123456789abcdef" for character in fixture.sha256
    ):
        raise ValueError(f"Fixture {fixture.fixture_id} requires SHA-256")
    if not fixture.filename or Path(fixture.filename).name != fixture.filename:
        raise ValueError(f"Fixture {fixture.fixture_id} has unsafe filename")


def _sha256(path: Path) -> str:
    """Return a local file SHA-256 without loading large reports into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
