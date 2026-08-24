"""Synthesize five-RLDC daily balances and optionally compare NLDC summaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import sqlite3
from typing import Any


_REGIONAL_FACT_TABLES = {
    "srldc": "FactSRLDCRegionalDaily",
    "nrldc": "FactNRLDCRegionalDaily",
    "wrldc": "FactWRLDCRegionalDaily",
    "erldc": "FactERLDCRegionalDaily",
    "nerldc": "FactNERLDCRegionalDaily",
}
_STATE_FACT_TABLES = {
    "srldc": "FactSRLDCStateDaily",
    "nrldc": "FactNRLDCStateDaily",
    "wrldc": "FactWRLDCStateDaily",
    "erldc": "FactERLDCStateDaily",
    "nerldc": "FactNERLDCStateDaily",
}
_FUEL_COLUMNS = {
    "srldc": {
        "thermal_generation_mu": "ThermalGenerationMU",
        "hydro_generation_mu": "HydroGenerationMU",
        "gas_generation_mu": "GasDieselNapthaGenerationMU",
        "wind_generation_mu": "WindGenerationMU",
        "solar_generation_mu": "SolarGenerationMU",
        "other_generation_mu": "OtherGenerationMU",
    },
    "nrldc": {
        "thermal_generation_mu": "ThermalGenerationMU",
        "hydro_generation_mu": "HydroGenerationMU",
        "gas_generation_mu": "GasNapthaDieselGenerationMU",
        "wind_generation_mu": "WindGenerationMU",
        "solar_generation_mu": "SolarGenerationMU",
        "other_generation_mu": "OtherGenerationMU",
    },
    "wrldc": {
        "thermal_generation_mu": "ThermalGenerationMU",
        "hydro_generation_mu": "HydroGenerationMU",
        "gas_generation_mu": "GasNapthaDieselGenerationMU",
        "wind_generation_mu": "WindGenerationMU",
        "solar_generation_mu": "SolarGenerationMU",
        "other_generation_mu": "OtherGenerationMU",
    },
    "erldc": {
        "thermal_generation_mu": "ThermalGenerationMU",
        "hydro_generation_mu": "HydroGenerationMU",
        "renewable_generation_mu": "RenewableGenerationMU",
        "other_generation_mu": "OtherGenerationMU",
    },
    "nerldc": {
        "thermal_generation_mu": "ThermalGenerationMU",
        "hydro_generation_mu": "HydroGenerationMU",
        "gas_generation_mu": "GasNapthaDieselGenerationMU",
        "wind_generation_mu": "WindGenerationMU",
        "solar_generation_mu": "SolarGenerationMU",
        "other_generation_mu": "OtherGenerationMU",
    },
}


@dataclass(frozen=True)
class MetricComparison:
    """Comparison of one synthesized metric with an NLDC-published value."""

    synthesized_value: float
    nldc_value: float
    variance: float
    variance_pct: float | None
    within_tolerance: bool


@dataclass(frozen=True)
class AllIndiaBalance:
    """Auditable daily aggregation of currently curated RLDC facts."""

    date_id: int
    sources_present: tuple[str, ...]
    sources_missing: tuple[str, ...]
    evening_peak_demand_met_mw: float | None
    day_energy_met_mu: float | None
    fuel_generation_mu: dict[str, float]
    nldc_comparisons: dict[str, MetricComparison]

    def as_dict(self) -> dict[str, Any]:
        """Return a serialization-friendly representation for callers and CLIs."""

        return asdict(self)


def synthesize_all_india_daily_balance(
    conn: sqlite3.Connection,
    date_id: int,
) -> AllIndiaBalance:
    """Aggregate latest regional facts and reconcile them if NLDC data exists.

    The function deliberately does not fill missing regional reports with zero.
    A comparison is returned only where an NLDC ``FactAllIndiaDailySummary``
    metric is present for the same date.
    """

    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        source_rows: dict[str, sqlite3.Row] = {}
        fuel_generation: dict[str, float] = {}
        for source_id, table_name in _REGIONAL_FACT_TABLES.items():
            report_id = _latest_report_id(conn, source_id, date_id)
            if report_id is None:
                continue
            row = conn.execute(
                f"SELECT EveningPeakDemandMetMW, DayEnergyMetMU FROM {table_name} "
                "WHERE ReportDocumentID = ? AND DateID = ?",
                (report_id, date_id),
            ).fetchone()
            if row is None:
                continue
            source_rows[source_id] = row
            _add_fuel_generation(
                conn,
                _STATE_FACT_TABLES[source_id],
                report_id,
                date_id,
                _FUEL_COLUMNS[source_id],
                fuel_generation,
            )

        demand = _sum_optional(row["EveningPeakDemandMetMW"] for row in source_rows.values())
        energy = _sum_optional(row["DayEnergyMetMU"] for row in source_rows.values())
        nldc_row = _nldc_summary(conn, date_id)
        comparisons: dict[str, MetricComparison] = {}
        if nldc_row is not None:
            _add_comparison(
                comparisons,
                "evening_peak_demand_met_mw",
                demand,
                nldc_row["EveningPeakDemandMet"],
                absolute_tolerance=5.0,
                relative_tolerance=0.01,
            )
            _add_comparison(
                comparisons,
                "day_energy_met_mu",
                energy,
                nldc_row["EnergyMet"],
                absolute_tolerance=1.0,
                relative_tolerance=0.01,
            )

        present = tuple(source_rows)
        return AllIndiaBalance(
            date_id=date_id,
            sources_present=present,
            sources_missing=tuple(source for source in _REGIONAL_FACT_TABLES if source not in source_rows),
            evening_peak_demand_met_mw=demand,
            day_energy_met_mu=energy,
            fuel_generation_mu=dict(sorted(fuel_generation.items())),
            nldc_comparisons=comparisons,
        )
    finally:
        conn.row_factory = original_row_factory


def _latest_report_id(
    conn: sqlite3.Connection,
    source_id: str,
    date_id: int,
) -> int | None:
    row = conn.execute(
        "SELECT d.id FROM psp_report_document AS d "
        "JOIN DimDates AS dates ON dates.ActualDate = d.report_date "
        "WHERE d.rldc = ? AND dates.DateID = ? "
        "ORDER BY d.fetched_at DESC, d.id DESC LIMIT 1",
        (source_id, date_id),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _add_fuel_generation(
    conn: sqlite3.Connection,
    table_name: str,
    report_id: int,
    date_id: int,
    columns: dict[str, str],
    totals: dict[str, float],
) -> None:
    select_list = ", ".join(
        f"SUM({column_name}) AS {column_name}"
        for column_name in columns.values()
    )
    row = conn.execute(
        f"SELECT {select_list} FROM {table_name} "
        "WHERE ReportDocumentID = ? AND DateID = ?",
        (report_id, date_id),
    ).fetchone()
    if row is None:
        return
    for metric_name, column_name in columns.items():
        value = row[column_name]
        if value is not None:
            totals[metric_name] = totals.get(metric_name, 0.0) + float(value)


def _nldc_summary(conn: sqlite3.Connection, date_id: int) -> sqlite3.Row | None:
    try:
        return conn.execute(
            "SELECT EveningPeakDemandMet, EnergyMet FROM FactAllIndiaDailySummary "
            "WHERE DateID = ? ORDER BY CASE WHEN RegionID IS NULL THEN 0 ELSE 1 END LIMIT 1",
            (date_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None


def _sum_optional(values: Any) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) if numbers else None


def _add_comparison(
    comparisons: dict[str, MetricComparison],
    metric_name: str,
    synthesized: float | None,
    nldc_value: float | None,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> None:
    if synthesized is None or nldc_value is None:
        return
    published = float(nldc_value)
    variance = synthesized - published
    variance_pct = (variance / published * 100.0) if published else None
    tolerance = max(absolute_tolerance, abs(published) * relative_tolerance)
    comparisons[metric_name] = MetricComparison(
        synthesized_value=synthesized,
        nldc_value=published,
        variance=variance,
        variance_pct=variance_pct,
        within_tolerance=abs(variance) <= tolerance,
    )
