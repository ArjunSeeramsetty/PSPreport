"""Download ERLDC daily PSP reports through the public reports API."""

from __future__ import annotations

import logging
import re
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://erldc.in/api"
TARGET_TABLE_CLASS = "DailyPSPReport"


@dataclass(frozen=True)
class ERLDCDownloadResult:
    """Summary of an ERLDC PSP API download run."""

    records_seen: int
    in_range: int
    already_present: int
    downloaded: int
    failed: int
    missing_after: int
    manifest_path: Path


def parse_report_date(product: dict[str, Any]) -> date | None:
    """Parse the PSP report date from an ERLDC API product."""

    file_name = str(product.get("fileName") or "")
    match = re.search(r"_(\d{2})(\d{2})(\d{4})(?:_[Rr]\d+)?\.pdf$", file_name)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None

    file_date = product.get("fileDate")
    if isinstance(file_date, (int, float)):
        return datetime.fromtimestamp(file_date / 1000, tz=timezone.utc).date()
    return None


def is_pdf_file(path: Path) -> bool:
    """Return true when a local path points to a non-empty PDF."""

    if not path.exists() or path.stat().st_size < 1024:
        return False
    with path.open("rb") as handle:
        return handle.read(4) == b"%PDF"


def fetch_products(client: httpx.Client) -> list[dict[str, Any]]:
    """Fetch ERLDC Daily PSP report metadata from the public API."""

    body = {
        "filterOptions": {
            "filterBy": None,
            "filterRange": None,
            "filterFY": None,
            "filterQuarter": None,
            "defaultFiltering": None,
        },
        "targetTableClass": TARGET_TABLE_CLASS,
    }
    response = client.post(f"{BASE_URL}//fetchAllStandardData", json=body)
    response.raise_for_status()
    payload = response.json()
    products = payload.get("data", {}).get("products", [])
    return [product for product in products if isinstance(product, dict)]


def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context compatible with ERLDC's legacy TLS settings."""

    context = ssl.create_default_context()
    legacy_option = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
    if legacy_option:
        context.options |= legacy_option
    return context


def download_url(product_id: str) -> str:
    """Return the ERLDC file download URL for a product id."""

    return f"{BASE_URL}//downloadFile/{TARGET_TABLE_CLASS}/{product_id}"


def missing_dates(output_dir: Path, start_date: date, end_date: date) -> list[date]:
    """Return expected dates not represented by an ERLDC PSP PDF filename."""

    present: set[date] = set()
    for path in output_dir.glob("*.pdf"):
        parsed = parse_report_date({"fileName": path.name})
        if parsed and is_pdf_file(path):
            present.add(parsed)

    missing: list[date] = []
    current = start_date
    while current <= end_date:
        if current not in present:
            missing.append(current)
        current += timedelta(days=1)
    return missing


def download_erldc_range(
    start_date: date,
    end_date: date,
    output_dir: Path,
    max_attempts: int = 3,
    timeout_seconds: float = 45.0,
    delay_seconds: float = 0.75,
) -> ERLDCDownloadResult:
    """Download ERLDC PSP PDFs for available API records in the date range."""

    output_dir.mkdir(parents=True, exist_ok=True)
    already_present = 0
    downloaded = 0
    failed = 0
    in_range = 0

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, verify=_ssl_context()) as client:
        products = fetch_products(client)
        for product in products:
            report_date = parse_report_date(product)
            if not report_date or report_date < start_date or report_date > end_date:
                continue
            in_range += 1
            file_name = str(product.get("fileName") or f"erldc-psp-{report_date.isoformat()}.pdf")
            destination = output_dir / file_name
            if is_pdf_file(destination):
                already_present += 1
                continue

            product_id = str(product.get("id") or "")
            if not product_id:
                failed += 1
                continue

            success = False
            for attempt in range(1, max_attempts + 1):
                try:
                    response = client.get(download_url(product_id))
                except httpx.HTTPError as exc:
                    logger.warning(
                        "erldc_download_error date=%s attempt=%s error=%s",
                        report_date.isoformat(),
                        attempt,
                        exc,
                    )
                    sleep(min(delay_seconds * attempt, 5.0))
                    continue
                if response.status_code >= 400 or not response.content:
                    sleep(min(delay_seconds * attempt, 5.0))
                    continue
                destination.write_bytes(response.content)
                if is_pdf_file(destination):
                    downloaded += 1
                    success = True
                    break
                destination.unlink(missing_ok=True)
                sleep(min(delay_seconds * attempt, 5.0))

            if not success:
                failed += 1
            elif delay_seconds > 0:
                sleep(delay_seconds)

    missing = missing_dates(output_dir, start_date, end_date)
    manifest_path = output_dir.parent / "missing_erldc_dates.txt"
    manifest_path.write_text(
        "\n".join(report_date.isoformat() for report_date in missing) + ("\n" if missing else ""),
        encoding="utf-8",
    )

    return ERLDCDownloadResult(
        records_seen=len(products),
        in_range=in_range,
        already_present=already_present,
        downloaded=downloaded,
        failed=failed,
        missing_after=len(missing),
        manifest_path=manifest_path,
    )
