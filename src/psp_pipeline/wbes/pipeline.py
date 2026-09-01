"""Isolated WBES schedule-matrix pipeline.

Disabled by default. Never called from the public PSP DAG. Does not sync Neo4j.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
import logging

from psp_pipeline.wbes.blocks import require_standard_blocks
from psp_pipeline.wbes.catalog import WbesSourceSpec, load_wbes_catalog
from psp_pipeline.wbes.client import WbesClient
from psp_pipeline.wbes.facts import expand_revision_facts
from psp_pipeline.wbes.models import (
    MatrixKind,
    ProbeResult,
    ScheduleComponent,
    WbesBlockFact,
    WbesRevisionDocument,
    WbesRunSummary,
)
from psp_pipeline.wbes.parser import WbesParseError, iter_drop_files, parse_wbes_path
from psp_pipeline.wbes.settings import WbesSettings, load_wbes_settings
from psp_pipeline.wbes.sqlite_store import WbesSqliteStore

LOGGER = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def run_wbes_schedule(
    settings: WbesSettings | None = None,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    force: bool = False,
    client: WbesClient | None = None,
    store: WbesSqliteStore | None = None,
    timescale_store=None,
) -> WbesRunSummary:
    """Ingest WBES drop files and optionally probe/fetch public endpoints.

    Args:
        settings: Isolated WBES settings. Loaded from the environment when omitted.
        start_date: First IST operating day to process.
        end_date: Last IST operating day to process.
        force: Re-parse documents even when the checkpoint says persisted.
        client: Optional HTTP client (tests inject ``httpx.MockTransport``).
        store: Optional SQLite store.
        timescale_store: Optional Timescale writer; never a graph repository.
    """

    config = settings or load_wbes_settings()
    run_id = _run_id()
    if not config.enabled:
        LOGGER.info("wbes_pipeline_disabled")
        return WbesRunSummary(status="disabled", run_id=run_id)

    require_standard_blocks(
        block_count=config.block_count,
        minutes=config.block_minutes,
        allow_five_minute=config.allow_five_minute,
    )
    catalog = load_wbes_catalog(config.catalog_path)
    sqlite_store = store or WbesSqliteStore(config.sqlite_path)
    start = start_date or datetime.now(IST).date()
    stop = end_date or start
    dates = tuple(_iter_dates(start, stop))

    probes: list[ProbeResult] = []
    live_fetches = 0
    owned_client = client is None
    http_client = client
    try:
        if config.live_fetch_enabled:
            http_client = http_client or WbesClient(config)
            probes.extend(http_client.probe_sources(catalog))
            live_fetches = _fetch_probe_json(
                http_client,
                catalog,
                config.raw_dir,
                config.drop_dir,
                probes,
            )
    finally:
        if owned_client and http_client is not None:
            http_client.close()

    documents, drop_files, parse_errors = _load_drop_documents(config, catalog)
    documents = [
        document
        for document in documents
        if start <= document.schedule_date <= stop
    ]

    facts_upserted = 0
    facts_deduplicated = 0
    skipped = 0
    imbalances = 0
    timescale_inserted = 0
    parsed = 0
    for document in documents:
        status = sqlite_store.checkpoint_status(
            document.source_id,
            document.schedule_date.isoformat(),
            document.revision_label,
        )
        if status == "persisted" and not force:
            skipped += 1
            continue
        facts = expand_revision_facts(document)
        sqlite_store.upsert_entities(document)
        inserted, deduped = sqlite_store.upsert_facts(facts)
        facts_upserted += inserted
        facts_deduplicated += deduped
        imbalances += _record_requisition_injection_balance(sqlite_store, document, facts)
        if config.write_timescale:
            writer = timescale_store
            if writer is None:
                from psp_pipeline.wbes.timescale_store import (
                    WbesTimescaleStore,
                    apply_wbes_schema,
                )

                apply_wbes_schema(config.postgres_dsn)
                writer = WbesTimescaleStore(config.postgres_dsn)
            timescale_inserted += writer.upsert_facts(facts)
        sqlite_store.mark_checkpoint(
            source_id=document.source_id,
            schedule_date=document.schedule_date.isoformat(),
            revision_label=document.revision_label,
            status="persisted",
            content_hash=document.content_hash,
            raw_path=document.raw_path,
            updated_at=datetime.now(timezone.utc),
        )
        parsed += 1

    status = "success"
    if parse_errors and parsed == 0 and live_fetches == 0:
        status = "failed"
    elif parse_errors:
        status = "partial"
    elif parsed == 0 and skipped == 0 and not probes:
        status = "idle"
    return WbesRunSummary(
        status=status,
        run_id=run_id,
        schedule_dates=tuple(item.isoformat() for item in dates),
        documents_parsed=parsed,
        facts_upserted=facts_upserted,
        facts_deduplicated=facts_deduplicated,
        drop_files=drop_files,
        live_fetches=live_fetches,
        probes=tuple(probes),
        skipped_checkpoints=skipped,
        recon_imbalances=imbalances,
        timescale_inserted=timescale_inserted,
        errors=tuple(parse_errors),
        details={"catalog_sources": [spec.source_id for spec in catalog]},
    )


def probe_wbes_public(
    settings: WbesSettings | None = None,
    *,
    client: WbesClient | None = None,
) -> WbesRunSummary:
    """Run the unauthenticated catalog probe without persisting schedules."""

    config = settings or load_wbes_settings()
    run_id = _run_id()
    if not config.enabled:
        return WbesRunSummary(status="disabled", run_id=run_id)
    if not config.allow_live_network:
        return WbesRunSummary(
            status="network_disabled",
            run_id=run_id,
            details={"reason": "Set WBES_ALLOW_LIVE_NETWORK=true to probe live portals"},
        )
    catalog = load_wbes_catalog(config.catalog_path)
    owned = client is None
    http_client = client or WbesClient(config)
    try:
        probes = http_client.probe_sources(catalog)
    finally:
        if owned:
            http_client.close()
    return WbesRunSummary(
        status="probed",
        run_id=run_id,
        probes=tuple(probes),
        details={"catalog_sources": [spec.source_id for spec in catalog]},
    )


def _load_drop_documents(
    settings: WbesSettings,
    catalog: tuple[WbesSourceSpec, ...],
) -> tuple[list[WbesRevisionDocument], int, list[str]]:
    files = iter_drop_files(settings.drop_dir)
    default_source = catalog[0] if catalog else None
    documents: list[WbesRevisionDocument] = []
    errors: list[str] = []
    for path in files:
        source_id, region = _source_for_drop(path, default_source)
        try:
            documents.append(
                parse_wbes_path(
                    path,
                    source_id=source_id,
                    source_region=region,
                    block_count=settings.block_count,
                    block_minutes=settings.block_minutes,
                    allow_five_minute=settings.allow_five_minute,
                )
            )
        except (WbesParseError, OSError, ValueError) as exc:
            LOGGER.warning("wbes_drop_parse_failed path=%s error=%s", path.name, exc)
            errors.append(f"{path.name}: {exc}")
    return documents, len(files), errors


def _source_for_drop(
    path: Path, default_source: WbesSourceSpec | None
) -> tuple[str, str]:
    if default_source is None:
        return "wbes_national", "ALL"
    parts = {part.lower() for part in path.parts}
    if "wr" in parts:
        return "wbes_wr", "WR"
    if "nr" in parts:
        return "wbes_nr", "NR"
    if "sr" in parts:
        return "wbes_sr", "SR"
    if "er" in parts:
        return "wbes_er", "ER"
    if "ner" in parts:
        return "wbes_ner", "NER"
    return default_source.source_id, default_source.region


def _fetch_probe_json(
    client: WbesClient,
    catalog: tuple[WbesSourceSpec, ...],
    raw_dir: Path,
    drop_dir: Path,
    probes: list[ProbeResult],
) -> int:
    """Persist probe bodies that look like public JSON for later parsing."""

    saved = 0
    by_url = {probe.url: probe for probe in probes}
    for source in catalog:
        for url in source.probe_urls or (source.landing_url,):
            probe = by_url.get(url)
            if probe is None or probe.classification != "public_json":
                continue
            payload = client.fetch_url(source_id=source.source_id, url=url, out_dir=raw_dir)
            if payload is None:
                continue
            drop_copy = drop_dir / Path(payload.local_path).name
            drop_copy.parent.mkdir(parents=True, exist_ok=True)
            drop_copy.write_bytes(Path(payload.local_path).read_bytes())
            saved += 1
    return saved


def _record_requisition_injection_balance(
    store: WbesSqliteStore,
    document: WbesRevisionDocument,
    facts: list[WbesBlockFact],
) -> int:
    """Record ISGS injection vs summed beneficiary requisition, without failing ingest."""

    requisition = [
        fact
        for fact in facts
        if fact.matrix_kind == MatrixKind.REQUISITION.value
    ]
    injection = [
        fact
        for fact in facts
        if fact.matrix_kind == MatrixKind.NET_SCHEDULE.value
        and fact.schedule_component == ScheduleComponent.INJECTION.value
    ]
    if not requisition or not injection:
        return 0
    req_by_block: dict[int, float] = {}
    for fact in requisition:
        req_by_block[fact.block_no] = req_by_block.get(fact.block_no, 0.0) + fact.operational_value
    inj_by_block: dict[int, float] = {}
    for fact in injection:
        inj_by_block[fact.block_no] = inj_by_block.get(fact.block_no, 0.0) + fact.operational_value
    rows = []
    for block_no, req_value in req_by_block.items():
        inj_value = inj_by_block.get(block_no)
        if inj_value is None:
            continue
        variance = abs(req_value - inj_value)
        if variance > 0.05:
            rows.append(
                (
                    document.schedule_date.isoformat(),
                    document.revision_label,
                    document.source_region,
                    block_no,
                    "requisition_vs_injection_mw",
                    req_value,
                    inj_value,
                    variance,
                )
            )
    return store.record_imbalances(rows)


def _iter_dates(start: date, stop: date) -> list[date]:
    if stop < start:
        raise ValueError("end_date must be on or after start_date")
    days = []
    cursor = start
    while cursor <= stop:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"wbes_{stamp}_{str(uuid4())[:8]}"


def settings_with_overrides(settings: WbesSettings, **changes: object) -> WbesSettings:
    """Return a copy of WBES settings with selected fields replaced."""

    return replace(settings, **changes)
