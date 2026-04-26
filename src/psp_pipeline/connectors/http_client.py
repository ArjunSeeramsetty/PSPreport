from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from psp_pipeline.models.contracts import FetchArtifact, SourceDefinition


class HttpFetcher:
    def __init__(
        self,
        timeout_seconds: int = 45,
        max_attempts: int = 3,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 12.0,
        jitter_seconds: float = 0.5,
        client: httpx.Client | None = None,
    ):
        self.client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
        self._owns_client = client is None
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.jitter_seconds = jitter_seconds

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def preflight_check(self, source: SourceDefinition) -> bool:
        """
        Lightweight availability check.
        Returns True if source looks fetchable, False if clearly unavailable.
        """
        try:
            response = self.client.head(source.url)
            if response.status_code in {405, 501}:
                # Some servers do not support HEAD; do not block full GET.
                return True
            if response.status_code >= 400:
                return False
            content_length = response.headers.get("content-length")
            if content_length is not None and content_length.isdigit() and int(content_length) == 0:
                return False
            return True
        except httpx.HTTPError:
            # Preflight is advisory; GET retry may still succeed.
            return True

    def fetch(self, source: SourceDefinition, out_dir: Path) -> Optional[FetchArtifact]:
        if not self.preflight_check(source):
            return None

        response = self._fetch_with_retry(source.url)
        if response.status_code >= 400:
            return None

        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = _infer_suffix(response.headers.get("content-type", "text/html"))
        local_path = out_dir / f"{source.source_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}{suffix}"
        local_path.write_bytes(response.content)
        digest = hashlib.sha256(response.content).hexdigest()

        return FetchArtifact(
            source_id=source.source_id,
            source_url=source.url,
            content_hash=digest,
            fetched_at=datetime.now(timezone.utc),
            mime_type=response.headers.get("content-type", "application/octet-stream"),
            local_path=str(local_path),
            status_code=response.status_code,
            metadata={
                "final_url": str(response.url),
                "content_length": response.headers.get("content-length"),
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
            },
        )

    def _fetch_with_retry(self, url: str) -> httpx.Response:
        retrying = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential_jitter(
                initial=self.base_delay_seconds,
                max=self.max_delay_seconds,
                jitter=self.jitter_seconds,
            ),
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

        raise RuntimeError("Retry loop exited unexpectedly")


def _infer_suffix(content_type: str) -> str:
    if "pdf" in content_type:
        return ".pdf"
    if "json" in content_type:
        return ".json"
    if "excel" in content_type or "spreadsheet" in content_type:
        return ".xlsx"
    return ".html"
