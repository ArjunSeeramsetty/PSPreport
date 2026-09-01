"""Discover public RPC DSM and REA settlement documents from listing pages."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from psp_pipeline.acquisition.adapters.rldc import BaseRLDCAdapter, DiscoveredLink
from psp_pipeline.parsing.rpc.contracts import classify_rpc_document, parse_rpc_period


logger = logging.getLogger(__name__)

_DOCUMENT_SUFFIXES = (".pdf", ".xlsx", ".xls")
_DEFAULT_KEYWORDS = (
    "dsm",
    "deviation settlement",
    "rea",
    "regional energy account",
)


class PublicListingRPCAdapter(BaseRLDCAdapter):
    """Discover weekly DSM and monthly REA files from a public RPC listing."""

    SOURCE_ID = "rpc"
    BASE_URL = ""
    LISTING_PATH = "/"
    REGION = ""
    INCLUDE_KEYWORDS = _DEFAULT_KEYWORDS
    ALLOW_HOSTS: tuple[str, ...] = ()
    DSM_PUBLICATION_LAG_DAYS = 10
    REA_PUBLICATION_LAG_DAYS = 25

    def __init__(self, source_config: dict[str, Any] | None = None) -> None:
        """Apply optional registry overrides for one public RPC source."""

        config = source_config or {}
        self._listing_url = str(
            config.get("listing_url")
            or urljoin(self.BASE_URL, self.LISTING_PATH)
        )
        configured_keywords = config.get("include_keywords")
        self._include_keywords = tuple(
            str(keyword).lower()
            for keyword in configured_keywords
        ) if isinstance(configured_keywords, list) else self.INCLUDE_KEYWORDS
        configured_hosts = config.get("allow_domains")
        self._allow_hosts = tuple(
            str(host).lower()
            for host in configured_hosts
        ) if isinstance(configured_hosts, list) else self.ALLOW_HOSTS

    def discover(self, client: httpx.Client, target_date: date) -> list[DiscoveredLink]:
        """Return DSM/REA documents whose accounting window covers ``target_date``."""

        listing_url = self._listing_url
        try:
            response = client.get(listing_url)
        except httpx.HTTPError as error:
            logger.warning("%s listing request failed: %s", self.SOURCE_ID, error)
            return []
        if response.status_code >= 400:
            logger.warning(
                "%s listing returned status %s", self.SOURCE_ID, response.status_code
            )
            return []
        return self.links_from_html(response.text, listing_url, target_date)

    def links_from_html(
        self,
        html: str,
        listing_url: str,
        target_date: date,
    ) -> list[DiscoveredLink]:
        """Parse listing markup into date-windowed DSM/REA document links."""

        soup = BeautifulSoup(html, "html.parser")
        candidates = {
            (anchor["href"].strip(), anchor.get_text(" ", strip=True))
            for anchor in soup.find_all("a", href=True)
        }
        links: list[DiscoveredLink] = []
        seen: set[str] = set()
        for href, text in candidates:
            document_url = urljoin(listing_url, href)
            if document_url in seen or not self._allowed_document(document_url, f"{href} {text}"):
                continue
            classified = classify_rpc_document(f"{href} {text}")
            if classified.family == "unknown":
                continue
            if not self._in_publication_window(classified, target_date, f"{href} {text}"):
                continue
            seen.add(document_url)
            report_date = _effective_report_date(classified, target_date)
            links.append(
                DiscoveredLink(
                    url=document_url,
                    report_date=report_date,
                    source_id=self.SOURCE_ID,
                    report_family=classified.family if classified.supported else classified.template_id,
                    confidence=0.9 if classified.supported else 0.4,
                )
            )
        return links

    def requires_playwright(self) -> bool:
        """Public HTML listing discovery does not need browser automation."""

        return False

    def _allowed_document(self, url: str, blob: str) -> bool:
        """Accept same-host settlement files whose title mentions DSM or REA."""

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = (parsed.hostname or "").lower()
        if self._allow_hosts and not any(host.endswith(allowed) for allowed in self._allow_hosts):
            return False
        lowered = blob.lower()
        if not any(suffix in lowered for suffix in _DOCUMENT_SUFFIXES):
            return False
        return any(keyword in lowered for keyword in self._include_keywords)

    def _in_publication_window(
        self,
        classified,
        target_date: date,
        blob: str,
    ) -> bool:
        """Keep documents whose week or month is still within publication lag."""

        period = parse_rpc_period(blob)
        if classified.family == "weekly_dsm":
            start = classified.week_start or period.week_start
            end = classified.week_end or period.week_end
            if start is None or end is None:
                return False
            return start <= target_date <= end + timedelta(days=self.DSM_PUBLICATION_LAG_DAYS)
        if classified.family == "monthly_rea":
            month = classified.period_month or period.period_month
            if not month:
                return False
            year, month_no = (int(part) for part in month.split("-"))
            start = date(year, month_no, 1)
            if month_no == 12:
                next_month = date(year + 1, 1, 1)
            else:
                next_month = date(year, month_no + 1, 1)
            end = next_month - timedelta(days=1)
            return start <= target_date <= end + timedelta(days=self.REA_PUBLICATION_LAG_DAYS)
        return False


class ERPCAdapter(PublicListingRPCAdapter):
    """Discover Eastern Region commercial DSM and REA accounts."""

    SOURCE_ID = "erpc"
    BASE_URL = "https://erpc.gov.in"
    LISTING_PATH = "/en/commercial/"
    REGION = "ER"
    ALLOW_HOSTS = ("erpc.gov.in",)


class NRPCAdapter(PublicListingRPCAdapter):
    """Discover Northern Region commercial DSM and REA accounts."""

    SOURCE_ID = "nrpc"
    BASE_URL = "https://www.nrpc.gov.in"
    LISTING_PATH = "/"
    REGION = "NR"
    ALLOW_HOSTS = ("nrpc.gov.in",)


class SRPCAdapter(PublicListingRPCAdapter):
    """Discover Southern Region commercial DSM and REA accounts."""

    SOURCE_ID = "srpc"
    BASE_URL = "https://www.srpc.kar.nic.in"
    LISTING_PATH = "/html/recent_uploads.html"
    REGION = "SR"
    ALLOW_HOSTS = ("srpc.kar.nic.in",)


class WRPCAdapter(PublicListingRPCAdapter):
    """Discover Western Region commercial DSM and REA accounts."""

    SOURCE_ID = "wrpc"
    BASE_URL = "https://www.wrpc.gov.in"
    LISTING_PATH = "/"
    REGION = "WR"
    ALLOW_HOSTS = ("wrpc.gov.in",)


class NERPCAdapter(PublicListingRPCAdapter):
    """Discover North-Eastern Region commercial DSM and REA accounts."""

    SOURCE_ID = "nerpc"
    BASE_URL = "https://nerpc.gov.in"
    LISTING_PATH = "/"
    REGION = "NER"
    ALLOW_HOSTS = ("nerpc.gov.in",)


RPC_ADAPTERS = {
    "erpc": ERPCAdapter,
    "nrpc": NRPCAdapter,
    "srpc": SRPCAdapter,
    "wrpc": WRPCAdapter,
    "nerpc": NERPCAdapter,
}


def rpc_adapter_for(
    source_id: str,
    source_config: dict[str, Any] | None = None,
) -> PublicListingRPCAdapter | None:
    """Return the listing adapter for one RPC source identifier."""

    adapter_cls = RPC_ADAPTERS.get(source_id.lower())
    return adapter_cls(source_config) if adapter_cls else None


def _effective_report_date(classified, target_date: date) -> date:
    """Prefer the accounting window start so dual-write grains stay stable."""

    if classified.week_start is not None:
        return classified.week_start
    if classified.period_month:
        year, month = (int(part) for part in classified.period_month.split("-"))
        return date(year, month, 1)
    return target_date
