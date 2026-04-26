"""Deterministic SRLDC PSP report URL construction and downloads."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MONTH_SHORT = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


@dataclass(frozen=True)
class DownloadSummary:
    """Counts produced by an SRLDC deterministic download run."""

    days_scanned: int
    already_present: int
    head_200: int
    downloaded: int
    failed: int


def iter_dates(start_date: date, end_date: date) -> list[date]:
    """Return inclusive dates between `start_date` and `end_date`."""
    dates: list[date] = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def srldc_psp_url(report_date: date) -> str:
    """Build the deterministic SRLDC daily PSP PDF URL for a report date."""
    month_folder = f"{MONTH_SHORT[report_date.month]}{report_date.strftime('%y')}"
    file_name = f"{report_date.strftime('%d-%m-%Y')}-psp.pdf"
    return f"https://www.srldc.in/var/ftp/reports/psp/{report_date.year}/{month_folder}/{file_name}"


def srldc_psp_filename(report_date: date) -> str:
    """Return the canonical local SRLDC PSP filename for a report date."""
    return f"{report_date.strftime('%d-%m-%Y')}-psp.pdf"


def missing_dates(start_date: date, end_date: date, output_dir: Path) -> list[date]:
    """Return dates whose canonical SRLDC PSP PDF is absent from `output_dir`."""
    return [
        report_date
        for report_date in iter_dates(start_date, end_date)
        if not (output_dir / srldc_psp_filename(report_date)).exists()
    ]


def download_srldc_range(
    start_date: date,
    end_date: date,
    output_dir: Path,
    max_attempts: int = 3,
) -> DownloadSummary:
    """Download missing SRLDC PSP PDFs over an inclusive date range."""
    output_dir.mkdir(parents=True, exist_ok=True)
    days = iter_dates(start_date, end_date)
    already_present = 0
    head_200 = 0
    downloaded = 0
    failed = 0

    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        for report_date in days:
            destination = output_dir / srldc_psp_filename(report_date)
            if destination.exists():
                already_present += 1
                continue
            if _download_one(client, report_date, destination, max_attempts=max_attempts):
                downloaded += 1
                head_200 += 1
            else:
                failed += 1

    return DownloadSummary(
        days_scanned=len(days),
        already_present=already_present,
        head_200=head_200,
        downloaded=downloaded,
        failed=failed,
    )


def _download_one(client: httpx.Client, report_date: date, destination: Path, max_attempts: int) -> bool:
    """Download one SRLDC PDF with bounded retry and backoff."""
    url = srldc_psp_url(report_date)
    for attempt in range(1, max_attempts + 1):
        try:
            head = client.head(url)
            if head.status_code == 200:
                response = client.get(url)
                if response.status_code == 200 and response.content:
                    destination.write_bytes(response.content)
                    return True
            if head.status_code not in (429, 500, 502, 503, 504):
                return False
        except httpx.HTTPError as exc:
            logger.debug("SRLDC download attempt failed for %s: %s", report_date, exc)
        _sleep_backoff(attempt)
    return False


def _sleep_backoff(attempt: int) -> None:
    delay = min(20.0, 1.5 * (2 ** (attempt - 1))) + random.uniform(0.2, 1.0)
    time.sleep(delay)
