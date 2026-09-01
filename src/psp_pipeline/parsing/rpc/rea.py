"""Parse monthly REA station PAFM and beneficiary allocation tables by header."""

from __future__ import annotations

from dataclasses import dataclass
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


REA_STATION_FIELDS: dict[str, FieldSpec] = {
    "station": FieldSpec(
        aliases=(
            "station",
            "generatingstation",
            "isgs",
            "nameofthestation",
            "powerstation",
        ),
        required=True,
        is_label=True,
    ),
    "InstalledCapacityMW": FieldSpec(
        aliases=("installedcapacitymw", "icmw", "capacitymw"),
        required=True,
    ),
    "PAFMPct": FieldSpec(
        aliases=("pafmpct", "pafpct", "plantavailabilityfactor", "pafm"),
        required=True,
    ),
    "ScheduledGenerationMU": FieldSpec(
        aliases=("scheduledgenerationmu", "schedulegenerationmu", "scheduledmu"),
        required=False,
    ),
    "DeemedGenerationMU": FieldSpec(
        aliases=("deemedgenerationmu", "deemedmu"),
        required=True,
    ),
    "AuxiliaryConsumptionMU": FieldSpec(
        aliases=("auxiliaryconsumptionmu", "auxconsumptionmu", "auxmu"),
        required=False,
    ),
}

REA_ALLOCATION_FIELDS: dict[str, FieldSpec] = {
    "beneficiary": FieldSpec(
        aliases=("beneficiary", "constituent", "utility", "state", "entity"),
        required=True,
        is_label=True,
    ),
    "station": FieldSpec(
        aliases=("station", "generatingstation", "isgs", "powerstation"),
        required=True,
        is_label=True,
    ),
    "AllocationWindow": FieldSpec(
        aliases=("allocationwindow", "timeblock", "period", "peakoffpeak"),
        required=False,
        is_label=True,
    ),
    "PeakCapacityMW": FieldSpec(
        aliases=("peakcapacitymw", "peakallocationmw", "peakmw", "peaksharemw"),
        required=False,
        pair_group="capacity_window",
    ),
    "OffPeakCapacityMW": FieldSpec(
        aliases=(
            "offpeakcapacitymw",
            "offpeakallocationmw",
            "offpeakmw",
            "offpeaksharemw",
        ),
        required=False,
        pair_group="capacity_window",
    ),
    "AllocatedEnergyMU": FieldSpec(
        aliases=("allocatedenergymu", "energysharemu", "sharemu", "allocationmu"),
        required=False,
    ),
}

_NINE_COLUMN_LEGACY_TOKENS = (
    "paf",
    "peak",
    "offpeak",
    "deemed",
    "schedule",
    "aux",
    "share",
    "capacity",
    "energy",
)


@dataclass(frozen=True)
class ReaStationRow:
    """One ISGS station's monthly availability and deemed generation."""

    station_name: str
    values: dict[str, float]
    sources: dict[str, tuple[int, int, int, int]]
    page_no: int
    table_no: int
    row_no: int


@dataclass(frozen=True)
class ReaAllocationRow:
    """One beneficiary's peak or off-peak capacity/energy allocation."""

    beneficiary_name: str
    station_name: str
    allocation_window: str
    values: dict[str, float]
    sources: dict[str, tuple[int, int, int, int]]
    page_no: int
    table_no: int
    row_no: int


@dataclass(frozen=True)
class ReaParseResult:
    """Header-located REA rows, or an explicit unsupported-family quarantine."""

    station_rows: tuple[ReaStationRow, ...]
    allocation_rows: tuple[ReaAllocationRow, ...]
    skipped_fields: tuple[str, ...]
    skipped_reasons: dict[str, str]
    contract_matched: bool
    unsupported_family: str | None
    reasons: tuple[str, ...]


def parse_monthly_rea_tables(tables: tuple[ExtractedTable, ...]) -> ReaParseResult:
    """Parse REA station and allocation tables from published headers.

    Nine-column legacy matrices are refused rather than coerced into the
    peak/off-peak allocation contract.
    """

    station_rows: list[ReaStationRow] = []
    allocation_rows: list[ReaAllocationRow] = []
    skipped_fields: list[str] = []
    skipped_reasons: dict[str, str] = {}
    reasons: list[str] = []
    unsupported: str | None = None
    for table in tables:
        if _is_legacy_nine_column_matrix(table):
            unsupported = "rpc_monthly_rea_v2010_9_column_matrix"
            reasons.append("unsupported_9_column_rea_matrix")
            continue
        station_binding = _best_binding(table, REA_STATION_FIELDS)
        if station_binding and station_binding.contract_matched:
            skipped_fields.extend(station_binding.skipped_fields)
            skipped_reasons.update(station_binding.skipped_reasons)
            station_rows.extend(_station_rows(table, station_binding))
            continue
        allocation_binding = _best_binding(table, REA_ALLOCATION_FIELDS)
        if allocation_binding and _allocation_contract_matched(allocation_binding):
            skipped_fields.extend(allocation_binding.skipped_fields)
            skipped_reasons.update(allocation_binding.skipped_reasons)
            allocation_rows.extend(_allocation_rows(table, allocation_binding))
    matched = bool(station_rows or allocation_rows) and unsupported is None
    return ReaParseResult(
        station_rows=tuple(station_rows),
        allocation_rows=tuple(allocation_rows),
        skipped_fields=tuple(dict.fromkeys(skipped_fields)),
        skipped_reasons=skipped_reasons,
        contract_matched=matched,
        unsupported_family=unsupported,
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


def _allocation_contract_matched(binding: ColumnBinding) -> bool:
    """Require beneficiary, station, and at least one capacity or energy measure."""

    if "beneficiary" not in binding.columns or "station" not in binding.columns:
        return False
    measures = {
        "PeakCapacityMW",
        "OffPeakCapacityMW",
        "AllocatedEnergyMU",
    }
    return bool(measures.intersection(binding.columns))


def _station_rows(table: ExtractedTable, binding: ColumnBinding) -> list[ReaStationRow]:
    """Materialize ISGS station rows after the located PAFM header."""

    header_index = locate_header_row(table.rows, REA_STATION_FIELDS)
    if header_index is None:
        return []
    label_column = binding.columns["station"]
    rows: list[ReaStationRow] = []
    for offset, raw in enumerate(table.rows[header_index + 1 :], start=header_index + 2):
        cells = header_cells(raw)
        label = cells.get(label_column, "").strip()
        if _is_total_or_header(label):
            continue
        values, sources = _numeric_values(
            cells, binding, table.page_no, table.table_no, offset, {"station"}
        )
        if not values:
            continue
        rows.append(
            ReaStationRow(
                station_name=re.sub(r"\s+", " ", label),
                values=values,
                sources=sources,
                page_no=table.page_no,
                table_no=table.table_no,
                row_no=offset,
            )
        )
    return rows


def _allocation_rows(
    table: ExtractedTable, binding: ColumnBinding
) -> list[ReaAllocationRow]:
    """Expand peak and off-peak capacity columns into windowed allocation rows."""

    header_index = locate_header_row(table.rows, REA_ALLOCATION_FIELDS)
    if header_index is None:
        return []
    beneficiary_column = binding.columns["beneficiary"]
    station_column = binding.columns["station"]
    window_column = binding.columns.get("AllocationWindow")
    rows: list[ReaAllocationRow] = []
    for offset, raw in enumerate(table.rows[header_index + 1 :], start=header_index + 2):
        cells = header_cells(raw)
        beneficiary = cells.get(beneficiary_column, "").strip()
        station = cells.get(station_column, "").strip()
        if _is_total_or_header(beneficiary) or not station:
            continue
        explicit_window = (
            _normalize_window(cells.get(window_column, "")) if window_column else None
        )
        rows.extend(
            _windowed_allocations(
                beneficiary=beneficiary,
                station=station,
                explicit_window=explicit_window,
                cells=cells,
                binding=binding,
                page_no=table.page_no,
                table_no=table.table_no,
                row_no=offset,
            )
        )
    return rows


def _windowed_allocations(
    *,
    beneficiary: str,
    station: str,
    explicit_window: str | None,
    cells: dict[int, str],
    binding: ColumnBinding,
    page_no: int,
    table_no: int,
    row_no: int,
) -> list[ReaAllocationRow]:
    """Emit one allocation row per peak/off-peak window present on the source row."""

    windows: list[tuple[str, dict[str, float], dict[str, tuple[int, int, int, int]]]] = []
    peak = _optional_number(cells, binding.columns.get("PeakCapacityMW"))
    off_peak = _optional_number(cells, binding.columns.get("OffPeakCapacityMW"))
    energy = _optional_number(cells, binding.columns.get("AllocatedEnergyMU"))
    peak_col = binding.columns.get("PeakCapacityMW")
    off_peak_col = binding.columns.get("OffPeakCapacityMW")
    energy_col = binding.columns.get("AllocatedEnergyMU")
    if peak is not None and peak_col is not None:
        windows.append(
            (
                "peak",
                {"AllocatedCapacityMW": peak},
                {"AllocatedCapacityMW": (page_no, table_no, row_no, peak_col)},
            )
        )
    if off_peak is not None and off_peak_col is not None:
        windows.append(
            (
                "off_peak",
                {"AllocatedCapacityMW": off_peak},
                {"AllocatedCapacityMW": (page_no, table_no, row_no, off_peak_col)},
            )
        )
    if explicit_window and not windows:
        values: dict[str, float] = {}
        sources: dict[str, tuple[int, int, int, int]] = {}
        if energy is not None and energy_col is not None:
            values["AllocatedEnergyMU"] = energy
            sources["AllocatedEnergyMU"] = (page_no, table_no, row_no, energy_col)
        if values:
            windows.append((explicit_window, values, sources))
    elif energy is not None and energy_col is not None:
        energy_source = (page_no, table_no, row_no, energy_col)
        if windows:
            for _window, values, sources in windows:
                values["AllocatedEnergyMU"] = energy
                sources["AllocatedEnergyMU"] = energy_source
        else:
            windows.append(
                (
                    explicit_window or "round_the_clock",
                    {"AllocatedEnergyMU": energy},
                    {"AllocatedEnergyMU": energy_source},
                )
            )
    return [
        ReaAllocationRow(
            beneficiary_name=re.sub(r"\s+", " ", beneficiary),
            station_name=re.sub(r"\s+", " ", station),
            allocation_window=window,
            values=values,
            sources=sources,
            page_no=page_no,
            table_no=table_no,
            row_no=row_no,
        )
        for window, values, sources in windows
        if values
    ]


def _numeric_values(
    cells: dict[int, str],
    binding: ColumnBinding,
    page_no: int,
    table_no: int,
    row_no: int,
    label_fields: set[str],
) -> tuple[dict[str, float], dict[str, tuple[int, int, int, int]]]:
    """Parse bound numeric columns, ignoring label fields and blanks."""

    values: dict[str, float] = {}
    sources: dict[str, tuple[int, int, int, int]] = {}
    for field_name, column in binding.columns.items():
        if field_name in label_fields:
            continue
        number = _parse_number(cells.get(column, ""))
        if number is None:
            continue
        values[field_name] = number
        sources[field_name] = (page_no, table_no, row_no, column)
    return values, sources


def _optional_number(cells: dict[int, str], column: int | None) -> float | None:
    """Return a numeric value when the column exists and parses."""

    if column is None:
        return None
    return _parse_number(cells.get(column, ""))


def _parse_number(text: str) -> float | None:
    """Parse a signed numeric cell, including Indian comma grouping."""

    compact = text.replace(",", "").replace("%", "").strip()
    if not compact or compact in {"-", "--", "NA", "N/A", "nil"}:
        return None
    try:
        return float(compact)
    except ValueError:
        return None


def _is_total_or_header(label: str) -> bool:
    """Skip control totals and repeated header rows."""

    token = normalize_header_token(label)
    return not token or token.startswith("total") or token in {
        "station",
        "beneficiary",
        "constituent",
        "utility",
        "state",
        "isgs",
    }


def _normalize_window(value: str) -> str:
    """Collapse publisher peak/off-peak labels onto the allocation grain."""

    token = normalize_header_token(value)
    if "offpeak" in token:
        return "off_peak"
    if "peak" in token:
        return "peak"
    if "rtc" in token or "roundtheclock" in token:
        return "round_the_clock"
    return re.sub(r"\s+", " ", value).strip().lower() or "round_the_clock"


def _is_legacy_nine_column_matrix(table: ExtractedTable) -> bool:
    """Refuse 9-column REA matrices whose grain cannot be mapped uniquely."""

    if not table.rows:
        return False
    width = max(len(row) for row in table.rows)
    if width != 9:
        return False
    tokens = {
        normalize_header_token(cell)
        for row in table.rows[:4]
        for cell in row
        if cell.strip()
    }
    hits = sum(1 for token in _NINE_COLUMN_LEGACY_TOKENS if any(token in item for item in tokens))
    has_pafm = any("pafm" in item or item == "paf" for item in tokens)
    has_distinct_windows = any("offpeak" in item for item in tokens) and any(
        item == "peak" or item.endswith("peakmw") for item in tokens
    )
    return hits >= 6 and has_pafm and not has_distinct_windows
