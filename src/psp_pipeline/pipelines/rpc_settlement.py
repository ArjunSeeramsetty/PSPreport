"""Collect and curate public RPC weekly DSM and monthly REA settlement accounts."""

from __future__ import annotations

from datetime import date, datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from psp_pipeline.acquisition.adapters.rpc import RPC_ADAPTERS, rpc_adapter_for
from psp_pipeline.acquisition.adapters.rldc import DiscoveredLink
from psp_pipeline.parsing.rldc.templates import TemplateMatch
from psp_pipeline.parsing.rpc.contracts import classify_rpc_document
from psp_pipeline.parsing.rpc.tables import extract_rpc_tables
from psp_pipeline.pipelines.rldc_daily_psp import (
    DownloadedReport,
    OcrAssessment,
    RawCell,
    RawLine,
    _hash_bytes,
    ensure_sqlite_schema,
    persist_report,
)


LOGGER = logging.getLogger(__name__)
RPC_SOURCE_IDS = tuple(RPC_ADAPTERS)


def load_rpc_sources(config_path: Path) -> dict[str, dict[str, Any]]:
    """Load the public RPC listing registry."""

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    sources = payload.get("rpc_sources", {})
    return {str(key).lower(): value for key, value in sources.items()}


def run_rpc_settlement_collection(
    config_path: Path,
    sqlite_db_path: Path,
    download_root: Path,
    target_date: date | None = None,
    target_rpcs: set[str] | None = None,
    max_reports_per_rpc: int = 4,
) -> dict[str, Any]:
    """Discover, persist, and promote RPC settlement accounts fail-soft per source."""

    run_date = target_date or datetime.now(timezone.utc).date()
    selected = [
        source_id
        for source_id in RPC_SOURCE_IDS
        if target_rpcs is None or source_id in {item.lower() for item in target_rpcs}
    ]
    _ = load_rpc_sources(config_path)
    aggregate = {
        "sources_requested": len(selected),
        "sources_completed": 0,
        "sources_failed": 0,
        "links_found": 0,
        "reports_downloaded": 0,
        "reports_persisted": 0,
        "unsupported_family": 0,
    }
    source_results: dict[str, dict[str, int]] = {}
    source_failures: dict[str, str] = {}
    sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
    download_root.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        for source_id in selected:
            try:
                result = _collect_one_rpc(
                    source_id=source_id,
                    client=client,
                    sqlite_db_path=sqlite_db_path,
                    download_root=download_root / source_id,
                    target_date=run_date,
                    max_reports=max_reports_per_rpc,
                )
            except Exception as error:  # Source failures must not block other RPCs.
                LOGGER.exception("rpc_source_failed source=%s", source_id)
                source_failures[source_id] = f"{type(error).__name__}: {error}"
                aggregate["sources_failed"] += 1
                continue
            source_results[source_id] = result
            aggregate["sources_completed"] += 1
            for key in (
                "links_found",
                "reports_downloaded",
                "reports_persisted",
                "unsupported_family",
            ):
                aggregate[key] += int(result.get(key, 0))
    return {
        "target_date": run_date.isoformat(),
        "aggregate": aggregate,
        "sources": source_results,
        "failures": source_failures,
    }


def persist_local_rpc_report(
    conn: sqlite3.Connection,
    report: DownloadedReport,
) -> None:
    """Extract local RPC tables and promote matching settlement contracts."""

    classified = classify_rpc_document(
        f"{report.local_path.name} {report.report_family} {report.source_url}"
    )
    template_match = TemplateMatch(
        template_id=classified.template_id,
        template_version="2022.dsm" if classified.family == "weekly_dsm" else "2024.rea",
        confidence=0.9 if classified.supported else 0.0,
        semantic_pass_required=not classified.supported,
        reasons=classified.reasons,
    )
    tables = extract_rpc_tables(report.local_path)
    raw_cells: list[RawCell] = []
    raw_lines: list[RawLine] = []
    line_no = 0
    for table in tables:
        for row_no, row in enumerate(table.rows, start=1):
            line_no += 1
            raw_lines.append(
                RawLine(
                    page_no=table.page_no,
                    line_no=line_no,
                    line_text=" ".join(cell for cell in row if cell),
                    extraction_method="rpc_table",
                )
            )
            for col_no, text in enumerate(row, start=1):
                if not text:
                    continue
                raw_cells.append(
                    RawCell(
                        page_no=table.page_no,
                        table_no=table.table_no,
                        row_no=row_no,
                        col_no=col_no,
                        cell_text=text,
                        extraction_method="rpc_table",
                    )
                )
    ocr = OcrAssessment(
        should_use_ocr=False,
        score=0.0,
        reason="rpc settlement tables use native text extraction",
        extracted_char_count=sum(len(cell.cell_text) for cell in raw_cells),
    )
    persist_report(
        conn,
        report,
        ocr,
        {},
        template_match,
        raw_lines=raw_lines,
        raw_cells=raw_cells,
        raw_text_items=[],
    )


def _collect_one_rpc(
    *,
    source_id: str,
    client: httpx.Client,
    sqlite_db_path: Path,
    download_root: Path,
    target_date: date,
    max_reports: int,
) -> dict[str, int]:
    """Collect one RPC listing without aborting sibling regions."""

    adapter = rpc_adapter_for(source_id)
    counts = {
        "links_found": 0,
        "reports_downloaded": 0,
        "reports_persisted": 0,
        "unsupported_family": 0,
    }
    if adapter is None:
        return counts
    links = adapter.discover(client, target_date)[:max_reports]
    counts["links_found"] = len(links)
    conn = sqlite3.connect(str(sqlite_db_path))
    try:
        ensure_sqlite_schema(conn)
        for link in links:
            downloaded = _download_rpc_report(client, link, download_root)
            if downloaded is None:
                continue
            counts["reports_downloaded"] += 1
            classified = classify_rpc_document(f"{downloaded.local_path.name} {link.report_family}")
            if not classified.supported:
                counts["unsupported_family"] += 1
            persist_local_rpc_report(conn, downloaded)
            counts["reports_persisted"] += 1
        conn.commit()
    finally:
        conn.close()
    LOGGER.info("rpc_source_complete source=%s counts=%s", source_id, counts)
    return counts


def _download_rpc_report(
    client: httpx.Client,
    link: DiscoveredLink,
    out_dir: Path,
) -> DownloadedReport | None:
    """Download one public RPC file, tolerating portals that reject HEAD."""

    try:
        head = client.head(link.url)
        last_modified = head.headers.get("last-modified")
        content_length = (
            int(head.headers["content-length"])
            if head.headers.get("content-length", "").isdigit()
            else None
        )
    except httpx.HTTPError:
        last_modified = None
        content_length = None
    try:
        response = client.get(link.url)
    except httpx.HTTPError as error:
        LOGGER.warning("rpc_download_failed url=%s error=%s", link.url, error)
        return None
    if response.status_code >= 400 or not response.content:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(urlparse(link.url).path).name or f"{link.source_id}_{link.report_date.isoformat()}.pdf"
    local_path = out_dir / safe_name
    local_path.write_bytes(response.content)
    return DownloadedReport(
        rldc=link.source_id,
        source_url=link.url,
        local_path=local_path,
        content_hash=_hash_bytes(response.content),
        fetched_at=datetime.now(timezone.utc),
        report_date=link.report_date,
        report_family=link.report_family,
        discovery_confidence=link.confidence,
        response_content_length=content_length or len(response.content),
        response_last_modified=last_modified,
    )
