"""Enforce explicit raw-cell coverage floors for replayable PSP fixtures."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from psp_pipeline.quality.raw_cell_coverage import generate_raw_cell_coverage_report


@dataclass(frozen=True)
class CoverageProfileResult:
    """One named coverage-profile evaluation against a curated SQLite replay."""

    profile_name: str
    required: bool
    floors: dict[str, float]
    actual: dict[str, float]
    missing_sources: tuple[str, ...]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether present sources met floors and required sources existed."""

        return not self.failures and not self.missing_sources

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready coverage evaluation for replay and DAG XCom."""

        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


def default_coverage_manifest_path() -> Path:
    """Return the committed two-tier coverage manifest path."""

    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "manifest.json"


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


def evaluate_coverage_floors(
    db_path: Path | str,
    floors: Mapping[str, float],
    *,
    profile_name: str = "adhoc",
    required: bool = True,
    require_sources: Iterable[str] | None = None,
) -> CoverageProfileResult:
    """Compare accounted-cell percentages against approved source floors.

    Sources without raw cells are omitted from ``actual`` unless they are listed
    in ``require_sources``. That distinction keeps bounded synthetic fixtures
    useful while letting full-corpus replays fail closed when a source vanishes.
    """

    required_sources = {str(source) for source in (require_sources or ())}
    actual: dict[str, float] = {}
    failures: list[str] = []
    missing: list[str] = []
    for source, floor in sorted(floors.items()):
        report = generate_raw_cell_coverage_report(db_path, rldc=source)
        if report["raw_nonempty_cell_count"] == 0:
            if source in required_sources:
                missing.append(source)
            continue
        value = float(report["accounted_cell_pct"])
        actual[source] = value
        if value < float(floor):
            failures.append(f"{source}: {value:.2f}% < {float(floor):.2f}%")
    return CoverageProfileResult(
        profile_name=profile_name,
        required=required,
        floors={key: float(value) for key, value in floors.items()},
        actual=actual,
        missing_sources=tuple(missing),
        failures=tuple(failures),
    )


def assert_coverage_floors(
    db_path: Path | str,
    floors: Mapping[str, float],
) -> dict[str, float]:
    """Assert that each source present in a replay meets its approved floor.

    Sources without raw cells are not interpreted as passing. Callers decide
    whether a fixture must contain every configured source before invoking this
    gate, which keeps bounded source fixtures useful and honest.
    """

    result = evaluate_coverage_floors(db_path, floors)
    _raise_if_failed(result)
    return result.actual


def evaluate_coverage_manifest(
    db_path: Path | str,
    manifest_path: Path | str | None = None,
    *,
    profile_name: str | None = None,
    require_sources: Iterable[str] | None = None,
    only_required: bool = False,
) -> dict[str, CoverageProfileResult]:
    """Evaluate one or more coverage profiles declared in the committed manifest."""

    manifest = load_coverage_manifest(manifest_path or default_coverage_manifest_path())
    selected = _selected_profiles(manifest, profile_name, only_required)
    return {
        name: evaluate_coverage_floors(
            db_path,
            profile["coverage_floors"],
            profile_name=name,
            required=bool(profile.get("required")),
            require_sources=require_sources,
        )
        for name, profile in selected.items()
    }


def enforce_coverage_manifest(
    db_path: Path | str,
    manifest_path: Path | str | None = None,
    *,
    profile_name: str | None = None,
    require_sources: Iterable[str] | None = None,
    only_required: bool = False,
) -> dict[str, CoverageProfileResult]:
    """Fail when a selected coverage profile regresses below its approved floor.

    ``only_required`` is the CI default: the synthetic profile must pass, while
    the corpus profile remains opt-in until checksum-pinned PDFs are present.
    Passing ``profile_name`` enforces that profile even when it is optional.
    """

    results = evaluate_coverage_manifest(
        db_path,
        manifest_path,
        profile_name=profile_name,
        require_sources=require_sources,
        only_required=only_required,
    )
    for result in results.values():
        _raise_if_failed(result)
    return results


def _selected_profiles(
    manifest: Mapping[str, Any],
    profile_name: str | None,
    only_required: bool,
) -> dict[str, dict[str, Any]]:
    """Return the manifest profiles that this evaluation should apply."""

    profiles = manifest["profiles"]
    if profile_name is not None:
        if profile_name not in profiles:
            raise ValueError(f"Unknown coverage profile {profile_name!r}")
        return {profile_name: profiles[profile_name]}
    if only_required:
        selected = {
            name: profile
            for name, profile in profiles.items()
            if profile.get("required")
        }
        if not selected:
            raise ValueError("Coverage manifest has no required profiles")
        return selected
    return dict(profiles)


def _raise_if_failed(result: CoverageProfileResult) -> None:
    """Raise a compact assertion when a profile missed floors or sources."""

    problems = list(result.failures)
    if result.missing_sources:
        problems.append("missing sources: " + ", ".join(result.missing_sources))
    if problems:
        raise AssertionError(
            f"Raw-cell coverage floors failed for {result.profile_name}: "
            + "; ".join(problems)
        )
