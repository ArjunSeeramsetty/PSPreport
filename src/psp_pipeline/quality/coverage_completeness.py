"""Distinguish floor-pass coverage from full PSP and RPC report coverage.

A corpus profile can pass while ERLDC sits near 62% and RPC facts are empty.
Callers that need an honest replay verdict must use this module instead of
treating ``CoverageProfileResult.passed`` as complete data coverage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import sqlite3
from typing import Any, Iterable, Mapping

from psp_pipeline.quality.coverage_contract import CoverageProfileResult

PSP_DAILY_SOURCES = (
    "srldc",
    "nrldc",
    "wrldc",
    "erldc",
    "nerldc",
    "grid_india_national",
)
RPC_SOURCES = ("erpc", "nrpc", "srpc", "wrpc", "nerpc")
RPC_FACT_TABLES = (
    "FactRPCWeeklyDSMEntity",
    "FactRPCWeeklyDSMAncillary",
    "FactRPCMonthlyREAStation",
    "FactRPCMonthlyREAAllocation",
)
FULL_COVERAGE_PCT = 100.0


@dataclass(frozen=True)
class CoverageCompleteness:
    """Honest completeness verdict for one replay or coverage evaluation."""

    floor_pass: bool
    all_psp_documents_present: bool
    psp_documents_present: tuple[str, ...]
    accounted_cell_pct_by_source: dict[str, float]
    sources_below_full_cell_coverage: dict[str, float]
    full_cell_coverage: bool
    rpc_status: str
    rpc_fact_row_count: int
    energy_reconciliation_certified: bool
    energy_reconciliation_status: str
    full_psp_and_rpc_coverage: bool
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready completeness payload for replay summaries."""

        payload = asdict(self)
        payload["psp_documents_present"] = list(self.psp_documents_present)
        payload["notes"] = list(self.notes)
        return payload


def source_accounted_cell_pcts(result: CoverageProfileResult) -> dict[str, float]:
    """Return source-level accounted-cell percentages, ignoring slice metrics."""

    return {
        source: float(value)
        for source, value in result.actual.items()
        if "." not in source
    }


def assess_coverage_completeness(
    profile: CoverageProfileResult,
    *,
    db_path: str | None = None,
    fact_table_counts: Mapping[str, int] | None = None,
    balance: Mapping[str, Any] | None = None,
    present_documents: Iterable[str] | None = None,
) -> CoverageCompleteness:
    """Build a completeness verdict that cannot be confused with a floor pass.

    ``floor_pass`` is the configured corpus/synthetic gate. Full PSP and RPC
    coverage additionally requires every daily PSP document, 100% accounted
    cells on those sources, and demonstrated RPC facts. Energy reconciliation
    is a separate certification and does not ride on ``floor_pass``.
    """

    accounted = source_accounted_cell_pcts(profile)
    below_full = {
        source: pct
        for source, pct in accounted.items()
        if pct < FULL_COVERAGE_PCT
    }
    documents = _present_documents(
        present_documents,
        db_path=db_path,
        accounted=accounted,
    )
    psp_present = tuple(source for source in PSP_DAILY_SOURCES if source in documents)
    all_psp_docs = set(PSP_DAILY_SOURCES) <= set(documents)
    rpc_count = _rpc_fact_row_count(fact_table_counts, db_path)
    rpc_status = _rpc_status(profile, accounted, rpc_count)
    energy_ok, energy_status = _energy_reconciliation(balance)
    full_cells = bool(accounted) and not below_full and not profile.missing_sources
    full_psp_rpc = (
        all_psp_docs
        and full_cells
        and rpc_status == "full"
        and not profile.missing_sources
    )
    notes = _notes(
        profile=profile,
        below_full=below_full,
        rpc_status=rpc_status,
        energy_ok=energy_ok,
        energy_status=energy_status,
        all_psp_docs=all_psp_docs,
    )
    return CoverageCompleteness(
        floor_pass=profile.passed,
        all_psp_documents_present=all_psp_docs,
        psp_documents_present=psp_present,
        accounted_cell_pct_by_source=dict(sorted(accounted.items())),
        sources_below_full_cell_coverage=dict(sorted(below_full.items())),
        full_cell_coverage=full_cells,
        rpc_status=rpc_status,
        rpc_fact_row_count=rpc_count,
        energy_reconciliation_certified=energy_ok,
        energy_reconciliation_status=energy_status,
        full_psp_and_rpc_coverage=full_psp_rpc,
        notes=notes,
    )


def _present_documents(
    present_documents: Iterable[str] | None,
    *,
    db_path: str | None,
    accounted: Mapping[str, float],
) -> set[str]:
    if present_documents is not None:
        return {str(source) for source in present_documents}
    if db_path:
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT rldc FROM psp_report_document"
                ).fetchall()
            return {str(row[0]) for row in rows}
        except sqlite3.Error:
            pass
    return set(accounted)


def _rpc_fact_row_count(
    fact_table_counts: Mapping[str, int] | None,
    db_path: str | None,
) -> int:
    if fact_table_counts is not None:
        return sum(int(fact_table_counts.get(table, 0)) for table in RPC_FACT_TABLES)
    if not db_path:
        return 0
    total = 0
    try:
        with sqlite3.connect(db_path) as conn:
            for table in RPC_FACT_TABLES:
                present = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                if present:
                    total += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return total
    return total


def _rpc_status(
    profile: CoverageProfileResult,
    accounted: Mapping[str, float],
    rpc_count: int,
) -> str:
    missing_rpc = [source for source in profile.missing_sources if source in RPC_SOURCES]
    if missing_rpc:
        return "missing"
    rpc_pcts = {
        source: pct for source, pct in accounted.items() if source in RPC_SOURCES
    }
    if not rpc_pcts and rpc_count == 0:
        return "not_demonstrated"
    all_rpc_present = set(RPC_SOURCES) <= set(accounted)
    if (
        all_rpc_present
        and rpc_count > 0
        and all(accounted[source] >= FULL_COVERAGE_PCT for source in RPC_SOURCES)
    ):
        return "full"
    return "floor_pass"


def _energy_reconciliation(
    balance: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    if not balance:
        return False, "energy_comparison_not_available"
    comparisons = balance.get("nldc_comparisons") or {}
    energy = comparisons.get("day_energy_met_mu")
    if not isinstance(energy, Mapping):
        return False, "energy_comparison_not_available"
    if energy.get("within_tolerance"):
        return True, "within_tolerance"
    pct = energy.get("variance_pct")
    if pct is None:
        return False, "energy_discrepancy_uncertified"
    return False, f"energy_discrepancy_uncertified variance_pct={float(pct):.2f}"


def _notes(
    *,
    profile: CoverageProfileResult,
    below_full: Mapping[str, float],
    rpc_status: str,
    energy_ok: bool,
    energy_status: str,
    all_psp_docs: bool,
) -> tuple[str, ...]:
    notes: list[str] = []
    if profile.passed and below_full:
        notes.append(
            "Corpus floors are not a 100% requirement; floor_pass does not "
            "mean full report coverage."
        )
    if not profile.required:
        notes.append("The selected coverage profile is marked non-required.")
    if all_psp_docs:
        notes.append("All six daily PSP source documents are present.")
    else:
        notes.append("One or more daily PSP source documents are absent.")
    if rpc_status == "not_demonstrated":
        notes.append("RPC coverage is not demonstrated (FactRPC* counts are zero).")
    if not energy_ok:
        notes.append(
            "Energy reconciliation is uncertified; this replay cannot certify "
            f"a corrected pipeline ({energy_status})."
        )
    if below_full:
        rendered = ", ".join(
            f"{source} {pct:.2f}%" for source, pct in sorted(below_full.items())
        )
        notes.append(f"Accounted-cell coverage below 100%: {rendered}.")
    return tuple(notes)
