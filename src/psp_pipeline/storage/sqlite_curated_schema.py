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
        """
    )
    _ensure_schema_design_tables(conn)
    _ensure_srldc_curated_tables(conn)
    _seed_curated_dimensions(conn)
    seed_srldc_schema_registry(conn)
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

        CREATE TABLE IF NOT EXISTS curated_field_lineage (
            LineageID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReportDocumentID INTEGER NOT NULL,
            DestinationTable TEXT NOT NULL,
            DestinationKey TEXT NOT NULL,
            DestinationColumn TEXT NOT NULL,
            RawCellID INTEGER,
            RawTextItemID INTEGER,
            ExtractionMethod TEXT NOT NULL,
            Confidence REAL NOT NULL,
            CreatedAt TEXT NOT NULL,
            CHECK(RawCellID IS NOT NULL OR RawTextItemID IS NOT NULL),
            UNIQUE(
                ReportDocumentID, DestinationTable, DestinationKey,
                DestinationColumn, RawCellID, RawTextItemID
            )
        );
        """
    )


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
            ToStateID INTEGER
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
    for table_name, column_name, unit_symbol in UNIT_MAPPINGS:
        conn.execute(
            """
            INSERT OR IGNORE INTO MetaTableColumnUnits(TableName, ColumnName, UnitID)
            SELECT ?, ?, UnitID FROM DimUnits WHERE UnitSymbol = ?
            """,
            (table_name, column_name, unit_symbol),
        )


def _state_id(conn: sqlite3.Connection, state_name: str | None) -> int | None:
    """Look up a state identifier when a canonical name is available."""

    if not state_name:
        return None
    row = conn.execute(
        "SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,)
    ).fetchone()
    return int(row[0]) if row else None


def _region_id(conn: sqlite3.Connection, region_name: str | None) -> int | None:
    """Look up a region identifier when a canonical name is available."""

    if not region_name:
        return None
    row = conn.execute(
        "SELECT RegionID FROM DimRegions WHERE RegionName = ?", (region_name,)
    ).fetchone()
    return int(row[0]) if row else None
