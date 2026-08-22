"""Seed and query the approved SRLDC schema mapping registry."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3


SRLDC_TEMPLATE_ID = "srldc_daily_psp_v2026_05"
SRLDC_COMPACT_TEMPLATE_ID = "srldc_daily_psp_v2026_01"
SRLDC_FLAT_8_TEMPLATE_ID = "srldc_daily_psp_v2024_flat_08"
SRLDC_FLAT_8_2025_TEMPLATE_ID = "srldc_daily_psp_v2025_flat_08"
SRLDC_FLAT_6_2023_TEMPLATE_ID = "srldc_daily_psp_v2023_flat_06"
SRLDC_FLAT_7_2023_TEMPLATE_ID = "srldc_daily_psp_v2023_flat_07"
SRLDC_FLAT_6_2024_WIDE_TEMPLATE_ID = "srldc_daily_psp_v2024_flat_06_wide_operations"
SRLDC_TEMPLATE_IDS = (
    SRLDC_TEMPLATE_ID,
    SRLDC_COMPACT_TEMPLATE_ID,
    SRLDC_FLAT_8_TEMPLATE_ID,
    SRLDC_FLAT_8_2025_TEMPLATE_ID,
    SRLDC_FLAT_6_2023_TEMPLATE_ID,
    SRLDC_FLAT_7_2023_TEMPLATE_ID,
    SRLDC_FLAT_6_2024_WIDE_TEMPLATE_ID,
)


@dataclass(frozen=True)
class ApprovedCellMapping:
    """Approved source-cell to curated-column mapping."""

    canonical_name: str
    destination_table: str
    destination_column: str
    unit_symbol: str | None
    section_name: str
    grain_dimensions: str
    requirement_level: str = "optional"


REGIONAL_MAPPINGS = {
    (1, 1): ApprovedCellMapping(
        "regional_evening_peak_demand_met_mw", "FactSRLDCRegionalDaily",
        "EveningPeakDemandMetMW", "MW", "regional_daily_summary", "report,date,region", "required"
    ),
    (1, 2): ApprovedCellMapping(
        "regional_evening_peak_shortage_mw", "FactSRLDCRegionalDaily",
        "EveningPeakShortageMW", "MW", "regional_daily_summary", "report,date,region", "required"
    ),
    (1, 3): ApprovedCellMapping(
        "regional_evening_peak_requirement_mw", "FactSRLDCRegionalDaily",
        "EveningPeakRequirementMW", "MW", "regional_daily_summary", "report,date,region"
    ),
    (1, 4): ApprovedCellMapping(
        "regional_evening_peak_frequency_hz", "FactSRLDCRegionalDaily",
        "EveningPeakFrequencyHz", "Hz", "regional_daily_summary", "report,date,region"
    ),
    (1, 5): ApprovedCellMapping(
        "regional_off_peak_demand_met_mw", "FactSRLDCRegionalDaily",
        "OffPeakDemandMetMW", "MW", "regional_daily_summary", "report,date,region"
    ),
    (1, 6): ApprovedCellMapping(
        "regional_off_peak_shortage_mw", "FactSRLDCRegionalDaily",
        "OffPeakShortageMW", "MW", "regional_daily_summary", "report,date,region"
    ),
    (1, 7): ApprovedCellMapping(
        "regional_off_peak_requirement_mw", "FactSRLDCRegionalDaily",
        "OffPeakRequirementMW", "MW", "regional_daily_summary", "report,date,region"
    ),
    (1, 8): ApprovedCellMapping(
        "regional_off_peak_frequency_hz", "FactSRLDCRegionalDaily",
        "OffPeakFrequencyHz", "Hz", "regional_daily_summary", "report,date,region"
    ),
    (1, 9): ApprovedCellMapping(
        "regional_day_energy_met_mu", "FactSRLDCRegionalDaily",
        "DayEnergyMetMU", "MU", "regional_daily_summary", "report,date,region", "required"
    ),
    (1, 10): ApprovedCellMapping(
        "regional_day_energy_shortage_mu", "FactSRLDCRegionalDaily",
        "DayEnergyShortageMU", "MU", "regional_daily_summary", "report,date,region"
    ),
}


STATE_ENERGY_MAPPINGS = {
    2: ("state_thermal_generation_mu", "ThermalGenerationMU", "MU"),
    3: ("state_hydro_generation_mu", "HydroGenerationMU", "MU"),
    4: ("state_gas_diesel_naptha_generation_mu", "GasDieselNapthaGenerationMU", "MU"),
    5: ("state_wind_generation_mu", "WindGenerationMU", "MU"),
    6: ("state_solar_generation_mu", "SolarGenerationMU", "MU"),
    7: ("state_other_generation_mu", "OtherGenerationMU", "MU"),
    8: ("state_net_schedule_mu", "NetScheduleMU", "MU"),
    9: ("state_drawal_mu", "DrawalMU", "MU"),
    10: ("state_ui_mu", "UIMU", "MU"),
    11: ("state_availability_mu", "AvailabilityMU", "MU"),
    12: ("state_demand_met_mu", "DemandMetMU", "MU"),
    13: ("state_energy_shortage_mu", "EnergyShortageMU", "MU"),
}


STATE_FORECAST_MAPPINGS = {
    2: ("state_evening_peak_demand_met_mw", "EveningPeakDemandMetMW", "MW"),
    3: ("state_evening_peak_shortage_mw", "EveningPeakShortageMW", "MW"),
    4: ("state_evening_peak_requirement_mw", "EveningPeakRequirementMW", "MW"),
    5: ("state_off_peak_demand_met_mw", "OffPeakDemandMetMW", "MW"),
    6: ("state_off_peak_shortage_mw", "OffPeakShortageMW", "MW"),
    7: ("state_off_peak_requirement_mw", "OffPeakRequirementMW", "MW"),
    8: ("state_average_demand_mw", "AverageDemandMW", "MW"),
}


STATE_PEAK_MAPPINGS = {
    2: ("state_maximum_demand_met_mw", "MaximumDemandMetMW", "MW"),
    3: ("state_maximum_demand_time", "MaximumDemandTime", "HH:MM:SS"),
    4: ("state_shortage_at_maximum_demand_mw", "ShortageAtMaximumDemandMW", "MW"),
    5: ("state_requirement_at_maximum_demand_mw", "RequirementAtMaximumDemandMW", "MW"),
    6: ("state_demand_at_maximum_requirement_mw", "DemandAtMaximumRequirementMW", "MW"),
    7: ("state_maximum_requirement_time", "MaximumRequirementTime", "HH:MM:SS"),
    8: ("state_shortage_at_maximum_requirement_mw", "ShortageAtMaximumRequirementMW", "MW"),
    9: ("state_maximum_requirement_mw", "MaximumRequirementMW", "MW"),
    10: ("state_ace_maximum_mw", "AceMaximumMW", "MW"),
    11: ("state_ace_maximum_time", "AceMaximumTime", "HH:MM:SS"),
    12: ("state_ace_minimum_mw", "AceMinimumMW", "MW"),
    13: ("state_ace_minimum_time", "AceMinimumTime", "HH:MM:SS"),
}


def seed_srldc_schema_registry(conn: sqlite3.Connection) -> None:
    """Seed approved sections and Page 1 SRLDC field contracts idempotently."""

    conn.executemany(
        """
        INSERT OR IGNORE INTO schema_report_template(
            TemplateID, SourceID, TemplateVersion, StructureFingerprint,
            ConfidenceThreshold, Status
        ) VALUES (?, 'srldc', ?, ?, 0.85, 'active')
        """,
        (
            (SRLDC_TEMPLATE_ID, "2026.05", "family:10-pages:41-tables"),
            (SRLDC_COMPACT_TEMPLATE_ID, "2026.01", "family:9-pages:38-tables"),
            (SRLDC_FLAT_8_TEMPLATE_ID, "2024.flat08", "family:8-pages:8-tables"),
            (SRLDC_FLAT_8_2025_TEMPLATE_ID, "2025.flat08", "family:8-pages:8-tables"),
            (SRLDC_FLAT_6_2023_TEMPLATE_ID, "2023.flat06", "family:6-pages:6-tables"),
            (SRLDC_FLAT_7_2023_TEMPLATE_ID, "2023.flat07", "family:7-pages:7-tables"),
            (SRLDC_FLAT_6_2024_WIDE_TEMPLATE_ID, "2024.flat06.wide_operations", "family:6-pages:6-tables:wide-operations"),
        ),
    )
    sections = (
        ("regional_daily_summary", "Regional demand, frequency, shortage and energy", "report,date,region", "FactSRLDCRegionalDaily", "required"),
        ("state_daily_position", "State generation, forecast, drawal and demand", "report,date,state", "FactSRLDCStateDaily", "required"),
        ("state_load_forecast", "State forecast fields merged into state daily", "report,date,state", "FactSRLDCStateDaily", "required"),
        ("generation_daily", "Generating entity performance", "report,date,entity,section", "FactSRLDCGenerationDaily", "required"),
        ("inter_regional_exchange", "Inter-regional schedule and flow", "report,date,element,category,direction", "FactSRLDCInterRegionalExchange", "required"),
        ("frequency_profile", "Frequency summary and fixed bands merged into regional daily", "report,date,region", "FactSRLDCRegionalDaily", "required"),
        ("voltage_profile", "Voltage-node daily extrema", "report,date,voltage_node", "FactSRLDCVoltageProfile", "required"),
        ("reservoir_daily", "Reservoir level and energy", "report,date,reservoir", "FactSRLDCReservoirDaily", "optional"),
        ("market_transaction", "Market and open-access transaction", "report,date,mechanism,product,direction", "FactSRLDCMarketTransaction", "optional"),
        ("regional_market_transaction", "Regional aggregate market and open-access transaction", "report,date,region,mechanism,product,direction", "FactSRLDCRegionalMarketTransaction", "optional"),
        ("operational_event", "Constraint, weather, outage or compliance event", "report,date,event", "FactSRLDCOperationalEvent", "conditional"),
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO schema_section(
            CanonicalName, Description, GrainDefinition, DestinationTable, RequirementLevel
        ) VALUES (?, ?, ?, ?, ?)
        """,
        sections,
    )

    for mapping in REGIONAL_MAPPINGS.values():
        _seed_field(conn, mapping)
    for canonical, column, unit in STATE_ENERGY_MAPPINGS.values():
        _seed_field(conn, ApprovedCellMapping(
            canonical, "FactSRLDCStateDaily", column, unit,
            "state_daily_position", "report,date,state", "required"
        ))
    for canonical, column, unit in STATE_FORECAST_MAPPINGS.values():
        _seed_field(conn, ApprovedCellMapping(
            canonical, "FactSRLDCStateDaily", column, unit,
            "state_daily_position", "report,date,state"
        ))
    for canonical, column, unit in STATE_PEAK_MAPPINGS.values():
        _seed_field(conn, ApprovedCellMapping(
            canonical, "FactSRLDCStateDaily", column, unit,
            "state_daily_position", "report,date,state"
        ))
    _seed_field(conn, ApprovedCellMapping(
        "state_forecast_demand_mu", "FactSRLDCStateDaily", "ForecastDemandMU", "MU",
        "state_load_forecast", "report,date,state", "required"
    ))
    _seed_field(conn, ApprovedCellMapping(
        "state_forecast_deviation_mu", "FactSRLDCStateDaily", "ForecastDeviationMU", "MU",
        "state_load_forecast", "report,date,state"
    ))
    for canonical, column in (
        ("regional_maximum_15_minute_block_frequency_hz", "Maximum15MinuteBlockFrequencyHz"),
        ("regional_minimum_15_minute_block_frequency_hz", "Minimum15MinuteBlockFrequencyHz"),
    ):
        _seed_field(conn, ApprovedCellMapping(
            canonical, "FactSRLDCRegionalDaily", column, "Hz",
            "frequency_profile", "report,date,region"
        ))
    for template_id in SRLDC_TEMPLATE_IDS:
        for (_, col_no), mapping in REGIONAL_MAPPINGS.items():
            _seed_mapping(conn, template_id, mapping.canonical_name, 1, 1, "row=3", f"col={col_no}")
        for col_no, (canonical, _, _) in STATE_ENERGY_MAPPINGS.items():
            _seed_mapping(conn, template_id, canonical, 1, 2, "rows=3:8", f"col={col_no}")
        for col_no, (canonical, _, _) in STATE_FORECAST_MAPPINGS.items():
            _seed_mapping(conn, template_id, canonical, 1, 3, "rows=3:8", f"col={col_no}")
        for col_no, (canonical, _, _) in STATE_PEAK_MAPPINGS.items():
            _seed_mapping(conn, template_id, canonical, 1, 4, "rows=3:8", f"col={col_no}")
        _seed_mapping(conn, template_id, "state_forecast_demand_mu", 1, 3, "rows=3:8", "col=9")
        _seed_mapping(conn, template_id, "state_forecast_deviation_mu", 1, 3, "rows=3:8", "col=10")


def _seed_field(conn: sqlite3.Connection, mapping: ApprovedCellMapping) -> None:
    """Insert one canonical field definition if absent."""

    data_type = "TIME" if mapping.unit_symbol == "HH:MM:SS" else "REAL"
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_field(
            SectionID, CanonicalName, BusinessDefinition, DataType, UnitSymbol,
            DestinationTable, DestinationColumn, GrainDimensions, RequirementLevel
        )
        SELECT SectionID, ?, ?, ?, ?, ?, ?, ?, ?
        FROM schema_section WHERE CanonicalName = ?
        """,
        (
            mapping.canonical_name,
            mapping.canonical_name.replace("_", " "),
            data_type,
            mapping.unit_symbol,
            mapping.destination_table,
            mapping.destination_column,
            mapping.grain_dimensions,
            mapping.requirement_level,
            mapping.section_name,
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_field_alias(FieldID, SourceID, AliasText, NormalizedAlias)
        SELECT FieldID, 'srldc', ?, ? FROM schema_field WHERE CanonicalName = ?
        """,
        (
            mapping.canonical_name.replace("_", " "),
            mapping.canonical_name.replace("_", " ").lower(),
            mapping.canonical_name,
        ),
    )


def _seed_mapping(
    conn: sqlite3.Connection,
    template_id: str,
    canonical_name: str,
    page_no: int,
    table_no: int,
    row_selector: str,
    col_selector: str,
) -> None:
    """Insert one approved template-specific coordinate mapping."""

    rule = f"page={page_no};table={table_no};{row_selector};{col_selector}"
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_field_mapping(
            TemplateID, FieldID, PageNo, TableNo, RowRole, RowSelector,
            ColSelector, MappingRule, Confidence, ApprovalStatus
        )
        SELECT ?, FieldID, ?, ?, 'detail', ?, ?, ?, 1.0, 'approved'
        FROM schema_field WHERE CanonicalName = ?
        """,
        (
            template_id, page_no, table_no, row_selector,
            col_selector, rule, canonical_name,
        ),
    )
