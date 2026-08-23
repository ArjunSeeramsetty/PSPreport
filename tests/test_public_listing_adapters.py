"""Unit tests for PublicListingPSPAdapter and regional RLDC subclasses."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from psp_pipeline.acquisition.adapters.rldc import (
    DiscoveredLink,
    ERLDCAdapter,
    NERLDCAdapter,
    NRLDCAdapter,
    PublicListingPSPAdapter,
    SRLDCAdapter,
    WRLDCAdapter,
)
from psp_pipeline.pipelines.rldc_daily_psp import _get_adapter


def _build_mock_client(transport_handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(transport_handler))


LISTING_ADAPTER_CASES = (
    (WRLDCAdapter, "https://www.wrldc.in/", "wrldc"),
    (ERLDCAdapter, "https://erldc.in/", "erldc"),
    (
        NERLDCAdapter,
        "https://www.nerldc.in/power-supply-position-psp-report/",
        "nerldc",
    ),
)


def test_get_adapter_resolves_all_five_rldcs():
    assert isinstance(_get_adapter("srldc"), SRLDCAdapter)
    assert isinstance(_get_adapter("nrldc"), NRLDCAdapter)
    assert isinstance(_get_adapter("wrldc"), WRLDCAdapter)
    assert isinstance(_get_adapter("erldc"), ERLDCAdapter)
    assert isinstance(_get_adapter("nerldc"), NERLDCAdapter)
    assert _get_adapter("unknown_rldc") is None


@pytest.mark.parametrize(
    ("adapter_class", "listing_url", "source_id"), LISTING_ADAPTER_CASES
)
def test_public_listing_adapters_accept_exact_date_relative_pdf_urls(
    adapter_class, listing_url, source_id
):
    target = date(2024, 5, 15)
    requested_urls: list[str] = []
    html = """
    <html>
      <body>
        <a href="/reports/psp_15-05-2024.pdf">Power Supply Position 15-05-2024</a>
        <a href="/reports/psp_14-05-2024.pdf">Power Supply Position 14-05-2024</a>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, text=html)

    adapter = adapter_class()
    client = _build_mock_client(handler)
    links = adapter.discover(client, target)

    assert requested_urls == [listing_url]
    assert len(links) == 1
    assert links[0].url == f"{adapter.BASE_URL}/reports/psp_15-05-2024.pdf"
    assert links[0].report_date == target
    assert links[0].source_id == source_id
    assert links[0].report_family == "psp"
    assert links[0].confidence == 0.9


@pytest.mark.parametrize(
    ("adapter_class", "listing_url", "_source_id"), LISTING_ADAPTER_CASES
)
def test_public_listing_adapters_reject_other_families_and_dates(
    adapter_class, listing_url, _source_id
):
    target = date(2024, 5, 15)
    html = """
    <html>
      <body>
        <a href="/files/tripping_report_15-05-2024.pdf">Tripping Report 15-05-2024</a>
        <a href="/files/psp_14-05-2024.pdf">Power Supply Position 14-05-2024</a>
        <a href="ftp://example.invalid/psp_15-05-2024.pdf">PSP Report 15-05-2024</a>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == listing_url
        return httpx.Response(200, text=html)

    adapter = adapter_class()
    client = _build_mock_client(handler)
    assert adapter.discover(client, target) == []


def test_public_listing_adapter_external_domain_rejected():
    target = date(2024, 5, 15)
    html = """
    <html>
      <body>
        <a href="https://malicious-site.com/psp_15-05-2024.pdf">PSP Report 15-05-2024</a>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    adapter = ERLDCAdapter()
    client = _build_mock_client(handler)
    links = adapter.discover(client, target)

    assert links == []


@pytest.mark.parametrize(
    ("adapter_class", "listing_url", "_source_id"), LISTING_ADAPTER_CASES
)
def test_public_listing_adapters_return_empty_for_http_failures(
    adapter_class, listing_url, _source_id
):
    target = date(2024, 5, 15)

    def handler_500(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == listing_url
        return httpx.Response(500, text="Internal Server Error")

    adapter = adapter_class()
    client = _build_mock_client(handler_500)
    assert adapter.discover(client, target) == []

    def handler_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network unreachable", request=request)

    client_err = _build_mock_client(handler_error)
    assert adapter.discover(client_err, target) == []


def test_public_listing_adapter_requires_playwright_false():
    wrldc = WRLDCAdapter()
    erldc = ERLDCAdapter()
    nerldc = NERLDCAdapter()

    assert wrldc.requires_playwright() is False
    assert erldc.requires_playwright() is False
    assert nerldc.requires_playwright() is False


def test_nerldc_custom_listing_path():
    target = date(2024, 6, 20)
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        html = """
        <html>
          <body>
            <a href="/docs/PSP_20-06-2024.pdf">Power Supply Position 20-06-2024</a>
          </body>
        </html>
        """
        return httpx.Response(200, text=html)

    adapter = NERLDCAdapter()
    client = _build_mock_client(handler)
    links = adapter.discover(client, target)

    assert requested_urls == ["https://www.nerldc.in/power-supply-position-psp-report/"]
    assert len(links) == 1
    assert links[0].url == "https://www.nerldc.in/docs/PSP_20-06-2024.pdf"
    assert links[0].source_id == "nerldc"
