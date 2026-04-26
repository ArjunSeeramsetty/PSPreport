"""Download WRLDC daily PSP reports from public directory listings."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from time import sleep
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://reporting.wrldc.in:8081/PSP/"
FILE_NAME_PATTERN = "WRLDC_PSP_Report_{report_date:%d-%m-%Y}.pdf"
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True)
class WRLDCDownloadResult:
    """Summary of a WRLDC PSP download run."""

    attempted: int
    already_present: int
    downloaded: int
    failed: int
    missing_after: int
    manifest_path: Path


def is_pdf_file(path: Path) -> bool:
    """Return true when a local path points to a non-empty PDF."""

    if not path.exists() or path.stat().st_size < 1024:
        return False
    with path.open("rb") as handle:
        return handle.read(4) == b"%PDF"


def report_url(report_date: date) -> str:
    """Build the deterministic WRLDC PSP PDF URL for a report date."""

    month_name = MONTH_NAMES[report_date.month - 1]
    file_name = FILE_NAME_PATTERN.format(report_date=report_date)
    return urljoin(BASE_URL, f"{report_date.year}/{month_name}/{file_name}")


def parse_report_date(file_name: str) -> date | None:
    """Parse a WRLDC PSP report date from the canonical file name."""

    match = re.search(r"WRLDC_PSP_Report_(\d{2})-(\d{2})-(\d{4})\.pdf$", file_name)
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def iter_dates(start_date: date, end_date: date) -> list[date]:
    """Return every calendar date in the inclusive date range."""

    report_dates: list[date] = []
    current = start_date
    while current <= end_date:
        report_dates.append(current)
        current += timedelta(days=1)
    return report_dates


def missing_dates(output_dir: Path, start_date: date, end_date: date) -> list[date]:
    """Return expected dates not represented by a local WRLDC PSP PDF."""

    present: set[date] = set()
    for path in output_dir.glob("*.pdf"):
        parsed = parse_report_date(path.name)
        if parsed and is_pdf_file(path):
            present.add(parsed)
    return [report_date for report_date in iter_dates(start_date, end_date) if report_date not in present]


def download_wrldc_range(
    start_date: date,
    end_date: date,
    output_dir: Path,
    max_attempts: int = 3,
    timeout_seconds: float = 45.0,
    delay_seconds: float = 0.5,
) -> WRLDCDownloadResult:
    """Download WRLDC PSP PDFs for the inclusive date range."""

    output_dir.mkdir(parents=True, exist_ok=True)
    attempted = 0
    already_present = 0
    downloaded = 0
    failed = 0

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        for report_date in iter_dates(start_date, end_date):
            attempted += 1
            destination = output_dir / FILE_NAME_PATTERN.format(report_date=report_date)
            if is_pdf_file(destination):
                already_present += 1
                continue

            success = False
            url = report_url(report_date)
            for attempt in range(1, max_attempts + 1):
                try:
                    response = client.get(url)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "wrldc_download_error date=%s attempt=%s error=%s",
                        report_date.isoformat(),
                        attempt,
                        exc,
                    )
                    sleep(min(delay_seconds * attempt, 5.0))
                    continue

                if response.status_code == 404:
                    break
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
    manifest_path = output_dir.parent / "missing_wrldc_dates.txt"
    manifest_path.write_text(
        "\n".join(report_date.isoformat() for report_date in missing) + ("\n" if missing else ""),
        encoding="utf-8",
    )
    return WRLDCDownloadResult(
        attempted=attempted,
        already_present=already_present,
        downloaded=downloaded,
        failed=failed,
        missing_after=len(missing),
        manifest_path=manifest_path,
    )
