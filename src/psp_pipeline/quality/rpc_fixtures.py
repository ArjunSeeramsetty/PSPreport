"""Canonical local RPC settlement fixtures used by replay and completeness tests.

These workbooks travel the live ``persist_local_rpc_report`` path: table
extraction, raw-cell persistence, and curated ``FactRPC*`` promotion. They are
not a substitute for public RPC portals; they exist so RPC coverage can leave
``not_demonstrated`` in tests and dual-write rehearsals.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from psp_pipeline.parsing.rpc.contracts import classify_rpc_document
from psp_pipeline.pipelines.rldc_daily_psp import DownloadedReport, ensure_sqlite_schema
from psp_pipeline.pipelines.rpc_settlement import persist_local_rpc_report


DEFAULT_RPC_FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rpc"
)
_SOURCE_PREFIXES = ("erpc", "nrpc", "srpc", "wrpc", "nerpc")

_DSM_HEADERS = (
    "Entity",
    "Scheduled Energy (MU)",
    "Actual Energy (MU)",
    "Deviation (MU)",
    "Frequency Linked Charges (Rs)",
)
_DSM_ANCILLARY_HEADERS = ("Entity", "Service Type", "Payable (Rs)", "Receivable (Rs)")
_REA_STATION_HEADERS = (
    "Generating Station",
    "Installed Capacity (MW)",
    "PAFM (%)",
    "Deemed Generation (MU)",
)
_REA_ALLOCATION_HEADERS = (
    "Beneficiary",
    "Station",
    "Peak Allocation (MW)",
    "Off-Peak Allocation (MW)",
    "Energy Share (MU)",
)

CANONICAL_RPC_FIXTURES = (
    {
        "filename": "ERPC_DSM_Account_Week_35_of_2026.xlsx",
        "source_id": "erpc",
        "family": "weekly_dsm",
        "sheets": (
            {
                "title": "DSM",
                "rows": (
                    _DSM_HEADERS,
                    ("West Bengal", 200.0, 198.5, -1.5, 25000),
                ),
            },
            {
                "title": "Ancillary",
                "rows": (
                    _DSM_ANCILLARY_HEADERS,
                    ("West Bengal", "SRAS", 1200, 0),
                ),
            },
        ),
    },
    {
        "filename": "NRPC_DSM_Account_Week_35_of_2026.xlsx",
        "source_id": "nrpc",
        "family": "weekly_dsm",
        "sheets": (
            {
                "title": "DSM",
                "rows": (_DSM_HEADERS, ("Delhi", 95.0, 94.2, -0.8, 4100)),
            },
        ),
    },
    {
        "filename": "SRPC_DSM_Account_Week_35_of_2026.xlsx",
        "source_id": "srpc",
        "family": "weekly_dsm",
        "sheets": (
            {
                "title": "DSM",
                "rows": (_DSM_HEADERS, ("Karnataka", 310.0, 308.5, -1.5, 8200)),
            },
        ),
    },
    {
        "filename": "WRPC_DSM_Account_Week_35_of_2026.xlsx",
        "source_id": "wrpc",
        "family": "weekly_dsm",
        "sheets": (
            {
                "title": "DSM",
                "rows": (_DSM_HEADERS, ("Maharashtra", 410.0, 412.2, 2.2, 6400)),
            },
        ),
    },
    {
        "filename": "NERPC_DSM_Account_Week_35_of_2026.xlsx",
        "source_id": "nerpc",
        "family": "weekly_dsm",
        "sheets": (
            {
                "title": "DSM",
                "rows": (_DSM_HEADERS, ("Assam", 28.0, 27.4, -0.6, 900)),
            },
        ),
    },
    {
        "filename": "ERPC_REA_August_2026.xlsx",
        "source_id": "erpc",
        "family": "monthly_rea",
        "sheets": (
            {
                "title": "REA",
                "rows": (
                    _REA_STATION_HEADERS,
                    ("Farakka STPS", 2100, 88.0, 155.4),
                ),
            },
            {
                "title": "Allocation",
                "rows": (
                    _REA_ALLOCATION_HEADERS,
                    ("Bihar", "Farakka STPS", 450, 380, 95.5),
                ),
            },
        ),
    },
)


def default_rpc_fixture_dir() -> Path:
    """Return the committed RPC fixture directory."""

    return DEFAULT_RPC_FIXTURE_DIR


def ensure_canonical_rpc_fixtures(directory: Path | str | None = None) -> tuple[Path, ...]:
    """Create missing canonical workbooks and drop stale filenames without rewriting bytes."""

    root = Path(directory) if directory is not None else default_rpc_fixture_dir()
    root.mkdir(parents=True, exist_ok=True)
    expected = {str(spec["filename"]) for spec in CANONICAL_RPC_FIXTURES}
    present = {path.name for path in root.glob("*.xlsx")}
    if present != expected:
        return write_canonical_rpc_fixtures(root)
    return tuple(root / str(spec["filename"]) for spec in CANONICAL_RPC_FIXTURES)


def write_canonical_rpc_fixtures(directory: Path | str | None = None) -> tuple[Path, ...]:
    """Write deterministic DSM/REA workbooks for live settlement ingestion."""

    from openpyxl import Workbook

    root = Path(directory) if directory is not None else default_rpc_fixture_dir()
    root.mkdir(parents=True, exist_ok=True)
    expected = {str(spec["filename"]) for spec in CANONICAL_RPC_FIXTURES}
    for stale in root.glob("*.xlsx"):
        if stale.name not in expected:
            stale.unlink()
    written: list[Path] = []
    for spec in CANONICAL_RPC_FIXTURES:
        path = root / str(spec["filename"])
        workbook = Workbook()
        sheets = spec.get("sheets") or (
            {"title": spec["sheet"], "rows": spec["rows"]},
        )
        first = True
        for sheet_spec in sheets:
            sheet = workbook.active if first else workbook.create_sheet()
            first = False
            sheet.title = str(sheet_spec["title"])
            for row in sheet_spec["rows"]:
                sheet.append(list(row))
        workbook.save(path)
        written.append(path)
    return tuple(written)


def ingest_rpc_fixture_reports(
    sqlite_db_path: Path | str,
    fixture_paths: Iterable[Path | str] | None = None,
    *,
    fixture_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Persist and promote local RPC fixtures through the live settlement path."""

    db_path = Path(sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    paths = [Path(item) for item in (fixture_paths or ())]
    if not paths:
        root = Path(fixture_dir) if fixture_dir is not None else default_rpc_fixture_dir()
        ensure_canonical_rpc_fixtures(root)
        paths = sorted(root.glob("*.xlsx"))
    persisted: list[dict[str, Any]] = []
    fact_counts: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_sqlite_schema(conn)
        for path in paths:
            if not path.is_file():
                continue
            report_id = persist_local_rpc_report(conn, _downloaded_rpc_fixture(path))
            classified = classify_rpc_document(path.name)
            persisted.append(
                {
                    "path": str(path),
                    "source_id": _source_id_from_name(path.name),
                    "family": classified.family,
                    "report_document_id": report_id,
                }
            )
        conn.commit()
        fact_counts = _rpc_fact_counts(conn)
    finally:
        conn.close()
    return {
        "reports_persisted": len(persisted),
        "reports": persisted,
        "fact_table_counts": fact_counts,
        "rpc_fact_row_count": sum(fact_counts.values()),
    }


def _downloaded_rpc_fixture(path: Path) -> DownloadedReport:
    """Build a DownloadedReport for one local RPC workbook."""

    classified = classify_rpc_document(path.name)
    payload = path.read_bytes()
    report_date = classified.week_end
    if report_date is None and classified.period_month:
        report_date = date.fromisoformat(f"{classified.period_month}-01")
    if report_date is None:
        report_date = date(2026, 8, 24)
    return DownloadedReport(
        rldc=_source_id_from_name(path.name),
        source_url=f"fixture://rpc/{path.name}",
        local_path=path,
        content_hash=hashlib.sha256(payload).hexdigest(),
        fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        report_date=report_date,
        report_family=classified.family,
        discovery_confidence=1.0,
        response_content_length=len(payload),
        response_last_modified=None,
    )


def _source_id_from_name(name: str) -> str:
    lowered = name.lower()
    for source_id in _SOURCE_PREFIXES:
        if lowered.startswith(source_id):
            return source_id
    return "erpc"


def _rpc_fact_counts(conn: sqlite3.Connection) -> dict[str, int]:
    from psp_pipeline.quality.coverage_completeness import RPC_FACT_TABLES

    counts: dict[str, int] = {}
    for table in RPC_FACT_TABLES:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if present:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        else:
            counts[table] = 0
    return counts
