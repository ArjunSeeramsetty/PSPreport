"""Promote verified WRLDC PSP regional, state, and station-generation facts."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3

from psp_pipeline.parsing.rldc.templates import (
    WRLDC_2023_REVISED_TEMPLATE,
    WRLDC_2023_TEMPLATE,
    WRLDC_2024_TEMPLATE,
    WRLDC_2024_REVISED_TEMPLATE,
    WRLDC_2024_TRANSITION_TEMPLATE,
    WRLDC_2025_REVISED_TEMPLATE,
    WRLDC_2025_TEMPLATE,
    WRLDC_2026_EARLY_TEMPLATE,
    WRLDC_2026_TEMPLATE,
)
from psp_pipeline.storage.sqlite_dimensions import (
    DimensionResolutionError,
    record_resolution_issue,
    resolve_generation_identity,
    resolve_state_id,
)
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema
from psp_pipeline.storage.sqlite_wrldc_enrichment import (
    transmission_location,
    voltage_node_location,
)


WR_REGION_NAME = "Western Region"
WRLDC_11_COLUMN_TEMPLATE_IDS = frozenset(
    template.template_id
    for template in (
        WRLDC_2024_REVISED_TEMPLATE,
        WRLDC_2024_TRANSITION_TEMPLATE,
        WRLDC_2025_TEMPLATE,
        WRLDC_2025_REVISED_TEMPLATE,
        WRLDC_2026_EARLY_TEMPLATE,
        WRLDC_2026_TEMPLATE,
    )
)
WRLDC_9_COLUMN_TEMPLATE_IDS = frozenset(
    template.template_id
    for template in (
        WRLDC_2023_TEMPLATE,
        WRLDC_2023_REVISED_TEMPLATE,
        WRLDC_2024_TEMPLATE,
    )
)
WRLDC_GENERATION_TEMPLATE_IDS = (
    WRLDC_9_COLUMN_TEMPLATE_IDS | WRLDC_11_COLUMN_TEMPLATE_IDS
)
WRLDC_2026_OPERATIONAL_TEMPLATE_IDS = frozenset(
    {
        WRLDC_2026_EARLY_TEMPLATE.template_id,
        WRLDC_2026_TEMPLATE.template_id,
    }
)
WRLDC_OPERATIONAL_TEMPLATE_IDS = frozenset(
    {
        WRLDC_2024_REVISED_TEMPLATE.template_id,
        WRLDC_2024_TRANSITION_TEMPLATE.template_id,
        WRLDC_2025_TEMPLATE.template_id,
        WRLDC_2025_REVISED_TEMPLATE.template_id,
        *WRLDC_2026_OPERATIONAL_TEMPLATE_IDS,
    }
)

_REGIONAL_COLUMNS = {
    "EveningPeakDemandMetMW": 1,
    "EveningPeakShortageMW": 2,
    "EveningPeakRequirementMW": 7,
    "EveningPeakFrequencyHz": 11,
    "OffPeakDemandMetMW": 14,
    "OffPeakShortageMW": 18,
    "OffPeakRequirementMW": 25,
    "OffPeakFrequencyHz": 30,
    "DayEnergyMetMU": 32,
    "DayEnergyShortageMU": 38,
}
_STATE_BALANCE_COLUMNS = {
    "ThermalGenerationMU": 4,
    "HydroGenerationMU": 5,
    "GasNapthaDieselGenerationMU": 9,
    "WindGenerationMU": 12,
    "SolarGenerationMU": 14,
    "OtherGenerationMU": 16,
    "TotalGenerationMU": 20,
    "ScheduledDrawalMU": 24,
    "ActualDrawalMU": 28,
    "UIMU": 31,
    "TotalAvailabilityMU": 33,
    "RequirementMU": 36,
    "EnergyShortageMU": 39,
    "ConsumptionMU": 42,
}
_STATE_FORECAST_COLUMNS = {
    "EveningPeakDemandMetMW": 3,
    "EveningPeakShortageMW": 6,
    "EveningPeakRequirementMW": 13,
    "OffPeakDemandMetMW": 15,
    "OffPeakShortageMW": 21,
    "OffPeakRequirementMW": 29,
    "AverageDemandMW": 32,
    "ForecastDemandMU": 35,
    "ForecastDeviationMU": 40,
}
_STATE_PEAK_COLUMNS = {
    "MaximumDemandMetMW": 3,
    "MaximumDemandTime": 8,
    "MaximumDemandShortageMW": 13,
    "MaximumDemandRequirementMW": 19,
    "MaximumACEMW": 26,
    "MaximumACETime": 31,
    "MinimumACEMW": 35,
    "MinimumACETime": 41,
}
_GENERATION_COLUMNS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 4,
    "DayPeakMW": 5,
    "DayPeakTime": 6,
    "MinimumGenerationMW": 7,
    "MinimumGenerationTime": 8,
    "GrossEnergyMU": 9,
    "NetEnergyMU": 10,
    "AverageMW": 11,
}
_NINE_COLUMN_GENERATION_COLUMNS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 4,
    "DayPeakMW": 5,
    "DayPeakTime": 6,
    "GrossEnergyMU": 7,
    "NetEnergyMU": 8,
    "AverageMW": 9,
}
_RENEWABLE_PAGE_FIVE_COLUMNS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 4,
    "DayPeakMW": 5,
    "DayPeakTime": 6,
    "MinimumGenerationMW": 7,
    "MinimumGenerationTime": 8,
    "ScheduledEnergyMU": 9,
    "GrossEnergyMU": 10,
    "NetEnergyMU": 11,
    "AverageMW": 12,
}
_RENEWABLE_PAGE_SIX_COLUMNS = {
    "InstalledCapacityMW": 5,
    "EveningPeakMW": 7,
    "OffPeakMW": 8,
    "DayPeakMW": 10,
    "DayPeakTime": 13,
    "MinimumGenerationMW": 14,
    "MinimumGenerationTime": 16,
    "ScheduledEnergyMU": 17,
    "GrossEnergyMU": 18,
    "NetEnergyMU": 20,
    "AverageMW": 23,
}
_STATE_SPARSE_GENERATION_COLUMNS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 5,
    "DayPeakMW": 7,
    "DayPeakTime": 9,
    "MinimumGenerationMW": 11,
    "MinimumGenerationTime": 14,
    "GrossEnergyMU": 16,
    "NetEnergyMU": 18,
    "AverageMW": 20,
}
_REGIONAL_SPARSE_GENERATION_COLUMNS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 4,
    "DayPeakMW": 6,
    "DayPeakTime": 8,
    "MinimumGenerationMW": 10,
    "MinimumGenerationTime": 12,
    "ScheduledEnergyMU": 13,
    "GrossEnergyMU": 15,
    "NetEnergyMU": 17,
    "AverageMW": 19,
}
_IPP_JV_GENERATION_COLUMNS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 4,
    "DayPeakMW": 5,
    "DayPeakTime": 6,
    "MinimumGenerationMW": 7,
    "MinimumGenerationTime": 8,
    "ScheduledEnergyMU": 9,
    "GrossEnergyMU": 10,
    "NetEnergyMU": 11,
    "AverageMW": 12,
}
_CONVENTIONAL_GENERATION_TEMPLATE_IDS = WRLDC_GENERATION_TEMPLATE_IDS
_NINE_COLUMN_REGIONAL_GENERATION_COLUMNS = {
    "InstalledCapacityMW": 2,
    "EveningPeakMW": 3,
    "OffPeakMW": 4,
    "DayPeakMW": 6,
    "DayPeakTime": 8,
    "MinimumGenerationMW": 10,
    "MinimumGenerationTime": 12,
    "GrossEnergyMU": 14,
    "NetEnergyMU": 16,
    "AverageMW": 18,
}
_CONVENTIONAL_STATE_COLUMN_CANDIDATES = (
    _STATE_SPARSE_GENERATION_COLUMNS,
    _NINE_COLUMN_GENERATION_COLUMNS,
    _NINE_COLUMN_REGIONAL_GENERATION_COLUMNS,
)
_CONVENTIONAL_REGIONAL_COLUMN_CANDIDATES = (
    _REGIONAL_SPARSE_GENERATION_COLUMNS,
    _NINE_COLUMN_REGIONAL_GENERATION_COLUMNS,
    _NINE_COLUMN_GENERATION_COLUMNS,
)
_CONVENTIONAL_CONTINUATION_COLUMN_CANDIDATES = (
    _IPP_JV_GENERATION_COLUMNS,
    _NINE_COLUMN_REGIONAL_GENERATION_COLUMNS,
    _NINE_COLUMN_GENERATION_COLUMNS,
)
_GENERATION_HEADER_TOKENS = {
    "InstalledCapacityMW": "instcapacity",
    "EveningPeakMW": "peakmw",
    "OffPeakMW": "offpeakmw",
    "DayPeakMW": "daypeak",
    "DayPeakTime": "hrs",
    "MinimumGenerationMW": "mingeneration",
    "MinimumGenerationTime": "hrs",
    "ScheduledEnergyMU": "schdmu",
    "GrossEnergyMU": "grossmu",
    "NetEnergyMU": "netmu",
    "AverageMW": "avgmw",
}
_WRLDC_MARKET_GEOGRAPHIC_LABELS = frozenset(
    {
        "CHHATTISGARH",
        "GOA",
        "GUJARAT",
        "MADHYAPRADESH",
        "MP",
        "MAHARASHTRA",
    }
)


def promote_wrldc_report_to_curated(
    conn: sqlite3.Connection,
    report_document_id: int,
) -> None:
    """Promote verified WRLDC PSP facts with raw-cell lineage.

    Approved nine- and eleven-column state-generation layouts are supported.
    Conventional page-three and page-four grids promote for every approved
    family after a complete two-row header match. The 2024-revised,
    2024-transition, 2025, and 2026 families also promote verified
    operational and market sections when those pages match a fixture-backed
    contract.
    """
    ensure_curated_sqlite_schema(conn)
    report = _fetch_report(conn, report_document_id)
    if not report or report["rldc"] != "wrldc":
        return
    template_id = str(report["template_id"] or "")
    if template_id not in WRLDC_GENERATION_TEMPLATE_IDS or _scope_is_affected(report):
        return

    date_id = _get_or_create_date_id(conn, str(report["report_date"]))
    region_id = _region_id(conn)
    if date_id is None or region_id is None:
        return

    _upsert_dim_report(conn, date_id, report)
    _clear_wrldc_facts(conn, report_document_id)
    mapped_cells: set[int] = set()
    _promote_regional_daily(conn, report_document_id, date_id, region_id, mapped_cells)
    _promote_state_sections(conn, report_document_id, date_id, mapped_cells)
    _promote_state_generation(
        conn,
        report_document_id,
        date_id,
        region_id,
        template_id,
        mapped_cells,
    )
    if (
        template_id in _CONVENTIONAL_GENERATION_TEMPLATE_IDS
        and not _conventional_generation_scope_is_affected(report)
    ):
        _promote_conventional_generation(
            conn,
            report_document_id,
            date_id,
            region_id,
            mapped_cells,
        )
    if (
        template_id in WRLDC_OPERATIONAL_TEMPLATE_IDS
        and not _renewable_scope_is_affected(report)
    ):
        _promote_renewable_generation(
            conn,
            report_document_id,
            date_id,
            region_id,
            mapped_cells,
        )
    if template_id in WRLDC_OPERATIONAL_TEMPLATE_IDS:
        _promote_physical_exchanges(
            conn,
            report_document_id,
            date_id,
            template_id,
            mapped_cells,
        )
        _promote_voltage_profiles(
            conn,
            report_document_id,
            date_id,
            region_id,
            template_id,
            mapped_cells,
        )
        _promote_reservoirs(
            conn,
            report_document_id,
            date_id,
            region_id,
            template_id,
            mapped_cells,
        )
        _promote_frequency_daily(
            conn,
            report_document_id,
            date_id,
            region_id,
            template_id,
            mapped_cells,
        )
        if not _market_energy_scope_is_affected(report):
            _promote_market_day_energy(
                conn,
                report_document_id,
                date_id,
                region_id,
                mapped_cells,
            )
            _promote_market_points_and_extrema(
                conn, report_document_id, date_id, region_id, mapped_cells
            )


def _scope_is_affected(report: sqlite3.Row) -> bool:
    """Block only structural drift that touches WRLDC pages owned by this promoter."""
    if not report["semantic_pass_required"]:
        return False
    reason = str(report["structure_deviation_reason"] or "")
    return bool(re.search(r"(?:p[1-3]_t|missing_table=p[1-3]_)", reason))


def _renewable_scope_is_affected(report: dict[str, object]) -> bool:
    """Return whether an approved renewable-table page is structurally drifted."""

    if not report["semantic_pass_required"]:
        return False
    reason = str(report["structure_deviation_reason"] or "")
    return bool(re.search(r"(?:p[5-6]_t|missing_table=p[5-6]_)", reason))


def _market_energy_scope_is_affected(report: dict[str, object]) -> bool:
    """Return whether the verified page 7/8 day-energy section has drifted."""

    if not report["semantic_pass_required"]:
        return False
    reason = str(report["structure_deviation_reason"] or "")
    return bool(re.search(r"(?:p[7-8]_t|missing_table=p[7-8]_)", reason))


def _conventional_generation_scope_is_affected(report: dict[str, object]) -> bool:
    """Return whether the verified page-three or page-four grids drifted."""

    if not report["semantic_pass_required"]:
        return False
    reason = str(report["structure_deviation_reason"] or "")
    return bool(re.search(r"(?:p[3-4]_t|missing_table=p[3-4]_)", reason))


def _promote_regional_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    row = _table_row(conn, report_id, 1, 1, 4)
    values, sources = _values(row, _REGIONAL_COLUMNS)
    if not any(value is not None for value in values.values()):
        return
    _insert_fact(
        conn,
        "FactWRLDCRegionalDaily",
        {"ReportDocumentID": report_id, "DateID": date_id, "RegionID": region_id, **values},
    )
    _write_lineage(
        conn,
        report_id,
        "FactWRLDCRegionalDaily",
        f"report={report_id};date={date_id};region={region_id}",
        sources,
        mapped_cells,
    )


def _promote_state_sections(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
) -> None:
    sections = (("2(a)", _STATE_BALANCE_COLUMNS), ("2(b)", _STATE_FORECAST_COLUMNS), ("2(c)", _STATE_PEAK_COLUMNS))
    rows = _table_rows(conn, report_id, 1, 1)
    for marker, columns in sections:
        for row in _section_rows(rows, marker):
            state_cell = row.get(1)
            state_id = _resolve_state_id(conn, report_id, state_cell[1] if state_cell else "")
            if state_id is None:
                continue
            values, sources = _values(row, columns)
            if not any(value is not None for value in values.values()):
                continue
            _upsert_state_daily(conn, report_id, date_id, state_id, values)
            if state_cell:
                mapped_cells.add(state_cell[0])
            _write_lineage(
                conn,
                report_id,
                "FactWRLDCStateDaily",
                f"report={report_id};date={date_id};state={state_id}",
                sources,
                mapped_cells,
            )


def _promote_state_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    generation_columns = _generation_columns(template_id)
    capacity_column = generation_columns["InstalledCapacityMW"]
    for page_no in (2,):
        current_state_id: int | None = None
        current_source_id: int | None = None
        for row in _table_rows(conn, report_id, page_no, 1):
            entity_cell = row.get(1)
            label = _clean_label(entity_cell[1]) if entity_cell else ""
            state_id = _resolve_state_id(conn, report_id, label)
            if state_id is not None and _cell_float(row, capacity_column) is None:
                current_state_id = state_id
                current_source_id = None
                if entity_cell:
                    mapped_cells.add(entity_cell[0])
                continue
            source_id = _source_id(conn, label)
            if source_id is not None and _cell_float(row, capacity_column) is None:
                current_source_id = source_id
                if entity_cell:
                    mapped_cells.add(entity_cell[0])
                continue
            if current_state_id is None or not label:
                continue
            values, sources = _generation_values(row, generation_columns)
            capacity = values["InstalledCapacityMW"]
            if capacity is None:
                continue
            is_total = _is_total_row(label)
            try:
                identity = resolve_generation_identity(
                    conn, "wrldc", label, current_state_id, region_id,
                    current_source_id, float(capacity), is_total,
                )
            except DimensionResolutionError as error:
                record_resolution_issue(conn, report_id, "wrldc", "generation_entity", label, str(error))
                continue
            entity_id = _get_or_create_grid_entity(
                conn, label, "generation_aggregate" if is_total else "generating_entity",
                current_state_id, region_id, current_source_id, float(capacity), is_total, identity,
            )
            section_name = f"state_generation_{current_state_id}"
            _insert_fact(
                conn,
                "FactWRLDCGenerationDaily",
                {
                    "ReportDocumentID": report_id, "DateID": date_id, "EntityID": entity_id,
                    "StateID": current_state_id, "GenerationSourceID": current_source_id,
                    "StationID": identity.station_id, "GeneratingUnitID": identity.generating_unit_id,
                    "AggregateID": identity.aggregate_id, "IsTotalRow": int(is_total),
                    "GenerationGrain": identity.entity_type, "SectionName": section_name, **values,
                },
            )
            if entity_cell:
                mapped_cells.add(entity_cell[0])
            _write_lineage(
                conn, report_id, "FactWRLDCGenerationDaily",
                f"report={report_id};date={date_id};entity={entity_id};section={section_name}",
                sources, mapped_cells,
            )
            _validate_average_mw(conn, report_id, label, values)


def _promote_conventional_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote header-validated conventional grids from pages three and four.

    Eleven-column families keep their sparse 2025/2026 maps. Nine-column
    families bind only when a complete two-row header matches a fixture map,
    including the single-header regional table that starts page 3 after
    state generation finished on page 2.
    """

    page_three_rows = _table_rows(conn, report_id, 3, 1)
    header_indexes = _station_header_indexes(page_three_rows)
    if len(header_indexes) >= 2:
        state_header_index, regional_header_index = header_indexes[:2]
        state_id = _preceding_state_id(
            conn,
            report_id,
            page_three_rows[:state_header_index],
        )
        state_columns = _first_matching_generation_columns(
            page_three_rows,
            state_header_index,
            _CONVENTIONAL_STATE_COLUMN_CANDIDATES,
        )
        if state_id is not None and state_columns is not None:
            _promote_conventional_block(
                conn,
                report_id,
                date_id,
                region_id,
                page_three_rows[state_header_index + 2:regional_header_index],
                state_columns,
                state_id,
                f"state_generation_{state_id}",
                mapped_cells,
            )
        regional_columns = _first_matching_generation_columns(
            page_three_rows,
            regional_header_index,
            _CONVENTIONAL_REGIONAL_COLUMN_CANDIDATES,
        )
        if regional_columns is not None:
            _promote_conventional_block(
                conn,
                report_id,
                date_id,
                region_id,
                page_three_rows[regional_header_index + 2:],
                regional_columns,
                None,
                "regional_generation_isgs",
                mapped_cells,
            )
    elif len(header_indexes) == 1:
        header_index = header_indexes[0]
        preceding = page_three_rows[:header_index]
        state_id = _preceding_state_id(conn, report_id, preceding)
        if _has_regional_entities_heading(preceding) or state_id is None:
            regional_columns = _first_matching_generation_columns(
                page_three_rows,
                header_index,
                _CONVENTIONAL_REGIONAL_COLUMN_CANDIDATES,
            )
            if regional_columns is not None:
                _promote_conventional_block(
                    conn,
                    report_id,
                    date_id,
                    region_id,
                    page_three_rows[header_index + 2:],
                    regional_columns,
                    None,
                    "regional_generation_isgs",
                    mapped_cells,
                )
        else:
            state_columns = _first_matching_generation_columns(
                page_three_rows,
                header_index,
                _CONVENTIONAL_STATE_COLUMN_CANDIDATES,
            )
            if state_columns is not None:
                _promote_conventional_block(
                    conn,
                    report_id,
                    date_id,
                    region_id,
                    page_three_rows[header_index + 2:],
                    state_columns,
                    state_id,
                    f"state_generation_{state_id}",
                    mapped_cells,
                )

    page_four_rows = _table_rows(conn, report_id, 4, 1)
    page_four_headers = _station_header_indexes(page_four_rows)
    if page_four_headers:
        header_index = page_four_headers[0]
        columns = _first_matching_generation_columns(
            page_four_rows,
            header_index,
            _CONVENTIONAL_CONTINUATION_COLUMN_CANDIDATES,
        )
        if columns is not None:
            section_name = (
                "regional_generation_ipp_jv"
                if columns == _IPP_JV_GENERATION_COLUMNS
                else "regional_generation_isgs"
            )
            _promote_conventional_block(
                conn,
                report_id,
                date_id,
                region_id,
                page_four_rows[header_index + 2:],
                columns,
                None,
                section_name,
                mapped_cells,
            )


def _station_header_indexes(rows: list[dict[int, tuple[int, str]]]) -> list[int]:
    """Return row indexes whose first cell is the published station header."""

    return [
        index
        for index, row in enumerate(rows)
        if re.sub(r"[^a-z]", "", _clean_label(row.get(1, (0, ""))[1]).lower())
        == "stationconstituents"
    ]


def _preceding_state_id(
    conn: sqlite3.Connection,
    report_id: int,
    rows: list[dict[int, tuple[int, str]]],
) -> int | None:
    """Resolve the closest published state heading before a generation grid."""

    for row in reversed(rows):
        label = _clean_label(row.get(1, (0, ""))[1])
        if not label:
            continue
        state_id = _resolve_state_id(conn, report_id, label, record=False)
        if state_id is not None:
            return state_id
    return None


def _generation_header_matches(
    rows: list[dict[int, tuple[int, str]]],
    header_index: int,
    columns: dict[str, int],
) -> bool:
    """Validate a full two-row generation header against its exact column map."""

    if header_index + 1 >= len(rows):
        return False
    header_row = rows[header_index]
    detail_row = rows[header_index + 1]
    for field_name, column_no in columns.items():
        expected = _GENERATION_HEADER_TOKENS[field_name]
        header_text = " ".join(
            cell[1]
            for row in (header_row, detail_row)
            if (cell := row.get(column_no))
        )
        normalized = re.sub(r"[^a-z]", "", header_text.lower())
        if expected not in normalized:
            return False
    return True


def _first_matching_generation_columns(
    rows: list[dict[int, tuple[int, str]]],
    header_index: int,
    candidates: tuple[dict[str, int], ...],
) -> dict[str, int] | None:
    """Return the first fixture map whose two-row header is complete."""

    for columns in candidates:
        if _generation_header_matches(rows, header_index, columns):
            return columns
    return None


def _has_regional_entities_heading(
    rows: list[dict[int, tuple[int, str]]],
) -> bool:
    """Return whether preceding rows publish the 3(B) regional heading."""

    for row in rows:
        label = re.sub(r"\s+", "", _clean_label(row.get(1, (0, ""))[1])).lower()
        if label.startswith("3(b)") or "regionalentitiesgeneration" in label:
            return True
    return False


def _promote_conventional_block(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    rows: list[dict[int, tuple[int, str]]],
    columns: dict[str, int],
    state_id: int | None,
    section_name: str,
    mapped_cells: set[int],
) -> None:
    """Persist one header-validated conventional generation table block."""

    for row in rows:
        entity_cell = row.get(1)
        label = _clean_label(entity_cell[1]) if entity_cell else ""
        if not label:
            continue
        values, sources = _generation_values(row, columns)
        capacity = values["InstalledCapacityMW"]
        if capacity is None:
            continue
        is_total = _is_total_row(label)
        try:
            identity = resolve_generation_identity(
                conn,
                "wrldc",
                label,
                state_id,
                region_id,
                None,
                float(capacity),
                is_total,
            )
        except DimensionResolutionError as error:
            record_resolution_issue(
                conn,
                report_id,
                "wrldc",
                "conventional_generation_entity",
                label,
                str(error),
            )
            continue
        entity_id = _get_or_create_grid_entity(
            conn,
            label,
            "generation_aggregate" if is_total else "generating_entity",
            state_id,
            region_id,
            None,
            float(capacity),
            is_total,
            identity,
        )
        _insert_fact(
            conn,
            "FactWRLDCGenerationDaily",
            {
                "ReportDocumentID": report_id,
                "DateID": date_id,
                "EntityID": entity_id,
                "StateID": state_id,
                "GenerationSourceID": None,
                "StationID": identity.station_id,
                "GeneratingUnitID": identity.generating_unit_id,
                "AggregateID": identity.aggregate_id,
                "IsTotalRow": int(is_total),
                "GenerationGrain": identity.entity_type,
                "SectionName": section_name,
                **values,
            },
        )
        if entity_cell:
            mapped_cells.add(entity_cell[0])
        _write_lineage(
            conn,
            report_id,
            "FactWRLDCGenerationDaily",
            f"report={report_id};date={date_id};entity={entity_id};section={section_name}",
            sources,
            mapped_cells,
        )
        _validate_average_mw(conn, report_id, label, values)


def _promote_renewable_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote the verified 2025/2026 renewable station continuation table.

    Page five is a dense twelve-column table.  Page six continues the same
    table with sparse raw-cell coordinates, then changes to the regional
    generation summary.  The published ``TOTAL`` row is retained as an
    aggregate; no source type is inferred from abbreviated station suffixes.
    """

    page_five_started = False
    for page_no, columns in (
        (5, _RENEWABLE_PAGE_FIVE_COLUMNS),
        (6, _RENEWABLE_PAGE_SIX_COLUMNS),
    ):
        for row in _table_rows(conn, report_id, page_no, 1):
            entity_cell = row.get(1)
            label = _clean_label(entity_cell[1]) if entity_cell else ""
            normalized = re.sub(r"[^a-z]", "", label.lower())
            if page_no == 5:
                if normalized == "renewable":
                    page_five_started = True
                    continue
                if not page_five_started:
                    continue
            elif normalized == "total":
                _promote_renewable_row(
                    conn,
                    report_id,
                    date_id,
                    region_id,
                    label,
                    entity_cell,
                    row,
                    columns,
                    mapped_cells,
                )
                return

            _promote_renewable_row(
                conn,
                report_id,
                date_id,
                region_id,
                label,
                entity_cell,
                row,
                columns,
                mapped_cells,
            )


def _promote_renewable_row(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    label: str,
    entity_cell: tuple[int, str] | None,
    row: dict[int, tuple[int, str]],
    columns: dict[str, int],
    mapped_cells: set[int],
) -> None:
    """Persist one renewable station or the published renewable total row."""

    if not label:
        return
    values, sources = _generation_values(row, columns)
    capacity = values["InstalledCapacityMW"]
    if capacity is None:
        return
    is_total = _is_total_row(label)
    source_id = _source_id(conn, label)
    try:
        identity = resolve_generation_identity(
            conn,
            "wrldc",
            label,
            None,
            region_id,
            source_id,
            float(capacity),
            is_total,
        )
    except DimensionResolutionError as error:
        record_resolution_issue(
            conn,
            report_id,
            "wrldc",
            "renewable_generation_entity",
            label,
            str(error),
        )
        return
    entity_id = _get_or_create_grid_entity(
        conn,
        label,
        "generation_aggregate" if is_total else "generating_entity",
        None,
        region_id,
        source_id,
        float(capacity),
        is_total,
        identity,
    )
    section_name = "renewable_generation"
    _insert_fact(
        conn,
        "FactWRLDCGenerationDaily",
        {
            "ReportDocumentID": report_id,
            "DateID": date_id,
            "EntityID": entity_id,
            "StateID": None,
            "GenerationSourceID": source_id,
            "StationID": identity.station_id,
            "GeneratingUnitID": identity.generating_unit_id,
            "AggregateID": identity.aggregate_id,
            "IsTotalRow": int(is_total),
            "GenerationGrain": identity.entity_type,
            "SectionName": section_name,
            **values,
        },
    )
    if entity_cell:
        mapped_cells.add(entity_cell[0])
    _write_lineage(
        conn,
        report_id,
        "FactWRLDCGenerationDaily",
        f"report={report_id};date={date_id};entity={entity_id};section={section_name}",
        sources,
        mapped_cells,
    )
    _validate_average_mw(conn, report_id, label, values)


def _fetch_report(conn: sqlite3.Connection, report_id: int) -> dict[str, object] | None:
    """Fetch only the report metadata needed by the WRLDC promoter."""
    row = conn.execute(
        """
        SELECT rldc, local_path, report_date, template_id,
               semantic_pass_required, structure_deviation_reason
        FROM psp_report_document WHERE id = ?
        """,
        (report_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "rldc": row[0],
        "local_path": row[1],
        "report_date": row[2],
        "template_id": row[3],
        "semantic_pass_required": bool(row[4]),
        "structure_deviation_reason": row[5],
    }


def _get_or_create_date_id(conn: sqlite3.Connection, report_date: str) -> int | None:
    conn.execute("INSERT OR IGNORE INTO DimDates(ActualDate) VALUES (?)", (report_date,))
    row = conn.execute("SELECT DateID FROM DimDates WHERE ActualDate = ?", (report_date,)).fetchone()
    return int(row[0]) if row else None


def _region_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT RegionID FROM DimRegions WHERE RegionName = ?", (WR_REGION_NAME,)).fetchone()
    return int(row[0]) if row else None


def _canonical_state_id(conn: sqlite3.Connection, state_name: str | None) -> int | None:
    """Return a seeded dimension identifier for a registry state name."""

    canonical_name = {
        "Dadra and Nagar Haveli and Daman and Diu": "DNHDDPDCL",
        "Madhya Pradesh": "MP",
        "Uttar Pradesh": "UP",
    }.get(state_name or "", state_name)
    if canonical_name is None:
        return None
    row = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = ?", (canonical_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _canonical_region_id(conn: sqlite3.Connection, region_name: str | None) -> int | None:
    """Return a seeded dimension identifier for a registry region name."""

    if region_name is None:
        return None
    row = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (region_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _upsert_dim_report(conn: sqlite3.Connection, date_id: int, report: sqlite3.Row) -> None:
    path = str(report["local_path"])
    conn.execute(
        "INSERT OR REPLACE INTO DimReports(DateID, ReportName, ReportPath, Source) VALUES (?, ?, ?, 'WRLDC')",
        (date_id, path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1], path),
    )


def _clear_wrldc_facts(conn: sqlite3.Connection, report_id: int) -> None:
    for table_name in (
        "FactWRLDCRegionalDaily",
        "FactWRLDCStateDaily",
        "FactWRLDCGenerationDaily",
        "FactWRLDCFrequencyDaily",
        "FactWRLDCVoltageProfile",
        "FactWRLDCReservoirDaily",
        "FactWRLDCMarketEnergyDaily",
        "FactWRLDCMarketPointDaily",
        "FactWRLDCMarketExtremaDaily",
        "FactWRLDCInterRegionalExchange",
    ):
        conn.execute(f"DELETE FROM {table_name} WHERE ReportDocumentID = ?", (report_id,))
    conn.execute("DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?", (report_id,))


def _table_rows(conn: sqlite3.Connection, report_id: int, page_no: int, table_no: int) -> list[dict[int, tuple[int, str]]]:
    rows: dict[int, dict[int, tuple[int, str]]] = {}
    for raw_id, row_no, col_no, text in conn.execute(
        "SELECT id, row_no, col_no, cell_text FROM psp_raw_cell WHERE report_document_id = ? AND page_no = ? AND table_no = ? ORDER BY row_no, col_no",
        (report_id, page_no, table_no),
    ):
        rows.setdefault(int(row_no), {})[int(col_no)] = (int(raw_id), str(text))
    return [rows[key] for key in sorted(rows)]


def _table_row(conn: sqlite3.Connection, report_id: int, page_no: int, table_no: int, row_no: int) -> dict[int, tuple[int, str]]:
    return {int(col): (int(raw_id), str(text)) for raw_id, col, text in conn.execute(
        "SELECT id, col_no, cell_text FROM psp_raw_cell WHERE report_document_id = ? AND page_no = ? AND table_no = ? AND row_no = ?",
        (report_id, page_no, table_no, row_no),
    )}


def _section_rows(rows: list[dict[int, tuple[int, str]]], marker: str) -> list[dict[int, tuple[int, str]]]:
    active = False
    selected: list[dict[int, tuple[int, str]]] = []
    for row in rows:
        label = re.sub(r"\s+", "", _clean_label(row.get(1, (0, ""))[1]).lower())
        if label.startswith(marker):
            active = True
            continue
        if active and label.startswith(("2(a)", "2(b)", "2(c)")):
            break
        if active:
            selected.append(row)
    return selected


def _values(row: dict[int, tuple[int, str]], columns: dict[str, int]) -> tuple[dict[str, float | str | None], dict[str, int]]:
    values: dict[str, float | str | None] = {}
    sources: dict[str, int] = {}
    time_fields = {"MaximumDemandTime", "MaximumACETime", "MinimumACETime", "DayPeakTime", "MinimumGenerationTime"}
    for name, column in columns.items():
        raw = row.get(column)
        value = _time(raw[1]) if raw and name in time_fields else _float(raw[1]) if raw else None
        values[name] = value
        if raw and value is not None:
            sources[name] = raw[0]
    return values, sources


def _generation_values(
    row: dict[int, tuple[int, str]],
    columns: dict[str, int],
) -> tuple[dict[str, float | str | None], dict[str, int]]:
    """Map the verified generation columns for the report's template family."""
    return _values(row, columns)


def _generation_columns(template_id: str) -> dict[str, int]:
    """Return the approved state-generation layout for a WRLDC template."""
    if template_id in WRLDC_9_COLUMN_TEMPLATE_IDS:
        return _NINE_COLUMN_GENERATION_COLUMNS
    return _GENERATION_COLUMNS


def _upsert_state_daily(conn: sqlite3.Connection, report_id: int, date_id: int, state_id: int, values: dict[str, float | str | None]) -> None:
    columns = list(values)
    assignments = ", ".join(f"{column} = excluded.{column}" for column in columns)
    conn.execute(
        f"INSERT INTO FactWRLDCStateDaily(ReportDocumentID, DateID, StateID, {', '.join(columns)}) VALUES (?, ?, ?, {', '.join('?' for _ in columns)}) ON CONFLICT(ReportDocumentID, DateID, StateID) DO UPDATE SET {assignments}",
        (report_id, date_id, state_id, *(values[column] for column in columns)),
    )


def _insert_fact(conn: sqlite3.Connection, table: str, values: dict[str, object]) -> None:
    columns = list(values)
    conn.execute(
        f"INSERT OR REPLACE INTO {table}({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(values[column] for column in columns),
    )


def _resolve_state_id(conn: sqlite3.Connection, report_id: int, raw_name: str, record: bool = True) -> int | None:
    try:
        return resolve_state_id(conn, "wrldc", raw_name)
    except DimensionResolutionError:
        if record and raw_name:
            record_resolution_issue(conn, report_id, "wrldc", "state", raw_name, "state alias is not approved")
        return None


def _source_id(conn: sqlite3.Connection, label: str) -> int | None:
    normalized = re.sub(r"[^a-z]", "", label.lower())
    source_name = next((name for token, name in (("thermal", "Thermal"), ("hydel", "Hydro"), ("hydro", "Hydro"), ("gas", "Gas, Naptha & Diesel"), ("wind", "Wind"), ("solar", "Solar")) if token in normalized), None)
    if source_name is None:
        return None
    row = conn.execute("SELECT GenerationSourceID FROM DimGenerationSources WHERE SourceName = ?", (source_name,)).fetchone()
    return int(row[0]) if row else None


def _get_or_create_grid_entity(*args: object, **kwargs: object) -> int:
    from psp_pipeline.storage.sqlite_curated_promoter import _get_or_create_grid_entity as resolver
    return resolver(*args, **kwargs)


def _write_lineage(conn: sqlite3.Connection, report_id: int, table: str, key: str, sources: dict[str, int], mapped_cells: set[int]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for column, raw_cell_id in sources.items():
        conn.execute("INSERT OR IGNORE INTO curated_field_lineage(ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn, RawCellID, ExtractionMethod, Confidence, CreatedAt) VALUES (?, ?, ?, ?, ?, 'pdfplumber', 1.0, ?)", (report_id, table, key, column, raw_cell_id, now))
        mapped_cells.add(raw_cell_id)


def _write_line_lineage(
    conn: sqlite3.Connection,
    report_id: int,
    table: str,
    key: str,
    sources: dict[str, int],
) -> None:
    """Record immutable provenance for values parsed from native PDF text lines."""

    now = datetime.now(timezone.utc).isoformat()
    for column, raw_line_id in sources.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO curated_field_lineage(
                ReportDocumentID, DestinationTable, DestinationKey,
                DestinationColumn, RawLineID, ExtractionMethod, Confidence,
                CreatedAt
            ) VALUES (?, ?, ?, ?, ?, 'pdfplumber_text', 1.0, ?)
            """,
            (report_id, table, key, column, raw_line_id, now),
        )


def _cell_float(row: dict[int, tuple[int, str]], column: int) -> float | None:
    raw = row.get(column)
    return _float(raw[1]) if raw else None


def _float(value: str) -> float | None:
    text = value.strip().replace(",", "").replace("−", "-")
    if not text or text.lower() in {"-", "--", "nil", "na", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _time(value: str) -> str | None:
    text = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        return f"{text}:00"
    if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", text):
        return text
    return None


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _is_total_row(value: str) -> bool:
    return re.sub(r"[^a-z]", "", value.lower()).startswith(("total", "subtotal"))


def _promote_market_day_energy(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote the verified WRLDC day-energy market matrix.

    2025 and 2026 reports publish this block on page 8. The 2024-revised family
    places the same seven MU measures on page 7. Header-derived columns preserve
    that published geometry without treating MW snapshots or extrema as daily
    energy values.
    """

    for page_no in (7, 8):
        rows = _table_rows(conn, report_id, page_no, 1)
        for index, row in enumerate(rows[:-1]):
            row_text = " ".join(text for _, text in row.values())
            if "dayenergy" not in re.sub(r"[^a-z]", "", row_text.lower()):
                continue
            columns = _market_day_energy_columns(rows[index + 1])
            if columns is None:
                return
            for data_row in rows[index + 2:]:
                label_cell = data_row.get(1)
                label = _clean_label(label_cell[1]) if label_cell else ""
                if _is_total_row(label):
                    break
                if not label:
                    continue
                values, sources = _values(data_row, columns)
                if not any(value is not None for value in values.values()):
                    continue
                state_id = _market_state_id(conn, report_id, label)
                entity_id = _market_participant_entity_id(
                    conn,
                    label,
                    state_id,
                    region_id,
                )
                _insert_fact(
                    conn,
                    "FactWRLDCMarketEnergyDaily",
                    {
                        "ReportDocumentID": report_id,
                        "DateID": date_id,
                        "EntityID": entity_id,
                        "StateID": state_id,
                        **values,
                    },
                )
                if label_cell:
                    mapped_cells.add(label_cell[0])
                _write_lineage(
                    conn,
                    report_id,
                    "FactWRLDCMarketEnergyDaily",
                    f"report={report_id};date={date_id};entity={entity_id}",
                    sources,
                    mapped_cells,
                )
            return


def _market_day_energy_columns(
    header_row: dict[int, tuple[int, str]],
) -> dict[str, int] | None:
    """Resolve the explicit Day Energy headers to their raw columns."""

    expected = {
        "isgsgnaschedule": "GNAScheduleMU",
        "gnaschedule": "GNAScheduleMU",
        "tgnabilateralmw": "TGNABilateralMU",
        "tgnabilateral": "TGNABilateralMU",
        "gdamschedule": "GDAMScheduleMU",
        "damschedule": "DAMScheduleMU",
        "hpdamschedule": "HPDAMScheduleMU",
        "rtmschedule": "RTMScheduleMU",
        "totalmu": "TotalMU",
    }
    required = {
        "GNAScheduleMU",
        "TGNABilateralMU",
        "GDAMScheduleMU",
        "DAMScheduleMU",
        "HPDAMScheduleMU",
        "RTMScheduleMU",
        "TotalMU",
    }
    columns: dict[str, int] = {}
    for column, (_, text) in header_row.items():
        normalized = re.sub(r"[^a-z]", "", text.lower())
        field_name = expected.get(normalized)
        if field_name:
            columns[field_name] = column
    return columns if set(columns) == required else None


def _promote_market_points_and_extrema(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote header-derived WRLDC market snapshots and extrema by epoch."""

    for page_no in (7, 8):
        rows = _table_rows(conn, report_id, page_no, 1)
        _promote_market_points_from_rows(
            conn, report_id, date_id, region_id, mapped_cells, rows
        )
        _promote_market_extrema_from_rows(
            conn, report_id, date_id, region_id, mapped_cells, rows
        )


def _promote_market_points_from_rows(
    conn: sqlite3.Connection, report_id: int, date_id: int, region_id: int,
    mapped_cells: set[int], rows: list[dict[int, tuple[int, str]]],
) -> None:
    """Promote one 03:00 or 19:00 market matrix after a complete header check."""

    for index, row in enumerate(rows[:-1]):
        heading = " ".join(text for _, text in row.values()).lower()
        time_category = "off_peak" if "off-peakhours(03:00)" in heading else (
            "peak" if "peakhours(19:00)" in heading else None
        )
        if time_category is None:
            continue
        mechanisms = _market_mechanism_columns(rows[index + 1])
        if len(mechanisms) != 13:
            continue
        for data_row in rows[index + 2:]:
            label_cell = data_row.get(1)
            label = _clean_label(label_cell[1]) if label_cell else ""
            if _is_total_row(label) or not label:
                break
            state_id = _market_state_id(conn, report_id, label)
            entity_id = _market_participant_entity_id(conn, label, state_id, region_id)
            for mechanism, column in mechanisms.items():
                value, raw_id = _value_and_raw(data_row, column)
                if value is None or raw_id is None:
                    continue
                _insert_fact(conn, "FactWRLDCMarketPointDaily", {
                    "ReportDocumentID": report_id, "DateID": date_id,
                    "EntityID": entity_id, "StateID": state_id,
                    "TimeCategory": time_category, "Mechanism": mechanism,
                    "ClearedMW": value,
                })
                _write_lineage(conn, report_id, "FactWRLDCMarketPointDaily",
                    f"report={report_id};date={date_id};entity={entity_id};time={time_category};mechanism={mechanism}",
                    {"ClearedMW": raw_id}, mapped_cells)
        return


def _promote_market_extrema_from_rows(
    conn: sqlite3.Connection, report_id: int, date_id: int, region_id: int,
    mapped_cells: set[int], rows: list[dict[int, tuple[int, str]]],
) -> None:
    """Promote a published Maximum/Minimum market matrix only when complete."""

    for index, row in enumerate(rows[:-1]):
        mechanisms = _market_mechanism_columns(row)
        if len(mechanisms) != 7:
            continue
        pairs = _market_extrema_columns(mechanisms, rows[index + 1])
        if pairs is None:
            continue
        for data_row in rows[index + 2:]:
            label_cell = data_row.get(1)
            label = _clean_label(label_cell[1]) if label_cell else ""
            if _is_total_row(label) or not label:
                break
            state_id = _market_state_id(conn, report_id, label)
            entity_id = _market_participant_entity_id(conn, label, state_id, region_id)
            for mechanism, (maximum_col, minimum_col) in pairs.items():
                maximum, maximum_raw = _value_and_raw(data_row, maximum_col)
                minimum, minimum_raw = _value_and_raw(data_row, minimum_col)
                if None in (maximum, minimum, maximum_raw, minimum_raw):
                    continue
                _insert_fact(conn, "FactWRLDCMarketExtremaDaily", {
                    "ReportDocumentID": report_id, "DateID": date_id,
                    "EntityID": entity_id, "StateID": state_id, "Mechanism": mechanism,
                    "MaximumMW": maximum, "MinimumMW": minimum,
                })
                _write_lineage(conn, report_id, "FactWRLDCMarketExtremaDaily",
                    f"report={report_id};date={date_id};entity={entity_id};mechanism={mechanism}",
                    {"MaximumMW": maximum_raw, "MinimumMW": minimum_raw}, mapped_cells)
        return


def _market_mechanism_columns(row: dict[int, tuple[int, str]]) -> dict[str, int]:
    """Resolve the 13 published market mechanisms from a header row."""

    names = {
        "isgsgnaschedule": "GNASchedule",
        "gnaschedule": "GNASchedule",
        "tgnabilateralmw": "TGNABilateral", "iexgdammw": "IEXGDAM",
        "iexdammw": "IEXDAM", "iexhpdammw": "IEXHPDAM", "iexrtmmw": "IEXRTM",
        "pxilgdammw": "PXILGDAM", "pxildammw": "PXILDAM", "pxilhpdammw": "PXILHPDAM",
        "pxirtmmw": "PXILRTM", "hpxgdammw": "HPXGDAM", "hpxdammw": "HPXDAM",
        "hpxhpdammw": "HPXHPDAM", "hpxrtmmw": "HPXRTM",
    }
    result = {}
    for column, (_, text) in row.items():
        name = names.get(re.sub(r"[^a-z]", "", text.lower()))
        if name:
            result[name] = column
    return result


def _market_extrema_columns(
    mechanisms: dict[str, int], row: dict[int, tuple[int, str]],
) -> dict[str, tuple[int, int]] | None:
    """Find each extrema pair within its published mechanism header band."""

    columns = sorted(mechanisms.items(), key=lambda item: item[1])
    pairs: dict[str, tuple[int, int]] = {}
    for index, (mechanism, start) in enumerate(columns):
        end = columns[index + 1][1] if index + 1 < len(columns) else max(row) + 1
        maximum = [column for column in range(start, end) if _clean_label(row.get(column, (0, ""))[1]).lower() == "maximum"]
        minimum = [column for column in range(start, end) if _clean_label(row.get(column, (0, ""))[1]).lower() == "minimum"]
        if len(maximum) != 1 or len(minimum) != 1:
            return None
        pairs[mechanism] = (maximum[0], minimum[0])
    return pairs


def _value_and_raw(row: dict[int, tuple[int, str]], column: int) -> tuple[float | None, int | None]:
    """Read one native numeric cell and retain its raw identity."""

    raw = row.get(column)
    return (_float(raw[1]), raw[0]) if raw else (None, None)


def _market_participant_entity_id(
    conn: sqlite3.Connection,
    label: str,
    state_id: int | None,
    region_id: int,
) -> int:
    """Resolve one published market participant without forcing a state alias."""

    entity_name = re.sub(r"\s+", " ", label).strip()
    row = conn.execute(
        """
        SELECT EntityID FROM DimGridEntities
        WHERE EntityName = ? AND EntityType = 'market_participant'
          AND StateID IS ? AND RegionID = ?
        """,
        (entity_name, state_id, region_id),
    ).fetchone()
    if row:
        return int(row[0])
    cursor = conn.execute(
        """
        INSERT INTO DimGridEntities(EntityName, EntityType, StateID, RegionID)
        VALUES (?, 'market_participant', ?, ?)
        """,
        (entity_name, state_id, region_id),
    )
    return int(cursor.lastrowid)


def _market_state_id(
    conn: sqlite3.Connection,
    report_id: int,
    label: str,
) -> int | None:
    """Resolve only geographical Page 8 labels as states.

    The WRLDC state-alias registry also contains commercial participants for
    other legacy tables. This market table keeps those participants at the
    entity grain and assigns ``StateID`` only to published geographical rows.
    """

    normalized = re.sub(r"[^A-Z]", "", label.upper())
    if normalized not in _WRLDC_MARKET_GEOGRAPHIC_LABELS:
        return None
    return _resolve_state_id(conn, report_id, label, record=False)


def _promote_physical_exchanges(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    """Promote verified Section 4(A) line-level exchanges by layout family."""

    in_section = False
    counterparty: str | None = None
    for page_no in (5, 6):
        for row in _table_rows(conn, report_id, page_no, 1):
            label = _clean_label(row.get(1, (0, ""))[1])
            normalized = re.sub(r"[^a-z0-9]", "", label.lower())
            if normalized.startswith("4a") and "interregional" in normalized:
                in_section = True
                continue
            if in_section and normalized.startswith("4b"):
                return
            if not in_section:
                continue
            counterparty = _counterparty_region(label) or counterparty
            name_cell = row.get(2)
            element_name = _clean_label(name_cell[1]) if name_cell else ""
            if counterparty is None or not _is_transmission_element(element_name):
                continue
            columns = (
                {
                    "EveningPeakMW": 7,
                    "OffPeakMW": 9,
                    "MaximumImportMW": 11,
                    "MaximumExportMW": 14,
                    "ImportEnergyMU": 17,
                    "ExportEnergyMU": 19,
                    "NetEnergyMU": 22,
                }
                if page_no == 5 or template_id in WRLDC_2026_OPERATIONAL_TEMPLATE_IDS
                else {
                    "EveningPeakMW": 9,
                    "OffPeakMW": 11,
                    "MaximumImportMW": 13,
                    "MaximumExportMW": 16,
                    "ImportEnergyMU": 19,
                    "ExportEnergyMU": 22,
                    "NetEnergyMU": 25,
                }
            )
            values, sources = _values(row, columns)
            if not any(value is not None for value in values.values()):
                continue
            element_id = _get_or_create_transmission_element(conn, element_name)
            _insert_fact(
                conn,
                "FactWRLDCInterRegionalExchange",
                {
                    "ReportDocumentID": report_id,
                    "DateID": date_id,
                    "ElementID": element_id,
                    "CounterpartyRegion": counterparty,
                    **values,
                },
            )
            if name_cell:
                mapped_cells.add(name_cell[0])
            _write_lineage(
                conn,
                report_id,
                "FactWRLDCInterRegionalExchange",
                f"report={report_id};date={date_id};element={element_id};region={counterparty}",
                sources,
                mapped_cells,
            )


def _promote_voltage_profiles(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    """Promote 400 and 765 kV Section 6 monitoring-node profiles."""

    nominal_kv: float | None = None
    if template_id in WRLDC_2026_OPERATIONAL_TEMPLATE_IDS:
        table_locations = ((7, 2),)
        columns = {
            "MaximumKV": 3,
            "MinimumKV": 5,
            "LowCriticalPct": 8,
            "IEGCBandPct": 10,
            "HighCriticalPct": 11,
            "VoltageDeviationIndexPct": 12,
        }
        maximum_time_column = 4
        minimum_time_column = 6
    else:
        table_locations = ((6, 1), (7, 1))
        columns = {
            "MaximumKV": 4,
            "MinimumKV": 8,
            "LowCriticalPct": 13,
            "IEGCBandPct": 15,
            "HighCriticalPct": 17,
            "VoltageDeviationIndexPct": 19,
        }
        maximum_time_column = 6
        minimum_time_column = 10
    for page_no, table_no in table_locations:
        for row in _table_rows(conn, report_id, page_no, table_no):
            label = _clean_label(row.get(1, (0, ""))[1])
            normalized = re.sub(r"\s+", "", label.lower())
            match = re.search(r"voltageprofile:?(\d+)kv", normalized)
            if match:
                nominal_kv = float(match.group(1))
                continue
            if normalized.startswith("7a"):
                return
            node_nominal_kv = _nominal_voltage_from_node(label) or nominal_kv
            if node_nominal_kv is None or _is_total_row(label):
                continue
            values, sources = _values(row, columns)
            values["MaximumTime"] = (
                _time(row[maximum_time_column][1])
                if row.get(maximum_time_column)
                else None
            )
            values["MinimumTime"] = (
                _time(row[minimum_time_column][1])
                if row.get(minimum_time_column)
                else None
            )
            for field_name, column in (
                ("MaximumTime", maximum_time_column),
                ("MinimumTime", minimum_time_column),
            ):
                raw = row.get(column)
                if raw and values[field_name] is not None:
                    sources[field_name] = raw[0]
            if values["MaximumKV"] is None or values["MinimumKV"] is None:
                continue
            node_id = _get_or_create_voltage_node(
                conn, label, node_nominal_kv, region_id
            )
            _insert_fact(
                conn,
                "FactWRLDCVoltageProfile",
                {
                    "ReportDocumentID": report_id,
                    "DateID": date_id,
                    "VoltageNodeID": node_id,
                    "NominalVoltageKV": node_nominal_kv,
                    **values,
                },
            )
            if row.get(1):
                mapped_cells.add(row[1][0])
            _write_lineage(
                conn,
                report_id,
                "FactWRLDCVoltageProfile",
                f"report={report_id};date={date_id};node={node_id}",
                sources,
                mapped_cells,
            )


def _promote_reservoirs(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    """Promote verified Section 8 major-reservoir measures by layout family."""

    page_no = 9 if template_id in WRLDC_2026_OPERATIONAL_TEMPLATE_IDS else 8
    columns = (
        {
            "MinimumDrawdownLevelM": 2,
            "FullReservoirLevelM": 3,
            "DesignedEnergyMU": 4,
            "CurrentLevelM": 6,
            "CurrentEnergyMU": 8,
            "PreviousYearLevelM": 10,
            "PreviousYearEnergyMU": 11,
            "InflowMU": 12,
            "ProgressiveInflowMU": 15,
            "ProgressiveUsageMU": 17,
        }
        if template_id in WRLDC_2026_OPERATIONAL_TEMPLATE_IDS
        else {
            "MinimumDrawdownLevelM": 2,
            "FullReservoirLevelM": 5,
            "DesignedEnergyMU": 8,
            "CurrentLevelM": 11,
            "CurrentEnergyMU": 13,
            "PreviousYearLevelM": 16,
            "PreviousYearEnergyMU": 18,
            "InflowMU": 21,
            "ProgressiveInflowMU": 26,
            "ProgressiveUsageMU": 29,
        }
    )
    in_section = False
    for row in _table_rows(conn, report_id, page_no, 1):
        label = _clean_label(row.get(1, (0, ""))[1])
        normalized = re.sub(r"\s+", "", label.lower())
        if normalized.startswith("8.majorreservoir"):
            in_section = True
            continue
        if in_section and normalized.startswith("9."):
            return
        if not in_section or not label or _is_total_row(label):
            continue
        values, sources = _values(row, columns)
        if values["MinimumDrawdownLevelM"] is None or values["FullReservoirLevelM"] is None:
            continue
        reservoir_id = _get_or_create_reservoir(conn, label, region_id)
        _insert_fact(
            conn,
            "FactWRLDCReservoirDaily",
            {
                "ReportDocumentID": report_id,
                "DateID": date_id,
                "ReservoirID": reservoir_id,
                **values,
            },
        )
        if row.get(1):
            mapped_cells.add(row[1][0])
        _write_lineage(
            conn,
            report_id,
            "FactWRLDCReservoirDaily",
            f"report={report_id};date={date_id};reservoir={reservoir_id}",
            sources,
            mapped_cells,
        )


def _promote_frequency_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    """Promote Section 5 frequency measures from their native text-line layout.

    The WRLDC PDF prints the extrema and the two IEGC-band measures as text
    lines rather than extractable table cells.  Their lineage is therefore
    retained through ``RawLineID`` instead of manufacturing a cell coordinate.
    """

    if template_id in WRLDC_2026_OPERATIONAL_TEMPLATE_IDS:
        _promote_2026_frequency_daily(
            conn,
            report_id,
            date_id,
            region_id,
            mapped_cells,
        )
        return

    rows = conn.execute(
        """
        SELECT id, line_text
        FROM psp_raw_line
        WHERE report_document_id = ? AND page_no = 6
        ORDER BY line_no
        """,
        (report_id,),
    ).fetchall()
    values: dict[str, float | str | None] = {
        "MaximumFrequencyHz": None,
        "MaximumFrequencyTime": None,
        "MinimumFrequencyHz": None,
        "MinimumFrequencyTime": None,
        "AverageFrequencyHz": None,
        "FrequencyVariationIndex": None,
        "StandardDeviationHz": None,
        "Maximum15MinuteBlockFrequencyHz": None,
        "Minimum15MinuteBlockFrequencyHz": None,
        "PercentageOutsideIEGCBand": None,
        "HoursOutsideIEGCBand": None,
    }
    sources: dict[str, int] = {}
    for raw_line_id, line_text in rows:
        text = str(line_text or "")
        normalized = re.sub(r"\s+", "", text.lower())
        if "percentageoftimefrequencyremainedoutside" in normalized:
            value = _trailing_float(text)
            if value is not None:
                values["PercentageOutsideIEGCBand"] = value
                sources["PercentageOutsideIEGCBand"] = int(raw_line_id)
        elif "no.ofhoursfrequencyoutside" in normalized:
            value = _trailing_float(text)
            if value is not None:
                values["HoursOutsideIEGCBand"] = value
                sources["HoursOutsideIEGCBand"] = int(raw_line_id)

        extrema = _frequency_extrema_values(text)
        if extrema is not None:
            values.update(extrema)
            sources.update({field_name: int(raw_line_id) for field_name in extrema})

    if values["MaximumFrequencyHz"] is None or values["MinimumFrequencyHz"] is None:
        return
    _insert_fact(
        conn,
        "FactWRLDCFrequencyDaily",
        {
            "ReportDocumentID": report_id,
            "DateID": date_id,
            "RegionID": region_id,
            **values,
        },
    )
    _write_line_lineage(
        conn,
        report_id,
        "FactWRLDCFrequencyDaily",
        f"report={report_id};date={date_id};region={region_id}",
        sources,
    )


def _promote_2026_frequency_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote the 2026 page-seven frequency tables with cell lineage."""

    extrema_row = _table_row(conn, report_id, 7, 2, 3)
    values, sources = _values(
        extrema_row,
        {
            "MaximumFrequencyHz": 1,
            "MinimumFrequencyHz": 3,
            "AverageFrequencyHz": 5,
            "FrequencyVariationIndex": 7,
            "StandardDeviationHz": 9,
            "Maximum15MinuteBlockFrequencyHz": 11,
            "Minimum15MinuteBlockFrequencyHz": 12,
        },
    )
    for field_name, column in (
        ("MaximumFrequencyTime", 2),
        ("MinimumFrequencyTime", 4),
    ):
        raw = extrema_row.get(column)
        values[field_name] = _time(raw[1]) if raw else None
        if raw and values[field_name] is not None:
            sources[field_name] = raw[0]
    for row_no, field_name in (
        (11, "PercentageOutsideIEGCBand"),
        (12, "HoursOutsideIEGCBand"),
    ):
        row = _table_row(conn, report_id, 7, 1, row_no)
        value_cell = row.get(14)
        values[field_name] = _float(value_cell[1]) if value_cell else None
        if value_cell and values[field_name] is not None:
            sources[field_name] = value_cell[0]
    if values["MaximumFrequencyHz"] is None or values["MinimumFrequencyHz"] is None:
        return
    _insert_fact(
        conn,
        "FactWRLDCFrequencyDaily",
        {
            "ReportDocumentID": report_id,
            "DateID": date_id,
            "RegionID": region_id,
            **values,
        },
    )
    _write_lineage(
        conn,
        report_id,
        "FactWRLDCFrequencyDaily",
        f"report={report_id};date={date_id};region={region_id}",
        sources,
        mapped_cells,
    )


def _frequency_extrema_values(text: str) -> dict[str, float | str] | None:
    """Parse the one WRLDC Section 5 extrema line when its shape is verified."""

    tokens = re.findall(r"\d{1,2}:\d{2}(?::\d{2})?|[-−]?\d+(?:\.\d+)?", text)
    if len(tokens) != 9:
        return None
    maximum_time = _time(tokens[1])
    minimum_time = _time(tokens[3])
    numbers = [_float(token) for token in (tokens[0], tokens[2], *tokens[4:])]
    if maximum_time is None or minimum_time is None or any(value is None for value in numbers):
        return None
    maximum, minimum, average, fvi, standard_deviation, maximum_block, minimum_block = numbers
    if not (45.0 <= maximum <= 55.0 and 45.0 <= minimum <= 55.0):
        return None
    return {
        "MaximumFrequencyHz": float(maximum),
        "MaximumFrequencyTime": maximum_time,
        "MinimumFrequencyHz": float(minimum),
        "MinimumFrequencyTime": minimum_time,
        "AverageFrequencyHz": float(average),
        "FrequencyVariationIndex": float(fvi),
        "StandardDeviationHz": float(standard_deviation),
        "Maximum15MinuteBlockFrequencyHz": float(maximum_block),
        "Minimum15MinuteBlockFrequencyHz": float(minimum_block),
    }


def _trailing_float(text: str) -> float | None:
    """Return the final numeric token from a labelled report line."""

    values = re.findall(r"[-−]?\d+(?:\.\d+)?", text)
    return _float(values[-1]) if values else None


def _counterparty_region(label: str) -> str | None:
    """Return a neighbouring region named by a Section 4(A) group heading."""

    normalized = re.sub(r"[^a-z]", "", label.lower())
    for token, name in (
        ("northregion", "NR"),
        ("eastregion", "ER"),
        ("southregion", "SR"),
        ("northeasternregion", "NER"),
    ):
        if token in normalized:
            return name
    return None


def _is_transmission_element(label: str) -> bool:
    """Recognize a printed AC or HVDC transmission-element label."""

    return bool(re.search(r"(?:\d{3,4}\s*kv|hvdc)", label, re.IGNORECASE))


def _nominal_voltage_from_node(label: str) -> float | None:
    """Read the printed nominal voltage when a profile heading split across pages."""

    match = re.search(r"(\d{3,4})\s*kv", label, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _get_or_create_transmission_element(
    conn: sqlite3.Connection,
    name: str,
) -> int:
    """Resolve a WRLDC physical exchange element without inferring endpoints."""

    metadata = transmission_location(name)
    conn.execute(
        """
        INSERT OR IGNORE INTO DimTransmissionElements(
            ElementName, ElementType, NominalVoltageKV, FromRegionID,
            ToRegionID, FromStateID, ToStateID
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            metadata.element_type,
            metadata.nominal_voltage_kv,
            _canonical_region_id(conn, metadata.from_location.region_name),
            _canonical_region_id(conn, metadata.to_location.region_name),
            _canonical_state_id(conn, metadata.from_location.state_name),
            _canonical_state_id(conn, metadata.to_location.state_name),
        ),
    )
    return int(
        conn.execute(
            "SELECT ElementID FROM DimTransmissionElements WHERE ElementName = ?",
            (name,),
        ).fetchone()[0]
    )


def _get_or_create_voltage_node(
    conn: sqlite3.Connection,
    name: str,
    nominal_kv: float,
    region_id: int,
) -> int:
    """Resolve a WRLDC voltage node at a known nominal voltage level."""

    location = voltage_node_location(name)
    conn.execute(
        """
        INSERT OR IGNORE INTO DimVoltageNodes(
            NodeName, NominalVoltageKV, StateID, RegionID
        ) VALUES (?, ?, ?, ?)
        """,
        (
            name,
            nominal_kv,
            _canonical_state_id(conn, location.state_name),
            _canonical_region_id(conn, location.region_name) or region_id,
        ),
    )
    return int(
        conn.execute(
            """
            SELECT VoltageNodeID FROM DimVoltageNodes
            WHERE NodeName = ? AND NominalVoltageKV = ?
            """,
            (name, nominal_kv),
        ).fetchone()[0]
    )


def _get_or_create_reservoir(
    conn: sqlite3.Connection,
    name: str,
    region_id: int,
) -> int:
    """Resolve a known WRLDC reservoir and its approved state association."""

    state_names = {
        "indirasagar": "Madhya Pradesh",
        "omkareshwar": "Madhya Pradesh",
        "uk\u00e4i": "Gujarat",
        "ukai": "Gujarat",
        "kadana": "Gujarat",
        "ssp": "Gujarat",
        "koyna": "Maharashtra",
        "tatabhira": "Maharashtra",
    }
    normalized = re.sub(r"[^a-z]", "", name.lower())
    state_name = state_names.get(normalized)
    state_id = _resolve_state_id(conn, 0, state_name, record=False) if state_name else None
    conn.execute(
        """
        INSERT OR IGNORE INTO DimReservoirs(ReservoirName, StateID, RegionID)
        VALUES (?, ?, ?)
        """,
        (name, state_id, region_id),
    )
    return int(
        conn.execute(
            "SELECT ReservoirID FROM DimReservoirs WHERE ReservoirName = ?",
            (name,),
        ).fetchone()[0]
    )


def _validate_average_mw(
    conn: sqlite3.Connection,
    report_id: int,
    entity_name: str,
    values: dict[str, float | str | None],
) -> None:
    """Record an auditable warning when net energy and reported average disagree."""
    net_energy = values.get("NetEnergyMU")
    average_mw = values.get("AverageMW")
    if not isinstance(net_energy, float) or not isinstance(average_mw, float):
        return
    expected_average = net_energy * 1000.0 / 24.0
    tolerance = max(5.0, abs(expected_average) * 0.01)
    if abs(average_mw - expected_average) > tolerance:
        record_resolution_issue(
            conn,
            report_id,
            "wrldc",
            "generation_average_mw",
            entity_name,
            f"reported={average_mw};expected={expected_average:.2f};tolerance={tolerance:.2f}",
        )
