from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.rldc_adapters import NRLDCAdapter, SRLDCAdapter


def _download(client: httpx.Client, url: str, out_dir: Path) -> Path | None:
    try:
        response = client.get(url, timeout=60.0, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code >= 400 or not response.content:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    name = Path(url.split("?")[0]).name or "report.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    path = out_dir / name
    path.write_bytes(response.content)
    return path


def run(days_back: int = 120, target_per_source: int = 12) -> dict[str, int]:
    adapters = {
        "srldc": SRLDCAdapter(),
        "nrldc": NRLDCAdapter(),
    }
    output_dirs = {
        "srldc": ROOT / "downloads" / "SRLDC_PSP",
        "nrldc": ROOT / "downloads" / "NRLDC_PSP",
    }
    counts = {
        "srldc_links": 0,
        "nrldc_links": 0,
        "srldc_downloaded": 0,
        "nrldc_downloaded": 0,
    }

    start = date.today() - timedelta(days=days_back)
    dates = [start + timedelta(days=i) for i in range(days_back + 1)]

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for source_id, adapter in adapters.items():
            seen: set[str] = set()
            for d in dates:
                if counts[f"{source_id}_downloaded"] >= target_per_source:
                    break
                links = adapter.discover(client, d)
                for link in links:
                    if link.url in seen:
                        continue
                    seen.add(link.url)
                    key = f"{source_id}_links"
                    counts[key] += 1
                    if _download(client, link.url, output_dirs[source_id]):
                        counts[f"{source_id}_downloaded"] += 1
                        if counts[f"{source_id}_downloaded"] >= target_per_source:
                            break
    return counts


if __name__ == "__main__":
    configure_logging("INFO")
    result = run(days_back=365, target_per_source=12)
    print(result)
