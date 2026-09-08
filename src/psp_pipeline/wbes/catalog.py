"""Load the isolated WBES endpoint catalog without touching public sources.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WbesSourceSpec:
    """One controlled WBES landing page and its public probe URLs."""

    source_id: str
    region: str
    landing_url: str
    probe_urls: tuple[str, ...]
    matrices: tuple[str, ...]
    components: tuple[str, ...]
    access_mode: str = "controlled"
    notes: str = ""


def default_catalog_path() -> Path:
    """Return the repository-owned WBES catalog path."""

    return Path(__file__).resolve().parents[3] / "config" / "wbes_sources.yaml"


def load_wbes_catalog(path: Path | None = None) -> tuple[WbesSourceSpec, ...]:
    """Parse ``config/wbes_sources.yaml`` into source specs."""

    catalog_path = path or default_catalog_path()
    payload: dict[str, Any] = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    sources: list[WbesSourceSpec] = []
    for item in payload.get("sources", []):
        sources.append(
            WbesSourceSpec(
                source_id=str(item["id"]),
                region=str(item.get("region", "ALL")),
                landing_url=str(item["landing_url"]),
                probe_urls=tuple(str(url) for url in item.get("probe_urls", [])),
                matrices=tuple(str(name) for name in item.get("matrices", ())),
                components=tuple(str(name) for name in item.get("components", ())),
                access_mode=str(item.get("access_mode", "controlled")),
                notes=str(item.get("notes", "")),
            )
        )
    return tuple(sources)
