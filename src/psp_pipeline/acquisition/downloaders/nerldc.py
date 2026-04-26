"""Download NERLDC daily PSP reports from deterministic public URLs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


BASE_URL = "https://www.nerldc.in/wp-content/uploads"


@dataclass(frozen=True)
class NERLDCDownloadResult:
    """Summary of a deterministic NERLDC PSP download run."""

    attempted: int
    already_present: int
    downloaded: int
    failed: int
    missing_after: int
    manifest_path: Path


def nerldc_psp_filename(report_date: date) -> str:
    """Return the canonical NERLDC PSP filename for a report date."""

    return f"NER-PSP-REPORT-DATED-{report_date:%d-%m-%Y}.pdf"


def nerldc_psp_url(report_date: date) -> str:
    """Return the deterministic NERLDC PSP PDF URL for a report date."""

    return f"{BASE_URL}/{nerldc_psp_filename(report_date)}"


def iter_dates(start_date: date, end_date: date) -> list[date]:
    """Return all dates in the inclusive range."""

    days: list[date] = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)
    return days


def is_pdf_file(path: Path) -> bool:
    """Return true when a local file is a non-empty PDF."""

    if not path.exists() or path.stat().st_size < 1024:
        return False
    with path.open("rb") as handle:
        return handle.read(4) == b"%PDF"


def missing_dates(output_dir: Path, start_date: date, end_date: date) -> list[date]:
    """Return dates whose canonical PDFs are absent from the output directory."""

    return [
        report_date
        for report_date in iter_dates(start_date, end_date)
        if not is_pdf_file(output_dir / nerldc_psp_filename(report_date))
    ]


def download_nerldc_range(
    start_date: date,
    end_date: date,
    output_dir: Path,
    max_attempts: int = 3,
    timeout_seconds: float = 45.0,
) -> NERLDCDownloadResult:
    """Download NERLDC PSP PDFs for the inclusive date range."""

    output_dir.mkdir(parents=True, exist_ok=True)
    attempted = 0
    already_present = 0
    downloaded = 0
    failed = 0

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        for report_date in iter_dates(start_date, end_date):
            destination = output_dir / nerldc_psp_filename(report_date)
            if is_pdf_file(destination):
                already_present += 1
                continue

            attempted += 1
            url = nerldc_psp_url(report_date)
            success = False
            for attempt in range(1, max_attempts + 1):
                try:
                    response = client.get(url)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "nerldc_download_error date=%s attempt=%s error=%s",
                        report_date.isoformat(),
                        attempt,
                        exc,
                    )
                    continue

                if response.status_code >= 400 or not response.content:
                    continue
                destination.write_bytes(response.content)
                if is_pdf_file(destination):
                    downloaded += 1
                    success = True
                    break
                destination.unlink(missing_ok=True)

            if not success:
                failed += 1

    missing = missing_dates(output_dir, start_date, end_date)
    manifest_path = output_dir.parent / "missing_nerldc_dates.txt"
    manifest_path.write_text(
        "\n".join(report_date.isoformat() for report_date in missing),
        encoding="utf-8",
    )
    if missing:
        manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    return NERLDCDownloadResult(
        attempted=attempted,
        already_present=already_present,
        downloaded=downloaded,
        failed=failed,
        missing_after=len(missing),
        manifest_path=manifest_path,
    )
