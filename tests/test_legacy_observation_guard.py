"""Regression coverage for the retired generic bootstrap fact path."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from psp_pipeline.models.contracts import FactObservation
from psp_pipeline.pipelines import stages


def test_parser_agent_emits_lineage_without_placeholder_observations() -> None:
    """The legacy parser cannot manufacture production observations."""

    from psp_pipeline.agents.parser_agent import ParserAgent

    lineage, facts = ParserAgent().run("run", [])
    assert lineage == []
    assert facts == []


def test_legacy_sql_persistence_rejects_placeholder_metrics(monkeypatch) -> None:
    """Direct callers cannot bypass the bootstrap publication guard."""

    now = datetime.now(timezone.utc)
    placeholder = FactObservation(
        entity_key="SR:bootstrap",
        metric_name="raw_artifact_count",
        time_block=None,
        operational_value=1.0,
        settlement_value=None,
        variance_pct=None,
        report_type="daily_psp",
        source_region="SR",
        valid_from=now,
        valid_to=None,
        version_no=1,
        ingested_at=now,
        timeseries_uuid="00000000-0000-0000-0000-000000000001",
    )

    class Settings:
        postgres_dsn = "postgresql://not-used"

    monkeypatch.setattr(stages, "PostgresRepository", lambda _: None)
    with pytest.raises(ValueError, match="not eligible"):
        stages.persist_sql(Settings(), [], [placeholder], [])
