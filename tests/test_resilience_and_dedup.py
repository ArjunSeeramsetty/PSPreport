from datetime import datetime, timezone
from pathlib import Path

import httpx

from psp_pipeline.agents.recon_agent import ReconAgent
from psp_pipeline.connectors.http_client import HttpFetcher
from psp_pipeline.models.contracts import FactObservation, FetchArtifact, SourceDefinition
from psp_pipeline.pipelines.bronze_pipeline import _deduplicate_artifacts, _reconcile_facts


def _source(url: str = "https://example.test/report") -> SourceDefinition:
    return SourceDefinition(
        source_id="srldc_daily_reports",
        domain="RLDC",
        region="SR",
        report_family="daily_psp",
        url=url,
        fmt="html/pdf",
        cadence="daily",
    )


def test_http_fetcher_retries_on_transient_failure(tmp_path: Path):
    counts = {"get": 0, "head": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            counts["head"] += 1
            return httpx.Response(200, headers={"content-length": "10"}, request=request)
        counts["get"] += 1
        if counts["get"] == 1:
            return httpx.Response(503, request=request, content=b"")
        return httpx.Response(
            200,
            request=request,
            content=b"ok-data",
            headers={"content-type": "application/pdf"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, follow_redirects=True)
    fetcher = HttpFetcher(
        client=client,
        max_attempts=3,
        base_delay_seconds=0.0,
        max_delay_seconds=0.0,
        jitter_seconds=0.0,
    )
    artifact = fetcher.fetch(_source(), tmp_path)

    assert artifact is not None
    assert counts["head"] == 1
    assert counts["get"] == 2


def test_dedup_skips_already_seen_hash(tmp_path: Path):
    file_path = tmp_path / "report.html"
    file_path.write_text("x", encoding="utf-8")
    artifact = FetchArtifact(
        source_id="srldc_daily_reports",
        source_url="https://example.test",
        content_hash="abc123",
        fetched_at=datetime.now(timezone.utc),
        mime_type="text/html",
        local_path=str(file_path),
        status_code=200,
        metadata={},
    )

    class FakeRepo:
        @staticmethod
        def fetch_existing_hash(source_id: str):
            if source_id == "srldc_daily_reports":
                return "abc123"
            return None

        @staticmethod
        def content_hash_exists(source_id: str, content_hash: str) -> bool:
            return source_id == "srldc_daily_reports" and content_hash == "abc123"

    unique, skipped = _deduplicate_artifacts(FakeRepo(), [artifact])
    assert skipped == 1
    assert unique == []
    assert not file_path.exists()


def test_reconciliation_builds_rows_and_updates_fact_variance():
    now = datetime.now(timezone.utc)
    facts = [
        FactObservation(
            entity_key="SR:unit-1",
            metric_name="energy",
            time_block="2026-04-26T00:00:00Z",
            operational_value=105.0,
            settlement_value=100.0,
            variance_pct=None,
            report_type="daily_psp",
            source_region="SR",
            valid_from=now,
            valid_to=None,
            version_no=1,
            ingested_at=now,
            timeseries_uuid="uuid-1",
        )
    ]
    updated_facts, reconciliation = _reconcile_facts("run-1", facts, ReconAgent())
    assert len(updated_facts) == 1
    assert round(updated_facts[0].variance_pct or 0, 2) == 5.0
    assert len(reconciliation) == 1
    assert reconciliation[0].run_id == "run-1"
    assert round(reconciliation[0].variance_pct or 0, 2) == 5.0
