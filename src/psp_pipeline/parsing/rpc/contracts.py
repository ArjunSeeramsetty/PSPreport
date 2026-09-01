"""Classify public RPC settlement documents and parse their accounting period."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re


RPC_WEEKLY_DSM_TEMPLATE_ID = "rpc_weekly_dsm_v2022_entity_charges"
RPC_MONTHLY_REA_TEMPLATE_ID = "rpc_monthly_rea_v2024_station_pafm"
RPC_UI_ERA_TEMPLATE_ID = "rpc_weekly_dsm_v2014_ui_charges"
RPC_REA_9COL_TEMPLATE_ID = "rpc_monthly_rea_v2010_9_column_matrix"

RPC_SUPPORTED_TEMPLATE_IDS = frozenset(
    {
        RPC_WEEKLY_DSM_TEMPLATE_ID,
        RPC_MONTHLY_REA_TEMPLATE_ID,
    }
)
RPC_UNSUPPORTED_FAMILIES = frozenset(
    {
        RPC_UI_ERA_TEMPLATE_ID,
        RPC_REA_9COL_TEMPLATE_ID,
    }
)

_MONTH_NAMES = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


@dataclass(frozen=True)
class RpcDocumentClass:
    """Family, template, and accounting window inferred from public metadata."""

    family: str
    template_id: str
    supported: bool
    week_start: date | None = None
    week_end: date | None = None
    period_month: str | None = None
    reasons: tuple[str, ...] = ()


def classify_rpc_document(text: str) -> RpcDocumentClass:
    """Classify a filename, title, or heading without opening the workbook.

    Unsupported families are identified explicitly so the promoter can
    quarantine them instead of guessing a column map.
    """

    blob = " ".join(text.lower().split())
    period = parse_rpc_period(text)
    if _is_ui_era(blob):
        return RpcDocumentClass(
            family="weekly_dsm",
            template_id=RPC_UI_ERA_TEMPLATE_ID,
            supported=False,
            week_start=period.week_start,
            week_end=period.week_end,
            reasons=("unsupported_ui_era_dsm",),
        )
    if _is_legacy_nine_column_rea(blob):
        return RpcDocumentClass(
            family="monthly_rea",
            template_id=RPC_REA_9COL_TEMPLATE_ID,
            supported=False,
            period_month=period.period_month,
            reasons=("unsupported_9_column_rea_matrix",),
        )
    if "dsm" in blob or "deviation settlement" in blob:
        return RpcDocumentClass(
            family="weekly_dsm",
            template_id=RPC_WEEKLY_DSM_TEMPLATE_ID,
            supported=True,
            week_start=period.week_start,
            week_end=period.week_end,
        )
    if "rea" in blob or "regional energy account" in blob:
        return RpcDocumentClass(
            family="monthly_rea",
            template_id=RPC_MONTHLY_REA_TEMPLATE_ID,
            supported=True,
            period_month=period.period_month,
        )
    return RpcDocumentClass(
        family="unknown",
        template_id="rpc_unclassified",
        supported=False,
        reasons=("unrecognized_rpc_family",),
    )


@dataclass(frozen=True)
class RpcPeriod:
    """Optional week or month window parsed from public document text."""

    week_start: date | None = None
    week_end: date | None = None
    period_month: str | None = None


def parse_rpc_period(text: str) -> RpcPeriod:
    """Parse week bounds or a calendar month from a public RPC title."""

    week_start, week_end = _parse_week_bounds(text)
    return RpcPeriod(
        week_start=week_start,
        week_end=week_end,
        period_month=_parse_period_month(text),
    )


def iso_week_bounds(year: int, week: int) -> tuple[date, date]:
    """Return Monday-Sunday bounds for an ISO week used by RPC DSM accounts."""

    start = date.fromisocalendar(year, week, 1)
    return start, start + timedelta(days=6)


def _compact_alnum(blob: str) -> str:
    """Strip separators so ``Week_35`` and ``UI_Charges`` still classify."""

    return re.sub(r"[^a-z0-9]", "", blob.lower())


def _is_ui_era(blob: str) -> bool:
    """Return whether the document still uses Unscheduled Interchange charges."""

    compact = _compact_alnum(blob)
    return "uicharge" in compact or "unscheduledinterchange" in compact


def _is_legacy_nine_column_rea(blob: str) -> bool:
    """Return whether the document is a quarantined 9-column REA matrix."""

    compact = _compact_alnum(blob)
    return "9column" in compact or "ninecolumn" in compact


def _parse_week_bounds(text: str) -> tuple[date | None, date | None]:
    """Parse an inclusive week window from common RPC title patterns."""

    range_match = re.search(
        r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})[_\s\-–]*(?:to|-|–)[_\s\-–]*"
        r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})",
        text,
        flags=re.IGNORECASE,
    )
    if range_match:
        start = _calendar_date(*range_match.group(1, 2, 3))
        end = _calendar_date(*range_match.group(4, 5, 6))
        if start and end and start <= end:
            return start, end
    week_match = re.search(
        r"(?:^|[^a-z0-9])week[_\s-]*(\d{1,2})[_\s-]*(?:of[_\s-]*)?(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if week_match:
        return iso_week_bounds(int(week_match.group(2)), int(week_match.group(1)))
    compact_week = re.search(
        r"(?:^|[^a-z0-9])w(\d{1,2})[_-]?(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if compact_week:
        return iso_week_bounds(int(compact_week.group(2)), int(compact_week.group(1)))
    return None, None


def _parse_period_month(text: str) -> str | None:
    """Return ``YYYY-MM`` when a month name or numeric month is published."""

    named = re.search(
        r"(?:^|[^a-z0-9])(" + "|".join(_MONTH_NAMES) + r")[a-z]*[\s_\-/]+(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if named:
        month = _MONTH_NAMES[named.group(1).lower()[:3]]
        return f"{named.group(2)}-{month:02d}"
    # Prefer day-month-year fragments over ``YYYY_dd`` from ``2026_18-08-2026``.
    dmy = re.search(r"(?:^|[^\d])(\d{1,2})[./-](\d{1,2})[./-](20\d{2})", text)
    if dmy and 1 <= int(dmy.group(2)) <= 12:
        return f"{dmy.group(3)}-{int(dmy.group(2)):02d}"
    if re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", text):
        return None
    numeric = re.search(r"(?:^|[^\d])(20\d{2})[-_/](\d{1,2})(?:[^\d]|$)", text)
    if numeric and 1 <= int(numeric.group(2)) <= 12:
        return f"{numeric.group(1)}-{int(numeric.group(2)):02d}"
    numeric_rev = re.search(r"(?:^|[^\d])(\d{1,2})[-_/](20\d{2})(?:[^\d]|$)", text)
    if numeric_rev and 1 <= int(numeric_rev.group(1)) <= 12:
        return f"{numeric_rev.group(2)}-{int(numeric_rev.group(1)):02d}"
    return None


def _calendar_date(day: str, month: str, year: str) -> date | None:
    """Parse a day-first Indian calendar date, including two-digit years."""

    resolved_year = year if len(year) == 4 else f"20{year}"
    try:
        return datetime.strptime(f"{int(day):02d}-{int(month):02d}-{resolved_year}", "%d-%m-%Y").date()
    except ValueError:
        return None
