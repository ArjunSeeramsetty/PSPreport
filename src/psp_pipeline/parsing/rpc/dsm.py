"""Parse weekly DSM entity charges and ancillary-service payments by header."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from psp_pipeline.parsing.rpc.headers import (
    ColumnBinding,
    FieldSpec,
    bind_header_columns,
    header_cells,
    locate_header_row,
    normalize_header_token,
)
from psp_pipeline.parsing.rpc.tables import ExtractedTable


DSM_ENTITY_FIELDS: dict[str, FieldSpec] = {
    "entity": FieldSpec(
        aliases=(
            "entity",
            "constituent",
            "utility",
            "nameoftheutility",
            "nameofutility",
            "beneficiary",
            "state",
            "nameofentity",
            "nameofconstituent",
        ),
        required=True,
        is_label=True,
    ),
    "ScheduledEnergyMU": FieldSpec(
        aliases=("scheduledenergymu", "schedulemu", "scheduledmu", "scheduleenergy"),
        required=True,
    ),
    "ActualEnergyMU": FieldSpec(
        aliases=("actualenergymu", "actualmu", "actualenergy"),
        required=True,
    ),
    "DeviationMU": FieldSpec(
        aliases=("deviationmu", "deviationenergymu", "netdeviationmu"),
        required=True,
    ),
    "FrequencyLinkedDeviationChargeRs": FieldSpec(
        aliases=(
            "frequencylinkeddeviationcharge",
            "frequencylinkeddeviationcharges",
            "frequencylinkedcharge",
            "frequencylinkedcharges",
            "dsmcharge",
            "dsmcharges",
            "deviationcharge",
            "deviationcharges",
        ),
        required=False,
        pair_group="dsm_charge",
    ),
    "SustainedDeviationPenaltyRs": FieldSpec(
        aliases=(
            "sustaineddeviationpenalty",
            "additionaldsmcharge",
            "additionaldsmcharges",
            "additionaldeviationcharge",
            "additionaldeviationcharges",
            "adc",
        ),
        required=False,
        pair_group="dsm_charge",
    ),
    "SignChangeViolationChargeRs": FieldSpec(
        aliases=(
            "signchangeviolationcharge",
            "signchangeviolationcharges",
            "signchange",
            "signviolationcharge",
            "signviolationcharges",
        ),
        required=False,
    ),
    "NetPayableReceivableRs": FieldSpec(
        aliases=(
            "netpayablereceivable",
            "netdsm",
            "payablereceivable",
            "netpayable",
            "netreceivable",
        ),
        required=False,
    ),
}

DSM_ANCILLARY_FIELDS: dict[str, FieldSpec] = {
    "entity": FieldSpec(
        aliases=("entity", "constituent", "utility", "beneficiary", "state"),
        required=True,
        is_label=True,
    ),
    "ServiceType": FieldSpec(
        aliases=("servicetype", "ancillaryservice", "product", "service"),
        required=True,
        is_label=True,
    ),
    "PayableRs": FieldSpec(
        aliases=("payable", "payment", "aspayable"),
        required=False,
        pair_group="ancillary_cash",
    ),
    "ReceivableRs": FieldSpec(
        aliases=("receivable", "receipts", "asreceivable"),
        required=False,
        pair_group="ancillary_cash",
    ),
    "NetRs": FieldSpec(
        aliases=("net", "netancillary", "netas"),
        required=False,
    ),
}


@dataclass(frozen=True)
class DsmEntityRow:
    """One constituent's weekly DSM energy and frequency-linked charges."""

    entity_name: str
    values: dict[str, float]
    sources: dict[str, tuple[int, int, int, int]]
    page_no: int
    table_no: int
    row_no: int


@dataclass(frozen=True)
class DsmAncillaryRow:
    """One constituent's weekly ancillary-service payable/receivable."""

    entity_name: str
    service_type: str
    values: dict[str, float]
    sources: dict[str, tuple[int, int, int, int]]
    page_no: int
    table_no: int
    row_no: int


@dataclass(frozen=True)
class DsmParseResult:
    """Header-located DSM rows plus skipped malformed charge pairs."""

    entity_rows: tuple[DsmEntityRow, ...]
    ancillary_rows: tuple[DsmAncillaryRow, ...]
    skipped_fields: tuple[str, ...]
    skipped_reasons: dict[str, str]
    contract_matched: bool
    reasons: tuple[str, ...]
    rejected_row_count: int = 0
    rejected_reasons: dict[str, int] | None = None


def parse_weekly_dsm_tables(
    tables: tuple[ExtractedTable, ...],
    *,
    week_start: date | None = None,
    week_end: date | None = None,
) -> DsmParseResult:
    """Parse DSM entity and ancillary tables wherever their headers appear.

    A malformed frequency-linked / additional-charge pair is skipped without
    dropping scheduled, actual, or deviation energy from clean columns.
    """

    _ = (week_start, week_end)
    entity_rows: list[DsmEntityRow] = []
    ancillary_rows: list[DsmAncillaryRow] = []
    skipped_fields: list[str] = []
    skipped_reasons: dict[str, str] = {}
    reasons: list[str] = []
    rejected_reasons: dict[str, int] = {}
    matched = False
    for table in tables:
        entity_binding = _best_binding(table, DSM_ENTITY_FIELDS)
        if entity_binding and entity_binding.contract_matched:
            matched = True
            skipped_fields.extend(entity_binding.skipped_fields)
            skipped_reasons.update(entity_binding.skipped_reasons)
            rows, rejections = _entity_rows(table, entity_binding)
            entity_rows.extend(rows)
            _merge_rejection_counts(rejected_reasons, rejections)
            continue
        ancillary_binding = _best_binding(table, DSM_ANCILLARY_FIELDS)
        if ancillary_binding and ancillary_binding.contract_matched:
            matched = True
            skipped_fields.extend(ancillary_binding.skipped_fields)
            skipped_reasons.update(ancillary_binding.skipped_reasons)
            rows, rejections = _ancillary_rows(table, ancillary_binding)
            ancillary_rows.extend(rows)
            _merge_rejection_counts(rejected_reasons, rejections)
            continue
        if _looks_like_ui_table(table):
            reasons.append("unsupported_ui_era_dsm")
    unique_skipped = tuple(dict.fromkeys(skipped_fields))
    rejected_row_count = sum(rejected_reasons.values())
    return DsmParseResult(
        entity_rows=tuple(entity_rows),
        ancillary_rows=tuple(ancillary_rows),
        skipped_fields=unique_skipped,
        skipped_reasons=skipped_reasons,
        contract_matched=matched and bool(entity_rows or ancillary_rows),
        reasons=tuple(dict.fromkeys(reasons)),
        rejected_row_count=rejected_row_count,
        rejected_reasons=rejected_reasons,
    )


def _best_binding(
    table: ExtractedTable,
    specs: dict[str, FieldSpec],
) -> ColumnBinding | None:
    """Bind the first header row that satisfies the required field contract."""

    header_index = locate_header_row(table.rows, specs)
    if header_index is None:
        return None
    return bind_header_columns(table.rows[header_index], specs)


def _entity_rows(
    table: ExtractedTable, binding: ColumnBinding
) -> tuple[list[DsmEntityRow], dict[str, int]]:
    """Materialize constituent rows after the located DSM header.

    A row is promoted only when scheduled, actual, and deviation energy all
    parse. Repeated mid-table headers and partial numeric rows are counted as
    rejections instead of writing a truncated settlement fact.
    """

    header_index = locate_header_row(table.rows, DSM_ENTITY_FIELDS)
    if header_index is None:
        return [], {}
    label_column = binding.columns["entity"]
    rows: list[DsmEntityRow] = []
    rejections: dict[str, int] = {}
    required = ("ScheduledEnergyMU", "ActualEnergyMU", "DeviationMU")
    for offset, raw in enumerate(table.rows[header_index + 1 :], start=header_index + 2):
        cells = header_cells(raw)
        label = cells.get(label_column, "").strip()
        if _is_repeated_header(label):
            _bump_rejection(rejections, "repeated_header")
            continue
        if _is_total_row(label):
            continue
        values, sources, reason = _numeric_values(
            cells,
            binding,
            table.page_no,
            table.table_no,
            offset,
            required_fields=required,
            label_fields={"entity"},
        )
        if reason:
            _bump_rejection(rejections, reason)
            continue
        rows.append(
            DsmEntityRow(
                entity_name=re.sub(r"\s+", " ", label),
                values=values,
                sources=sources,
                page_no=table.page_no,
                table_no=table.table_no,
                row_no=offset,
            )
        )
    return rows, rejections


def _ancillary_rows(
    table: ExtractedTable, binding: ColumnBinding
) -> tuple[list[DsmAncillaryRow], dict[str, int]]:
    """Materialize ancillary-service cash rows after a verified header."""

    header_index = locate_header_row(table.rows, DSM_ANCILLARY_FIELDS)
    if header_index is None:
        return [], {}
    entity_column = binding.columns["entity"]
    service_column = binding.columns["ServiceType"]
    rows: list[DsmAncillaryRow] = []
    rejections: dict[str, int] = {}
    cash_fields = ("PayableRs", "ReceivableRs", "NetRs")
    for offset, raw in enumerate(table.rows[header_index + 1 :], start=header_index + 2):
        cells = header_cells(raw)
        entity_name = cells.get(entity_column, "").strip()
        service = cells.get(service_column, "").strip()
        if _is_repeated_header(entity_name):
            _bump_rejection(rejections, "repeated_header")
            continue
        if _is_total_row(entity_name) or not service:
            continue
        values, sources, reason = _numeric_values(
            cells,
            binding,
            table.page_no,
            table.table_no,
            offset,
            required_any=cash_fields,
            label_fields={"entity", "ServiceType"},
        )
        if reason:
            _bump_rejection(rejections, reason)
            continue
        rows.append(
            DsmAncillaryRow(
                entity_name=re.sub(r"\s+", " ", entity_name),
                service_type=_normalize_service(service),
                values=values,
                sources=sources,
                page_no=table.page_no,
                table_no=table.table_no,
                row_no=offset,
            )
        )
    return rows, rejections


def _numeric_values(
    cells: dict[int, str],
    binding: ColumnBinding,
    page_no: int,
    table_no: int,
    row_no: int,
    *,
    required_fields: tuple[str, ...] = (),
    required_any: tuple[str, ...] = (),
    label_fields: set[str] | None = None,
) -> tuple[dict[str, float], dict[str, tuple[int, int, int, int]], str | None]:
    """Parse bound numeric columns and enforce row-level required fields.

    Returns values, sources, and a rejection reason when the row must not
    promote. Invalid numeric text in a bound column fails closed even if other
    optional fields parsed.
    """

    labels = label_fields or {"entity", "ServiceType"}
    values: dict[str, float] = {}
    sources: dict[str, tuple[int, int, int, int]] = {}
    for field_name, column in binding.columns.items():
        if field_name in labels:
            continue
        cell_text = cells.get(column, "")
        number, invalid = _parse_number_status(cell_text)
        if invalid:
            return {}, {}, "invalid_numeric"
        if number is None:
            continue
        values[field_name] = number
        sources[field_name] = (page_no, table_no, row_no, column)
    if any(name not in values for name in required_fields):
        return {}, {}, "missing_required_energy"
    if required_any and not any(name in values for name in required_any):
        return {}, {}, "missing_required_measure"
    if not values:
        return {}, {}, "missing_required_measure"
    return values, sources, None


def _parse_number(text: str) -> float | None:
    """Parse a signed numeric cell, including Indian comma grouping."""

    number, _invalid = _parse_number_status(text)
    return number


def _parse_number_status(text: str) -> tuple[float | None, bool]:
    """Return ``(value, invalid)`` distinguishing blanks from garbage text."""

    compact = text.replace(",", "").replace("₹", "").strip()
    if not compact or compact in {"-", "--", "NA", "N/A", "nil"}:
        return None, False
    if compact.startswith("(") and compact.endswith(")"):
        compact = f"-{compact[1:-1]}"
    try:
        return float(compact), False
    except ValueError:
        return None, True


def _is_repeated_header(label: str) -> bool:
    """Return whether a data-row label is a repeated table heading."""

    token = normalize_header_token(label)
    return token in {
        "entity",
        "constituent",
        "utility",
        "state",
        "beneficiary",
        "nameofentity",
        "nameofconstituent",
        "nameoftheutility",
        "nameofutility",
    }


def _is_total_row(label: str) -> bool:
    """Skip control-total rows that are not settlement constituents."""

    token = normalize_header_token(label)
    return not token or token.startswith("total")


def _is_total_or_header(label: str) -> bool:
    """Skip control totals and repeated header rows."""

    return _is_total_row(label) or _is_repeated_header(label)


def _bump_rejection(counts: dict[str, int], reason: str) -> None:
    """Increment one row-level rejection reason."""

    counts[reason] = counts.get(reason, 0) + 1


def _merge_rejection_counts(target: dict[str, int], incoming: dict[str, int]) -> None:
    """Merge per-table rejection counts into the parse result."""

    for reason, count in incoming.items():
        target[reason] = target.get(reason, 0) + count


def _normalize_service(value: str) -> str:
    """Collapse publisher variants onto SRAS/TRAS/other ancillary names."""

    token = normalize_header_token(value)
    if "sras" in token or "secondaryreserve" in token:
        return "SRAS"
    if "tras" in token or "tertiaryreserve" in token:
        return "TRAS"
    if "rras" in token:
        return "RRAS"
    return re.sub(r"\s+", " ", value).strip().upper()


def _looks_like_ui_table(table: ExtractedTable) -> bool:
    """Detect Unscheduled Interchange tables that must not be promoted."""

    blob = " ".join(cell for row in table.rows for cell in row).lower()
    compact = re.sub(r"[^a-z0-9]", "", blob)
    return "unscheduledinterchange" in compact or "uicharge" in compact
