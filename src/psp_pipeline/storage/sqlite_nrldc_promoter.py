"""Promote verified NRLDC daily PSP sections into curated SQLite facts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import re
import sqlite3

from psp_pipeline.parsing.rldc.templates import (
    NRLDC_2024_TEMPLATE,
    NRLDC_2025_TEMPLATE,
    NRLDC_2026_TEMPLATE,
)
from psp_pipeline.parsing.rldc.spatial_rows import (
    SpatialTextItem,
    reconstruct_generation_rows,
)
from psp_pipeline.storage.sqlite_dimensions import (
    DimensionResolutionError,
    record_resolution_issue,
    resolve_generation_identity,
    resolve_state_id,
)
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema


NR_REGION_NAME = "Northern Region"
NRLDC_TEMPLATE_IDS = frozenset(
    (
        NRLDC_2024_TEMPLATE.template_id,
        NRLDC_2025_TEMPLATE.template_id,
        NRLDC_2026_TEMPLATE.template_id,
    )
)

_REGIONAL_COLUMNS = {
    NRLDC_2024_TEMPLATE.template_id: {
        "EveningPeakDemandMetMW": 1,
        "EveningPeakShortageMW": 3,
        "EveningPeakRequirementMW": 7,
        "EveningPeakFrequencyHz": 9,
        "OffPeakDemandMetMW": 12,
        "OffPeakShortageMW": 15,
        "OffPeakRequirementMW": 20,
        "OffPeakFrequencyHz": 23,
        "DayEnergyMetMU": 28,
        "DayEnergyShortageMU": 35,
    },
    NRLDC_2025_TEMPLATE.template_id: {
        "EveningPeakDemandMetMW": 1,
        "EveningPeakShortageMW": 3,
        "EveningPeakRequirementMW": 7,
        "EveningPeakFrequencyHz": 10,
        "OffPeakDemandMetMW": 13,
        "OffPeakShortageMW": 16,
        "OffPeakRequirementMW": 21,
        "OffPeakFrequencyHz": 27,
        "DayEnergyMetMU": 30,
        "DayEnergyShortageMU": 37,
    },
    NRLDC_2026_TEMPLATE.template_id: {
        "EveningPeakDemandMetMW": 1,
        "EveningPeakShortageMW": 3,
        "EveningPeakRequirementMW": 7,
        "EveningPeakFrequencyHz": 10,
        "OffPeakDemandMetMW": 13,
        "OffPeakShortageMW": 16,
        "OffPeakRequirementMW": 21,
        "OffPeakFrequencyHz": 27,
        "DayEnergyMetMU": 30,
        "DayEnergyShortageMU": 37,
    },
}

_STATE_POSITION_COLUMNS = {
    NRLDC_2024_TEMPLATE.template_id: {
        "ThermalGenerationMU": 4,
        "HydroGenerationMU": 6,
        "GasNapthaDieselGenerationMU": 8,
        "SolarGenerationMU": 10,
        "WindGenerationMU": 13,
        "OtherGenerationMU": 16,
        "TotalGenerationMU": 21,
        "ScheduledDrawalMU": 22,
        "ActualDrawalMU": 25,
        "UIMU": 29,
        "RequirementMU": 32,
        "EnergyShortageMU": 35,
        "ConsumptionMU": 37,
    },
    NRLDC_2025_TEMPLATE.template_id: {
        "ThermalGenerationMU": 4,
        "HydroGenerationMU": 6,
        "GasNapthaDieselGenerationMU": 8,
        "SolarGenerationMU": 11,
        "WindGenerationMU": 14,
        "OtherGenerationMU": 17,
        "TotalGenerationMU": 22,
        "ScheduledDrawalMU": 24,
        "ActualDrawalMU": 28,
        "UIMU": 31,
        "RequirementMU": 34,
        "EnergyShortageMU": 37,
        "ConsumptionMU": 39,
    },
    NRLDC_2026_TEMPLATE.template_id: {
        "ThermalGenerationMU": 4,
        "HydroGenerationMU": 6,
        "GasNapthaDieselGenerationMU": 8,
        "SolarGenerationMU": 11,
        "WindGenerationMU": 14,
        "OtherGenerationMU": 17,
        "TotalGenerationMU": 22,
        "ScheduledDrawalMU": 24,
        "ActualDrawalMU": 28,
        "UIMU": 31,
        "RequirementMU": 34,
        "EnergyShortageMU": 37,
        "ConsumptionMU": 39,
    },
}

_GENERATION_COLUMNS = {
    NRLDC_2024_TEMPLATE.template_id: {
        "InstalledCapacityMW": 2,
        "EveningPeakMW": 3,
        "OffPeakMW": 4,
        "DayPeakMW": 5,
        "DayPeakTime": 6,
        "GrossEnergyMU": 7,
        "NetEnergyMU": 8,
        "AverageMW": 9,
    },
    NRLDC_2025_TEMPLATE.template_id: {
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
    },
    NRLDC_2026_TEMPLATE.template_id: {
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
    },
}
_NRLDC_2026_RAW_CONTINUATION_DENSE_COLUMNS = {
    "InstalledCapacityMW": 2,
    "DeclaredCapacityMW": 3,
    "EveningPeakMW": 4,
    "OffPeakMW": 5,
    "DayPeakMW": 6,
    "DayPeakTime": 7,
    "MinimumGenerationMW": 8,
    "MinimumGenerationTime": 9,
    "ScheduledEnergyMU": 10,
    "GrossEnergyMU": 11,
    "NetEnergyMU": 12,
    "AverageMW": 13,
    "UIMU": 14,
}
_NRLDC_2026_RAW_CONTINUATION_SPARSE_COLUMNS = {
    "InstalledCapacityMW": 3,
    "DeclaredCapacityMW": 4,
    "EveningPeakMW": 6,
    "OffPeakMW": 8,
    "DayPeakMW": 10,
    "DayPeakTime": 12,
    "MinimumGenerationMW": 14,
    "MinimumGenerationTime": 15,
    "ScheduledEnergyMU": 17,
    "GrossEnergyMU": 18,
    "NetEnergyMU": 21,
    "AverageMW": 22,
    "UIMU": 23,
}
_MARKET_DAY_ENERGY_PAGE = {
    NRLDC_2025_TEMPLATE.template_id: 11,
    NRLDC_2026_TEMPLATE.template_id: 12,
}
_MARKET_DAY_ENERGY_COLUMNS = {
    "GNAScheduleMU": 4,
    "TGNABilateralMU": 7,
    "GDAMScheduleMU": 10,
    "DAMScheduleMU": 15,
    "RTMScheduleMU": 19,
    "TotalMU": 23,
}
_MARKET_POINT_PAGE = NRLDC_2026_TEMPLATE.template_id
_MARKET_OFF_PEAK_COLUMNS = {
    "TGNABilateralMW": 2,
    "IEXGDAMMW": 4,
    "IEXDAMMW": 5,
    "IEXRTMMW": 7,
    "PXILGDAMMW": 8,
    "PXILDAMMW": 10,
    "PXIRTMMW": 11,
}
_MARKET_PEAK_COLUMNS = {
    "TGNABilateralMW": 13,
    "IEXGDAMMW": 14,
    "IEXDAMMW": 16,
    "IEXRTMMW": 18,
    "PXILGDAMMW": 20,
    "PXILDAMMW": 22,
    "PXIRTMMW": 24,
}
_MARKET_EXTREMA_FIRST_BLOCK = {
    "GNA": (2, 5),
    "T_GNA_BILATERAL": (8, 12),
    "IEX_GDAM": (16, 20),
    "PXIL_GDAM": (22, 25),
}
_MARKET_EXTREMA_SECOND_BLOCK = {
    "IEX_DAM": (3, 6),
    "PXIL_DAM": (9, 11),
    "IEX_RTM": (14, 17),
    "PXIL_RTM": (21, 24),
}
_PAGE_ELEVEN_24_COLUMN_VOLTAGE_COLUMNS = {
    "MaximumKV": 3,
    "MinimumKV": 9,
    "LowCriticalPct": 15,
    "LowWarningPct": 17,
    "HighWarningPct": 19,
    "HighCriticalPct": 21,
    "VoltageDeviationIndexPct": 23,
}
_PAGE_ELEVEN_28_COLUMN_VOLTAGE_COLUMNS = {
    "MaximumKV": 3,
    "MinimumKV": 10,
    "LowCriticalPct": 18,
    "LowWarningPct": 20,
    "HighWarningPct": 22,
    "HighCriticalPct": 24,
    "VoltageDeviationIndexPct": 27,
}


def promote_nrldc_report_to_curated(
    conn: sqlite3.Connection,
    report_document_id: int,
) -> None:
    """Promote verified NRLDC regional, state, and generation sections."""
    from psp_pipeline.storage.sqlite_curated_promoter import (
        _fetch_report,
        _get_or_create_date_id,
        _record_unrecognized_report,
    )

    ensure_curated_sqlite_schema(conn)
    report = _fetch_report(conn, report_document_id)
    if not report or report["rldc"] != "nrldc":
        return
    template_id = str(report.get("template_id") or "")
    if template_id not in NRLDC_TEMPLATE_IDS or _has_curated_scope_deviation(report):
        _clear_nrldc_curated_report(conn, report_document_id)
        _record_unrecognized_report(conn, report_document_id, report)
        return

    date_id = _get_or_create_date_id(conn, report["report_date"])
    region_id = _lookup_region_id(conn)
    if date_id is None or region_id is None:
        return

    _upsert_dim_report(conn, date_id, report)
    _clear_nrldc_curated_report(conn, report_document_id)

    mapped_cells: set[int] = set()
    validation_failures = 0
    _promote_regional_daily(
        conn, report_document_id, date_id, region_id, template_id, mapped_cells
    )
    validation_failures += _promote_state_daily(
        conn, report_document_id, date_id, template_id, mapped_cells
    )
    validation_failures += _promote_state_generation(
        conn, report_document_id, date_id, region_id, template_id, mapped_cells
    )
    validation_failures += _promote_regional_generation(
        conn, report_document_id, date_id, region_id, template_id, mapped_cells
    )
    validation_failures += _promote_spatial_continuation_generation(
        conn, report_document_id, date_id, region_id, template_id
    )
    validation_failures += _promote_2026_raw_continuation_generation(
        conn,
        report_document_id,
        date_id,
        region_id,
        template_id,
        mapped_cells,
    )
    _promote_frequency_daily(conn, report_document_id, date_id, region_id, mapped_cells)
    _promote_voltage_profiles(conn, report_document_id, date_id, region_id, mapped_cells)
    _promote_reservoirs(conn, report_document_id, date_id, region_id, mapped_cells)
    _promote_physical_exchanges(conn, report_document_id, date_id, mapped_cells)
    _promote_schedule_exchanges(conn, report_document_id, date_id, mapped_cells)
    _promote_nepal_exchanges(conn, report_document_id, date_id, mapped_cells)
    if not _market_scope_is_affected(report, template_id):
        _promote_market_day_energy(
            conn,
            report_document_id,
            date_id,
            template_id,
            mapped_cells,
        )
    if not _market_point_scope_is_affected(report, template_id):
        _promote_2026_market_point_in_time(
            conn,
            report_document_id,
            date_id,
            template_id,
            mapped_cells,
        )
    if not _market_extrema_scope_is_affected(report, template_id):
        _promote_2026_market_extrema(
            conn,
            report_document_id,
            date_id,
            mapped_cells,
        )
    _record_initial_coverage(
        conn, report_document_id, template_id, mapped_cells, validation_failures
    )


def _has_curated_scope_deviation(report: sqlite3.Row) -> bool:
    """Return whether template drift affects sections promoted by this module.

    This promoter owns regional, state-position, and station-generation data on
    pages 1 through 4. Differences in later sections remain visible on the
    report record but do not discard verified facts from this stable scope.
    """

    if not report["semantic_pass_required"]:
        return False
    reason = str(report.get("structure_deviation_reason") or "")
    return bool(re.search(r"(?:p[1-4]_t|missing_table=p[1-4]_)", reason))


def _market_scope_is_affected(
    report: Mapping[str, object],
    template_id: str,
) -> bool:
    """Block market promotion only when its verified page has structural drift."""

    if not report["semantic_pass_required"]:
        return False
    page_no = _MARKET_DAY_ENERGY_PAGE.get(template_id)
    if page_no is None:
        return True
    reason = str(report.get("structure_deviation_reason") or "")
    return bool(re.search(rf"(?:p{page_no}_t|missing_table=p{page_no}_)", reason))


def _market_point_scope_is_affected(
    report: Mapping[str, object],
    template_id: str,
) -> bool:
    """Block point-in-time promotion until its verified 2026 layout is stable."""

    if template_id != _MARKET_POINT_PAGE:
        return True
    if not report["semantic_pass_required"]:
        return False
    reason = str(report.get("structure_deviation_reason") or "")
    return bool(re.search(r"(?:p11_t|missing_table=p11_)", reason))


def _market_extrema_scope_is_affected(
    report: Mapping[str, object],
    template_id: str,
) -> bool:
    """Block Section 7(B) promotion until its verified page-12 layout is stable."""

    if template_id != _MARKET_POINT_PAGE:
        return True
    if not report["semantic_pass_required"]:
        return False
    reason = str(report.get("structure_deviation_reason") or "")
    return bool(re.search(r"(?:p12_t|missing_table=p12_)", reason))


def _clear_nrldc_curated_report(
    conn: sqlite3.Connection,
    report_document_id: int,
) -> None:
    """Remove NRLDC facts and coverage that an updated gate no longer permits."""

    coverage = conn.execute(
        "SELECT CoverageRunID FROM schema_coverage_run WHERE ReportDocumentID = ?",
        (report_document_id,),
    ).fetchone()
    if coverage:
        conn.execute(
            "DELETE FROM schema_coverage_item WHERE CoverageRunID = ?",
            (coverage[0],),
        )
        conn.execute(
            "DELETE FROM schema_coverage_run WHERE CoverageRunID = ?",
            (coverage[0],),
        )
    conn.execute(
        "DELETE FROM curated_field_lineage WHERE ReportDocumentID = ?",
        (report_document_id,),
    )
    conn.execute(
        "DELETE FROM FactNRLDCRegionalDaily WHERE ReportDocumentID = ?",
        (report_document_id,),
    )
    conn.execute(
        "DELETE FROM FactNRLDCStateDaily WHERE ReportDocumentID = ?",
        (report_document_id,),
    )
    conn.execute(
        "DELETE FROM FactNRLDCGenerationDaily WHERE ReportDocumentID = ?",
        (report_document_id,),
    )
    for table_name in (
        "FactNRLDCFrequencyDaily",
        "FactNRLDCVoltageProfile",
        "FactNRLDCReservoirDaily",
        "FactNRLDCInterRegionalExchange",
        "FactNRLDCInterRegionalScheduleExchange",
        "FactNRLDCInternationalExchange",
        "FactNRLDCStateMarketDaily",
        "FactNRLDCStateMarketPointDaily",
        "FactNRLDCStateMarketExtremaDaily",
    ):
        conn.execute(
            f"DELETE FROM {table_name} WHERE ReportDocumentID = ?",
            (report_document_id,),
        )


def _promote_market_day_energy(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    """Promote the fixture-verified Section 7(A) state Day Energy matrix.

    The contract is shared by the 2025 and 2026 templates; only the page
    number shifts.  Peak/off-peak and Section 7(B) extrema have separate
    grains and are intentionally not handled here.
    """

    page_no = _MARKET_DAY_ENERGY_PAGE.get(template_id)
    if page_no is None:
        return
    in_day_energy = False
    for row in _table_rows(conn, report_id, page_no, 1):
        label_cell = row.get(1)
        label = _clean_label(label_cell[1]) if label_cell else ""
        normalized = re.sub(r"[^a-z0-9]", "", label.lower())
        day_energy_header = "dayenergy" in re.sub(
            r"[^a-z]", "", str(row.get(4, (0, ""))[1]).lower()
        )
        if normalized == "state" and day_energy_header:
            in_day_energy = True
            continue
        if in_day_energy and normalized.startswith("7b"):
            break
        if not in_day_energy or _is_total_row(label):
            continue
        state_id = _resolve_state_id(conn, report_id, label, record=False)
        if state_id is None:
            continue
        values, sources = _mapped_values(row, _MARKET_DAY_ENERGY_COLUMNS)
        if not any(value is not None for value in values.values()):
            continue
        columns = list(values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCStateMarketDaily(
                ReportDocumentID, DateID, StateID, {', '.join(columns)}
            ) VALUES (?, ?, ?, {', '.join('?' for _ in columns)})
            """,
            (report_id, date_id, state_id, *(values[column] for column in columns)),
        )
        if label_cell:
            mapped_cells.add(label_cell[0])
        _write_lineage(
            conn,
            report_id,
            "FactNRLDCStateMarketDaily",
            f"report={report_id};date={date_id};state={state_id}",
            sources,
            mapped_cells,
        )


def _promote_2026_market_point_in_time(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    """Promote the verified 03:00 and 19:00 Section 7(A) market snapshots."""

    if template_id != _MARKET_POINT_PAGE:
        return
    in_section = False
    for row in _table_rows(conn, report_id, 11, 1):
        label_cell = row.get(1)
        label = _clean_label(label_cell[1]) if label_cell else ""
        normalized = re.sub(r"[^a-z0-9]", "", label.lower())
        if normalized.startswith("7ashorttermopenaccessdetails"):
            in_section = True
            continue
        if not in_section:
            continue
        if normalized == "state":
            continue
        if _is_total_row(label):
            break
        state_id = _resolve_state_id(conn, report_id, label, record=False)
        if state_id is None:
            continue
        for time_category, columns in (
            ("off_peak", _MARKET_OFF_PEAK_COLUMNS),
            ("peak", _MARKET_PEAK_COLUMNS),
        ):
            values, sources = _mapped_values(row, columns)
            if not any(value is not None for value in values.values()):
                continue
            names = list(values)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO FactNRLDCStateMarketPointDaily(
                    ReportDocumentID, DateID, StateID, TimeCategory,
                    {', '.join(names)}
                ) VALUES (?, ?, ?, ?, {', '.join('?' for _ in names)})
                """,
                (
                    report_id,
                    date_id,
                    state_id,
                    time_category,
                    *(values[name] for name in names),
                ),
            )
            if label_cell:
                mapped_cells.add(label_cell[0])
            _write_lineage(
                conn,
                report_id,
                "FactNRLDCStateMarketPointDaily",
                f"report={report_id};date={date_id};state={state_id};time={time_category}",
                sources,
                mapped_cells,
            )


def _promote_2026_market_extrema(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote Section 7(B) 24-hour market maximum and minimum MW pairs."""

    in_section = False
    columns: dict[str, tuple[int, int]] | None = None
    for row in _table_rows(conn, report_id, 12, 1):
        label_cell = row.get(1)
        label = _clean_label(label_cell[1]) if label_cell else ""
        normalized = re.sub(r"[^a-z0-9]", "", label.lower())
        if normalized.startswith("7bshorttermopenaccessdetails"):
            in_section = True
            continue
        if not in_section:
            continue
        if normalized.startswith("8majorreservoir"):
            break
        if normalized == "state":
            if 2 in row and "gna" in row[2][1].lower():
                columns = _MARKET_EXTREMA_FIRST_BLOCK
            elif (
                3 in row
                and "iexd" in re.sub(r"[^a-z]", "", row[3][1].lower())
            ):
                columns = _MARKET_EXTREMA_SECOND_BLOCK
            continue
        if columns is None or _is_total_row(label):
            continue
        state_id = _resolve_state_id(conn, report_id, label, record=False)
        if state_id is None:
            continue
        for mechanism, (maximum_column, minimum_column) in columns.items():
            maximum_raw = row.get(maximum_column)
            minimum_raw = row.get(minimum_column)
            maximum = _to_float(maximum_raw[1]) if maximum_raw else None
            minimum = _to_float(minimum_raw[1]) if minimum_raw else None
            if maximum is None and minimum is None:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO FactNRLDCStateMarketExtremaDaily(
                    ReportDocumentID, DateID, StateID, Mechanism, MaximumMW, MinimumMW
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (report_id, date_id, state_id, mechanism, maximum, minimum),
            )
            if label_cell:
                mapped_cells.add(label_cell[0])
            sources: dict[str, int] = {}
            if maximum_raw and maximum is not None:
                sources["MaximumMW"] = maximum_raw[0]
            if minimum_raw and minimum is not None:
                sources["MinimumMW"] = minimum_raw[0]
            _write_lineage(
                conn,
                report_id,
                "FactNRLDCStateMarketExtremaDaily",
                f"report={report_id};date={date_id};state={state_id};mechanism={mechanism}",
                sources,
                mapped_cells,
            )


def repromote_nrldc_reports(conn: sqlite3.Connection) -> dict[str, int]:
    """Replay eligible NRLDC reports from persisted raw cells into curated facts.

    This is intentionally independent of PDF extraction. It lets an operator
    apply a corrected field mapping to an existing local SQLite corpus while
    preserving each report's immutable raw-cell lineage.
    """

    reports = conn.execute(
        """
        SELECT id
        FROM psp_report_document
        WHERE rldc = 'nrldc'
          AND template_id IN (?, ?, ?)
        ORDER BY report_date, id
        """,
        tuple(sorted(NRLDC_TEMPLATE_IDS)),
    ).fetchall()
    for (report_document_id,) in reports:
        promote_nrldc_report_to_curated(conn, int(report_document_id))
    return {"reports_repromoted": len(reports)}


def _promote_regional_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> None:
    """Promote Section 1 regional demand, shortage, energy, and frequency values."""
    row = _table_row(conn, report_id, 1, 1, 4)
    if not row:
        return
    values, sources = _mapped_values(row, _REGIONAL_COLUMNS[template_id])
    columns = list(values)
    conn.execute(
        f"""
        INSERT OR REPLACE INTO FactNRLDCRegionalDaily(
            ReportDocumentID, DateID, RegionID, {', '.join(columns)}
        ) VALUES (?, ?, ?, {', '.join('?' for _ in columns)})
        """,
        (report_id, date_id, region_id, *(values[column] for column in columns)),
    )
    key = f"report={report_id};date={date_id};region={region_id}"
    _write_lineage(
        conn, report_id, "FactNRLDCRegionalDaily", key, sources, mapped_cells
    )


def _promote_state_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> int:
    """Promote Section 2(A) state generation and drawal balances."""
    validation_failures = 0
    for row in _state_position_rows(conn, report_id):
        state_cell = row.get(1)
        state_name = state_cell[1].strip() if state_cell else ""
        state_id = _resolve_state_id(conn, report_id, state_name)
        if state_id is None:
            continue
        values, sources = _mapped_values(row, _STATE_POSITION_COLUMNS[template_id])
        if not any(value is not None for value in values.values()):
            continue
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCStateDaily(
                ReportDocumentID, DateID, StateID, {', '.join(values)}
            ) VALUES (?, ?, ?, {', '.join('?' for _ in values)})
            """,
            (report_id, date_id, state_id, *values.values()),
        )
        if state_cell:
            mapped_cells.add(state_cell[0])
        key = f"report={report_id};date={date_id};state={state_id}"
        _write_lineage(
            conn, report_id, "FactNRLDCStateDaily", key, sources, mapped_cells
        )
        component_columns = (
            "ThermalGenerationMU",
            "HydroGenerationMU",
            "GasNapthaDieselGenerationMU",
            "SolarGenerationMU",
            "WindGenerationMU",
            "OtherGenerationMU",
        )
        components = [values[column] for column in component_columns]
        total = values["TotalGenerationMU"]
        if total is not None and all(value is not None for value in components):
            if abs(sum(float(value) for value in components) - float(total)) > 0.05:
                validation_failures += 1
    return validation_failures


def _state_position_rows(
    conn: sqlite3.Connection,
    report_id: int,
) -> list[dict[int, tuple[int, str]]]:
    """Return only Section 2(A) state-balance rows from page one."""
    rows: list[dict[int, tuple[int, str]]] = []
    in_section = False
    for row in _table_rows(conn, report_id, 1, 1):
        label = _clean_label(row.get(1, (0, ""))[1]).lower()
        compact_label = re.sub(r"\s+", "", label)
        if compact_label.startswith("2(a)"):
            in_section = True
            continue
        if in_section and compact_label.startswith(("2(b)", "2(c)")):
            break
        if in_section:
            rows.append(row)
    return rows


def _promote_state_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> int:
    """Promote the verified state-entity generation tables on pages two through four."""
    validation_failures = 0
    for page_no in (2, 3, 4):
        current_state_id: int | None = None
        for row in _table_rows(conn, report_id, page_no, 1):
            entity_cell = row.get(1)
            entity_name = _clean_label(entity_cell[1]) if entity_cell else ""
            candidate_state_id = _resolve_state_id(conn, report_id, entity_name, record=False)
            if candidate_state_id is not None and _cell_float(row, 2) is None:
                current_state_id = candidate_state_id
                if entity_cell:
                    mapped_cells.add(entity_cell[0])
                continue
            if current_state_id is None or not entity_name:
                continue

            values, sources = _generation_values(row, _GENERATION_COLUMNS[template_id])
            capacity = values["InstalledCapacityMW"]
            if capacity is None:
                continue
            is_total = _is_total_row(entity_name)
            source_id = _generation_source_id(conn, entity_name)
            try:
                identity = resolve_generation_identity(
                    conn,
                    "nrldc",
                    entity_name,
                    current_state_id,
                    region_id,
                    source_id,
                    float(capacity),
                    is_total,
                )
            except DimensionResolutionError as error:
                record_resolution_issue(
                    conn, report_id, "nrldc", "generation_entity", entity_name, str(error)
                )
                continue
            entity_id = _get_or_create_grid_entity(
                conn,
                entity_name,
                "generation_aggregate" if is_total else "generating_entity",
                current_state_id,
                region_id,
                source_id,
                float(capacity),
                is_total,
                identity,
            )
            section_name = f"state_generation_{current_state_id}"
            columns = list(values)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO FactNRLDCGenerationDaily(
                    ReportDocumentID, DateID, EntityID, StateID, GenerationSourceID,
                    StationID, GeneratingUnitID, AggregateID, IsTotalRow,
                    GenerationGrain, SectionName, {', '.join(columns)}
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {', '.join('?' for _ in columns)})
                """,
                (
                    report_id,
                    date_id,
                    entity_id,
                    current_state_id,
                    source_id,
                    identity.station_id,
                    identity.generating_unit_id,
                    identity.aggregate_id,
                    int(is_total),
                    identity.entity_type,
                    section_name,
                    *(values[column] for column in columns),
                ),
            )
            if entity_cell:
                mapped_cells.add(entity_cell[0])
            key = f"report={report_id};date={date_id};entity={entity_id};section={section_name}"
            _write_lineage(
                conn, report_id, "FactNRLDCGenerationDaily", key, sources, mapped_cells
            )
            net_energy = values["NetEnergyMU"]
            average_mw = values["AverageMW"]
            if net_energy is not None and average_mw is not None:
                expected_average = float(net_energy) * 1000.0 / 24.0
                tolerance = max(5.0, abs(expected_average) * 0.01)
                if abs(float(average_mw) - expected_average) > tolerance:
                    validation_failures += 1
    return validation_failures


def _promote_regional_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> int:
    """Promote the clean page-five Section 3(B) regional entity table.

    Later pages continue with large IPP and renewable lists whose text cells are
    frequently collapsed by the PDF extractor.  This bounded promoter handles
    only the stable, grid-aligned first page and leaves those continuation pages
    for their source-specific spatial extraction pass.
    """

    validation_failures = 0
    in_section = False
    columns = _regional_generation_columns(template_id)
    for row in _table_rows(conn, report_id, 5, 1):
        entity_cell = row.get(1)
        entity_name = _clean_label(entity_cell[1]) if entity_cell else ""
        normalized = re.sub(r"\s+", "", entity_name.lower())
        if normalized.startswith("3(b)regionalentitiesgeneration"):
            in_section = True
            continue
        if not in_section or not entity_name:
            continue
        values, sources = _generation_values(row, columns)
        capacity = values["InstalledCapacityMW"]
        if capacity is None:
            continue
        is_total = _is_total_row(entity_name)
        source_id = _generation_source_id(conn, entity_name)
        try:
            identity = resolve_generation_identity(
                conn,
                "nrldc",
                entity_name,
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
                "nrldc",
                "regional_generation_entity",
                entity_name,
                str(error),
            )
            continue
        entity_id = _get_or_create_grid_entity(
            conn,
            entity_name,
            "generation_aggregate" if is_total else "generating_entity",
            None,
            region_id,
            source_id,
            float(capacity),
            is_total,
            identity,
        )
        section_name = "regional_entities_generation"
        names = list(values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCGenerationDaily(
                ReportDocumentID, DateID, EntityID, StateID, GenerationSourceID,
                StationID, GeneratingUnitID, AggregateID, IsTotalRow,
                GenerationGrain, SectionName, {', '.join(names)}
            ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?,
                {', '.join('?' for _ in names)})
            """,
            (
                report_id,
                date_id,
                entity_id,
                source_id,
                identity.station_id,
                identity.generating_unit_id,
                identity.aggregate_id,
                int(is_total),
                identity.entity_type,
                section_name,
                *(values[name] for name in names),
            ),
        )
        if entity_cell:
            mapped_cells.add(entity_cell[0])
        key = f"report={report_id};date={date_id};entity={entity_id};section={section_name}"
        _write_lineage(
            conn, report_id, "FactNRLDCGenerationDaily", key, sources, mapped_cells
        )
        net_energy = values["NetEnergyMU"]
        average_mw = values["AverageMW"]
        if net_energy is not None and average_mw is not None:
            expected_average = float(net_energy) * 1000.0 / 24.0
            tolerance = max(5.0, abs(expected_average) * 0.01)
            if abs(float(average_mw) - expected_average) > tolerance:
                validation_failures += 1
    return validation_failures


def _regional_generation_columns(template_id: str) -> dict[str, int]:
    """Return Section 3(B) columns for the approved NRLDC report family."""

    common = {
        "InstalledCapacityMW": 2,
        "DeclaredCapacityMW": 3,
        "EveningPeakMW": 4,
        "OffPeakMW": 5,
        "DayPeakMW": 6,
        "DayPeakTime": 7,
    }
    if template_id == NRLDC_2024_TEMPLATE.template_id:
        return {
            **common,
            "ScheduledEnergyMU": 8,
            "GrossEnergyMU": 9,
            "NetEnergyMU": 10,
            "AGCEnergyMU": 11,
            "AverageMW": 12,
            "UIMU": 13,
        }
    return {
        **common,
        "MinimumGenerationMW": 8,
        "MinimumGenerationTime": 9,
        "ScheduledEnergyMU": 10,
        "GrossEnergyMU": 11,
        "NetEnergyMU": 12,
        "AGCEnergyMU": 13,
        "AverageMW": 14,
        "UIMU": 15,
    }


def _promote_spatial_continuation_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
) -> int:
    """Promote verified 2025/2026 IPP, renewable, hybrid, and storage rows.

    The native PDF table grid collapses many continuation rows into the first
    column.  Only persisted LiteParse coordinates are used here; reports
    without that forensic layer remain review-required and receive no guessed
    continuation facts.
    """

    if template_id == NRLDC_2024_TEMPLATE.template_id or not _table_exists(
        conn, "psp_raw_text_item"
    ):
        return 0
    items_by_page: dict[int, list[SpatialTextItem]] = {}
    for raw_id, page_no, text, x, y in conn.execute(
        """
        SELECT id, page_no, item_text, x, y
        FROM psp_raw_text_item
        WHERE report_document_id = ?
          AND extraction_method = 'liteparse'
          AND page_no IN (6, 7, 8, 9)
          AND x IS NOT NULL
          AND y IS NOT NULL
        ORDER BY page_no, item_no
        """,
        (report_id,),
    ):
        items_by_page.setdefault(int(page_no), []).append(
            SpatialTextItem(int(raw_id), int(page_no), str(text), float(x), float(y))
        )

    validation_failures = 0
    for page_no, items in items_by_page.items():
        rows = reconstruct_generation_rows(
            items,
            column_centers=_NRLDC_CONTINUATION_COLUMN_CENTERS,
        )
        for row in rows:
            values = _spatial_generation_values(row.values)
            capacity = values["InstalledCapacityMW"]
            entity_name = _clean_continuation_entity_name(row.label)
            if (
                capacity is None
                or _is_header_or_unit(entity_name)
                or not _is_complete_continuation_entity_name(entity_name)
            ):
                continue
            is_total = _is_total_row(entity_name)
            source_id = _generation_source_id(conn, entity_name)
            try:
                identity = resolve_generation_identity(
                    conn,
                    "nrldc",
                    entity_name,
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
                    "nrldc",
                    "continuation_generation_entity",
                    entity_name,
                    str(error),
                )
                continue
            entity_id = _get_or_create_grid_entity(
                conn,
                entity_name,
                "generation_aggregate" if is_total else "generating_entity",
                None,
                region_id,
                source_id,
                float(capacity),
                is_total,
                identity,
            )
            section_name = f"continuation_spatial_p{page_no}"
            names = list(values)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO FactNRLDCGenerationDaily(
                    ReportDocumentID, DateID, EntityID, StateID, GenerationSourceID,
                    StationID, GeneratingUnitID, AggregateID, IsTotalRow,
                    GenerationGrain, SectionName, {', '.join(names)}
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?,
                    {', '.join('?' for _ in names)})
                """,
                (
                    report_id,
                    date_id,
                    entity_id,
                    source_id,
                    identity.station_id,
                    identity.generating_unit_id,
                    identity.aggregate_id,
                    int(is_total),
                    identity.entity_type,
                    section_name,
                    *(values[name] for name in names),
                ),
            )
            key = (
                f"report={report_id};date={date_id};entity={entity_id};"
                f"section={section_name}"
            )
            _write_spatial_lineage(
                conn,
                report_id,
                "FactNRLDCGenerationDaily",
                key,
                row.label_item_ids,
                row.value_item_ids,
            )
            net_energy = values["NetEnergyMU"]
            average_mw = values["AverageMW"]
            if net_energy is not None and average_mw is not None:
                expected_average = float(net_energy) * 1000.0 / 24.0
                tolerance = max(5.0, abs(expected_average) * 0.01)
                if abs(float(average_mw) - expected_average) > tolerance:
                    validation_failures += 1
    return validation_failures


def _promote_2026_raw_continuation_generation(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    template_id: str,
    mapped_cells: set[int],
) -> int:
    """Attach raw-cell lineage to complete 2026 renewable continuation rows.

    LiteParse remains the source for line-wrapped or collapsed continuation
    rows.  This pass accepts only rows with a published capacity in the
    verified native grid, retaining the same fact grain while making their
    exact raw cells auditable in the coverage gate.
    """

    if template_id != NRLDC_2026_TEMPLATE.template_id:
        return 0

    validation_failures = 0
    active_source_id: int | None = None
    for page_no, columns in (
        (7, _NRLDC_2026_RAW_CONTINUATION_DENSE_COLUMNS),
        (8, _NRLDC_2026_RAW_CONTINUATION_DENSE_COLUMNS),
        (9, _NRLDC_2026_RAW_CONTINUATION_SPARSE_COLUMNS),
    ):
        for row in _table_rows(conn, report_id, page_no, 1):
            label_cell = row.get(1)
            label = _clean_label(label_cell[1]) if label_cell else ""
            normalized = re.sub(r"[^a-z]", "", label.lower())
            if normalized.startswith("summarysection"):
                return validation_failures
            heading_source_id = _continuation_heading_source_id(conn, normalized)
            if heading_source_id is not None or normalized in {
                "ipp",
                "hybridipp",
                "bess",
            }:
                active_source_id = heading_source_id
                continue

            values, sources = _generation_values(row, columns)
            capacity = values["InstalledCapacityMW"]
            if not label or capacity is None:
                continue
            is_total = _is_total_row(label)
            source_id = _generation_source_id(conn, label) or active_source_id
            try:
                identity = resolve_generation_identity(
                    conn,
                    "nrldc",
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
                    "nrldc",
                    "continuation_generation_entity",
                    label,
                    str(error),
                )
                continue
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
            section_name = f"continuation_spatial_p{page_no}"
            names = list(values)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO FactNRLDCGenerationDaily(
                    ReportDocumentID, DateID, EntityID, StateID, GenerationSourceID,
                    StationID, GeneratingUnitID, AggregateID, IsTotalRow,
                    GenerationGrain, SectionName, {', '.join(names)}
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?,
                    {', '.join('?' for _ in names)})
                """,
                (
                    report_id,
                    date_id,
                    entity_id,
                    source_id,
                    identity.station_id,
                    identity.generating_unit_id,
                    identity.aggregate_id,
                    int(is_total),
                    identity.entity_type,
                    section_name,
                    *(values[name] for name in names),
                ),
            )
            if label_cell:
                mapped_cells.add(label_cell[0])
            _write_lineage(
                conn,
                report_id,
                "FactNRLDCGenerationDaily",
                f"report={report_id};date={date_id};entity={entity_id};section={section_name}",
                sources,
                mapped_cells,
            )
            net_energy = values["NetEnergyMU"]
            average_mw = values["AverageMW"]
            if net_energy is not None and average_mw is not None:
                expected_average = float(net_energy) * 1000.0 / 24.0
                tolerance = max(5.0, abs(expected_average) * 0.01)
                if abs(float(average_mw) - expected_average) > tolerance:
                    validation_failures += 1
    return validation_failures


def _continuation_heading_source_id(
    conn: sqlite3.Connection,
    normalized_label: str,
) -> int | None:
    """Resolve only explicit continuation source headings, never suffix hints."""

    if normalized_label == "solaripp":
        return _generation_source_id(conn, "solar")
    return None


_NRLDC_CONTINUATION_COLUMN_CENTERS = {
    "InstalledCapacityMW": 121.0,
    "DeclaredCapacityMW": 165.0,
    "EveningPeakMW": 207.0,
    "OffPeakMW": 246.0,
    "DayPeakMW": 286.0,
    "DayPeakTime": 329.0,
    "MinimumGenerationMW": 380.0,
    "MinimumGenerationTime": 420.0,
    "ScheduledEnergyMU": 459.0,
    "GrossEnergyMU": 502.0,
    "NetEnergyMU": 542.0,
    "AverageMW": 582.0,
    "UIMU": 620.0,
}


def _spatial_generation_values(
    raw_values: dict[str, str] | Mapping[str, str],
) -> dict[str, float | str | None]:
    """Normalize values reconstructed from the approved spatial column centers."""

    values: dict[str, float | str | None] = {}
    for field_name in _NRLDC_CONTINUATION_COLUMN_CENTERS:
        raw = raw_values.get(field_name)
        if field_name in {"DayPeakTime", "MinimumGenerationTime"}:
            values[field_name] = _normalize_time(raw)
        else:
            values[field_name] = _to_float(raw)
    return values


def _clean_continuation_entity_name(label: str) -> str:
    """Remove a detached source heading from a reconstructed station label."""

    if re.search(r"sub[-\s]*total|^total$", label, re.IGNORECASE):
        return "Sub-Total" if "sub" in label.lower() else "Total"
    return re.sub(
        r"^(?:IPP|SOLAR\s+IPP|HYBRID\s+IPP|STORAGE|BESS)\s+",
        "",
        label,
        flags=re.IGNORECASE,
    ).strip()


def _is_complete_continuation_entity_name(label: str) -> bool:
    """Reject spatial labels visibly truncated by a page-row boundary."""

    if _is_total_row(label):
        return True
    if not re.match(r"[A-Za-z]", label):
        return False
    return bool(
        re.search(
            r"(?:\)|\b(?:limited|ltd\.?|hps|hep|tps|stps|gps)|_?bess)$",
            label,
            re.IGNORECASE,
        )
    )


def _promote_frequency_daily(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote the regional frequency summary from the Section 5 data row."""

    for _, row in _rows_on_pages(conn, report_id, (9, 10, 11)):
        maximum = _cell_float(row, 1)
        minimum = _cell_float(row, 4)
        average = _cell_float(row, 12)
        if maximum is None or minimum is None or average is None:
            continue
        if not 45.0 <= maximum <= 55.0 or not 45.0 <= minimum <= 55.0:
            continue
        values, sources = _mapped_values(
            row,
            {
                "MaximumFrequencyHz": 1,
                "MinimumFrequencyHz": 4,
                "AverageFrequencyHz": 12,
                "FrequencyVariationIndex": 15,
                "StandardDeviationHz": 18,
                "Maximum15MinuteBlockFrequencyHz": 19,
                "Minimum15MinuteBlockFrequencyHz": 22,
                "FrequencyDeviationIndexPct": 24,
            },
        )
        values["MaximumFrequencyTime"] = _cell_time(row, 3)
        values["MinimumFrequencyTime"] = _cell_time(row, 8)
        for column in ("MaximumFrequencyTime", "MinimumFrequencyTime"):
            raw = row.get(3 if column.startswith("Maximum") else 8)
            if raw and values[column] is not None:
                sources[column] = raw[0]
        columns = list(values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCFrequencyDaily(
                ReportDocumentID, DateID, RegionID, {', '.join(columns)}
            ) VALUES (?, ?, ?, {', '.join('?' for _ in columns)})
            """,
            (report_id, date_id, region_id, *(values[column] for column in columns)),
        )
        _write_lineage(
            conn,
            report_id,
            "FactNRLDCFrequencyDaily",
            f"report={report_id};date={date_id};region={region_id}",
            sources,
            mapped_cells,
        )
        return


def _promote_voltage_profiles(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote 400 and 765 kV voltage rows using their printed section headings."""

    nominal_kv: float | None = None
    for page_no, row in _rows_on_pages(conn, report_id, (10, 11)):
        label = _clean_label(row.get(1, (0, ""))[1])
        heading = re.search(r"voltage\s*profile\s*:\s*(\d+)", label, re.IGNORECASE)
        if heading:
            nominal_kv = float(heading.group(1))
            continue
        if label.lower().startswith("7(a)"):
            break
        if nominal_kv is None or not label or _is_header_or_unit(label):
            continue
        if page_no == 10:
            columns = {
                "MaximumKV": 3,
                "MinimumKV": 8,
                "LowCriticalPct": 15,
                "LowWarningPct": 18,
                "HighWarningPct": 19,
                "HighCriticalPct": 22,
                "VoltageDeviationIndexPct": 24,
            }
            maximum_time_column, minimum_time_column = 4, 12
        else:
            layout = _page_eleven_voltage_layout(row)
            if layout is None:
                continue
            columns, maximum_time_column, minimum_time_column = layout
        maximum = _cell_float(row, columns["MaximumKV"])
        minimum = _cell_float(row, columns["MinimumKV"])
        if maximum is None or minimum is None:
            continue
        values, sources = _mapped_values(row, columns)
        values["MaximumTime"] = _cell_time(row, maximum_time_column)
        values["MinimumTime"] = _cell_time(row, minimum_time_column)
        for column, cell_column in (
            ("MaximumTime", maximum_time_column),
            ("MinimumTime", minimum_time_column),
        ):
            raw = row.get(cell_column)
            if raw and values[column] is not None:
                sources[column] = raw[0]
        node_id = _get_or_create_voltage_node(conn, label, nominal_kv, region_id)
        columns_to_insert = list(values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCVoltageProfile(
                ReportDocumentID, DateID, VoltageNodeID, NominalVoltageKV,
                {', '.join(columns_to_insert)}
            ) VALUES (?, ?, ?, ?, {', '.join('?' for _ in columns_to_insert)})
            """,
            (
                report_id,
                date_id,
                node_id,
                nominal_kv,
                *(values[column] for column in columns_to_insert),
            ),
        )
        if row.get(1):
            mapped_cells.add(row[1][0])
        _write_lineage(
            conn,
            report_id,
            "FactNRLDCVoltageProfile",
            f"report={report_id};date={date_id};node={node_id}",
            sources,
            mapped_cells,
        )


def _page_eleven_voltage_layout(
    row: dict[int, tuple[int, str]],
) -> tuple[dict[str, int], int, int] | None:
    """Return the verified Page 11 voltage map for one printed node row.

    A 24-column continuation uses minimum voltage at column nine.  Later
    reports retain the established 28-column geometry with minimum voltage at
    column ten.  Both maps require their distinguishing minimum-value column
    to contain a numeric value before a fact can be emitted.
    """

    if _cell_float(row, 9) is not None and _cell_float(row, 10) is None:
        return _PAGE_ELEVEN_24_COLUMN_VOLTAGE_COLUMNS, 6, 12
    if _cell_float(row, 10) is not None:
        return _PAGE_ELEVEN_28_COLUMN_VOLTAGE_COLUMNS, 6, 14
    return None


def _promote_reservoirs(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    region_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote Section 8 reservoir levels, energy, inflow, and usage values."""

    in_section = False
    for _, row in _rows_on_pages(conn, report_id, (12, 13)):
        label = _clean_label(row.get(1, (0, ""))[1])
        normalized = re.sub(r"\s+", "", label.lower())
        if normalized.startswith("8.majorreservoir"):
            in_section = True
            continue
        if in_section and normalized.startswith("9.systemreliability"):
            break
        if not in_section or not label or _is_total_row(label):
            continue
        if _cell_float(row, 3) is None or _cell_float(row, 7) is None:
            continue
        values, sources = _mapped_values(
            row,
            {
                "MinimumDrawdownLevelM": 3,
                "FullReservoirLevelM": 7,
                "EnergyContentAtFullReservoirMU": 12,
                "CurrentLevelM": 17,
                "CurrentEnergyMU": 19,
                "PreviousYearLevelM": 23,
                "PreviousYearEnergyMU": 25,
                "InflowCusec": 28,
                "UsageCusec": 31,
            },
        )
        reservoir_id = _get_or_create_reservoir(conn, label, region_id)
        columns = list(values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCReservoirDaily(
                ReportDocumentID, DateID, ReservoirID, {', '.join(columns)}
            ) VALUES (?, ?, ?, {', '.join('?' for _ in columns)})
            """,
            (report_id, date_id, reservoir_id, *(values[column] for column in columns)),
        )
        if row.get(1):
            mapped_cells.add(row[1][0])
        _write_lineage(
            conn,
            report_id,
            "FactNRLDCReservoirDaily",
            f"report={report_id};date={date_id};reservoir={reservoir_id}",
            sources,
            mapped_cells,
        )


def _promote_physical_exchanges(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote Section 4(A) line-level exchange energy by counterparty region."""

    counterparty = ""
    in_section = False
    for page_no, row in _rows_on_pages(conn, report_id, (9, 10)):
        label = _clean_label(row.get(1, (0, ""))[1])
        normalized = re.sub(r"\s+", "", label.lower())
        if normalized.startswith(("4(a)interregionalexchange", "4(a)inter-region")):
            in_section = True
            continue
        if in_section and normalized.startswith("4(b)"):
            break
        if not in_section:
            continue
        region_match = re.search(r"between(.+?)andnorthregion", normalized)
        if region_match:
            counterparty = region_match.group(1).upper().replace("_", " ")
            continue
        name_cell = row.get(2) if page_no == 9 else row.get(3)
        element_name = _clean_label(name_cell[1]) if name_cell else ""
        if not counterparty or not re.search(r"(?:kv|hvdc)", element_name, re.I):
            continue
        columns = (
            {
                "EveningPeakMW": 7,
                "OffPeakMW": 11,
                "MaximumImportMW": 13,
                "MaximumExportMW": 16,
                "ImportEnergyMU": 20,
                "ExportEnergyMU": 22,
                "NetEnergyMU": 23,
            }
            if page_no == 9
            else {
                "EveningPeakMW": 7,
                "OffPeakMW": 9,
                "MaximumImportMW": 12,
                "MaximumExportMW": 15,
                "ImportEnergyMU": 19,
                "ExportEnergyMU": 22,
                "NetEnergyMU": 24,
            }
        )
        values, sources = _mapped_values(row, columns)
        element_id = _get_or_create_transmission_element(conn, element_name)
        names = list(values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCInterRegionalExchange(
                ReportDocumentID, DateID, ElementID, CounterpartyRegion,
                {', '.join(names)}
            ) VALUES (?, ?, ?, ?, {', '.join('?' for _ in names)})
            """,
            (report_id, date_id, element_id, counterparty, *(values[name] for name in names)),
        )
        if name_cell:
            mapped_cells.add(name_cell[0])
        _write_lineage(
            conn,
            report_id,
            "FactNRLDCInterRegionalExchange",
            f"report={report_id};date={date_id};element={element_id};region={counterparty}",
            sources,
            mapped_cells,
        )


def _promote_schedule_exchanges(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote Section 4(B) regional schedule, actual, and deviation energy.

    The printed row position changes as the preceding line-level exchange table
    grows.  Section headings, rather than fixed page coordinates, define the
    extraction boundary.  Rows collapsed by PDF extraction are deliberately
    left as raw cells instead of being reconstructed heuristically.
    """

    in_section = False
    columns = {
        "ISGSAndGNAScheduleMU": 2,
        "BilateralScheduleMU": 6,
        "GDAMScheduleMU": 8,
        "DAMScheduleMU": 11,
        "RTMScheduleMU": 13,
        "TotalScheduleMU": 16,
        "ActualMU": 20,
        "DeviationMU": 23,
    }
    for _, row in _rows_on_pages(conn, report_id, (9, 10, 11)):
        label_cell = row.get(1)
        label = _clean_label(label_cell[1]) if label_cell else ""
        normalized = re.sub(r"\s+", "", label.lower())
        if normalized.startswith("4(b)interregionalschedule"):
            in_section = True
            continue
        if in_section and normalized.startswith("5.internationalexchange"):
            break
        if not in_section:
            continue

        counterparty = _schedule_counterparty(label)
        if counterparty is None:
            continue
        values, sources = _mapped_values(row, columns)
        if not any(value is not None for value in values.values()):
            continue
        is_total = int(counterparty == "TOTAL")
        names = list(values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCInterRegionalScheduleExchange(
                ReportDocumentID, DateID, CounterpartyRegion, IsTotalRow,
                {', '.join(names)}
            ) VALUES (?, ?, ?, ?, {', '.join('?' for _ in names)})
            """,
            (report_id, date_id, counterparty, is_total, *(values[name] for name in names)),
        )
        if label_cell:
            mapped_cells.add(label_cell[0])
        _write_lineage(
            conn,
            report_id,
            "FactNRLDCInterRegionalScheduleExchange",
            f"report={report_id};date={date_id};region={counterparty}",
            sources,
            mapped_cells,
        )


def _promote_nepal_exchanges(
    conn: sqlite3.Connection,
    report_id: int,
    date_id: int,
    mapped_cells: set[int],
) -> None:
    """Promote Section 5 linkwise cross-border exchange with Nepal."""

    in_section = False
    columns = {
        "EveningPeakMW": 5,
        "OffPeakMW": 8,
        "MaximumImportMW": 10,
        "MaximumExportMW": 14,
        "ImportEnergyMU": 17,
        "ExportEnergyMU": 20,
        "NetEnergyMU": 21,
        "ScheduleEnergyMU": 25,
    }
    for _, row in _rows_on_pages(conn, report_id, (9, 10, 11)):
        label_cell = row.get(1)
        label = _clean_label(label_cell[1]) if label_cell else ""
        normalized = re.sub(r"\s+", "", label.lower())
        if normalized.startswith("5.internationalexchangewithnepal"):
            in_section = True
            continue
        if in_section and normalized.startswith("5.frequencyprofile"):
            break
        if not in_section or not _is_transmission_element(label):
            continue
        values, sources = _mapped_values(row, columns)
        if not any(value is not None for value in values.values()):
            continue
        element_id = _get_or_create_transmission_element(conn, label)
        names = list(values)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO FactNRLDCInternationalExchange(
                ReportDocumentID, DateID, ElementID, CounterpartyCountry,
                {', '.join(names)}
            ) VALUES (?, ?, ?, 'Nepal', {', '.join('?' for _ in names)})
            """,
            (report_id, date_id, element_id, *(values[name] for name in names)),
        )
        if label_cell:
            mapped_cells.add(label_cell[0])
        _write_lineage(
            conn,
            report_id,
            "FactNRLDCInternationalExchange",
            f"report={report_id};date={date_id};element={element_id};country=Nepal",
            sources,
            mapped_cells,
        )


def _mapped_values(
    row: dict[int, tuple[int, str]],
    columns: dict[str, int],
) -> tuple[dict[str, float | None], dict[str, int]]:
    values: dict[str, float | None] = {}
    sources: dict[str, int] = {}
    for column, col_no in columns.items():
        raw = row.get(col_no)
        value = _to_float(raw[1]) if raw else None
        values[column] = value
        if raw and value is not None:
            sources[column] = raw[0]
    return values, sources


def _generation_values(
    row: dict[int, tuple[int, str]],
    columns: dict[str, int],
) -> tuple[dict[str, float | str | None], dict[str, int]]:
    values, sources = _mapped_values(row, columns)
    for field_name in ("DayPeakTime", "MinimumGenerationTime"):
        col_no = columns.get(field_name)
        raw = row.get(col_no) if col_no else None
        values[field_name] = _normalize_time(raw[1]) if raw else None
        if raw and values[field_name] is not None:
            sources[field_name] = raw[0]
    for field_name in (
        "MinimumGenerationMW",
        "DayPeakTime",
        "MinimumGenerationTime",
    ):
        values.setdefault(field_name, None)
    return values, sources


def _resolve_state_id(
    conn: sqlite3.Connection,
    report_id: int,
    raw_name: str,
    record: bool = True,
) -> int | None:
    """Resolve one NRLDC state heading through approved aliases only."""
    if not raw_name:
        return None
    try:
        return resolve_state_id(conn, "nrldc", raw_name)
    except DimensionResolutionError:
        if record and _looks_like_state_label(raw_name):
            record_resolution_issue(
                conn, report_id, "nrldc", "state", raw_name, "state alias is not approved"
            )
        return None


def _generation_source_id(conn: sqlite3.Connection, entity_name: str) -> int | None:
    normalized = entity_name.lower()
    source_name = None
    if "thermal" in normalized or any(token in normalized for token in ("tps", "stps")):
        source_name = "Thermal"
    elif "hydro" in normalized or "hps" in normalized:
        source_name = "Hydro"
    elif any(token in normalized for token in ("gas", "naptha", "diesel")):
        source_name = "Gas, Naptha & Diesel"
    elif "solar" in normalized:
        source_name = "Solar"
    elif "wind" in normalized:
        source_name = "Wind"
    if source_name is None:
        return None
    row = conn.execute(
        "SELECT GenerationSourceID FROM DimGenerationSources WHERE SourceName = ?",
        (source_name,),
    ).fetchone()
    return int(row[0]) if row else None


def _record_initial_coverage(
    conn: sqlite3.Connection,
    report_id: int,
    template_id: str,
    mapped_cells: set[int],
    validation_failures: int,
) -> None:
    """Record transparent initial coverage without borrowing SRLDC field contracts."""
    now = datetime.now(timezone.utc).isoformat()
    dispositions: list[tuple[int, str, str, str]] = []
    for raw_id, row_no, col_no, cell_text in conn.execute(
        """
        SELECT id, row_no, col_no, cell_text
        FROM psp_raw_cell
        WHERE report_document_id = ? AND TRIM(COALESCE(cell_text, '')) <> ''
        """,
        (report_id,),
    ):
        text = str(cell_text)
        if int(raw_id) in mapped_cells:
            disposition, reason = "mapped_value", "approved_initial_nrldc_mapping"
        elif int(col_no) == 1:
            disposition, reason = "dimension", "row_label_or_entity"
        elif _is_header_or_unit(text):
            disposition, reason = "header", "recognized_header_or_unit_label"
        elif _to_float(text) is not None:
            disposition, reason = "ambiguous", "numeric_value_without_approved_mapping"
        else:
            disposition, reason = "ambiguous", "text_value_without_approved_mapping"
        reference = f"cell:{raw_id}:r{row_no}:c{col_no}"
        dispositions.append((int(raw_id), reference, disposition, reason))

    expected = sum(
        1
        for _, _, disposition, _ in dispositions
        if disposition not in {"header", "dimension"}
    )
    mapped = sum(1 for _, _, disposition, _ in dispositions if disposition == "mapped_value")
    ambiguous = sum(1 for _, _, disposition, _ in dispositions if disposition == "ambiguous")
    coverage_pct = round(100.0 * mapped / expected, 2) if expected else 0.0
    previous = conn.execute(
        "SELECT CoverageRunID FROM schema_coverage_run WHERE ReportDocumentID = ?",
        (report_id,),
    ).fetchone()
    if previous:
        conn.execute("DELETE FROM schema_coverage_item WHERE CoverageRunID = ?", (previous[0],))
        conn.execute("DELETE FROM schema_coverage_run WHERE CoverageRunID = ?", (previous[0],))
    cursor = conn.execute(
        """
        INSERT INTO schema_coverage_run(
            ReportDocumentID, TemplateID, ExpectedFieldCount, MappedFieldCount,
            ExcludedFieldCount, AmbiguousFieldCount, MissingRequiredCount,
            LineageCompleteCount, ValidationFailureCount, CoveragePct, Status, ComputedAt
        ) VALUES (?, ?, ?, ?, 0, ?, 0, ?, ?, ?, 'review_required', ?)
        """,
        (
            report_id,
            template_id,
            expected,
            mapped,
            ambiguous,
            mapped,
            validation_failures,
            coverage_pct,
            now,
        ),
    )
    coverage_run_id = int(cursor.lastrowid)
    conn.executemany(
        """
        INSERT INTO schema_coverage_item(
            CoverageRunID, RawCellID, SourceReference, Disposition, Reason
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ((coverage_run_id, *item) for item in dispositions),
    )


def _upsert_dim_report(
    conn: sqlite3.Connection,
    date_id: int,
    report: dict[str, object],
) -> None:
    report_path = str(report["local_path"])
    report_name = report_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    conn.execute(
        """
        INSERT OR REPLACE INTO DimReports(DateID, ReportName, ReportPath, Source)
        VALUES (?, ?, ?, 'NRLDC')
        """,
        (date_id, report_name, report_path),
    )


def _table_rows(
    conn: sqlite3.Connection,
    report_id: int,
    page_no: int,
    table_no: int,
) -> list[dict[int, tuple[int, str]]]:
    rows: dict[int, dict[int, tuple[int, str]]] = {}
    for raw_id, row_no, col_no, cell_text in conn.execute(
        """
        SELECT id, row_no, col_no, cell_text
        FROM psp_raw_cell
        WHERE report_document_id = ? AND page_no = ? AND table_no = ?
        ORDER BY row_no, col_no
        """,
        (report_id, page_no, table_no),
    ):
        rows.setdefault(int(row_no), {})[int(col_no)] = (int(raw_id), str(cell_text))
    return [rows[row_no] for row_no in sorted(rows)]


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return whether a raw support table exists in a legacy SQLite database."""

    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    )


def _rows_on_pages(
    conn: sqlite3.Connection,
    report_id: int,
    page_numbers: tuple[int, ...],
) -> list[tuple[int, dict[int, tuple[int, str]]]]:
    """Return page-tagged table-one rows in report order for section scanning."""

    return [
        (page_no, row)
        for page_no in page_numbers
        for row in _table_rows(conn, report_id, page_no, 1)
    ]


def _table_row(
    conn: sqlite3.Connection,
    report_id: int,
    page_no: int,
    table_no: int,
    row_no: int,
) -> dict[int, tuple[int, str]]:
    """Return one raw table row by its published row coordinate."""
    return {
        int(col_no): (int(raw_id), str(cell_text))
        for raw_id, col_no, cell_text in conn.execute(
            """
            SELECT id, col_no, cell_text
            FROM psp_raw_cell
            WHERE report_document_id = ? AND page_no = ?
              AND table_no = ? AND row_no = ?
            ORDER BY col_no
            """,
            (report_id, page_no, table_no, row_no),
        )
    }


def _lookup_region_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (NR_REGION_NAME,)
    ).fetchone()
    return int(row[0]) if row else None


def _get_or_create_grid_entity(*args: object, **kwargs: object) -> int:
    """Reuse the shared canonical grid-entity dimension implementation."""
    from psp_pipeline.storage.sqlite_curated_promoter import _get_or_create_grid_entity as resolver

    return resolver(*args, **kwargs)


def _write_lineage(
    conn: sqlite3.Connection,
    report_id: int,
    table_name: str,
    destination_key: str,
    sources: dict[str, int],
    mapped_cells: set[int],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for column, raw_cell_id in sources.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO curated_field_lineage(
                ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn,
                RawCellID, ExtractionMethod, Confidence, CreatedAt
            ) VALUES (?, ?, ?, ?, ?, 'pdfplumber', 1.0, ?)
            """,
            (report_id, table_name, destination_key, column, raw_cell_id, now),
        )
        mapped_cells.add(raw_cell_id)


def _write_spatial_lineage(
    conn: sqlite3.Connection,
    report_id: int,
    table_name: str,
    destination_key: str,
    label_item_ids: tuple[int, ...],
    value_item_ids: Mapping[str, int],
) -> None:
    """Write forensic lineage for a fact reconstructed from LiteParse geometry."""

    now = datetime.now(timezone.utc).isoformat()
    entries = [("EntityID", item_id) for item_id in label_item_ids]
    entries.extend(value_item_ids.items())
    for column, raw_text_item_id in entries:
        conn.execute(
            """
            INSERT OR IGNORE INTO curated_field_lineage(
                ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn,
                RawCellID, RawTextItemID, ExtractionMethod, Confidence, CreatedAt
            ) VALUES (?, ?, ?, ?, NULL, ?, 'liteparse', 1.0, ?)
            """,
            (
                report_id,
                table_name,
                destination_key,
                column,
                raw_text_item_id,
                now,
            ),
        )


def _cell_float(row: dict[int, tuple[int, str]], col_no: int) -> float | None:
    raw = row.get(col_no)
    return _to_float(raw[1]) if raw else None


def _cell_time(row: dict[int, tuple[int, str]], col_no: int) -> str | None:
    """Return a normalized time from a sparse PDF cell when present."""

    raw = row.get(col_no)
    return _normalize_time(raw[1]) if raw else None


def _schedule_counterparty(label: str) -> str | None:
    """Return a clean Section 4(B) counterparty label when a row is usable."""

    compact = re.sub(r"\s+", "", label.upper())
    if compact == "TOTAL":
        return "TOTAL"
    match = re.fullmatch(r"NR-(ER|WR|NORTH_EASTREGION|NER)", compact)
    if not match:
        return None
    return {
        "ER": "EAST REGION",
        "WR": "WEST REGION",
        "NORTH_EASTREGION": "NORTH EAST REGION",
        "NER": "NORTH EAST REGION",
    }[match.group(1)]


def _is_transmission_element(label: str) -> bool:
    """Return whether a row label is a line or HVDC element name."""

    return bool(re.search(r"(?:\d{2,4}\s*KV|HVDC)", label, re.IGNORECASE))


def _get_or_create_transmission_element(
    conn: sqlite3.Connection,
    name: str,
) -> int:
    """Delegate canonical line identity creation to the shared dimension helper."""

    from psp_pipeline.storage.sqlite_curated_promoter import (
        _get_or_create_transmission_element as resolver,
    )

    return resolver(conn, name)


def _get_or_create_voltage_node(
    conn: sqlite3.Connection,
    name: str,
    nominal_kv: float,
    region_id: int,
) -> int:
    """Delegate canonical voltage-node identity creation to shared dimensions."""

    from psp_pipeline.storage.sqlite_curated_promoter import (
        _get_or_create_voltage_node as resolver,
    )

    return resolver(conn, name, nominal_kv, region_id)


def _get_or_create_reservoir(
    conn: sqlite3.Connection,
    name: str,
    region_id: int,
) -> int:
    """Delegate canonical reservoir identity creation to shared dimensions."""

    from psp_pipeline.storage.sqlite_curated_promoter import (
        _get_or_create_reservoir as resolver,
    )

    return resolver(conn, name, region_id)


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace(",", "").replace("−", "-")
    if not text or text.lower() in {"-", "--", "nil", "na", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        return f"{text}:00"
    if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", text):
        return text
    return None


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _is_total_row(value: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", value.lower())
    return normalized.startswith(("total", "subtotal"))


def _looks_like_state_label(value: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", value.lower())
    return normalized in {
        "punjab",
        "haryana",
        "rajasthan",
        "delhi",
        "uttarpradesh",
        "uttarakhand",
        "himachalpradesh",
        "chandigarh",
    }


def _is_header_or_unit(value: str) -> bool:
    """Return whether an NRLDC cell is structural rather than a report fact."""
    normalized = re.sub(r"\s+", " ", value).strip().lower()
    return normalized in {
        "state",
        "station/constituents",
        "inst.capacity",
        "(mw)",
        "peakmw",
        "offpeakmw",
        "dayenergy",
        "avg.mw",
        "demand met",
        "shortage",
        "requirement",
        "freq(hz)",
        "thermal",
        "hydro",
        "gas/naptha/ diesel",
        "solar",
        "wind",
    }
