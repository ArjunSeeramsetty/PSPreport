"""Unauthenticated WBES probe classification, including TLS/login walls."""

from pathlib import Path

import httpx

from psp_pipeline.wbes.catalog import load_wbes_catalog
from psp_pipeline.wbes.client import WbesClient, classify_http_payload
from psp_pipeline.wbes.pipeline import probe_wbes_public, settings_with_overrides
from psp_pipeline.wbes.settings import load_wbes_settings


def test_catalog_is_controlled_and_separate_from_public_sources() -> None:
    sources = load_wbes_catalog()
    assert sources
    assert all(source.access_mode == "controlled" for source in sources)
    assert any(source.landing_url.startswith("https://newwbes.grid-india.in") for source in sources)


def test_login_html_is_classified_as_login_wall() -> None:
    result = classify_http_payload(
        url="https://newwbes.grid-india.in/",
        status_code=200,
        content_type="text/html",
        body=b"<html><body>Please Login with username and password</body></html>",
        final_url="https://newwbes.grid-india.in/login",
    )
    assert result.classification == "login_wall"


def test_json_payload_is_classified_as_public_json() -> None:
    result = classify_http_payload(
        url="https://example.test/schedule.json",
        status_code=200,
        content_type="application/json",
        body=b'{"schedule_date":"2026-09-01","matrices":[]}',
    )
    assert result.classification == "public_json"
    assert "schedule_date" in result.json_keys


def test_tls_eof_is_classified_as_tls_blocked() -> None:
    result = classify_http_payload(
        url="https://newwbes.grid-india.in/",
        status_code=None,
        content_type=None,
        body=b"",
        error="ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol",
    )
    assert result.classification == "tls_blocked"


def test_timeout_is_classified_before_generic_ssl_noise() -> None:
    result = classify_http_payload(
        url="https://wbes.wrldc.in/",
        status_code=None,
        content_type=None,
        body=b"",
        error="ConnectTimeout: _ssl.c:983: The handshake operation timed out",
    )
    assert result.classification == "timeout"


def test_client_probe_uses_injected_transport(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            content=b"<html>Sign in</html>",
        )

    settings = settings_with_overrides(
        load_wbes_settings(tmp_path),
        enabled=True,
        allow_live_network=True,
        project_root=tmp_path,
        catalog_path=Path("config/wbes_sources.yaml"),
    )
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, follow_redirects=True)
    with WbesClient(settings, client=client) as wbes_client:
        result = wbes_client.probe_url("https://newwbes.grid-india.in/")
    assert result.classification == "login_wall"
    assert result.status_code == 200


def test_probe_pipeline_is_noop_when_disabled(tmp_path: Path) -> None:
    settings = settings_with_overrides(load_wbes_settings(tmp_path), enabled=False)
    summary = probe_wbes_public(settings)
    assert summary.status == "disabled"
    assert summary.probes == ()
