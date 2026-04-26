from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from psp_pipeline.models.contracts import FetchArtifact, SourceDefinition


class HttpFetcher:
    def __init__(self, timeout_seconds: int = 45):
        self.client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def fetch(self, source: SourceDefinition, out_dir: Path) -> Optional[FetchArtifact]:
        response = self.client.get(source.url)
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
            metadata={"final_url": str(response.url)},
        )


def _infer_suffix(content_type: str) -> str:
    if "pdf" in content_type:
        return ".pdf"
    if "json" in content_type:
        return ".json"
    if "excel" in content_type or "spreadsheet" in content_type:
        return ".xlsx"
    return ".html"

