"""Unauthenticated WBES probe and optional session fetch.

Live calls are opt-in. Public PSP fetchers are not reused, so artifacts land
under ``data/wbes/`` rather than the daily PSP raw bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from psp_pipeline.wbes.catalog import WbesSourceSpec
from psp_pipeline.wbes.models import ProbeResult
from psp_pipeline.wbes.settings import WbesSettings

LOGGER = logging.getLogger(__name__)

_LOGIN_TOKENS = (
    "login",
    "sign in",
    "password",
    "otp",
    "captcha",
    "userid",
    "user id",
    "username",
    "authenticate",
)


@dataclass(frozen=True)
class FetchedPayload:
    """A raw WBES response saved under the isolated data directory."""

    source_id: str
    source_url: str
    content_hash: str
    local_path: str
    mime_type: str
    status_code: int
    fetched_at: datetime


def classify_http_payload(
    *,
    url: str,
    status_code: int | None,
    content_type: str | None,
    body: bytes,
    final_url: str | None = None,
    error: str | None = None,
) -> ProbeResult:
    """Classify a probe as public JSON, login wall, empty, or transport failure."""

    text = body.decode("utf-8", errors="replace")
    lowered = text.lower()
    content_type = content_type or ""
    jsonish = "application/json" in content_type.lower() or text.lstrip().startswith(("{", "["))
    htmlish = "text/html" in content_type.lower() or "<html" in lowered
    login_wall = htmlish and any(token in lowered for token in _LOGIN_TOKENS)
    json_keys: tuple[str, ...] = ()
    if jsonish:
        json_keys = _json_top_keys(text)
    if error:
        classification = _error_classification(error)
    elif status_code is not None and status_code >= 400:
        classification = "http_error"
    elif login_wall:
        classification = "login_wall"
    elif jsonish:
        classification = "public_json"
    elif htmlish:
        classification = "public_html"
    elif not body:
        classification = "empty"
    else:
        classification = "opaque"
    return ProbeResult(
        url=url,
        status_code=status_code,
        classification=classification,
        content_type=content_type or None,
        final_url=final_url,
        byte_count=len(body),
        error=error,
        json_keys=json_keys,
    )


def _error_classification(error: str) -> str:
    lowered = error.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "unexpected_eof" in lowered or "ssl" in lowered or "tls" in lowered:
        return "tls_blocked"
    if "name or service not known" in lowered or "nodename" in lowered:
        return "dns_failure"
    return "connect_error"


def _json_top_keys(text: str) -> tuple[str, ...]:
    try:
        import json

        payload = json.loads(text)
    except (ValueError, TypeError):
        return ()
    if isinstance(payload, dict):
        return tuple(str(key) for key in list(payload)[:12])
    return ()


class WbesClient:
    """HTTP client used only by the WBES pipeline."""

    def __init__(
        self,
        settings: WbesSettings,
        *,
        client: httpx.Client | None = None,
    ):
        self.settings = settings
        headers = {"User-Agent": settings.user_agent, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}
        if settings.session_cookie:
            headers["Cookie"] = settings.session_cookie
        self.client = client or httpx.Client(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers=headers,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "WbesClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def probe_sources(self, sources: Iterable[WbesSourceSpec]) -> list[ProbeResult]:
        """GET catalog probe URLs without treating failures as pipeline errors."""

        results: list[ProbeResult] = []
        for source in sources:
            urls = source.probe_urls or (source.landing_url,)
            for url in urls:
                results.append(self.probe_url(url))
        return results

    def probe_url(self, url: str) -> ProbeResult:
        """Probe one URL and classify login walls, JSON, or transport blocks."""

        LOGGER.info("wbes_probe_start host=%s", urlparse(url).hostname)
        try:
            response = self._get_with_retry(url)
        except Exception as exc:
            LOGGER.warning("wbes_probe_failed host=%s class=%s", urlparse(url).hostname, type(exc).__name__)
            return classify_http_payload(
                url=url,
                status_code=None,
                content_type=None,
                body=b"",
                error=f"{type(exc).__name__}: {exc}",
            )
        body = response.content
        result = classify_http_payload(
            url=url,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            body=body,
            final_url=str(response.url),
        )
        LOGGER.info(
            "wbes_probe_complete host=%s classification=%s status=%s bytes=%s",
            urlparse(url).hostname,
            result.classification,
            result.status_code,
            result.byte_count,
        )
        return result

    def fetch_url(self, *, source_id: str, url: str, out_dir: Path) -> FetchedPayload | None:
        """Save a live response under ``data/wbes/raw`` when the body is non-empty."""

        try:
            response = self._get_with_retry(url)
        except Exception as exc:
            LOGGER.warning("wbes_fetch_failed host=%s class=%s", urlparse(url).hostname, type(exc).__name__)
            return None
        if response.status_code >= 400 or not response.content:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(response.content).hexdigest()
        suffix = _suffix_for(response.headers.get("content-type", ""), url)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        local_path = out_dir / f"{source_id}_{stamp}_{digest[:12]}{suffix}"
        local_path.write_bytes(response.content)
        return FetchedPayload(
            source_id=source_id,
            source_url=url,
            content_hash=digest,
            local_path=str(local_path),
            mime_type=response.headers.get("content-type", "application/octet-stream"),
            status_code=response.status_code,
            fetched_at=datetime.now(timezone.utc),
        )

    def _get_with_retry(self, url: str) -> httpx.Response:
        retrying = Retrying(
            stop=stop_after_attempt(self.settings.max_attempts),
            wait=wait_exponential_jitter(initial=0.2, max=2.0, jitter=0.1),
            retry=retry_if_exception_type(httpx.HTTPError),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                response = self.client.get(url)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        f"Retryable status code {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                return response
        raise RuntimeError("WBES retry loop exited unexpectedly")


def _suffix_for(content_type: str, url: str) -> str:
    lowered = content_type.lower()
    if "json" in lowered or url.endswith(".json"):
        return ".json"
    if "excel" in lowered or "spreadsheet" in lowered or url.endswith(".xlsx"):
        return ".xlsx"
    if "html" in lowered:
        return ".html"
    return ".bin"
