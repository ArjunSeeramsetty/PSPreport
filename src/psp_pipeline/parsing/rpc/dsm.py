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
    matched = False
    for table in tables:
        entity_binding = _best_binding(table, DSM_ENTITY_FIELDS)
        if entity_binding and entity_binding.contract_matched:
            matched = True
            skipped_fields.extend(entity_binding.skipped_fields)
            skipped_reasons.update(entity_binding.skipped_reasons)
            entity_rows.extend(_entity_rows(table, entity_binding))
            continue
        ancillary_binding = _best_binding(table, DSM_ANCILLARY_FIELDS)
        if ancillary_binding and ancillary_binding.contract_matched:
            matched = True
            skipped_fields.extend(ancillary_binding.skipped_fields)
            skipped_reasons.update(ancillary_binding.skipped_reasons)
            ancillary_rows.extend(_ancillary_rows(table, ancillary_binding))
            continue
        if _looks_like_ui_table(table):
            reasons.append("unsupported_ui_era_dsm")
    unique_skipped = tuple(dict.fromkeys(skipped_fields))
    return DsmParseResult(
        entity_rows=tuple(entity_rows),
        ancillary_rows=tuple(ancillary_rows),
        skipped_fields=unique_skipped,
        skipped_reasons=skipped_reasons,
        contract_matched=matched and bool(entity_rows or ancillary_rows),
        reasons=tuple(dict.fromkeys(reasons)),
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


def _entity_rows(table: ExtractedTable, binding: ColumnBinding) -> list[DsmEntityRow]:
    """Materialize constituent rows after the located DSM header."""

    header_index = locate_header_row(table.rows, DSM_ENTITY_FIELDS)
    if header_index is None:
        return []
    label_column = binding.columns["entity"]
    rows: list[DsmEntityRow] = []
    for offset, raw in enumerate(table.rows[header_index + 1 :], start=header_index + 2):
        cells = header_cells(raw)
        label = cells.get(label_column, "").strip()
        if _is_total_or_header(label):
            continue
        values, sources = _numeric_values(
            cells, binding, table.page_no, table.table_no, offset
        )
        if not values:
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
    return rows


def _ancillary_rows(
    table: ExtractedTable, binding: ColumnBinding
) -> list[DsmAncillaryRow]:
    """Materialize ancillary-service cash rows after a verified header."""

    header_index = locate_header_row(table.rows, DSM_ANCILLARY_FIELDS)
    if header_index is None:
        return []
    entity_column = binding.columns["entity"]
    service_column = binding.columns["ServiceType"]
    rows: list[DsmAncillaryRow] = []
    for offset, raw in enumerate(table.rows[header_index + 1 :], start=header_index + 2):
        cells = header_cells(raw)
        entity_name = cells.get(entity_column, "").strip()
        service = cells.get(service_column, "").strip()
        if _is_total_or_header(entity_name) or not service:
            continue
        values, sources = _numeric_values(
            cells, binding, table.page_no, table.table_no, offset
        )
        if not values:
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
    return rows


def _numeric_values(
    cells: dict[int, str],
    binding: ColumnBinding,
    page_no: int,
    table_no: int,
    row_no: int,
) -> tuple[dict[str, float], dict[str, tuple[int, int, int, int]]]:
    """Parse bound numeric columns, ignoring label fields and blanks."""

    values: dict[str, float] = {}
    sources: dict[str, tuple[int, int, int, int]] = {}
    for field_name, column in binding.columns.items():
        if field_name in {"entity", "ServiceType"}:
            continue
        text = cells.get(column, "")
        number = _parse_number(text)
        if number is None:
            continue
        values[field_name] = number
        sources[field_name] = (page_no, table_no, row_no, column)
    return values, sources


def _parse_number(text: str) -> float | None:
    """Parse a signed numeric cell, including Indian comma grouping."""

    compact = text.replace(",", "").replace("₹", "").strip()
    if not compact or compact in {"-", "--", "NA", "N/A", "nil"}:
        return None
    if compact.startswith("(") and compact.endswith(")"):
        compact = f"-{compact[1:-1]}"
    try:
        return float(compact)
    except ValueError:
        return None


def _is_total_or_header(label: str) -> bool:
    """Skip control totals and repeated header rows."""

    token = normalize_header_token(label)
    return not token or token.startswith("total") or token in {
        "entity",
        "constituent",
        "utility",
        "state",
        "beneficiary",
    }


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
