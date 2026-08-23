"""Tests for deterministic public NRLDC daily PSP discovery."""

from __future__ import annotations

from datetime import date

import httpx

from psp_pipeline.acquisition.adapters.rldc import (
    NRLDCAdapter,
    _parse_nrldc_daily_report_date,
)


def test_parse_nrldc_daily_report_date_accepts_six_and_eight_digit_dates() -> None:
    """NRLDC filenames use both legacy and current daily date suffixes."""
    assert _parse_nrldc_daily_report_date("daily220226.pdf") == date(2026, 2, 22)
    assert _parse_nrldc_daily_report_date("daily22052025.pdf") == date(2025, 5, 22)


def test_nrldc_document_api_discovers_exact_date_after_pagination() -> None:
    """The adapter preserves session metadata and pages until it finds the target."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/daily/daily-psp-report":
            return httpx.Response(
                200,
                text='<html><meta name="csrf_token" content="test-csrf-token"></html>',
            )
        assert request.url.path == "/get-documents-list/111"
        assert request.headers["x-csrf-token"] == "test-csrf-token"
        assert request.headers["x-requested-with"] == "XMLHttpRequest"
        if request.url.params["start"] == "0":
            return httpx.Response(200, json={"data": [{}] * 100})
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "file_name": "daily220226.pdf",
                        "title": "Daily PSP",
                        "download": "<a href='/files/daily220226.pdf'>Download</a>",
                    }
                ]
            },
        )

    adapter = NRLDCAdapter(max_attempts=1, base_delay_seconds=0)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        links = adapter.discover(client, date(2026, 2, 22))

    assert len(links) == 1
    assert links[0].url == "https://www.nrldc.in/files/daily220226.pdf"
    assert links[0].report_date == date(2026, 2, 22)
    assert links[0].confidence == 1.0
    assert [request.url.params.get("start") for request in calls[1:]] == ["0", "100"]


def test_nrldc_retries_transient_document_api_error() -> None:
    """A temporary portal error does not drop an otherwise available daily report."""
    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        if request.url.path == "/daily/daily-psp-report":
            return httpx.Response(
                200,
                text='<html><meta name="csrf_token" content="test-csrf-token"></html>',
            )
        api_calls += 1
        if api_calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "file_name": "daily220226.pdf",
                        "download": "<a href='/files/daily220226.pdf'>Download</a>",
                    }
                ]
            },
        )

    adapter = NRLDCAdapter(max_attempts=3, base_delay_seconds=0)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        links = adapter.discover(client, date(2026, 2, 22))

    assert len(links) == 1
    assert api_calls == 2


def test_nrldc_uses_legacy_path_only_when_document_discovery_fails() -> None:
    """Pre-April-2024 reports retain an auditable deterministic fallback path."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/daily/daily-psp-report"
        return httpx.Response(200, text="<html></html>")

    adapter = NRLDCAdapter(max_attempts=1, base_delay_seconds=0)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        links = adapter.discover(client, date(2024, 3, 31))

    assert len(links) == 1
    assert links[0].url.endswith("/Websitedata/DoReport/pdf/daily310324.pdf")
    assert links[0].confidence == 0.6
