"""Curated SQLite schema inspired by the archived PSP star schema."""

from __future__ import annotations

import re
import sqlite3

from psp_pipeline.schema_design.registry import seed_srldc_schema_registry
from psp_pipeline.storage.sqlite_srldc_enrichment import (
    reservoir_state_name,
    transmission_location,
    voltage_node_state_name,
)
from psp_pipeline.storage.sqlite_wrldc_enrichment import (
    transmission_location as wrldc_transmission_location,
    voltage_node_location as wrldc_voltage_node_location,
)
from psp_pipeline.storage.sqlite_erldc_enrichment import (
    generation_entity_state_name as erldc_generation_entity_state_name,
    reservoir_location as erldc_reservoir_location,
    transmission_location as erldc_transmission_location,
    voltage_node_location as erldc_voltage_node_location,
)
from psp_pipeline.storage.sqlite_nerldc_enrichment import (
    transmission_location as nerldc_transmission_location,
    voltage_node_location as nerldc_voltage_node_location,
)


UNIT_ROWS = (
    ("MegaWatts", "MW", "Power", "Standard unit of active power"),
    ("Million Units", "MU", "Energy", "1 MU = 1 GWh"),
    ("Hertz", "Hz", "Frequency", "Standard unit of electrical frequency"),
    ("Percent", "%", "Ratio", "Dimensionless unit for ratios or shares"),
    ("Kilovolt", "kV", "Voltage", "Unit of electrical potential"),
    ("Index", "Index", "Index", "Dimensionless index value"),
    ("Hours", "hrs", "TimeDuration", "Unit of time duration"),
    ("Count", "Count", "Count", "Simple count of items"),
    ("Time", "HH:MM:SS", "Time", "Time in hours:minutes:seconds format"),
    ("Rupees", "Rs", "Currency", "Indian rupee settlement amount"),
)

REGION_ROWS = (
    ("Northern Region",),
    ("Western Region",),
    ("Southern Region",),
    ("Eastern Region",),
    ("North Eastern Region",),
    ("India",),
)

GENERATION_SOURCE_ROWS = (
    ("Coal", "Thermal"),
    ("Lignite", "Thermal"),
    ("Gas", "Thermal"),
    ("Naptha", "Thermal"),
    ("Diesel", "Thermal"),
    ("Gas, Naptha & Diesel", "Thermal"),
    ("Thermal", "Thermal"),
    ("Hydro", "Hydro"),
    ("Nuclear", "Nuclear"),
    ("Solar", "Renewable"),
    ("Wind", "Renewable"),
    ("Biomass", "Renewable"),
    ("Others", "Renewable"),
    ("RE", "Renewable"),
    ("Total", "Total"),
)

COUNTRY_ROWS = (
    ("Bhutan",),
    ("Nepal",),
    ("Bangladesh",),
    ("Myanmar",),
    ("Godda (Bangladesh)",),
    ("Total Export",),
    ("Total Import",),
    ("Total Net",),
)

EXCHANGE_MECHANISM_ROWS = (
    ("PPA",),
    ("Bilateral",),
    ("DAM IEX",),
    ("DAM PXIL",),
    ("DAM HPX",),
    ("RTM IEX",),
    ("RTM PXIL",),
    ("RTM HPX",),
    ("TOTAL",),
)

STATE_ROWS = (
    ("Punjab", "Northern Region"),
    ("Haryana", "Northern Region"),
    ("Rajasthan", "Northern Region"),
    ("Delhi", "Northern Region"),
    ("UP", "Northern Region"),
    ("Uttarakhand", "Northern Region"),
    ("HP", "Northern Region"),
    ("J&K(UT) & Ladakh(UT)", "Northern Region"),
    ("Chandigarh", "Northern Region"),
    ("Railways_NR ISTS", "Northern Region"),
    ("Chhattisgarh", "Western Region"),
    ("Gujarat", "Western Region"),
    ("MP", "Western Region"),
    ("Maharashtra", "Western Region"),
    ("Goa", "Western Region"),
    ("DNHDDPDCL", "Western Region"),
    ("AMNSIL", "Western Region"),
    ("BALCO", "Western Region"),
    ("RIL JAMNAGAR", "Western Region"),
    ("Andhra Pradesh", "Southern Region"),
    ("Telangana", "Southern Region"),
    ("Karnataka", "Southern Region"),
    ("Kerala", "Southern Region"),
    ("Tamil Nadu", "Southern Region"),
    ("Puducherry", "Southern Region"),
    ("Bihar", "Eastern Region"),
    ("DVC", "Eastern Region"),
    ("Jharkhand", "Eastern Region"),
    ("Odisha", "Eastern Region"),
    ("West Bengal", "Eastern Region"),
    ("Sikkim", "Eastern Region"),
    ("Railways_ER ISTS", "Eastern Region"),
    ("Arunachal Pradesh", "North Eastern Region"),
    ("Assam", "North Eastern Region"),
    ("Manipur", "North Eastern Region"),
    ("Meghalaya", "North Eastern Region"),
    ("Mizoram", "North Eastern Region"),
    ("Nagaland", "North Eastern Region"),
    ("Tripura", "North Eastern Region"),
)

SOUTHERN_STATE_CODES = {
    "Andhra Pradesh": "IN-AP",
    "Telangana": "IN-TS",
    "Karnataka": "IN-KA",
    "Kerala": "IN-KL",
    "Tamil Nadu": "IN-TN",
    "Puducherry": "IN-PY",
}

UNIT_MAPPINGS = (
    ("FactAllIndiaDailySummary", "EveningPeakDemandMet", "MW"),
    ("FactAllIndiaDailySummary", "PeakShortage", "MW"),
    ("FactAllIndiaDailySummary", "EnergyMet", "MU"),
    ("FactAllIndiaDailySummary", "EnergyShortage", "MU"),
    ("FactAllIndiaDailySummary", "MaxDemandSCADA", "MW"),
    ("FactAllIndiaDailySummary", "TimeOfMaxDemandMet", "HH:MM:SS"),
    ("FactAllIndiaDailySummary", "ScheduleDrawal", "MU"),
    ("FactAllIndiaDailySummary", "ActualDrawal", "MU"),
    ("FactAllIndiaDailySummary", "OverUnderDrawal", "MU"),
    ("FactAllIndiaDailySummary", "ShareRESInTotalGeneration", "%"),
    ("FactAllIndiaDailySummary", "ShareNonFossilInTotalGeneration", "%"),
    ("FactAllIndiaDailySummary", "FrequencyViolationIndex", "Index"),
    ("FactAllIndiaDailySummary", "DurationFrequencyBelow49_7", "%"),
    ("FactAllIndiaDailySummary", "DurationFrequency_49_7_to_49_8", "%"),
    ("FactAllIndiaDailySummary", "DurationFrequency_49_8_to_49_9", "%"),
    ("FactAllIndiaDailySummary", "DurationFrequencyBelow49_9", "%"),
    ("FactAllIndiaDailySummary", "DurationFrequency_49_9_to_50_05", "%"),
    ("FactAllIndiaDailySummary", "DurationFrequencyAbove50_05", "%"),
    ("FactAllIndiaDailySummary", "SolarHRMaxDemand", "MW"),
    ("FactAllIndiaDailySummary", "SolarHRMaxDemandTime", "HH:MM:SS"),
    ("FactAllIndiaDailySummary", "SolarHRShortage", "MW"),
    ("FactAllIndiaDailySummary", "NonSolarHRMaxDemand", "MW"),
    ("FactAllIndiaDailySummary", "NonSolarHRMaxDemandTime", "HH:MM:SS"),
    ("FactAllIndiaDailySummary", "NonSolarHRShortage", "MW"),
    ("FactStateDailyEnergy", "MaximumDemand", "MW"),
    ("FactStateDailyEnergy", "Shortage", "MW"),
    ("FactStateDailyEnergy", "EnergyMet", "MU"),
    ("FactStateDailyEnergy", "DrawalSchedule", "MU"),
    ("FactStateDailyEnergy", "OverUnderDrawal", "MU"),
    ("FactStateDailyEnergy", "MaxOverDrawal", "MW"),
    ("FactStateDailyEnergy", "EnergyShortage", "MU"),
    ("FactDailyGenerationBreakdown", "GenerationAmount", "MU"),
    ("FactTimeBlockPowerData", "Frequency", "Hz"),
    ("FactTimeBlockPowerData", "DemandMet", "MW"),
    ("FactTimeBlockPowerData", "NetDemandMet", "MW"),
    ("FactTimeBlockPowerData", "TotalGeneration", "MW"),
    ("FactTimeBlockPowerData", "NetTransnationalExchange", "MW"),
    ("FactTimeBlockGeneration", "GenerationOutput", "MW"),
    ("FactTransmissionLinkFlow", "MaxImport", "MW"),
    ("FactTransmissionLinkFlow", "MaxExport", "MW"),
    ("FactTransmissionLinkFlow", "ImportEnergy", "MU"),
    ("FactTransmissionLinkFlow", "ExportEnergy", "MU"),
    ("FactTransmissionLinkFlow", "NetImportEnergy", "MU"),
    ("FactInternationalTransmissionLinkFlow", "MaxLoading", "MW"),
    ("FactInternationalTransmissionLinkFlow", "MinLoading", "MW"),
    ("FactInternationalTransmissionLinkFlow", "AvgLoading", "MW"),
    ("FactInternationalTransmissionLinkFlow", "EnergyExchanged", "MU"),
    ("FactCountryDailyExchange", "TotalEnergyExchanged", "MU"),
    ("FactCountryDailyExchange", "PeakExchange", "MW"),
    ("FactTransnationalExchangeDetail", "ExchangeValue", "MU"),
    ("FactRPCWeeklyDSMEntity", "ScheduledEnergyMU", "MU"),
    ("FactRPCWeeklyDSMEntity", "ActualEnergyMU", "MU"),
    ("FactRPCWeeklyDSMEntity", "DeviationMU", "MU"),
    ("FactRPCWeeklyDSMEntity", "FrequencyLinkedDeviationChargeRs", "Rs"),
    ("FactRPCWeeklyDSMEntity", "SustainedDeviationPenaltyRs", "Rs"),
    ("FactRPCWeeklyDSMEntity", "SignChangeViolationChargeRs", "Rs"),
    ("FactRPCWeeklyDSMEntity", "NetPayableReceivableRs", "Rs"),
    ("FactRPCWeeklyDSMAncillary", "PayableRs", "Rs"),
    ("FactRPCWeeklyDSMAncillary", "ReceivableRs", "Rs"),
    ("FactRPCWeeklyDSMAncillary", "NetRs", "Rs"),
    ("FactRPCMonthlyREAStation", "InstalledCapacityMW", "MW"),
    ("FactRPCMonthlyREAStation", "PAFMPct", "%"),
    ("FactRPCMonthlyREAStation", "ScheduledGenerationMU", "MU"),
    ("FactRPCMonthlyREAStation", "DeemedGenerationMU", "MU"),
    ("FactRPCMonthlyREAStation", "AuxiliaryConsumptionMU", "MU"),
    ("FactRPCMonthlyREAAllocation", "AllocatedCapacityMW", "MW"),
    ("FactRPCMonthlyREAAllocation", "AllocatedEnergyMU", "MU"),
)


def ensure_curated_sqlite_schema(conn: sqlite3.Connection) -> None:
    """Create archive-compatible curated dimension and fact tables."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS DimDates (
            DateID INTEGER PRIMARY KEY AUTOINCREMENT,
            ActualDate TEXT NOT NULL UNIQUE,
            DayOfWeek TEXT,
            DayOfMonth INTEGER,
            Month INTEGER,
            Quarter INTEGER,
            Year INTEGER
        );

        CREATE TABLE IF NOT EXISTS DimRegions (
            RegionID INTEGER PRIMARY KEY AUTOINCREMENT,
            RegionName TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS DimStates (
            StateID INTEGER PRIMARY KEY AUTOINCREMENT,
            StateName TEXT NOT NULL UNIQUE,
            RegionID INTEGER,
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID)
        );

        CREATE TABLE IF NOT EXISTS DimCountries (
            CountryID INTEGER PRIMARY KEY AUTOINCREMENT,
            CountryName TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS DimGenerationSources (
            GenerationSourceID INTEGER PRIMARY KEY AUTOINCREMENT,
            SourceName TEXT NOT NULL UNIQUE,
            SourceCategory TEXT
        );

        CREATE TABLE IF NOT EXISTS DimTransmissionLines (
            LineID INTEGER PRIMARY KEY AUTOINCREMENT,
            LineIdentifier TEXT NOT NULL UNIQUE,
            VoltageLevel_kV TEXT,
            NumberOfCircuits INTEGER,
            CountryID INTEGER,
            FOREIGN KEY (CountryID) REFERENCES DimCountries(CountryID)
        );

        CREATE TABLE IF NOT EXISTS DimExchangeMechanisms (
            MechanismID INTEGER PRIMARY KEY AUTOINCREMENT,
            MechanismName TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS DimUnits (
            UnitID INTEGER PRIMARY KEY AUTOINCREMENT,
            UnitName TEXT NOT NULL UNIQUE,
            UnitSymbol TEXT NOT NULL UNIQUE,
            UnitCategory TEXT,
            Description TEXT
        );

        CREATE TABLE IF NOT EXISTS DimReports (
            DateID INTEGER,
            ReportName TEXT NOT NULL UNIQUE,
            ReportPath TEXT,
            Source TEXT,
            PRIMARY KEY (DateID, ReportName),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID)
        );

        CREATE TABLE IF NOT EXISTS FactAllIndiaDailySummary (
            DateID INTEGER NOT NULL,
            RegionID INTEGER,
            EveningPeakDemandMet REAL,
            PeakShortage REAL,
            EnergyMet REAL,
            EnergyShortage REAL,
            MaxDemandSCADA REAL,
            TimeOfMaxDemandMet TEXT,
            ScheduleDrawal REAL,
            ActualDrawal REAL,
            OverUnderDrawal REAL,
            CentralSectorOutage REAL,
            StateSectorOutage REAL,
            TotalOutage REAL,
            ShareRESInTotalGeneration REAL,
            ShareNonFossilInTotalGeneration REAL,
            FrequencyViolationIndex REAL,
            DurationFrequencyBelow49_7 REAL,
            DurationFrequency_49_7_to_49_8 REAL,
            DurationFrequency_49_8_to_49_9 REAL,
            DurationFrequencyBelow49_9 REAL,
            DurationFrequency_49_9_to_50_05 REAL,
            DurationFrequencyAbove50_05 REAL,
            RegionDDF REAL,
            StatesDDF REAL,
            SolarHRMaxDemand REAL,
            SolarHRMaxDemandTime TEXT,
            SolarHRShortage REAL,
            NonSolarHRMaxDemand REAL,
            NonSolarHRMaxDemandTime TEXT,
            NonSolarHRShortage REAL,
            PRIMARY KEY (DateID, RegionID),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactDailyGenerationBreakdown (
            DateID INTEGER NOT NULL,
            RegionID INTEGER,
            GenerationSourceID INTEGER NOT NULL,
            GenerationAmount REAL,
            PRIMARY KEY (DateID, RegionID, GenerationSourceID),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID),
            FOREIGN KEY (GenerationSourceID) REFERENCES DimGenerationSources(GenerationSourceID)
        );

        CREATE TABLE IF NOT EXISTS FactStateDailyEnergy (
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            MaximumDemand REAL,
            Shortage REAL,
            EnergyMet REAL,
            DrawalSchedule REAL,
            OverUnderDrawal REAL,
            MaxOverDrawal REAL,
            EnergyShortage REAL,
            PRIMARY KEY (DateID, StateID),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (StateID) REFERENCES DimStates(StateID)
        );

        CREATE TABLE IF NOT EXISTS FactTransmissionLinkFlow (
            DateID INTEGER NOT NULL,
            LineID INTEGER NOT NULL,
            Inter_Region TEXT NOT NULL,
            MaxImport REAL,
            MaxExport REAL,
            ImportEnergy REAL,
            ExportEnergy REAL,
            NetImportEnergy REAL,
            PRIMARY KEY (DateID, LineID, Inter_Region),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (LineID) REFERENCES DimTransmissionLines(LineID)
        );

        CREATE TABLE IF NOT EXISTS FactInternationalTransmissionLinkFlow (
            DateID INTEGER NOT NULL,
            LineID INTEGER NOT NULL,
            CountryID INTEGER,
            StateID INTEGER,
            RegionID INTEGER,
            MaxLoading REAL,
            MinLoading REAL,
            AvgLoading REAL,
            EnergyExchanged REAL,
            PRIMARY KEY (DateID, LineID),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (LineID) REFERENCES DimTransmissionLines(LineID),
            FOREIGN KEY (CountryID) REFERENCES DimCountries(CountryID),
            FOREIGN KEY (StateID) REFERENCES DimStates(StateID),
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactTransnationalExchangeDetail (
            DateID INTEGER NOT NULL,
            CountryID INTEGER NOT NULL,
            MechanismID INTEGER NOT NULL,
            ExchangeDirection TEXT NOT NULL,
            ExchangeValue REAL,
            PRIMARY KEY (DateID, CountryID, MechanismID, ExchangeDirection),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (CountryID) REFERENCES DimCountries(CountryID),
            FOREIGN KEY (MechanismID) REFERENCES DimExchangeMechanisms(MechanismID)
        );

        CREATE TABLE IF NOT EXISTS FactCountryDailyExchange (
            DateID INTEGER NOT NULL,
            CountryID INTEGER NOT NULL,
            TotalEnergyExchanged REAL,
            PeakExchange REAL,
            PRIMARY KEY (DateID, CountryID),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (CountryID) REFERENCES DimCountries(CountryID)
        );

        CREATE TABLE IF NOT EXISTS FactTimeBlockPowerData (
            DateID INTEGER NOT NULL,
            BlockTime TEXT NOT NULL,
            BlockNumber INTEGER NOT NULL,
            Frequency REAL,
            DemandMet REAL,
            NetDemandMet REAL,
            TotalGeneration REAL,
            NetTransnationalExchange REAL,
            PRIMARY KEY (DateID, BlockTime),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID)
        );

        CREATE TABLE IF NOT EXISTS FactTimeBlockGeneration (
            DateID INTEGER NOT NULL,
            BlockTime TEXT NOT NULL,
            BlockNumber INTEGER NOT NULL,
            GenerationSourceID INTEGER NOT NULL,
            GenerationOutput REAL,
            PRIMARY KEY (DateID, BlockTime, GenerationSourceID),
            FOREIGN KEY (DateID, BlockTime) REFERENCES FactTimeBlockPowerData(DateID, BlockTime),
            FOREIGN KEY (GenerationSourceID) REFERENCES DimGenerationSources(GenerationSourceID)
        );

        CREATE TABLE IF NOT EXISTS MetaTableColumnUnits (
            TableColumnUnitID INTEGER PRIMARY KEY AUTOINCREMENT,
            SchemaName TEXT NOT NULL DEFAULT 'main',
            TableName TEXT NOT NULL,
            ColumnName TEXT NOT NULL,
            UnitID INTEGER NOT NULL,
            FOREIGN KEY (UnitID) REFERENCES DimUnits(UnitID),
            UNIQUE (SchemaName, TableName, ColumnName)
        );

        CREATE TABLE IF NOT EXISTS DimMetric (
            MetricID TEXT PRIMARY KEY,
            TableName TEXT NOT NULL,
            ColumnName TEXT NOT NULL,
            UnitID INTEGER,
            Description TEXT NOT NULL,
            FOREIGN KEY (UnitID) REFERENCES DimUnits(UnitID),
            UNIQUE (TableName, ColumnName)
        );
        """
    )
    _ensure_schema_design_tables(conn)
    _ensure_srldc_curated_tables(conn)
    _ensure_nrldc_curated_tables(conn)
    _ensure_wrldc_curated_tables(conn)
    _ensure_erldc_curated_tables(conn)
    _ensure_nerldc_curated_tables(conn)
    _ensure_nldc_curated_tables(conn)
    _ensure_rpc_curated_tables(conn)
    _ensure_canonical_identity_tables(conn)
    _ensure_transmission_country_columns(conn)
    _migrate_curated_lineage_for_raw_lines(conn)
    _seed_curated_dimensions(conn)
    _backfill_wrldc_dimension_locations(conn)
    _backfill_erldc_dimension_locations(conn)
    _backfill_nerldc_dimension_locations(conn)
    seed_srldc_schema_registry(conn)
    _seed_metric_registry(conn)
    conn.commit()


def _ensure_schema_design_tables(conn: sqlite3.Connection) -> None:
    """Create governed schema-design, coverage, and lineage tables."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_report_template (
            TemplateID TEXT PRIMARY KEY,
            SourceID TEXT NOT NULL,
            TemplateVersion TEXT NOT NULL,
            StructureFingerprint TEXT NOT NULL,
            EffectiveFrom TEXT,
            EffectiveTo TEXT,
            ConfidenceThreshold REAL NOT NULL DEFAULT 0.85,
            Status TEXT NOT NULL DEFAULT 'active',
            UNIQUE(SourceID, TemplateVersion)
        );

        CREATE TABLE IF NOT EXISTS schema_section (
            SectionID INTEGER PRIMARY KEY AUTOINCREMENT,
            CanonicalName TEXT NOT NULL UNIQUE,
            Description TEXT,
            GrainDefinition TEXT NOT NULL,
            DestinationTable TEXT,
            RequirementLevel TEXT NOT NULL DEFAULT 'optional'
                CHECK(RequirementLevel IN ('required', 'optional', 'conditional'))
        );

        CREATE TABLE IF NOT EXISTS schema_field (
            FieldID INTEGER PRIMARY KEY AUTOINCREMENT,
            SectionID INTEGER NOT NULL,
            CanonicalName TEXT NOT NULL UNIQUE,
            BusinessDefinition TEXT,
            DataType TEXT NOT NULL,
            UnitSymbol TEXT,
            DestinationTable TEXT NOT NULL,
            DestinationColumn TEXT NOT NULL,
            GrainDimensions TEXT NOT NULL,
            RequirementLevel TEXT NOT NULL DEFAULT 'optional'
                CHECK(RequirementLevel IN ('required', 'optional', 'conditional')),
            ValidationRule TEXT,
            Status TEXT NOT NULL DEFAULT 'active',
            FOREIGN KEY(SectionID) REFERENCES schema_section(SectionID),
            UNIQUE(DestinationTable, DestinationColumn)
        );

        CREATE TABLE IF NOT EXISTS schema_field_alias (
            AliasID INTEGER PRIMARY KEY AUTOINCREMENT,
            FieldID INTEGER NOT NULL,
            SourceID TEXT NOT NULL,
            AliasText TEXT NOT NULL,
            NormalizedAlias TEXT NOT NULL,
            FOREIGN KEY(FieldID) REFERENCES schema_field(FieldID),
            UNIQUE(FieldID, SourceID, NormalizedAlias)
        );

        CREATE TABLE IF NOT EXISTS schema_field_mapping (
            MappingID INTEGER PRIMARY KEY AUTOINCREMENT,
            TemplateID TEXT NOT NULL,
            FieldID INTEGER NOT NULL,
            PageNo INTEGER,
            TableNo INTEGER,
            HeaderPath TEXT,
            RowRole TEXT,
            RowSelector TEXT,
            ColSelector TEXT,
            MappingRule TEXT NOT NULL,
            Confidence REAL NOT NULL,
            ApprovalStatus TEXT NOT NULL DEFAULT 'approved'
                CHECK(ApprovalStatus IN ('proposed', 'approved', 'rejected', 'deprecated')),
            FOREIGN KEY(TemplateID) REFERENCES schema_report_template(TemplateID),
            FOREIGN KEY(FieldID) REFERENCES schema_field(FieldID),
            UNIQUE(TemplateID, FieldID, MappingRule)
        );

        CREATE TABLE IF NOT EXISTS schema_proposal (
            ProposalID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER,
            ProposalType TEXT NOT NULL,
            CandidateKey TEXT NOT NULL,
            EvidenceJson TEXT NOT NULL,
            ProposedContractJson TEXT,
            ProposedDDL TEXT,
            CompatibilityResult TEXT,
            Status TEXT NOT NULL DEFAULT 'pending'
                CHECK(Status IN ('pending', 'approved', 'rejected', 'implemented')),
            CreatedAt TEXT NOT NULL,
            ReviewedAt TEXT,
            ReviewedBy TEXT,
            UNIQUE(ReportDocumentID, ProposalType, CandidateKey)
        );

        CREATE TABLE IF NOT EXISTS schema_coverage_run (
            CoverageRunID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL UNIQUE,
            TemplateID TEXT,
            ExpectedFieldCount INTEGER NOT NULL DEFAULT 0,
            MappedFieldCount INTEGER NOT NULL DEFAULT 0,
            ExcludedFieldCount INTEGER NOT NULL DEFAULT 0,
            AmbiguousFieldCount INTEGER NOT NULL DEFAULT 0,
            MissingRequiredCount INTEGER NOT NULL DEFAULT 0,
            LineageCompleteCount INTEGER NOT NULL DEFAULT 0,
            ValidationFailureCount INTEGER NOT NULL DEFAULT 0,
            CoveragePct REAL NOT NULL DEFAULT 0,
            Status TEXT NOT NULL,
            ComputedAt TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS schema_coverage_item (
            CoverageItemID INTEGER PRIMARY KEY AUTOINCREMENT,
            CoverageRunID INTEGER NOT NULL,
            RawCellID INTEGER,
            FieldID INTEGER,
            SourceReference TEXT NOT NULL,
            Disposition TEXT NOT NULL CHECK(Disposition IN (
                'mapped_value', 'dimension', 'header', 'derived', 'duplicate',
                'decorative', 'intentionally_excluded', 'ambiguous', 'missing'
            )),
            Reason TEXT,
            FOREIGN KEY(CoverageRunID) REFERENCES schema_coverage_run(CoverageRunID),
            FOREIGN KEY(FieldID) REFERENCES schema_field(FieldID),
            UNIQUE(CoverageRunID, SourceReference)
        );

        CREATE TABLE IF NOT EXISTS promotion_quarantine (
            QuarantineID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL,
            SourceID TEXT NOT NULL,
            Stage TEXT NOT NULL,
            ReasonCode TEXT NOT NULL,
            DetailsJson TEXT NOT NULL DEFAULT '{}',
            Status TEXT NOT NULL DEFAULT 'pending'
                CHECK(Status IN ('pending', 'resolved', 'dismissed')),
            CreatedAt TEXT NOT NULL,
            UpdatedAt TEXT NOT NULL,
            FOREIGN KEY(ReportDocumentID) REFERENCES psp_report_document(id),
            UNIQUE(ReportDocumentID, Stage, ReasonCode)
        );

        CREATE TABLE IF NOT EXISTS curated_field_lineage (
            LineageID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL,
            DestinationTable TEXT NOT NULL,
            DestinationKey TEXT NOT NULL,
            DestinationColumn TEXT NOT NULL,
            RawCellID INTEGER,
            RawTextItemID INTEGER,
            RawLineID INTEGER,
            ExtractionMethod TEXT NOT NULL,
            Confidence REAL NOT NULL,
            CreatedAt TEXT NOT NULL,
            CHECK(
                RawCellID IS NOT NULL OR RawTextItemID IS NOT NULL
                OR RawLineID IS NOT NULL
            ),
            UNIQUE(
                ReportDocumentID, DestinationTable, DestinationKey,
                DestinationColumn, RawCellID, RawTextItemID, RawLineID
            )
        );
        """
    )


def _ensure_nldc_curated_tables(conn: sqlite3.Connection) -> None:
    """Create NLDC fact tables once the raw document contract is available.

    NLDC facts reference the raw report identity directly. Curated-only
    in-memory databases intentionally omit these tables; the normal PSP
    persistence path creates ``psp_report_document`` before curated promotion.
    """

    raw_document_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'psp_report_document'"
    ).fetchone()
    if not raw_document_exists:
        return

    legacy_tables = _prepare_legacy_nldc_tables(conn)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS FactNLDCDailyNational (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EveningPeakDemandMetMW REAL,
            PeakShortageMW REAL,
            EnergyMetMU REAL,
            HydroGenMU REAL,
            WindGenMU REAL,
            SolarGenMU REAL,
            EnergyShortageMU REAL,
            MaxDemandMetMW REAL,
            TimeOfMaxDemand TEXT,
            PRIMARY KEY (ReportDocumentID, DateID),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID)
        );

        CREATE TABLE IF NOT EXISTS FactNLDCDailyRegional (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            EveningPeakDemandMetMW REAL,
            PeakShortageMW REAL,
            EnergyMetMU REAL,
            HydroGenMU REAL,
            WindGenMU REAL,
            SolarGenMU REAL,
            EnergyShortageMU REAL,
            MaxDemandMetMW REAL,
            TimeOfMaxDemand TEXT,
            PRIMARY KEY (ReportDocumentID, DateID, RegionID),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactNLDCDailyFrequency (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            FVI REAL,
            Below_49_7 REAL,
            From_49_7_to_49_8 REAL,
            From_49_8_to_49_9 REAL,
            Below_49_9 REAL,
            From_49_9_to_50_05 REAL,
            Above_50_05 REAL,
            PRIMARY KEY (ReportDocumentID, DateID),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID)
        );

        CREATE TABLE IF NOT EXISTS FactNLDCDailyInterRegionalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ElementID INTEGER NOT NULL,
            CounterpartyRegion TEXT NOT NULL,
            VoltageLevel TEXT,
            CircuitCount INTEGER,
            MaxImportMW REAL,
            MaxExportMW REAL,
            ImportMU REAL,
            ExportMU REAL,
            NetMU REAL,
            PRIMARY KEY (ReportDocumentID, DateID, ElementID, CounterpartyRegion),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (ElementID) REFERENCES DimTransmissionElements(ElementID)
        );

        CREATE TABLE IF NOT EXISTS FactNLDCDailyControlAreaDrawal (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            MaximumDemandMetMW REAL,
            MaximumDemandShortageMW REAL,
            EnergyMetMU REAL,
            DrawalScheduleMU REAL,
            OverUnderDrawalMU REAL,
            MaximumOverDrawalMW REAL,
            MaximumUnderDrawalMW REAL,
            EnergyShortageMU REAL,
            PRIMARY KEY (ReportDocumentID, DateID, EntityID),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (EntityID) REFERENCES DimGridEntities(EntityID),
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactNLDC15MinuteGridSnapshot (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            BlockStartTime TEXT NOT NULL,
            FrequencyHz REAL,
            DemandMetMW REAL,
            StorageDemandMW REAL,
            NuclearGenerationMW REAL,
            WindGenerationMW REAL,
            SolarGenerationMW REAL,
            HydroGenerationMW REAL,
            GasGenerationMW REAL,
            ThermalGenerationMW REAL,
            StorageGenerationMW REAL,
            OtherGenerationMW REAL,
            NetDemandMetMW REAL,
            TotalGenerationMW REAL,
            NetTransnationalExchangeMW REAL,
            PRIMARY KEY (ReportDocumentID, DateID, BlockStartTime),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID)
        );

        CREATE TABLE IF NOT EXISTS FactNLDCCrossBorderExchangeDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            CountryID INTEGER NOT NULL,
            Direction TEXT NOT NULL CHECK(Direction IN ('export', 'import', 'net')),
            GNAMU REAL,
            TGNABilateralMU REAL,
            IEXIDAMMU REAL,
            PXILIDAMMU REAL,
            HPXIDAMMU REAL,
            IEXRTMMU REAL,
            PXILRTMMU REAL,
            HPXRTMMU REAL,
            TotalMU REAL,
            PRIMARY KEY (ReportDocumentID, DateID, CountryID, Direction),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (CountryID) REFERENCES DimCountries(CountryID)
        );
        """
    )
    _copy_compatible_legacy_nldc_rows(conn, legacy_tables)


def _prepare_legacy_nldc_tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Rename NLDC tables whose foreign keys or exchange grain are obsolete.

    SQLite cannot alter a foreign key in place. Earlier experimental tables
    pointed at ``DimReports(DateID)`` and the exchange table stored a page-two
    schedule matrix rather than physical lines, so affected tables are rebuilt.
    """

    table_names = (
        "FactNLDCDailyNational",
        "FactNLDCDailyRegional",
        "FactNLDCDailyFrequency",
        "FactNLDCDailyInterRegionalExchange",
        "FactNLDCDailyControlAreaDrawal",
    )
    renamed: list[str] = []
    for table_name in table_names:
        columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if not columns:
            continue
        foreign_keys = conn.execute(
            f"PRAGMA foreign_key_list({table_name})"
        ).fetchall()
        has_legacy_document_key = any(str(row[2]) == "DimReports" for row in foreign_keys)
        invalid_exchange_grain = (
            table_name == "FactNLDCDailyInterRegionalExchange"
            and "ElementID" not in columns
        )
        if not has_legacy_document_key and not invalid_exchange_grain:
            continue
        legacy_name = f"{table_name}_legacy"
        conn.execute(f"DROP TABLE IF EXISTS {legacy_name}")
        conn.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_name}")
        renamed.append(table_name)
    return tuple(renamed)


def _copy_compatible_legacy_nldc_rows(
    conn: sqlite3.Connection, legacy_tables: tuple[str, ...]
) -> None:
    """Copy valid compatible NLDC rows after an FK rebuild.

    The old physical-exchange rows deliberately remain retired because their
    schedule-matrix grain cannot be converted to an individual tie line.
    """

    columns_by_table = {
        "FactNLDCDailyNational": (
            "ReportDocumentID, DateID, EveningPeakDemandMetMW, PeakShortageMW, "
            "EnergyMetMU, HydroGenMU, WindGenMU, SolarGenMU, EnergyShortageMU, "
            "MaxDemandMetMW, TimeOfMaxDemand"
        ),
        "FactNLDCDailyRegional": (
            "ReportDocumentID, DateID, RegionID, EveningPeakDemandMetMW, "
            "PeakShortageMW, EnergyMetMU, HydroGenMU, WindGenMU, SolarGenMU, "
            "EnergyShortageMU, MaxDemandMetMW, TimeOfMaxDemand"
        ),
        "FactNLDCDailyFrequency": (
            "ReportDocumentID, DateID, FVI, Below_49_7, From_49_7_to_49_8, "
            "From_49_8_to_49_9, Below_49_9, From_49_9_to_50_05, Above_50_05"
        ),
    }
    for table_name in legacy_tables:
        legacy_name = f"{table_name}_legacy"
        columns = columns_by_table.get(table_name)
        if columns:
            conn.execute(
                f"INSERT OR IGNORE INTO {table_name}({columns}) "
                f"SELECT {columns} FROM {legacy_name} "
                "WHERE ReportDocumentID IN (SELECT id FROM psp_report_document)"
            )
        conn.execute(f"DROP TABLE {legacy_name}")


def _migrate_curated_lineage_for_raw_lines(conn: sqlite3.Connection) -> None:
    """Rebuild legacy lineage tables so text-line-derived facts stay auditable."""

    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(curated_field_lineage)")
    }
    if "RawLineID" in columns:
        return
    conn.executescript(
        """
        ALTER TABLE curated_field_lineage RENAME TO curated_field_lineage_legacy;
        CREATE TABLE curated_field_lineage (
            LineageID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL,
            DestinationTable TEXT NOT NULL,
            DestinationKey TEXT NOT NULL,
            DestinationColumn TEXT NOT NULL,
            RawCellID INTEGER,
            RawTextItemID INTEGER,
            RawLineID INTEGER,
            ExtractionMethod TEXT NOT NULL,
            Confidence REAL NOT NULL,
            CreatedAt TEXT NOT NULL,
            CHECK(
                RawCellID IS NOT NULL OR RawTextItemID IS NOT NULL
                OR RawLineID IS NOT NULL
            ),
            UNIQUE(
                ReportDocumentID, DestinationTable, DestinationKey,
                DestinationColumn, RawCellID, RawTextItemID, RawLineID
            )
        );
        INSERT INTO curated_field_lineage(
            LineageID, ReportDocumentID, DestinationTable, DestinationKey,
            DestinationColumn, RawCellID, RawTextItemID, ExtractionMethod,
            Confidence, CreatedAt
        )
        SELECT LineageID, ReportDocumentID, DestinationTable, DestinationKey,
               DestinationColumn, RawCellID, RawTextItemID, ExtractionMethod,
               Confidence, CreatedAt
        FROM curated_field_lineage_legacy;
        DROP TABLE curated_field_lineage_legacy;
        """
    )


def _ensure_rpc_curated_tables(conn: sqlite3.Connection) -> None:
    """Create weekly DSM and monthly REA settlement fact tables.

    RPC facts reference the raw report identity directly. Curated-only
    in-memory databases omit these tables until ``psp_report_document`` exists.
    """

    raw_document_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'psp_report_document'"
    ).fetchone()
    if not raw_document_exists:
        return

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS FactRPCWeeklyDSMEntity (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            WeekEndDate TEXT NOT NULL,
            ScheduledEnergyMU REAL,
            ActualEnergyMU REAL,
            DeviationMU REAL,
            FrequencyLinkedDeviationChargeRs REAL,
            SustainedDeviationPenaltyRs REAL,
            SignChangeViolationChargeRs REAL,
            NetPayableReceivableRs REAL,
            PRIMARY KEY (ReportDocumentID, DateID, EntityID),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID),
            FOREIGN KEY (EntityID) REFERENCES DimGridEntities(EntityID)
        );

        CREATE TABLE IF NOT EXISTS FactRPCWeeklyDSMAncillary (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            ServiceType TEXT NOT NULL,
            WeekEndDate TEXT NOT NULL,
            PayableRs REAL,
            ReceivableRs REAL,
            NetRs REAL,
            PRIMARY KEY (ReportDocumentID, DateID, EntityID, ServiceType),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID),
            FOREIGN KEY (EntityID) REFERENCES DimGridEntities(EntityID)
        );

        CREATE TABLE IF NOT EXISTS FactRPCMonthlyREAStation (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            PeriodMonth TEXT NOT NULL,
            InstalledCapacityMW REAL,
            PAFMPct REAL,
            ScheduledGenerationMU REAL,
            DeemedGenerationMU REAL,
            AuxiliaryConsumptionMU REAL,
            PRIMARY KEY (ReportDocumentID, DateID, EntityID),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID),
            FOREIGN KEY (EntityID) REFERENCES DimGridEntities(EntityID)
        );

        CREATE TABLE IF NOT EXISTS FactRPCMonthlyREAAllocation (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            StationID INTEGER NOT NULL,
            AllocationWindow TEXT NOT NULL,
            PeriodMonth TEXT NOT NULL,
            AllocatedCapacityMW REAL,
            AllocatedEnergyMU REAL,
            PRIMARY KEY (
                ReportDocumentID, DateID, EntityID, StationID, AllocationWindow
            ),
            FOREIGN KEY (ReportDocumentID) REFERENCES psp_report_document(id),
            FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
            FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID),
            FOREIGN KEY (EntityID) REFERENCES DimGridEntities(EntityID),
            FOREIGN KEY (StationID) REFERENCES DimPowerStations(StationID)
        );
        """
    )


def _ensure_canonical_identity_tables(conn: sqlite3.Connection) -> None:
    """Create the local canonical entity index used before Postgres publication."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS canonical_entity (
            EntityID TEXT PRIMARY KEY,
            EntityCode TEXT NOT NULL UNIQUE,
            EntityType TEXT NOT NULL,
            CanonicalName TEXT NOT NULL,
            RegionCode TEXT,
            StateCode TEXT,
            CreatedAt TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS canonical_entity_alias (
            AliasID INTEGER PRIMARY KEY AUTOINCREMENT,
            EntityID TEXT NOT NULL,
            SourceID TEXT NOT NULL,
            EntityType TEXT NOT NULL,
            RawName TEXT NOT NULL,
            NormalizedName TEXT NOT NULL,
            ObservationEntityKey TEXT,
            MatchMethod TEXT NOT NULL,
            MatchConfidence REAL NOT NULL,
            ApprovalStatus TEXT NOT NULL,
            CreatedAt TEXT NOT NULL,
            FOREIGN KEY(EntityID) REFERENCES canonical_entity(EntityID),
            UNIQUE(SourceID, EntityType, NormalizedName)
        );

        CREATE INDEX IF NOT EXISTS canonical_entity_alias_observation_key_idx
            ON canonical_entity_alias(ObservationEntityKey);

        CREATE TABLE IF NOT EXISTS canonical_entity_adjudication (
            IssueID INTEGER PRIMARY KEY AUTOINCREMENT,
            SourceID TEXT NOT NULL,
            EntityType TEXT NOT NULL,
            RawName TEXT NOT NULL,
            NormalizedName TEXT NOT NULL,
            CandidateEntityID TEXT,
            CandidateScore REAL,
            Reason TEXT NOT NULL,
            Status TEXT NOT NULL DEFAULT 'pending',
            CreatedAt TEXT NOT NULL,
            DecidedAt TEXT,
            DecidedBy TEXT,
            UNIQUE(SourceID, EntityType, NormalizedName, Reason)
        );
        """
    )
    existing = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(canonical_entity_adjudication)")
    }
    if "DecidedAt" not in existing:
        conn.execute("ALTER TABLE canonical_entity_adjudication ADD COLUMN DecidedAt TEXT")
    if "DecidedBy" not in existing:
        conn.execute("ALTER TABLE canonical_entity_adjudication ADD COLUMN DecidedBy TEXT")


def _ensure_srldc_curated_tables(conn: sqlite3.Connection) -> None:
    """Create SRLDC-specific dimensions and grain-stable fact tables."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS DimGridEntities (
            EntityID INTEGER PRIMARY KEY AUTOINCREMENT,
            EntityName TEXT NOT NULL,
            EntityType TEXT NOT NULL,
            StateID INTEGER,
            RegionID INTEGER,
            GenerationSourceID INTEGER,
            OwnershipCategory TEXT,
            InstalledCapacityMW REAL,
            IsAggregate INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(StateID) REFERENCES DimStates(StateID),
            FOREIGN KEY(RegionID) REFERENCES DimRegions(RegionID),
            FOREIGN KEY(GenerationSourceID) REFERENCES DimGenerationSources(GenerationSourceID),
            UNIQUE(EntityName, EntityType, StateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS DimOrganizations (
            OrganizationID INTEGER PRIMARY KEY AUTOINCREMENT,
            OrganizationCode TEXT NOT NULL UNIQUE,
            CanonicalName TEXT NOT NULL UNIQUE,
            OrganizationType TEXT,
            ValidFrom TEXT,
            ValidTo TEXT
        );

        CREATE TABLE IF NOT EXISTS DimPowerStations (
            StationID INTEGER PRIMARY KEY AUTOINCREMENT,
            StationCode TEXT NOT NULL UNIQUE,
            CanonicalStationName TEXT NOT NULL,
            StateID INTEGER,
            RegionID INTEGER NOT NULL,
            OwnerID INTEGER,
            GenerationSourceID INTEGER,
            InstalledCapacityMW REAL,
            ValidFrom TEXT,
            ValidTo TEXT,
            IsActive INTEGER NOT NULL DEFAULT 1,
            UNIQUE(CanonicalStationName, StateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS DimGeneratingUnits (
            GeneratingUnitID INTEGER PRIMARY KEY AUTOINCREMENT,
            UnitCode TEXT NOT NULL UNIQUE,
            StationID INTEGER NOT NULL,
            CanonicalUnitName TEXT NOT NULL,
            UnitNumber TEXT,
            CapacityMW REAL,
            ValidFrom TEXT,
            ValidTo TEXT,
            IsActive INTEGER NOT NULL DEFAULT 1,
            UNIQUE(StationID, CanonicalUnitName)
        );

        CREATE TABLE IF NOT EXISTS DimGenerationAggregates (
            AggregateID INTEGER PRIMARY KEY AUTOINCREMENT,
            AggregateCode TEXT NOT NULL UNIQUE,
            CanonicalAggregateName TEXT NOT NULL,
            StateID INTEGER,
            RegionID INTEGER NOT NULL,
            GenerationSourceID INTEGER,
            UNIQUE(CanonicalAggregateName, StateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS DimStateAliases (
            StateAliasID INTEGER PRIMARY KEY AUTOINCREMENT,
            SourceID TEXT NOT NULL,
            RawName TEXT NOT NULL,
            NormalizedName TEXT NOT NULL,
            StateID INTEGER NOT NULL,
            ApprovalStatus TEXT NOT NULL,
            MatchConfidence REAL NOT NULL,
            UNIQUE(SourceID, NormalizedName)
        );

        CREATE TABLE IF NOT EXISTS DimEntityAliases (
            EntityAliasID INTEGER PRIMARY KEY AUTOINCREMENT,
            SourceID TEXT NOT NULL,
            EntityType TEXT NOT NULL,
            RawName TEXT NOT NULL,
            NormalizedName TEXT NOT NULL,
            CanonicalEntityID INTEGER NOT NULL,
            MatchMethod TEXT NOT NULL,
            MatchConfidence REAL NOT NULL,
            ApprovalStatus TEXT NOT NULL,
            ValidFrom TEXT,
            ValidTo TEXT,
            UNIQUE(SourceID, EntityType, NormalizedName)
        );

        CREATE TABLE IF NOT EXISTS dimension_resolution_issue (
            ResolutionIssueID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL,
            SourceID TEXT NOT NULL,
            EntityType TEXT NOT NULL,
            RawName TEXT NOT NULL,
            NormalizedName TEXT,
            Reason TEXT NOT NULL,
            Status TEXT NOT NULL DEFAULT 'pending',
            CreatedAt TEXT NOT NULL,
            UNIQUE(ReportDocumentID, EntityType, RawName, Reason)
        );

        CREATE TABLE IF NOT EXISTS DimTransmissionElements (
            ElementID INTEGER PRIMARY KEY AUTOINCREMENT,
            ElementName TEXT NOT NULL UNIQUE,
            ElementType TEXT,
            NominalVoltageKV REAL,
            CircuitCount INTEGER,
            FromRegionID INTEGER,
            ToRegionID INTEGER,
            FromStateID INTEGER,
            ToStateID INTEGER,
            FromCountryID INTEGER,
            ToCountryID INTEGER
        );

        CREATE TABLE IF NOT EXISTS DimVoltageNodes (
            VoltageNodeID INTEGER PRIMARY KEY AUTOINCREMENT,
            NodeName TEXT NOT NULL,
            NominalVoltageKV REAL NOT NULL,
            StateID INTEGER,
            RegionID INTEGER,
            UNIQUE(NodeName, NominalVoltageKV)
        );

        CREATE TABLE IF NOT EXISTS DimReservoirs (
            ReservoirID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReservoirName TEXT NOT NULL UNIQUE,
            StateID INTEGER,
            RegionID INTEGER,
            LinkedEntityID INTEGER
        );

        CREATE TABLE IF NOT EXISTS DimFrequencyBands (
            FrequencyBandID INTEGER PRIMARY KEY AUTOINCREMENT,
            BandLabel TEXT NOT NULL UNIQUE,
            LowerHz REAL,
            UpperHz REAL,
            LowerInclusive INTEGER,
            UpperInclusive INTEGER,
            SortOrder INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS DimEventTypes (
            EventTypeID INTEGER PRIMARY KEY AUTOINCREMENT,
            EventTypeName TEXT NOT NULL UNIQUE,
            EventCategory TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCRegionalDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            EveningPeakDemandMetMW REAL,
            EveningPeakShortageMW REAL,
            EveningPeakRequirementMW REAL,
            EveningPeakFrequencyHz REAL,
            OffPeakDemandMetMW REAL,
            OffPeakShortageMW REAL,
            OffPeakRequirementMW REAL,
            OffPeakFrequencyHz REAL,
            DayEnergyMetMU REAL,
            DayEnergyShortageMU REAL,
            MaximumDemandMetMW REAL,
            MaximumDemandTime TEXT,
            ScheduleDrawalMU REAL,
            ActualDrawalMU REAL,
            OverUnderDrawalMU REAL,
            MaximumFrequencyHz REAL,
            MaximumFrequencyTime TEXT,
            MinimumFrequencyHz REAL,
            MinimumFrequencyTime TEXT,
            AverageFrequencyHz REAL,
            StandardDeviationHz REAL,
            FrequencyVariationIndex REAL,
            Maximum15MinuteBlockFrequencyHz REAL,
            Minimum15MinuteBlockFrequencyHz REAL,
            DurationBelow49_70Pct REAL,
            Duration49_70To49_80Pct REAL,
            Duration49_80To49_90Pct REAL,
            Duration49_90To50_05Pct REAL,
            DurationAbove50_05Pct REAL,
            DurationBelow49_70Minutes REAL,
            Duration49_70To49_80Minutes REAL,
            Duration49_80To49_90Minutes REAL,
            Duration49_90To50_05Minutes REAL,
            DurationAbove50_05Minutes REAL,
            FrequencyBandDefinitionVersion TEXT,
            DurationBelow48_80Pct REAL,
            DurationBelow49_00Pct REAL,
            DurationBelow49_20Pct REAL,
            DurationBelow49_50Pct REAL,
            DurationBelow49_90Pct REAL,
            Duration49_90To50_05InclusivePct REAL,
            DurationAbove50_00Pct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCStateDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            ThermalGenerationMU REAL,
            HydroGenerationMU REAL,
            GasDieselNapthaGenerationMU REAL,
            WindGenerationMU REAL,
            SolarGenerationMU REAL,
            OtherGenerationMU REAL,
            NetScheduleMU REAL,
            DrawalMU REAL,
            UIMU REAL,
            AvailabilityMU REAL,
            DemandMetMU REAL,
            EnergyShortageMU REAL,
            EveningPeakDemandMetMW REAL,
            EveningPeakShortageMW REAL,
            EveningPeakRequirementMW REAL,
            OffPeakDemandMetMW REAL,
            OffPeakShortageMW REAL,
            OffPeakRequirementMW REAL,
            AverageDemandMW REAL,
            MaximumDemandMetMW REAL,
            MaximumDemandTime TEXT,
            ShortageAtMaximumDemandMW REAL,
            RequirementAtMaximumDemandMW REAL,
            DemandAtMaximumRequirementMW REAL,
            MaximumRequirementTime TEXT,
            ShortageAtMaximumRequirementMW REAL,
            MaximumRequirementMW REAL,
            AceMaximumMW REAL,
            AceMaximumTime TEXT,
            AceMinimumMW REAL,
            AceMinimumTime TEXT,
            ForecastType TEXT NOT NULL DEFAULT 'LGBR',
            ForecastDemandMU REAL,
            ActualDemandMU REAL,
            ForecastDeviationMU REAL,
            ForecastDeviationPct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID)
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCGenerationDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            StateID INTEGER,
            GenerationSourceID INTEGER,
            StationID INTEGER,
            GeneratingUnitID INTEGER,
            AggregateID INTEGER,
            InstalledCapacityMW REAL,
            EveningPeakMW REAL,
            OffPeakMW REAL,
            DayPeakMW REAL,
            DayPeakTime TEXT,
            MinimumGenerationMW REAL,
            MinimumGenerationTime TEXT,
            GrossEnergyMU REAL,
            NetEnergyMU REAL,
            AverageMW REAL,
            IsTotalRow INTEGER NOT NULL DEFAULT 0,
            GenerationGrain TEXT NOT NULL DEFAULT 'power_station',
            SectionName TEXT NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, SectionName),
            CHECK(
                AggregateID IS NOT NULL OR StationID IS NOT NULL
            )
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCInterRegionalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ElementID INTEGER NOT NULL,
            ExchangeCategory TEXT NOT NULL,
            Direction TEXT NOT NULL,
            MaximumMW REAL,
            MinimumMW REAL,
            AverageMW REAL,
            ScheduledMU REAL,
            ActualMU REAL,
            DeviationMU REAL,
            EveningPeakMW REAL,
            OffPeakMW REAL,
            MaximumImportMW REAL,
            MaximumExportMW REAL,
            ImportEnergyMU REAL,
            ExportEnergyMU REAL,
            NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ElementID, ExchangeCategory, Direction)
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCVoltageProfile (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            VoltageNodeID INTEGER NOT NULL,
            MaximumKV REAL,
            MaximumTime TEXT,
            MinimumKV REAL,
            MinimumTime TEXT,
            BelowBandPct REAL,
            AboveBandPct REAL,
            LowCriticalPct REAL,
            LowWarningPct REAL,
            HighWarningPct REAL,
            HighCriticalPct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, VoltageNodeID)
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCReservoirDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ReservoirID INTEGER NOT NULL,
            FullReservoirLevelM REAL,
            MinimumDrawdownLevelM REAL,
            CurrentLevelM REAL,
            CurrentEnergyMU REAL,
            PreviousYearLevelM REAL,
            DesignedEnergyMU REAL,
            PreviousYearEnergyMU REAL,
            InflowMU REAL,
            UsageMU REAL,
            ProgressiveInflowMU REAL,
            ProgressiveUsageMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ReservoirID)
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCMarketTransaction (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER,
            MechanismID INTEGER NOT NULL,
            ProductName TEXT NOT NULL,
            Direction TEXT NOT NULL,
            TimeCategory TEXT NOT NULL,
            EnergyMU REAL,
            ScheduledMW REAL,
            MaximumMW REAL,
            MinimumMW REAL,
            PRIMARY KEY(
                ReportDocumentID, DateID, StateID, MechanismID,
                ProductName, Direction, TimeCategory
            )
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCRegionalMarketTransaction (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            MechanismID INTEGER NOT NULL,
            ProductName TEXT NOT NULL,
            Direction TEXT NOT NULL,
            TimeCategory TEXT NOT NULL,
            EnergyMU REAL,
            ScheduledMW REAL,
            MaximumMW REAL,
            MinimumMW REAL,
            PRIMARY KEY(
                ReportDocumentID, DateID, RegionID, MechanismID,
                ProductName, Direction, TimeCategory
            )
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCOperationalEvent (
            EventID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EventTypeID INTEGER NOT NULL,
            StateID INTEGER,
            EntityID INTEGER,
            ElementID INTEGER,
            StartTime TEXT,
            EndTime TEXT,
            EventText TEXT NOT NULL,
            OccurrenceCount INTEGER,
            EventMW REAL,
            EventMU REAL,
            ReasonText TEXT,
            DetailsText TEXT
        );

        CREATE TABLE IF NOT EXISTS FactSRLDCReportAnnotation (
            AnnotationID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL,
            SectionName TEXT,
            PageNo INTEGER,
            RawLineID INTEGER,
            AnnotationText TEXT NOT NULL,
            UNIQUE(ReportDocumentID, SectionName, PageNo, AnnotationText)
        );
        """
    )
    _ensure_srldc_fact_columns(conn)


def _ensure_srldc_fact_columns(conn: sqlite3.Connection) -> None:
    """Add newly curated SRLDC columns to databases created by older versions."""

    additions = {
        "FactSRLDCRegionalDaily": (
            ("DurationBelow48_80Pct", "REAL"),
            ("DurationBelow49_00Pct", "REAL"),
            ("DurationBelow49_20Pct", "REAL"),
            ("DurationBelow49_50Pct", "REAL"),
            ("DurationBelow49_90Pct", "REAL"),
            ("Duration49_90To50_05InclusivePct", "REAL"),
            ("DurationAbove50_00Pct", "REAL"),
            ("Maximum15MinuteBlockFrequencyHz", "REAL"),
            ("Minimum15MinuteBlockFrequencyHz", "REAL"),
        ),
        "FactSRLDCVoltageProfile": (
            ("LowCriticalPct", "REAL"),
            ("LowWarningPct", "REAL"),
            ("HighWarningPct", "REAL"),
            ("HighCriticalPct", "REAL"),
        ),
        "FactSRLDCReservoirDaily": (
            ("DesignedEnergyMU", "REAL"),
            ("PreviousYearEnergyMU", "REAL"),
            ("ProgressiveInflowMU", "REAL"),
            ("ProgressiveUsageMU", "REAL"),
        ),
        "FactSRLDCInterRegionalExchange": (
            ("EveningPeakMW", "REAL"),
            ("OffPeakMW", "REAL"),
            ("MaximumImportMW", "REAL"),
            ("MaximumExportMW", "REAL"),
            ("ImportEnergyMU", "REAL"),
            ("ExportEnergyMU", "REAL"),
            ("NetEnergyMU", "REAL"),
        ),
        "FactSRLDCReportAnnotation": (
            ("RawLineID", "INTEGER"),
        ),
        "DimStates": (
            ("StateCode", "TEXT"),
        ),
        "DimGridEntities": (
            ("StationID", "INTEGER"),
            ("GeneratingUnitID", "INTEGER"),
            ("AggregateID", "INTEGER"),
        ),
        "FactSRLDCGenerationDaily": (
            ("StateID", "INTEGER"),
            ("GenerationSourceID", "INTEGER"),
            ("StationID", "INTEGER"),
            ("GeneratingUnitID", "INTEGER"),
            ("AggregateID", "INTEGER"),
            ("GenerationGrain", "TEXT NOT NULL DEFAULT 'power_station'"),
        ),
    }
    for table_name, columns in additions.items():
        existing = {
            row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")
        }
        for column_name, column_type in columns:
            if column_name not in existing:
                conn.execute(
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN {column_name} {column_type}"
                )
    _backfill_srldc_dimension_locations(conn)
    _backfill_srldc_generation_dimensions(conn)
    _migrate_srldc_market_table(conn)


def _ensure_nrldc_curated_tables(conn: sqlite3.Connection) -> None:
    """Create NRLDC fact tables at regional, state, and generation grains."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS FactNRLDCRegionalDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            EveningPeakDemandMetMW REAL,
            EveningPeakShortageMW REAL,
            EveningPeakRequirementMW REAL,
            EveningPeakFrequencyHz REAL,
            OffPeakDemandMetMW REAL,
            OffPeakShortageMW REAL,
            OffPeakRequirementMW REAL,
            OffPeakFrequencyHz REAL,
            DayEnergyMetMU REAL,
            DayEnergyShortageMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCStateDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            ThermalGenerationMU REAL,
            HydroGenerationMU REAL,
            GasNapthaDieselGenerationMU REAL,
            SolarGenerationMU REAL,
            WindGenerationMU REAL,
            OtherGenerationMU REAL,
            TotalGenerationMU REAL,
            ScheduledDrawalMU REAL,
            ActualDrawalMU REAL,
            UIMU REAL,
            RequirementMU REAL,
            EnergyShortageMU REAL,
            ConsumptionMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCGenerationDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            StateID INTEGER,
            GenerationSourceID INTEGER,
            StationID INTEGER,
            GeneratingUnitID INTEGER,
            AggregateID INTEGER,
            InstalledCapacityMW REAL,
            DeclaredCapacityMW REAL,
            EveningPeakMW REAL,
            OffPeakMW REAL,
            DayPeakMW REAL,
            DayPeakTime TEXT,
            MinimumGenerationMW REAL,
            MinimumGenerationTime TEXT,
            GrossEnergyMU REAL,
            NetEnergyMU REAL,
            ScheduledEnergyMU REAL,
            AGCEnergyMU REAL,
            AverageMW REAL,
            UIMU REAL,
            IsTotalRow INTEGER NOT NULL DEFAULT 0,
            GenerationGrain TEXT NOT NULL DEFAULT 'power_station',
            SectionName TEXT NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, SectionName),
            CHECK(AggregateID IS NOT NULL OR StationID IS NOT NULL)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCFrequencyDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            MaximumFrequencyHz REAL,
            MaximumFrequencyTime TEXT,
            MinimumFrequencyHz REAL,
            MinimumFrequencyTime TEXT,
            AverageFrequencyHz REAL,
            FrequencyVariationIndex REAL,
            StandardDeviationHz REAL,
            Maximum15MinuteBlockFrequencyHz REAL,
            Minimum15MinuteBlockFrequencyHz REAL,
            FrequencyDeviationIndexPct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCVoltageProfile (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            VoltageNodeID INTEGER NOT NULL,
            NominalVoltageKV REAL NOT NULL,
            MaximumKV REAL,
            MaximumTime TEXT,
            MinimumKV REAL,
            MinimumTime TEXT,
            LowCriticalPct REAL,
            LowWarningPct REAL,
            HighWarningPct REAL,
            HighCriticalPct REAL,
            VoltageDeviationIndexPct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, VoltageNodeID)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCReservoirDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ReservoirID INTEGER NOT NULL,
            MinimumDrawdownLevelM REAL,
            FullReservoirLevelM REAL,
            EnergyContentAtFullReservoirMU REAL,
            CurrentLevelM REAL,
            CurrentEnergyMU REAL,
            PreviousYearLevelM REAL,
            PreviousYearEnergyMU REAL,
            InflowCusec REAL,
            UsageCusec REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ReservoirID)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCInterRegionalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ElementID INTEGER NOT NULL,
            CounterpartyRegion TEXT NOT NULL,
            EveningPeakMW REAL,
            OffPeakMW REAL,
            MaximumImportMW REAL,
            MaximumExportMW REAL,
            ImportEnergyMU REAL,
            ExportEnergyMU REAL,
            NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ElementID, CounterpartyRegion)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCInterRegionalScheduleExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            CounterpartyRegion TEXT NOT NULL,
            IsTotalRow INTEGER NOT NULL DEFAULT 0,
            ISGSAndGNAScheduleMU REAL,
            BilateralScheduleMU REAL,
            GDAMScheduleMU REAL,
            DAMScheduleMU REAL,
            RTMScheduleMU REAL,
            TotalScheduleMU REAL,
            ActualMU REAL,
            DeviationMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, CounterpartyRegion)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCInternationalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ElementID INTEGER NOT NULL,
            CounterpartyCountry TEXT NOT NULL,
            EveningPeakMW REAL,
            OffPeakMW REAL,
            MaximumImportMW REAL,
            MaximumExportMW REAL,
            ImportEnergyMU REAL,
            ExportEnergyMU REAL,
            NetEnergyMU REAL,
            ScheduleEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ElementID, CounterpartyCountry)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCStateMarketDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            GNAScheduleMU REAL,
            TGNABilateralMU REAL,
            GDAMScheduleMU REAL,
            DAMScheduleMU REAL,
            RTMScheduleMU REAL,
            TotalMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCStateMarketPointDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            TimeCategory TEXT NOT NULL CHECK(TimeCategory IN ('off_peak', 'peak')),
            TGNABilateralMW REAL,
            IEXGDAMMW REAL,
            IEXDAMMW REAL,
            IEXRTMMW REAL,
            PXILGDAMMW REAL,
            PXILDAMMW REAL,
            PXIRTMMW REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID, TimeCategory)
        );

        CREATE TABLE IF NOT EXISTS FactNRLDCStateMarketExtremaDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            Mechanism TEXT NOT NULL,
            MaximumMW REAL,
            MinimumMW REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID, Mechanism)
        );
        """
    )
    _ensure_nrldc_generation_columns(conn)


def _ensure_nrldc_generation_columns(conn: sqlite3.Connection) -> None:
    """Add later NRLDC regional-generation measures to an existing local DB."""

    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(FactNRLDCGenerationDaily)")
    }
    for column_name in (
        "DeclaredCapacityMW",
        "ScheduledEnergyMU",
        "AGCEnergyMU",
        "UIMU",
    ):
        if column_name not in existing:
            conn.execute(
                f"ALTER TABLE FactNRLDCGenerationDaily ADD COLUMN {column_name} REAL"
            )


def _ensure_erldc_curated_tables(conn: sqlite3.Connection) -> None:
    """Create ERLDC facts at regional, state, asset, and exchange grains."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS FactERLDCRegionalDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, RegionID INTEGER NOT NULL,
            EveningPeakDemandMetMW REAL, EveningPeakShortageMW REAL, EveningPeakRequirementMW REAL,
            EveningPeakFrequencyHz REAL, OffPeakDemandMetMW REAL, OffPeakShortageMW REAL,
            OffPeakRequirementMW REAL, OffPeakFrequencyHz REAL, DayEnergyMetMU REAL,
            DayEnergyShortageMU REAL, PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );
        CREATE TABLE IF NOT EXISTS FactERLDCStateDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, StateID INTEGER NOT NULL,
            ThermalGenerationMU REAL, HydroGenerationMU REAL, GasNapthaDieselGenerationMU REAL,
            RenewableGenerationMU REAL, OtherGenerationMU REAL, TotalGenerationMU REAL,
            ScheduledDrawalMU REAL, ActualDrawalMU REAL, UIMU REAL, TotalAvailabilityMU REAL,
            RequirementMU REAL, EnergyShortageMU REAL, ConsumptionMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID)
        );
        CREATE TABLE IF NOT EXISTS FactERLDCGenerationDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, EntityID INTEGER NOT NULL,
            StateID INTEGER, GenerationSourceID INTEGER, StationID INTEGER, GeneratingUnitID INTEGER,
            AggregateID INTEGER, InstalledCapacityMW REAL, EveningPeakMW REAL, OffPeakMW REAL,
            DayPeakMW REAL, DayPeakTime TEXT, MinimumGenerationMW REAL, MinimumGenerationTime TEXT,
            ScheduledEnergyMU REAL, GrossEnergyMU REAL, NetEnergyMU REAL, AverageMW REAL,
            IsTotalRow INTEGER NOT NULL DEFAULT 0,
            GenerationGrain TEXT NOT NULL DEFAULT 'power_station', SectionName TEXT NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, SectionName),
            CHECK(AggregateID IS NOT NULL OR StationID IS NOT NULL)
        );
        CREATE TABLE IF NOT EXISTS FactERLDCFrequencyDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, RegionID INTEGER NOT NULL,
            MaximumFrequencyHz REAL, MaximumFrequencyTime TEXT, MinimumFrequencyHz REAL,
            MinimumFrequencyTime TEXT, AverageFrequencyHz REAL, FrequencyVariationIndex REAL,
            StandardDeviationHz REAL, Maximum15MinuteBlockFrequencyHz REAL,
            Minimum15MinuteBlockFrequencyHz REAL, DurationBelow49_90Pct REAL,
            Duration49_90To50_05Pct REAL, DurationAbove50_05Pct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );
        CREATE TABLE IF NOT EXISTS FactERLDCVoltageProfile (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, VoltageNodeID INTEGER NOT NULL,
            NominalVoltageKV REAL NOT NULL, MaximumKV REAL, MaximumTime TEXT, MinimumKV REAL,
            MinimumTime TEXT, LowCriticalPct REAL, IEGCBandPct REAL, HighCriticalPct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, VoltageNodeID)
        );
        CREATE TABLE IF NOT EXISTS FactERLDCReservoirDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, ReservoirID INTEGER NOT NULL,
            MinimumDrawdownLevelM REAL, FullReservoirLevelM REAL, DesignedEnergyMU REAL,
            CurrentLevelM REAL, CurrentEnergyMU REAL, PreviousYearLevelM REAL,
            PreviousYearEnergyMU REAL, InflowMU REAL, UsageMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ReservoirID)
        );
        CREATE TABLE IF NOT EXISTS FactERLDCInterRegionalExchange (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, ElementID INTEGER NOT NULL,
            CounterpartyRegion TEXT NOT NULL, EveningPeakMW REAL, OffPeakMW REAL,
            MaximumImportMW REAL, MaximumExportMW REAL, ImportEnergyMU REAL,
            ExportEnergyMU REAL, NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ElementID, CounterpartyRegion)
        );
        CREATE TABLE IF NOT EXISTS FactERLDCInternationalExchange (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, CountryID INTEGER NOT NULL,
            CounterpartyCountry TEXT NOT NULL, ScheduledEnergyMU REAL, ActualEnergyMU REAL,
            DayPeakMW REAL, DayMinimumMW REAL, AverageMW REAL, NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, CountryID, CounterpartyCountry)
        );
        CREATE TABLE IF NOT EXISTS FactERLDCMarketEnergyDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, EntityID INTEGER NOT NULL,
            StateID INTEGER,
            GNAScheduleMU REAL, TGNABilateralMU REAL, GDAMScheduleMU REAL, DAMScheduleMU REAL,
            HPDAMScheduleMU REAL, RTMScheduleMU REAL, TotalMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID)
        );
        CREATE TABLE IF NOT EXISTS FactERLDCMarketExtremaDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, EntityID INTEGER NOT NULL,
            StateID INTEGER, Mechanism TEXT NOT NULL, MaximumMW REAL NOT NULL, MinimumMW REAL NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, Mechanism)
        );
        """
    )
    _ensure_erldc_generation_columns(conn)
    _ensure_frequency_operating_band_columns(conn, "FactERLDCFrequencyDaily")


def _ensure_erldc_generation_columns(conn: sqlite3.Connection) -> None:
    """Add later verified ERLDC regional-generation measures to existing DBs."""

    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(FactERLDCGenerationDaily)")
    }
    if "ScheduledEnergyMU" not in existing:
        conn.execute(
            "ALTER TABLE FactERLDCGenerationDaily "
            "ADD COLUMN ScheduledEnergyMU REAL"
        )


def _ensure_nerldc_curated_tables(conn: sqlite3.Connection) -> None:
    """Create NERLDC facts at region, state, entity, and exchange grains."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS FactNERLDCRegionalDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, RegionID INTEGER NOT NULL,
            EveningPeakDemandMetMW REAL, EveningPeakShortageMW REAL, EveningPeakRequirementMW REAL,
            EveningPeakFrequencyHz REAL, OffPeakDemandMetMW REAL, OffPeakShortageMW REAL,
            OffPeakRequirementMW REAL, OffPeakFrequencyHz REAL, DayEnergyMetMU REAL,
            DayEnergyShortageMU REAL, PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );
        CREATE TABLE IF NOT EXISTS FactNERLDCStateDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, StateID INTEGER NOT NULL,
            ThermalGenerationMU REAL, HydroGenerationMU REAL, GasNapthaDieselGenerationMU REAL,
            WindGenerationMU REAL, SolarGenerationMU REAL, OtherGenerationMU REAL,
            TotalGenerationMU REAL, ScheduledDrawalMU REAL, ActualDrawalMU REAL, UIMU REAL,
            TotalAvailabilityMU REAL, DemandMetMU REAL, EnergyShortageMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, StateID)
        );
        CREATE TABLE IF NOT EXISTS FactNERLDCGenerationDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, EntityID INTEGER NOT NULL,
            StateID INTEGER, StationID INTEGER, GeneratingUnitID INTEGER, AggregateID INTEGER,
            InstalledCapacityMW REAL, EveningPeakMW REAL, OffPeakMW REAL, DayPeakMW REAL,
            DayPeakTime TEXT, MinimumGenerationMW REAL, MinimumGenerationTime TEXT,
            GrossEnergyMU REAL, NetEnergyMU REAL, AverageMW REAL,
            ScheduledEnergyMU REAL, UIMU REAL, RRASScheduleMU REAL,
            IsTotalRow INTEGER NOT NULL DEFAULT 0,
            GenerationGrain TEXT NOT NULL DEFAULT 'power_station', SectionName TEXT NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, SectionName),
            CHECK(AggregateID IS NOT NULL OR StationID IS NOT NULL)
        );
        CREATE TABLE IF NOT EXISTS FactNERLDCFrequencyDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, RegionID INTEGER NOT NULL,
            MaximumFrequencyHz REAL, MaximumFrequencyTime TEXT, MinimumFrequencyHz REAL,
            MinimumFrequencyTime TEXT, AverageFrequencyHz REAL, FrequencyVariationIndex REAL,
            StandardDeviationHz REAL, Maximum15MinuteBlockFrequencyHz REAL,
            Minimum15MinuteBlockFrequencyHz REAL, DurationBelow49_90Pct REAL,
            Duration49_90To50_05Pct REAL, DurationAbove50_05Pct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );
        CREATE TABLE IF NOT EXISTS FactNERLDCVoltageProfile (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, VoltageNodeID INTEGER NOT NULL,
            NominalVoltageKV REAL NOT NULL, MaximumKV REAL, MaximumTime TEXT, MinimumKV REAL,
            MinimumTime TEXT, LowCriticalPct REAL, IEGCBandPct REAL, HighCriticalPct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, VoltageNodeID)
        );
        CREATE TABLE IF NOT EXISTS FactNERLDCReservoirDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, ReservoirID INTEGER NOT NULL,
            MinimumDrawdownLevelM REAL, FullReservoirLevelM REAL, DesignedEnergyMU REAL,
            CurrentLevelM REAL, CurrentEnergyMU REAL, PreviousYearLevelM REAL,
            PreviousYearEnergyMU REAL, PreviousDayLevelM REAL, PreviousDayEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ReservoirID)
        );
        CREATE TABLE IF NOT EXISTS FactNERLDCInterRegionalExchange (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, ElementID INTEGER NOT NULL,
            CounterpartyRegion TEXT NOT NULL, EveningPeakMW REAL, OffPeakMW REAL,
            MaximumImportMW REAL, MaximumExportMW REAL, ImportEnergyMU REAL,
            ExportEnergyMU REAL, NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ElementID, CounterpartyRegion)
        );
        CREATE TABLE IF NOT EXISTS FactNERLDCInternationalExchange (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, CountryID INTEGER NOT NULL,
            CounterpartyCountry TEXT NOT NULL, ScheduledEnergyMU REAL, ActualEnergyMU REAL,
            DayPeakMW REAL, DayMinimumMW REAL, AverageMW REAL, NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, CountryID, CounterpartyCountry)
        );
        """
    )
    _ensure_nerldc_generation_columns(conn)
    _ensure_frequency_operating_band_columns(conn, "FactNERLDCFrequencyDaily")


def _ensure_frequency_operating_band_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> None:
    """Add IEGC operating-band duration columns to existing frequency facts."""

    existing = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")
    }
    for column_name in (
        "DurationBelow49_90Pct",
        "Duration49_90To50_05Pct",
        "DurationAbove50_05Pct",
    ):
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} REAL")


def _ensure_nerldc_generation_columns(conn: sqlite3.Connection) -> None:
    """Add verified regional-generation measures to existing NERLDC DBs."""

    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(FactNERLDCGenerationDaily)")
    }
    for column_name in (
        "GrossEnergyMU",
        "ScheduledEnergyMU",
        "UIMU",
        "RRASScheduleMU",
    ):
        if column_name not in existing:
            conn.execute(
                f"ALTER TABLE FactNERLDCGenerationDaily ADD COLUMN {column_name} REAL"
            )


def _ensure_transmission_country_columns(conn: sqlite3.Connection) -> None:
    """Ensure DimTransmissionElements has FromCountryID and ToCountryID columns."""
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(DimTransmissionElements)").fetchall()
    }
    if "FromCountryID" not in columns:
        conn.execute("ALTER TABLE DimTransmissionElements ADD COLUMN FromCountryID INTEGER")
    if "ToCountryID" not in columns:
        conn.execute("ALTER TABLE DimTransmissionElements ADD COLUMN ToCountryID INTEGER")


def _ensure_wrldc_curated_tables(conn: sqlite3.Connection) -> None:
    """Create WRLDC facts at regional, state, and generating-entity grains."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS FactWRLDCRegionalDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            EveningPeakDemandMetMW REAL,
            EveningPeakShortageMW REAL,
            EveningPeakRequirementMW REAL,
            EveningPeakFrequencyHz REAL,
            OffPeakDemandMetMW REAL,
            OffPeakShortageMW REAL,
            OffPeakRequirementMW REAL,
            OffPeakFrequencyHz REAL,
            DayEnergyMetMU REAL,
            DayEnergyShortageMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactWRLDCStateDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER NOT NULL,
            ThermalGenerationMU REAL,
            HydroGenerationMU REAL,
            GasNapthaDieselGenerationMU REAL,
            WindGenerationMU REAL,
            SolarGenerationMU REAL,
            OtherGenerationMU REAL,
            TotalGenerationMU REAL,
            ScheduledDrawalMU REAL,
            ActualDrawalMU REAL,
            UIMU REAL,
            TotalAvailabilityMU REAL,
            RequirementMU REAL,
            EnergyShortageMU REAL,
            ConsumptionMU REAL,
            EveningPeakDemandMetMW REAL,
            EveningPeakShortageMW REAL,
            EveningPeakRequirementMW REAL,
            OffPeakDemandMetMW REAL,
            OffPeakShortageMW REAL,
            OffPeakRequirementMW REAL,
            AverageDemandMW REAL,
            ForecastDemandMU REAL,
            ForecastDeviationMU REAL,
            MaximumDemandMetMW REAL,
            MaximumDemandTime TEXT,
            MaximumDemandShortageMW REAL,
            MaximumDemandRequirementMW REAL,
            MaximumACEMW REAL,
            MaximumACETime TEXT,
            MinimumACEMW REAL,
            MinimumACETime TEXT,
            PRIMARY KEY(ReportDocumentID, DateID, StateID)
        );

        CREATE TABLE IF NOT EXISTS FactWRLDCGenerationDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            StateID INTEGER,
            GenerationSourceID INTEGER,
            StationID INTEGER,
            GeneratingUnitID INTEGER,
            AggregateID INTEGER,
            InstalledCapacityMW REAL,
            EveningPeakMW REAL,
            OffPeakMW REAL,
            DayPeakMW REAL,
            DayPeakTime TEXT,
            MinimumGenerationMW REAL,
            MinimumGenerationTime TEXT,
            ScheduledEnergyMU REAL,
            GrossEnergyMU REAL,
            NetEnergyMU REAL,
            AverageMW REAL,
            IsTotalRow INTEGER NOT NULL DEFAULT 0,
            GenerationGrain TEXT NOT NULL DEFAULT 'power_station',
            SectionName TEXT NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, SectionName),
            CHECK(AggregateID IS NOT NULL OR StationID IS NOT NULL)
        );

        CREATE TABLE IF NOT EXISTS FactWRLDCFrequencyDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            RegionID INTEGER NOT NULL,
            MaximumFrequencyHz REAL,
            MaximumFrequencyTime TEXT,
            MinimumFrequencyHz REAL,
            MinimumFrequencyTime TEXT,
            AverageFrequencyHz REAL,
            FrequencyVariationIndex REAL,
            StandardDeviationHz REAL,
            Maximum15MinuteBlockFrequencyHz REAL,
            Minimum15MinuteBlockFrequencyHz REAL,
            PercentageOutsideIEGCBand REAL,
            HoursOutsideIEGCBand REAL,
            PRIMARY KEY(ReportDocumentID, DateID, RegionID)
        );

        CREATE TABLE IF NOT EXISTS FactWRLDCVoltageProfile (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            VoltageNodeID INTEGER NOT NULL,
            NominalVoltageKV REAL NOT NULL,
            MaximumKV REAL,
            MaximumTime TEXT,
            MinimumKV REAL,
            MinimumTime TEXT,
            LowCriticalPct REAL,
            IEGCBandPct REAL,
            HighCriticalPct REAL,
            VoltageDeviationIndexPct REAL,
            PRIMARY KEY(ReportDocumentID, DateID, VoltageNodeID)
        );

        CREATE TABLE IF NOT EXISTS FactWRLDCReservoirDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ReservoirID INTEGER NOT NULL,
            MinimumDrawdownLevelM REAL,
            FullReservoirLevelM REAL,
            DesignedEnergyMU REAL,
            CurrentLevelM REAL,
            CurrentEnergyMU REAL,
            PreviousYearLevelM REAL,
            PreviousYearEnergyMU REAL,
            InflowMU REAL,
            ProgressiveInflowMU REAL,
            ProgressiveUsageMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ReservoirID)
        );

        CREATE TABLE IF NOT EXISTS FactWRLDCMarketEnergyDaily (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL,
            StateID INTEGER,
            GNAScheduleMU REAL,
            TGNABilateralMU REAL,
            GDAMScheduleMU REAL,
            DAMScheduleMU REAL,
            HPDAMScheduleMU REAL,
            RTMScheduleMU REAL,
            TotalMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID)
        );
        CREATE TABLE IF NOT EXISTS FactWRLDCMarketPointDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, EntityID INTEGER NOT NULL,
            StateID INTEGER, TimeCategory TEXT NOT NULL CHECK(TimeCategory IN ('off_peak', 'peak')),
            Mechanism TEXT NOT NULL, ClearedMW REAL NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, TimeCategory, Mechanism)
        );
        CREATE TABLE IF NOT EXISTS FactWRLDCMarketExtremaDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL, EntityID INTEGER NOT NULL,
            StateID INTEGER, Mechanism TEXT NOT NULL, MaximumMW REAL NOT NULL, MinimumMW REAL NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, Mechanism)
        );

        CREATE TABLE IF NOT EXISTS FactWRLDCInterRegionalExchange (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            ElementID INTEGER NOT NULL,
            CounterpartyRegion TEXT NOT NULL,
            EveningPeakMW REAL,
            OffPeakMW REAL,
            MaximumImportMW REAL,
            MaximumExportMW REAL,
            ImportEnergyMU REAL,
            ExportEnergyMU REAL,
            NetEnergyMU REAL,
            PRIMARY KEY(ReportDocumentID, DateID, ElementID, CounterpartyRegion)
        );
        """
    )


def _backfill_srldc_dimension_locations(conn: sqlite3.Connection) -> None:
    """Backfill deterministic SRLDC location metadata on existing dimensions."""

    for voltage_node_id, node_name, nominal_kv in conn.execute(
        "SELECT VoltageNodeID, NodeName, NominalVoltageKV FROM DimVoltageNodes"
    ).fetchall():
        state_id = _state_id(conn, voltage_node_state_name(node_name))
        region_id = _region_id(conn, "Southern Region")
        conn.execute(
            """
            UPDATE DimVoltageNodes
            SET StateID = COALESCE(StateID, ?),
                RegionID = COALESCE(RegionID, ?)
            WHERE VoltageNodeID = ?
            """,
            (state_id, region_id, voltage_node_id),
        )
    for reservoir_id, reservoir_name in conn.execute(
        "SELECT ReservoirID, ReservoirName FROM DimReservoirs"
    ).fetchall():
        state_id = _state_id(conn, reservoir_state_name(reservoir_name))
        region_id = _region_id(conn, "Southern Region")
        conn.execute(
            """
            UPDATE DimReservoirs
            SET StateID = COALESCE(StateID, ?),
                RegionID = COALESCE(RegionID, ?)
            WHERE ReservoirID = ?
            """,
            (state_id, region_id, reservoir_id),
        )
    for element_id, element_name in conn.execute(
        "SELECT ElementID, ElementName FROM DimTransmissionElements"
    ).fetchall():
        metadata = transmission_location(element_name)
        conn.execute(
            """
            UPDATE DimTransmissionElements
            SET ElementType = COALESCE(ElementType, ?),
                NominalVoltageKV = COALESCE(NominalVoltageKV, ?),
                FromRegionID = COALESCE(FromRegionID, ?),
                ToRegionID = COALESCE(ToRegionID, ?),
                FromStateID = COALESCE(FromStateID, ?),
                ToStateID = COALESCE(ToStateID, ?)
            WHERE ElementID = ?
            """,
            (
                metadata.element_type,
                metadata.nominal_voltage_kv,
                _region_id(conn, metadata.from_location.region_name),
                _region_id(conn, metadata.to_location.region_name),
                _state_id(conn, metadata.from_location.state_name),
                _state_id(conn, metadata.to_location.state_name),
                element_id,
            ),
        )


def _backfill_erldc_dimension_locations(conn: sqlite3.Connection) -> None:
    """Fill missing ERLDC dimension locations from exact verified registry entries."""

    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_report_document'").fetchone() is None:
        return
    for node_id, name in conn.execute("SELECT DISTINCT n.VoltageNodeID, n.NodeName FROM DimVoltageNodes n JOIN FactERLDCVoltageProfile f ON f.VoltageNodeID = n.VoltageNodeID JOIN psp_report_document d ON d.id = f.ReportDocumentID WHERE d.rldc = 'erldc'"):
        location = erldc_voltage_node_location(str(name))
        if location.evidence == "unverified": continue
        conn.execute("UPDATE DimVoltageNodes SET StateID = COALESCE(StateID, ?), RegionID = COALESCE(RegionID, ?) WHERE VoltageNodeID = ?", (_state_id(conn, location.state_name), _region_id(conn, location.region_name), node_id))
    for reservoir_id, name in conn.execute("SELECT DISTINCT r.ReservoirID, r.ReservoirName FROM DimReservoirs r JOIN FactERLDCReservoirDaily f ON f.ReservoirID = r.ReservoirID JOIN psp_report_document d ON d.id = f.ReportDocumentID WHERE d.rldc = 'erldc'"):
        location = erldc_reservoir_location(str(name))
        if location.evidence == "unverified": continue
        conn.execute("UPDATE DimReservoirs SET StateID = COALESCE(StateID, ?), RegionID = COALESCE(RegionID, ?) WHERE ReservoirID = ?", (_state_id(conn, location.state_name), _region_id(conn, location.region_name), reservoir_id))
    for entity_id, name in conn.execute("SELECT DISTINCT e.EntityID, e.EntityName FROM DimGridEntities e JOIN FactERLDCGenerationDaily f ON f.EntityID = e.EntityID JOIN psp_report_document d ON d.id = f.ReportDocumentID WHERE d.rldc = 'erldc'"):
        state_name = erldc_generation_entity_state_name(str(name))
        if state_name:
            state_id = _state_id(conn, state_name)
            region_id = _region_id(conn, "Eastern Region")
            canonical = conn.execute(
                "SELECT EntityID FROM DimGridEntities WHERE EntityName = ("
                "SELECT EntityName FROM DimGridEntities WHERE EntityID = ?) "
                "AND EntityType = (SELECT EntityType FROM DimGridEntities WHERE EntityID = ?) "
                "AND StateID = ? AND RegionID = ? AND EntityID <> ?",
                (entity_id, entity_id, state_id, region_id, entity_id),
            ).fetchone()
            if canonical:
                _merge_erldc_generation_entity(
                    conn,
                    source_entity_id=int(entity_id),
                    canonical_entity_id=int(canonical[0]),
                )
                continue
            conn.execute(
                "UPDATE DimGridEntities SET StateID = COALESCE(StateID, ?), "
                "RegionID = COALESCE(RegionID, ?) WHERE EntityID = ?",
                (state_id, region_id, entity_id),
            )
    for element_id, name in conn.execute("SELECT DISTINCT e.ElementID, e.ElementName FROM DimTransmissionElements e JOIN FactERLDCInterRegionalExchange f ON f.ElementID = e.ElementID JOIN psp_report_document d ON d.id = f.ReportDocumentID WHERE d.rldc = 'erldc'"):
        meta = erldc_transmission_location(str(name))
        if meta.evidence == "unverified": continue
        conn.execute("UPDATE DimTransmissionElements SET ElementType = COALESCE(ElementType, ?), NominalVoltageKV = COALESCE(NominalVoltageKV, ?), FromRegionID = COALESCE(FromRegionID, ?), ToRegionID = COALESCE(ToRegionID, ?), FromStateID = COALESCE(FromStateID, ?), ToStateID = COALESCE(ToStateID, ?) WHERE ElementID = ?", (meta.element_type, meta.nominal_voltage_kv, _region_id(conn, meta.from_location.region_name), _region_id(conn, meta.to_location.region_name), _state_id(conn, meta.from_location.state_name), _state_id(conn, meta.to_location.state_name), element_id))


def _merge_erldc_generation_entity(
    conn: sqlite3.Connection,
    source_entity_id: int,
    canonical_entity_id: int,
) -> None:
    """Coalesce a legacy state-null ERLDC entity into its canonical identity."""

    conn.execute(
        "UPDATE OR REPLACE FactERLDCGenerationDaily SET EntityID = ?, "
        "AggregateID = CASE WHEN AggregateID = ? THEN ? ELSE AggregateID END "
        "WHERE EntityID = ?",
        (
            canonical_entity_id,
            source_entity_id,
            canonical_entity_id,
            source_entity_id,
        ),
    )
    source_token = f"entity={source_entity_id};"
    canonical_token = f"entity={canonical_entity_id};"
    conn.execute(
        "UPDATE OR REPLACE curated_field_lineage "
        "SET DestinationKey = REPLACE(DestinationKey, ?, ?) "
        "WHERE DestinationTable = 'FactERLDCGenerationDaily' "
        "AND DestinationKey LIKE ?",
        (source_token, canonical_token, f"%{source_token}%"),
    )
    conn.execute(
        "DELETE FROM DimGridEntities WHERE EntityID = ?",
        (source_entity_id,),
    )


def _backfill_nerldc_dimension_locations(conn: sqlite3.Connection) -> None:
    """Enrich only NERLDC-referenced topology from the controlled registry."""

    document_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'psp_report_document'"
    ).fetchone()
    if document_table is None:
        return

    nodes = conn.execute(
        "SELECT DISTINCT n.VoltageNodeID, n.NodeName "
        "FROM DimVoltageNodes AS n "
        "JOIN FactNERLDCVoltageProfile AS f ON f.VoltageNodeID = n.VoltageNodeID "
        "JOIN psp_report_document AS d ON d.id = f.ReportDocumentID "
        "WHERE d.rldc = 'nerldc'"
    ).fetchall()
    for node_id, name in nodes:
        location = nerldc_voltage_node_location(str(name))
        if location.evidence == "unverified":
            continue
        conn.execute(
            "UPDATE DimVoltageNodes SET StateID = COALESCE(StateID, ?), "
            "RegionID = COALESCE(RegionID, ?) WHERE VoltageNodeID = ?",
            (_state_id(conn, location.state_name), _region_id(conn, location.region_name), node_id),
        )

    elements = conn.execute(
        "SELECT DISTINCT e.ElementID, e.ElementName "
        "FROM DimTransmissionElements AS e "
        "JOIN FactNERLDCInterRegionalExchange AS f ON f.ElementID = e.ElementID "
        "JOIN psp_report_document AS d ON d.id = f.ReportDocumentID "
        "WHERE d.rldc = 'nerldc'"
    ).fetchall()
    for element_id, name in elements:
        metadata = nerldc_transmission_location(str(name))
        if metadata.evidence == "unverified":
            continue
        conn.execute(
            "UPDATE DimTransmissionElements SET ElementType = COALESCE(ElementType, ?), "
            "NominalVoltageKV = COALESCE(NominalVoltageKV, ?), "
            "FromRegionID = COALESCE(FromRegionID, ?), "
            "ToRegionID = COALESCE(ToRegionID, ?), "
            "FromStateID = COALESCE(FromStateID, ?), "
            "ToStateID = COALESCE(ToStateID, ?), "
            "FromCountryID = COALESCE(FromCountryID, ?), "
            "ToCountryID = COALESCE(ToCountryID, ?) WHERE ElementID = ?",
            (
                metadata.element_type,
                metadata.nominal_voltage_kv,
                _region_id(conn, metadata.from_location.region_name),
                _region_id(conn, metadata.to_location.region_name),
                _state_id(conn, metadata.from_location.state_name),
                _state_id(conn, metadata.to_location.state_name),
                _country_id(conn, metadata.from_location.country_name),
                _country_id(conn, metadata.to_location.country_name),
                element_id,
            ),
        )


def _backfill_wrldc_dimension_locations(conn: sqlite3.Connection) -> None:
    """Enrich only WRLDC-referenced topology from the controlled registry."""

    raw_document_table = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'psp_report_document'
        """
    ).fetchone()
    if raw_document_table is None:
        return

    voltage_nodes = conn.execute(
        """
        SELECT DISTINCT node.VoltageNodeID, node.NodeName
        FROM DimVoltageNodes AS node
        JOIN FactWRLDCVoltageProfile AS fact
          ON fact.VoltageNodeID = node.VoltageNodeID
        JOIN psp_report_document AS document
          ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'wrldc'
        """
    ).fetchall()
    for voltage_node_id, node_name in voltage_nodes:
        location = wrldc_voltage_node_location(str(node_name))
        if location.state_name is None:
            continue
        conn.execute(
            """
            UPDATE DimVoltageNodes
            SET StateID = COALESCE(StateID, ?),
                RegionID = COALESCE(RegionID, ?)
            WHERE VoltageNodeID = ?
            """,
            (
                _wrldc_state_id(conn, location.state_name),
                _region_id(conn, location.region_name),
                voltage_node_id,
            ),
        )

    elements = conn.execute(
        """
        SELECT DISTINCT element.ElementID, element.ElementName
        FROM DimTransmissionElements AS element
        JOIN FactWRLDCInterRegionalExchange AS fact
          ON fact.ElementID = element.ElementID
        JOIN psp_report_document AS document
          ON document.id = fact.ReportDocumentID
        WHERE document.rldc = 'wrldc'
        """
    ).fetchall()
    for element_id, element_name in elements:
        metadata = wrldc_transmission_location(str(element_name))
        if (
            metadata.from_location.state_name is None
            or metadata.to_location.state_name is None
        ):
            continue
        conn.execute(
            """
            UPDATE DimTransmissionElements
            SET ElementType = COALESCE(ElementType, ?),
                NominalVoltageKV = COALESCE(NominalVoltageKV, ?),
                FromRegionID = COALESCE(FromRegionID, ?),
                ToRegionID = COALESCE(ToRegionID, ?),
                FromStateID = COALESCE(FromStateID, ?),
                ToStateID = COALESCE(ToStateID, ?)
            WHERE ElementID = ?
            """,
            (
                metadata.element_type,
                metadata.nominal_voltage_kv,
                _region_id(conn, metadata.from_location.region_name),
                _region_id(conn, metadata.to_location.region_name),
                _wrldc_state_id(conn, metadata.from_location.state_name),
                _wrldc_state_id(conn, metadata.to_location.state_name),
                element_id,
            ),
        )
def _backfill_srldc_generation_dimensions(conn: sqlite3.Connection) -> None:
    """Populate newly added denormalized generation dimensions for legacy rows."""

    conn.execute(
        """
        UPDATE FactSRLDCGenerationDaily
        SET StateID = COALESCE(
                StateID,
                (SELECT e.StateID
                 FROM DimGridEntities AS e
                 WHERE e.EntityID = FactSRLDCGenerationDaily.EntityID)
            ),
            GenerationSourceID = COALESCE(
                GenerationSourceID,
                (SELECT e.GenerationSourceID
                 FROM DimGridEntities AS e
                 WHERE e.EntityID = FactSRLDCGenerationDaily.EntityID)
            ),
            GenerationGrain = CASE
                WHEN AggregateID IS NOT NULL THEN 'aggregate'
                WHEN GeneratingUnitID IS NOT NULL THEN 'generating_unit'
                WHEN StationID IS NOT NULL THEN 'power_station'
                ELSE COALESCE(GenerationGrain, 'power_station')
            END
        """
    )


def _migrate_srldc_market_table(conn: sqlite3.Connection) -> None:
    """Rebuild the market fact when upgrading from its original coarse grain."""

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(FactSRLDCMarketTransaction)")
    }
    if {"StateID", "TimeCategory", "ScheduledMW", "MinimumMW"}.issubset(columns):
        return
    conn.execute(
        "ALTER TABLE FactSRLDCMarketTransaction "
        "RENAME TO FactSRLDCMarketTransactionLegacy"
    )
    conn.execute(
        """
        CREATE TABLE FactSRLDCMarketTransaction (
            ReportDocumentID INTEGER NOT NULL,
            DateID INTEGER NOT NULL,
            StateID INTEGER,
            MechanismID INTEGER NOT NULL,
            ProductName TEXT NOT NULL,
            Direction TEXT NOT NULL,
            TimeCategory TEXT NOT NULL,
            EnergyMU REAL,
            ScheduledMW REAL,
            MaximumMW REAL,
            MinimumMW REAL,
            PRIMARY KEY(
                ReportDocumentID, DateID, StateID, MechanismID,
                ProductName, Direction, TimeCategory
        )
        )
        """
    )
    conn.execute(
        """
        INSERT INTO FactSRLDCMarketTransaction(
            ReportDocumentID, DateID, StateID, MechanismID, ProductName,
            Direction, TimeCategory, EnergyMU, MaximumMW
        )
        SELECT ReportDocumentID, DateID, NULL, MechanismID, ProductName,
               Direction, 'legacy', EnergyMU, MaximumMW
        FROM FactSRLDCMarketTransactionLegacy
        """
    )
    conn.execute("DROP TABLE FactSRLDCMarketTransactionLegacy")


def _seed_curated_dimensions(conn: sqlite3.Connection) -> None:
    """Seed stable dimensions and unit mappings from the archive schema."""

    conn.executemany(
        """
        INSERT OR IGNORE INTO DimUnits(UnitName, UnitSymbol, UnitCategory, Description)
        VALUES (?, ?, ?, ?)
        """,
        UNIT_ROWS,
    )
    conn.executemany("INSERT OR IGNORE INTO DimRegions(RegionName) VALUES (?)", REGION_ROWS)
    conn.executemany(
        """
        INSERT OR IGNORE INTO DimGenerationSources(SourceName, SourceCategory)
        VALUES (?, ?)
        """,
        GENERATION_SOURCE_ROWS,
    )
    conn.executemany("INSERT OR IGNORE INTO DimCountries(CountryName) VALUES (?)", COUNTRY_ROWS)
    conn.executemany(
        "INSERT OR IGNORE INTO DimExchangeMechanisms(MechanismName) VALUES (?)",
        EXCHANGE_MECHANISM_ROWS,
    )
    for state_name, region_name in STATE_ROWS:
        conn.execute(
            """
            INSERT OR IGNORE INTO DimStates(StateName, RegionID)
            SELECT ?, RegionID FROM DimRegions WHERE RegionName = ?
            """,
            (state_name, region_name),
        )
    for state_name, state_code in SOUTHERN_STATE_CODES.items():
        conn.execute(
            "UPDATE DimStates SET StateCode = ? WHERE StateName = ?",
            (state_code, state_name),
        )
    state_aliases = {
        "Andhra Pradesh": ("Andhra Pradesh", "AP"),
        "Telangana": ("Telangana", "TS"),
        "Karnataka": ("Karnataka", "KA"),
        "Kerala": ("Kerala", "KL"),
        "Tamil Nadu": ("Tamil Nadu", "Tamilnadu", "TN"),
        "Puducherry": ("Puducherry", "Pondicherry", "Pondicher", "PY"),
    }
    for state_name, aliases in state_aliases.items():
        state_row = conn.execute(
            "SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)
        ).fetchone()
        if not state_row:
            continue
        for alias in aliases:
            normalized = re.sub(r"[^a-z0-9]", "", alias.lower())
            conn.execute(
                """
                INSERT OR IGNORE INTO DimStateAliases(
                    SourceID, RawName, NormalizedName, StateID,
                    ApprovalStatus, MatchConfidence
                ) VALUES ('srldc', ?, ?, ?, 'approved', 1.0)
                """,
                (alias, normalized, state_row[0]),
            )
    nrldc_state_aliases = {
        "Punjab": ("Punjab",),
        "Haryana": ("Haryana",),
        "Rajasthan": ("Rajasthan",),
        "Delhi": ("Delhi",),
        "UP": ("UP", "Uttar Pradesh", "UttarPradesh"),
        "Uttarakhand": ("Uttarakhand",),
        "HP": ("HP", "Himachal Pradesh", "HimachalPradesh"),
        "J&K(UT) & Ladakh(UT)": (
            "J&K(UT)&Ladakh(UT)",
            "Jammu and Kashmir and Ladakh",
        ),
        "Chandigarh": ("Chandigarh",),
        "Railways_NR ISTS": ("Railways", "Railways NR ISTS"),
    }
    for state_name, aliases in nrldc_state_aliases.items():
        state_row = conn.execute(
            "SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)
        ).fetchone()
        if not state_row:
            continue
        for alias in aliases:
            normalized = re.sub(r"[^a-z0-9]", "", alias.lower())
            conn.execute(
                """
                INSERT OR IGNORE INTO DimStateAliases(
                    SourceID, RawName, NormalizedName, StateID,
                    ApprovalStatus, MatchConfidence
                ) VALUES ('nrldc', ?, ?, ?, 'approved', 1.0)
                """,
                (alias, normalized, state_row[0]),
            )
    wrldc_state_aliases = {
        "Chhattisgarh": ("Chhattisgarh",),
        "Gujarat": ("Gujarat",),
        "MP": ("MP", "Madhya Pradesh", "MadhyaPradesh"),
        "Maharashtra": ("Maharashtra",),
        "Goa": ("Goa",),
        "DNHDDPDCL": ("DNHDDPDCL",),
        "AMNSIL": ("AMNSIL",),
        "BALCO": ("BALCO",),
        "RIL JAMNAGAR": ("RILJAMNAGAR", "RIL JAMNAGAR"),
    }
    for state_name, aliases in wrldc_state_aliases.items():
        state_row = conn.execute(
            "SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)
        ).fetchone()
        if not state_row:
            continue
        for alias in aliases:
            normalized = re.sub(r"[^a-z0-9]", "", alias.lower())
            conn.execute(
                """
                INSERT OR IGNORE INTO DimStateAliases(
                    SourceID, RawName, NormalizedName, StateID,
                    ApprovalStatus, MatchConfidence
                ) VALUES ('wrldc', ?, ?, ?, 'approved', 1.0)
                """,
                (alias, normalized, state_row[0]),
            )
    for table_name, column_name, unit_symbol in UNIT_MAPPINGS:
        conn.execute(
            """
            INSERT OR IGNORE INTO MetaTableColumnUnits(TableName, ColumnName, UnitID)
            SELECT ?, ?, UnitID FROM DimUnits WHERE UnitSymbol = ?
            """,
            (table_name, column_name, unit_symbol),
        )


def _seed_metric_registry(conn: sqlite3.Connection) -> None:
    """Materialize stable metric identities for all curated numeric measures.

    ``MetricID`` is deliberately derived from the physical curated contract,
    rather than a regional export prefix.  The existing source-prefixed metric
    name remains a backward-compatible export alias while this registry gives
    consumers a stable, unit-aware identity.
    """

    dimension_columns = {
        "ReportDocumentID",
        "DateID",
        "RegionID",
        "StateID",
        "CountryID",
        "EntityID",
        "GenerationSourceID",
        "StationID",
        "GeneratingUnitID",
        "AggregateID",
        "ElementID",
        "VoltageNodeID",
        "ReservoirID",
        "MechanismID",
        "IsTotalRow",
        "BlockNumber",
    }
    numeric_types = {"INTEGER", "REAL", "FLOAT", "DOUBLE", "NUMERIC"}
    tables = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name LIKE 'Fact%'
        ORDER BY name
        """
    ).fetchall()
    for (table_name,) in tables:
        for _, column_name, declared_type, *_ in conn.execute(
            f"PRAGMA table_info({table_name})"
        ):
            if column_name in dimension_columns:
                continue
            affinity = str(declared_type or "").upper().split("(", 1)[0]
            if affinity not in numeric_types:
                continue
            unit = conn.execute(
                """
                SELECT UnitID
                FROM MetaTableColumnUnits
                WHERE TableName = ? AND ColumnName = ?
                """,
                (table_name, column_name),
            ).fetchone()
            unit_id = int(unit[0]) if unit else _inferred_unit_id(conn, column_name)
            conn.execute(
                """
                INSERT OR IGNORE INTO DimMetric(
                    MetricID, TableName, ColumnName, UnitID, Description
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"{table_name}.{column_name}",
                    table_name,
                    column_name,
                    unit_id,
                    f"Curated PSP measure {table_name}.{column_name}",
                ),
            )


def _inferred_unit_id(conn: sqlite3.Connection, column_name: str) -> int | None:
    """Return a conservative unit inferred from a stable curated column suffix."""

    normalized = re.sub(r"[^a-z0-9]", "", column_name.lower())
    suffixes = (
        ("mw", "MW"),
        ("mu", "MU"),
        ("hz", "Hz"),
        ("kv", "kV"),
        ("pct", "%"),
        ("percent", "%"),
        ("index", "Index"),
        ("circuits", "Count"),
        ("count", "Count"),
        ("rs", "Rs"),
        ("inr", "Rs"),
    )
    for suffix, unit_symbol in suffixes:
        if normalized.endswith(suffix):
            row = conn.execute(
                "SELECT UnitID FROM DimUnits WHERE UnitSymbol = ?", (unit_symbol,)
            ).fetchone()
            return int(row[0]) if row else None
    return None


def _state_id(conn: sqlite3.Connection, state_name: str | None) -> int | None:
    """Look up a state identifier when a canonical name is available."""

    if not state_name:
        return None
    row = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _country_id(conn: sqlite3.Connection, country_name: str | None) -> int | None:
    """Return a seeded country identifier without synthesizing geography."""

    if not country_name:
        return None
    conn.execute(
        "INSERT OR IGNORE INTO DimCountries(CountryName) VALUES (?)",
        (country_name,),
    )
    row = conn.execute(
        "SELECT CountryID FROM DimCountries WHERE CountryName = ?",
        (country_name,),
    ).fetchone()
    return int(row[0]) if row else None


def _wrldc_state_id(conn: sqlite3.Connection, state_name: str | None) -> int | None:
    """Resolve WRLDC registry display names to existing canonical state keys."""

    canonical_name = {
        "Dadra and Nagar Haveli and Daman and Diu": "DNHDDPDCL",
        "Madhya Pradesh": "MP",
        "Uttar Pradesh": "UP",
    }.get(state_name or "", state_name)
    return _state_id(conn, canonical_name)


def _region_id(conn: sqlite3.Connection, region_name: str | None) -> int | None:
    """Look up a region identifier when a canonical name is available."""

    if not region_name:
        return None
    row = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (region_name,)
    ).fetchone()
    return int(row[0]) if row else None
