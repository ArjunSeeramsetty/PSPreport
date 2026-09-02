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
    lineage_rate_floors: Mapping[str, float] | None = None,
    null_rate_ceilings: Mapping[str, float] | None = None,
    template_floors: Mapping[str, Mapping[str, float]] | None = None,
    table_floors: Mapping[str, Mapping[str, float]] | None = None,
) -> CoverageProfileResult:
    """Compare accounted-cell percentages against approved source floors.

    Sources without raw cells are omitted from ``actual`` unless they are listed
    in ``require_sources``. Optional lineage-rate floors and null-rate ceilings
    apply to the same present sources. Template and table floors are additive
    and fail closed when a named slice is present and below contract.
    """

    required_sources = {str(source) for source in (require_sources or ())}
    actual: dict[str, float] = {}
    failures: list[str] = []
    missing: list[str] = []
    reports: dict[str, dict[str, Any]] = {}
    for source, floor in sorted(floors.items()):
        report = generate_raw_cell_coverage_report(db_path, rldc=source)
        reports[source] = report
        if report["raw_nonempty_cell_count"] == 0:
            if source in required_sources:
                missing.append(source)
            continue
        value = float(report["accounted_cell_pct"])
        actual[source] = value
        if value < float(floor):
            failures.append(f"{source}: {value:.2f}% < {float(floor):.2f}%")
        lineage_floor = (lineage_rate_floors or {}).get(source)
        if lineage_floor is not None:
            lineage = float(report["lineage_rate_pct"])
            actual[f"{source}.lineage_rate_pct"] = lineage
            if lineage < float(lineage_floor):
                failures.append(
                    f"{source} lineage_rate_pct: {lineage:.2f}% < {float(lineage_floor):.2f}%"
                )
        null_ceiling = (null_rate_ceilings or {}).get(source)
        if null_ceiling is not None:
            null_rate = float(report["null_rate_pct"])
            actual[f"{source}.null_rate_pct"] = null_rate
            if null_rate > float(null_ceiling):
                failures.append(
                    f"{source} null_rate_pct: {null_rate:.2f}% > {float(null_ceiling):.2f}%"
                )
    _evaluate_named_slice_floors(
        reports,
        template_floors or {},
        slice_kind="template",
        actual=actual,
        failures=failures,
    )
    _evaluate_named_slice_floors(
        reports,
        table_floors or {},
        slice_kind="table",
        actual=actual,
        failures=failures,
    )
    declared_floors = {key: float(value) for key, value in floors.items()}
    for source, floor in (lineage_rate_floors or {}).items():
        declared_floors[f"{source}.lineage_rate_pct"] = float(floor)
    for source, ceiling in (null_rate_ceilings or {}).items():
        declared_floors[f"{source}.null_rate_pct_max"] = float(ceiling)
    return CoverageProfileResult(
        profile_name=profile_name,
        required=required,
        floors=declared_floors,
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
            lineage_rate_floors=profile.get("lineage_rate_floors"),
            null_rate_ceilings=profile.get("null_rate_ceilings"),
            template_floors=profile.get("template_floors"),
            table_floors=profile.get("table_floors"),
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


def _evaluate_named_slice_floors(
    reports: Mapping[str, Mapping[str, Any]],
    floors: Mapping[str, Mapping[str, float]],
    *,
    slice_kind: str,
    actual: dict[str, float],
    failures: list[str],
) -> None:
    """Apply optional per-template or per-table coverage contracts."""

    for slice_key, contract in floors.items():
        source, _, name = str(slice_key).partition("/")
        report = reports.get(source)
        if not report:
            continue
        slice_rows = report.get("templates" if slice_kind == "template" else "tables") or []
        match_key = "template_id" if slice_kind == "template" else "destination_table"
        matched = next(
            (row for row in slice_rows if str(row.get(match_key) or "") == name),
            None,
        )
        if matched is None:
            continue
        key_prefix = f"{source}/{name}"
        accounted = float(matched.get("accounted_cell_pct") or 0.0)
        actual[f"{key_prefix}.accounted_cell_pct"] = accounted
        min_accounted = contract.get("accounted_cell_pct")
        if min_accounted is not None and accounted < float(min_accounted):
            failures.append(
                f"{key_prefix} accounted_cell_pct: {accounted:.2f}% < {float(min_accounted):.2f}%"
            )
        lineage = float(matched.get("lineage_rate_pct") or 0.0)
        actual[f"{key_prefix}.lineage_rate_pct"] = lineage
        min_lineage = contract.get("lineage_rate_pct")
        if min_lineage is not None and lineage < float(min_lineage):
            failures.append(
                f"{key_prefix} lineage_rate_pct: {lineage:.2f}% < {float(min_lineage):.2f}%"
            )
        null_rate = float(matched.get("null_rate_pct") or 0.0)
        actual[f"{key_prefix}.null_rate_pct"] = null_rate
        max_null = contract.get("null_rate_pct_max")
        if max_null is not None and null_rate > float(max_null):
            failures.append(
                f"{key_prefix} null_rate_pct: {null_rate:.2f}% > {float(max_null):.2f}%"
            )


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
