from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredLink:
    url: str
    report_date: date
    source_id: str
    report_family: str
    confidence: float


class BaseRLDCAdapter(ABC):
    SOURCE_ID: str
    BASE_URL: str

    @abstractmethod
    def discover(self, client: httpx.Client, target_date: date) -> list[DiscoveredLink]:
        raise NotImplementedError

    @abstractmethod
    def requires_playwright(self) -> bool:
        raise NotImplementedError


def _parse_report_date_from_text(text: str) -> date | None:
    patterns = [
        r"(\d{2})-(\d{2})-(\d{4})",
        r"(\d{2})\.(\d{2})\.(\d{2,4})",
        r"(\d{2})_(\d{2})_(\d{2,4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        day, month, year = match.group(1), match.group(2), match.group(3)
        if len(year) == 2:
            year = f"20{year}"
        try:
            return datetime(int(year), int(month), int(day)).date()
        except ValueError:
            continue
    return None


def _extract_pdf_candidates_from_html(html: str, base_url: str) -> set[str]:
    candidates: set[str] = set()
    # Absolute URLs
    for match in re.findall(r"https?://[^\s\"'<>]+?\.pdf", html, flags=re.IGNORECASE):
        candidates.add(match)
    # Relative paths in scripts/attributes
    for match in re.findall(r"(?:/|\.{1,2}/)[^\s\"'<>]+?\.pdf", html, flags=re.IGNORECASE):
        candidates.add(urljoin(base_url, match))
    return candidates


def _parse_nrldc_daily_report_date(text: str) -> date | None:
    """Extract an NRLDC PSP date from its ``dailyDDMMYY[YY]`` filename."""
    match = re.search(
        r"daily[-_ ]?(\d{2})(\d{2})(\d{4}|\d{2})(?!\d)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return _parse_report_date_from_text(text)

    day, month, year = match.groups()
    if len(year) == 2:
        year = f"20{year}"
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


class SRLDCAdapter(BaseRLDCAdapter):
    SOURCE_ID = "srldc"
    BASE_URL = "https://www.srldc.in"

    def discover(self, client: httpx.Client, target_date: date) -> list[DiscoveredLink]:
        listing_url = f"{self.BASE_URL}/Daily-Reports"
        try:
            response = client.get(listing_url)
        except httpx.HTTPError:
            # SRLDC intermittently fails TLS handshakes in some environments.
            listing_url = listing_url.replace("https://", "http://", 1)
            try:
                response = client.get(listing_url)
            except httpx.HTTPError:
                return []
        if response.status_code >= 400:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        discovered_exact: list[DiscoveredLink] = []
        discovered_fallback: list[DiscoveredLink] = []
        candidates: set[tuple[str, str]] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            text = anchor.get_text(" ", strip=True)
            candidates.add((href, text))
        for url in _extract_pdf_candidates_from_html(response.text, listing_url):
            candidates.add((url, ""))

        for href, text in candidates:
            candidate = f"{href} {text}".lower()
            if ".pdf" not in candidate:
                continue
            if "psp" not in candidate and "power supply position" not in candidate:
                continue
            absolute = urljoin(listing_url, href)
            if "srldc.in" not in urlparse(absolute).netloc:
                continue
            report_date = _parse_report_date_from_text(f"{href} {text}") or target_date
            link = DiscoveredLink(
                url=absolute,
                report_date=report_date,
                source_id=self.SOURCE_ID,
                report_family="psp",
                confidence=1.0 if report_date == target_date else 0.8,
            )
            if report_date == target_date:
                discovered_exact.append(link)
            else:
                discovered_fallback.append(link)
        if discovered_exact:
            return discovered_exact
        return discovered_fallback

    def requires_playwright(self) -> bool:
        return False


class NRLDCAdapter(BaseRLDCAdapter):
    """Discover public daily NRLDC PSP reports through its document endpoint."""

    SOURCE_ID = "nrldc"
    BASE_URL = "https://www.nrldc.in"
    DAILY_PSP_PAGE_PATH = "/daily/daily-psp-report"
    DOCUMENT_API_PATH = "/get-documents-list/111"
    DOCUMENT_PAGE_SIZE = 100
    MAX_DOCUMENT_PAGES = 100
    LEGACY_LAST_REPORT_DATE = date(2024, 3, 31)

    def __init__(self, max_attempts: int = 3, base_delay_seconds: float = 1.0) -> None:
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds

    def _request_with_retry(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response | None:
        """Send a bounded, jittered retry request for unstable public portals."""
        for attempt in range(self.max_attempts):
            try:
                response = client.request(method, url, **kwargs)
            except httpx.HTTPError as error:
                if attempt + 1 == self.max_attempts:
                    logger.warning("NRLDC request failed after retries: %s", error)
                    return None
                self._sleep_before_retry(attempt, url)
                continue

            if response.status_code < 500 and response.status_code != 429:
                return response
            if attempt + 1 == self.max_attempts:
                logger.warning(
                    "NRLDC request returned status %s after retries: %s",
                    response.status_code,
                    url,
                )
                return response
            self._sleep_before_retry(attempt, url)
        return None

    def _sleep_before_retry(self, attempt: int, url: str) -> None:
        delay = self.base_delay_seconds * (2**attempt)
        delay += random.uniform(0, delay * 0.25)
        logger.info("Retrying NRLDC request after %.2fs: %s", delay, url)
        time.sleep(delay)

    @classmethod
    def _csrf_token(cls, page_html: str) -> str | None:
        soup = BeautifulSoup(page_html, "html.parser")
        for name in ("csrf_token", "csrf-token", "_token"):
            element = soup.find("meta", attrs={"name": name})
            if element and element.get("content"):
                return str(element["content"])
            element = soup.find("input", attrs={"name": name})
            if element and element.get("value"):
                return str(element["value"])
        return None

    @classmethod
    def _document_url(cls, row: dict[str, Any], page_url: str) -> str | None:
        values = [
            row.get(key)
            for key in (
                "document_url",
                "download_url",
                "file_url",
                "url",
                "file_path",
                "path",
                "download",
            )
        ]
        for value in values:
            if not isinstance(value, str):
                continue
            soup = BeautifulSoup(value, "html.parser")
            anchor = soup.find("a", href=True)
            candidate = anchor["href"] if anchor else value
            if ".pdf" not in candidate.lower():
                continue
            absolute = urljoin(page_url, candidate)
            if "nrldc.in" in urlparse(absolute).netloc:
                return absolute
        return None

    @classmethod
    def _document_text(cls, row: dict[str, Any]) -> str:
        values = (
            row.get("file_name"),
            row.get("filename"),
            row.get("title"),
            row.get("document_name"),
            row.get("file_date_sort"),
            row.get("download"),
        )
        return " ".join(str(value) for value in values if value)

    @classmethod
    def _links_from_document_rows(
        cls,
        rows: Iterable[dict[str, Any]],
        target_date: date,
        page_url: str,
    ) -> list[DiscoveredLink]:
        links: list[DiscoveredLink] = []
        seen_urls: set[str] = set()
        for row in rows:
            text = cls._document_text(row)
            report_date = _parse_nrldc_daily_report_date(text)
            if report_date != target_date:
                continue
            url = cls._document_url(row, page_url)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            links.append(
                DiscoveredLink(
                    url=url,
                    report_date=report_date,
                    source_id=cls.SOURCE_ID,
                    report_family="psp",
                    confidence=1.0,
                )
            )
        return links

    def _discover_from_document_api(
        self,
        client: httpx.Client,
        target_date: date,
    ) -> list[DiscoveredLink]:
        page_url = urljoin(self.BASE_URL, self.DAILY_PSP_PAGE_PATH)
        page = self._request_with_retry(client, "GET", page_url)
        if not page or page.status_code >= 400:
            return []

        csrf_token = self._csrf_token(page.text)
        if not csrf_token:
            logger.warning("NRLDC daily PSP page did not expose a CSRF token")
            return []

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": page_url,
            "X-CSRF-TOKEN": csrf_token,
            "X-Requested-With": "XMLHttpRequest",
        }
        api_url = urljoin(self.BASE_URL, self.DOCUMENT_API_PATH)
        for page_number in range(self.MAX_DOCUMENT_PAGES):
            response = self._request_with_retry(
                client,
                "GET",
                api_url,
                headers=headers,
                params={
                    "draw": 1,
                    "start": page_number * self.DOCUMENT_PAGE_SIZE,
                    "length": self.DOCUMENT_PAGE_SIZE,
                },
            )
            if not response or response.status_code >= 400:
                return []
            try:
                payload = response.json()
            except ValueError:
                logger.warning("NRLDC document endpoint returned non-JSON content")
                return []

            rows = payload.get("data", []) if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                logger.warning("NRLDC document endpoint returned an invalid data shape")
                return []
            links = self._links_from_document_rows(
                (row for row in rows if isinstance(row, dict)),
                target_date,
                page_url,
            )
            if links:
                return links
            if len(rows) < self.DOCUMENT_PAGE_SIZE:
                break
        return []

    def _discover_from_listing_page(
        self,
        client: httpx.Client,
        target_date: date,
    ) -> list[DiscoveredLink]:
        page_url = urljoin(self.BASE_URL, self.DAILY_PSP_PAGE_PATH)
        response = self._request_with_retry(client, "GET", page_url)
        if not response or response.status_code >= 400:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        candidates = {
            (anchor["href"].strip(), anchor.get_text(" ", strip=True))
            for anchor in soup.find_all("a", href=True)
        }
        candidates.update((url, "") for url in _extract_pdf_candidates_from_html(response.text, page_url))

        links: list[DiscoveredLink] = []
        for href, text in candidates:
            report_date = _parse_nrldc_daily_report_date(f"{href} {text}")
            if report_date != target_date:
                continue
            absolute = urljoin(page_url, href)
            if "nrldc.in" not in urlparse(absolute).netloc or ".pdf" not in absolute.lower():
                continue
            links.append(
                DiscoveredLink(
                    url=absolute,
                    report_date=target_date,
                    source_id=self.SOURCE_ID,
                    report_family="psp",
                    confidence=0.9,
                )
            )
        return links

    def _legacy_link(self, target_date: date) -> DiscoveredLink | None:
        if target_date > self.LEGACY_LAST_REPORT_DATE:
            return None
        filename = target_date.strftime("daily%d%m%y.pdf")
        return DiscoveredLink(
            url=urljoin(self.BASE_URL, f"/Websitedata/DoReport/pdf/{filename}"),
            report_date=target_date,
            source_id=self.SOURCE_ID,
            report_family="psp",
            confidence=0.6,
        )

    def discover(self, client: httpx.Client, target_date: date) -> list[DiscoveredLink]:
        """Return the public PSP link for ``target_date`` without browser automation."""
        links = self._discover_from_document_api(client, target_date)
        if links:
            return links

        links = self._discover_from_listing_page(client, target_date)
        if links:
            return links

        legacy_link = self._legacy_link(target_date)
        return [legacy_link] if legacy_link else []

    def requires_playwright(self) -> bool:
        return False
