"""Expand WBES revision documents into bitemporal block facts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from uuid import NAMESPACE_URL, uuid5

from psp_pipeline.wbes.blocks import iter_schedule_blocks
from psp_pipeline.wbes.models import (
    WbesBlockFact,
    WbesRevisionDocument,
    entity_key,
    metric_name,
)


def build_series_key(
    *,
    entity_key_value: str,
    metric: str,
    time_block: str,
    source_region: str,
    valid_from: str,
    valid_to: str,
) -> str:
    """Return a compact hash for one logical (entity, metric, block) series."""

    payload = "|".join(
        (entity_key_value, metric, time_block, source_region, valid_from, valid_to)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def expand_revision_facts(
    document: WbesRevisionDocument,
    *,
    ingested_at: datetime | None = None,
) -> list[WbesBlockFact]:
    """Turn one revision document into one fact per block cell."""

    ingested = ingested_at or datetime.now(timezone.utc)
    blocks = iter_schedule_blocks(
        document.schedule_date,
        block_count=document.block_count,
        minutes=document.block_minutes,
    )
    facts: list[WbesBlockFact] = []
    for matrix in document.matrices:
        metric = metric_name(matrix.kind, matrix.component)
        for row in matrix.rows:
            key = entity_key(
                region=document.source_region,
                archetype=row.archetype,
                entity_id=row.entity_id,
                counterparty_archetype=row.counterparty_archetype,
                counterparty_id=row.counterparty_id,
            )
            counterparty_key = None
            if row.counterparty_id and row.counterparty_archetype is not None:
                counterparty_key = entity_key(
                    region=document.source_region,
                    archetype=row.counterparty_archetype,
                    entity_id=row.counterparty_id,
                )
            for block, value in zip(blocks, row.values_mw, strict=True):
                series_key = build_series_key(
                    entity_key_value=key,
                    metric=metric,
                    time_block=block.start_clock,
                    source_region=document.source_region,
                    valid_from=block.valid_from.isoformat(),
                    valid_to=block.valid_to.isoformat(),
                )
                revision_uuid = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{series_key}|{document.content_hash}|{document.revision_label}",
                    )
                )
                facts.append(
                    WbesBlockFact(
                        series_key=series_key,
                        revision_uuid=revision_uuid,
                        entity_key=key,
                        archetype=row.archetype.value,
                        matrix_kind=matrix.kind.value,
                        metric_name=metric,
                        time_block=block.start_clock,
                        block_no=block.block_no,
                        operational_value=float(value),
                        source_region=document.source_region,
                        source_id=document.source_id,
                        valid_from=block.valid_from,
                        valid_to=block.valid_to,
                        version_no=document.revision_no,
                        revision_label=document.revision_label,
                        ingested_at=ingested,
                        content_hash=document.content_hash,
                        counterparty_key=counterparty_key,
                        schedule_component=(
                            matrix.component.value if matrix.component else None
                        ),
                    )
                )
    return facts
