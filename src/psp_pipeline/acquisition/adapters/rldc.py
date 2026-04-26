from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


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
    SOURCE_ID = "nrldc"
    BASE_URL = "https://www.nrldc.in"

    def discover(self, client: httpx.Client, target_date: date) -> list[DiscoveredLink]:
        response = client.get(self.BASE_URL)
        if response.status_code >= 400:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        discovered: list[DiscoveredLink] = []
        candidates: set[tuple[str, str]] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            text = anchor.get_text(" ", strip=True)
            candidates.add((href, text))
        for url in _extract_pdf_candidates_from_html(response.text, self.BASE_URL):
            candidates.add((url, ""))

        for href, text in candidates:
            candidate = f"{href} {text}".lower()
            if ".pdf" not in candidate:
                continue
            if "psp" not in candidate and "power supply position" not in candidate:
                continue
            absolute = urljoin(self.BASE_URL, href)
            if "nrldc.in" not in urlparse(absolute).netloc:
                continue
            report_date = _parse_report_date_from_text(f"{href} {text}")
            confidence = 1.0 if report_date else 0.7
            if report_date and report_date != target_date:
                continue
            discovered.append(
                DiscoveredLink(
                    url=absolute,
                    report_date=report_date or target_date,
                    source_id=self.SOURCE_ID,
                    report_family="psp",
                    confidence=confidence,
                )
            )
        return discovered

    def requires_playwright(self) -> bool:
        return False
