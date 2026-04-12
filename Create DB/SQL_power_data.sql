-- Enable Foreign Key support if not enabled by default
PRAGMA foreign_keys = ON;

-- ============================================
-- Unit Management Tables
-- ============================================

CREATE TABLE DimUnits (
    UnitID INTEGER PRIMARY KEY AUTOINCREMENT,
    UnitName TEXT NOT NULL UNIQUE,
    UnitSymbol TEXT NOT NULL UNIQUE,
    UnitCategory TEXT,
    Description TEXT
);

CREATE TABLE MetaTableColumnUnits (
    TableColumnUnitID INTEGER PRIMARY KEY AUTOINCREMENT,
    SchemaName TEXT NOT NULL DEFAULT 'main', -- 'main' is the default schema in SQLite
    TableName TEXT NOT NULL,
    ColumnName TEXT NOT NULL,
    UnitID INTEGER NOT NULL,
    FOREIGN KEY (UnitID) REFERENCES DimUnits(UnitID),
    UNIQUE (SchemaName, TableName, ColumnName)
);

-- ============================================
-- Dimension Tables
-- ============================================

CREATE TABLE DimDates (
    DateID INTEGER PRIMARY KEY AUTOINCREMENT,
    ActualDate TEXT NOT NULL UNIQUE, -- Store as 'YYYY-MM-DD'
    DayOfWeek TEXT,
    DayOfMonth INTEGER,
    Month INTEGER,
    Quarter INTEGER,
    Year INTEGER
);

CREATE TABLE DimRegions (
    RegionID INTEGER PRIMARY KEY AUTOINCREMENT,
    RegionName TEXT NOT NULL UNIQUE
);

CREATE TABLE DimStates (
    StateID INTEGER PRIMARY KEY AUTOINCREMENT,
    StateName TEXT NOT NULL UNIQUE,
    RegionID INTEGER,
    FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID)
);

CREATE TABLE DimCountries (
    CountryID INTEGER PRIMARY KEY AUTOINCREMENT,
    CountryName TEXT NOT NULL UNIQUE
);

CREATE TABLE DimGenerationSources (
    GenerationSourceID INTEGER PRIMARY KEY AUTOINCREMENT,
    SourceName TEXT NOT NULL UNIQUE,
    SourceCategory TEXT -- e.g., Renewable, Thermal, Hydro, Nuclear
);

CREATE TABLE DimTransmissionLines (
    LineID INTEGER PRIMARY KEY AUTOINCREMENT,
    LineIdentifier TEXT NOT NULL UNIQUE, -- e.g., Name or Code of the line
    VoltageLevel_kV TEXT, -- Store voltage in kV directly if available, or TEXT if varied format
    NumberOfCircuits INTEGER,
    CountryID INTEGER, -- NULL for domestic, set for international lines
    FOREIGN KEY (CountryID) REFERENCES DimCountries(CountryID)
);

CREATE TABLE DimExchangeMechanisms (
    MechanismID INTEGER PRIMARY KEY AUTOINCREMENT,
    MechanismName TEXT NOT NULL UNIQUE -- e.g., PPA, Bilateral, DAM IEX
);

CREATE TABLE DimReports (
    DateID INTEGER,
    ReportName TEXT NOT NULL UNIQUE,
    ReportPath TEXT,
    Source TEXT,
    PRIMARY KEY (DateID, ReportName),
    FOREIGN KEY (DateID) REFERENCES DimDates(DateID)
);

-- ============================================
-- Fact Tables
-- ============================================

-- Fact Table for DataFrame 1 (All India Power Position like data)
CREATE TABLE FactAllIndiaDailySummary (
    DateID INTEGER NOT NULL,
    RegionID INTEGER,              -- NULL for all-India summary
    EveningPeakDemandMet REAL,             -- Unit: MW
    PeakShortage REAL,              -- Unit: MW
    EnergyMet REAL,                 -- Unit: MU
    EnergyShortage REAL,            -- Unit: MU
    MaxDemandSCADA REAL,            -- Unit: MW
    TimeOfMaxDemandMet TEXT,        -- Store as 'HH:MM:SS'
    ScheduleDrawal REAL,            -- Unit: MU
    ActualDrawal REAL,              -- Unit: MU
    OverUnderDrawal REAL,           -- Unit: MU
    CentralSectorOutage REAL,
    StateSectorOutage REAL,
    TotalOutage REAL,
    ShareRESInTotalGeneration REAL, -- Unit: Percent
    ShareNonFossilInTotalGeneration REAL, -- Unit: Percent
    FrequencyViolationIndex REAL,   -- Unit: Defined in DimUnits
    DurationFrequencyBelow49_7 REAL, -- Unit: e.g., Percent of time or Hours
    DurationFrequency_49_7_to_49_8 REAL,
    DurationFrequency_49_8_to_49_9 REAL,
    DurationFrequencyBelow49_9 REAL,
    DurationFrequency_49_9_to_50_05 REAL,
    DurationFrequencyAbove50_05 REAL,
    RegionDDF REAL,                 -- Define unit if applicable
    StatesDDF REAL,                 -- Define unit if applicable
    SolarHRMaxDemand REAL,           -- New: Solar Hour Max Demand (MW)
    SolarHRMaxDemandTime TEXT,       -- New: Solar Hour Max Demand Time (HH:MM:SS)
    SolarHRShortage REAL,            -- New: Solar Hour Shortage (MW)
    NonSolarHRMaxDemand REAL,        -- New: Non-Solar Hour Max Demand (MW)
    NonSolarHRMaxDemandTime TEXT,    -- New: Non-Solar Hour Max Demand Time (HH:MM:SS)
    NonSolarHRShortage REAL,         -- New: Non-Solar Hour Shortage (MW)
    PRIMARY KEY (DateID, RegionID),
    FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
    FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID)
);

-- Related to FactAllIndiaDailySummary for generation breakdown
CREATE TABLE FactDailyGenerationBreakdown (
    DateID INTEGER NOT NULL,
    RegionID INTEGER, -- To match the composite PK of FactAllIndiaDailySummary
    GenerationSourceID INTEGER NOT NULL,
    GenerationAmount REAL,        -- Unit: MU
    PRIMARY KEY (DateID, RegionID, GenerationSourceID),
    FOREIGN KEY (DateID, RegionID) REFERENCES FactAllIndiaDailySummary(DateID, RegionID),
    FOREIGN KEY (GenerationSourceID) REFERENCES DimGenerationSources(GenerationSourceID)
);

-- Fact Table for DataFrame 2 (State-wise Demand and Supply like data)
CREATE TABLE FactStateDailyEnergy (
    DateID INTEGER NOT NULL,
    StateID INTEGER NOT NULL,
    MaximumDemand REAL,           -- Unit: MW
    Shortage REAL,                -- Unit: MW
    EnergyMet REAL,               -- Unit: MU
    DrawalSchedule REAL,          -- Unit: MU
    OverUnderDrawal REAL,         -- Unit: MU
    MaxOverDrawal REAL,           -- Unit: MW
    EnergyShortage REAL,          -- Unit: MU
    PRIMARY KEY (DateID, StateID),
    FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
    FOREIGN KEY (StateID) REFERENCES DimStates(StateID)
);

-- Fact Table for DataFrame 3 (Transnational Exchange Summary like data)
CREATE TABLE FactCountryDailyExchange (
    DateID INTEGER NOT NULL,
    CountryID INTEGER NOT NULL,
    TotalEnergyExchanged REAL,    -- Unit: MU
    PeakExchange REAL,            -- Unit: MW
    PRIMARY KEY (DateID, CountryID),
    FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
    FOREIGN KEY (CountryID) REFERENCES DimCountries(CountryID)
);

-- Fact Table for DataFrame 4 (Inter-Regional/National Links like data)
CREATE TABLE FactTransmissionLinkFlow (
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

-- Fact Table for DataFrame 5 (Congestion Information like data)
CREATE TABLE FactInternationalTransmissionLinkFlow (
    DateID INTEGER NOT NULL,
    LineID INTEGER NOT NULL,
    CountryID INTEGER,             -- Track the foreign country
    StateID INTEGER,               -- Can be NULL if not applicable
    RegionID INTEGER,              -- Can be NULL if not applicable
    MaxLoading REAL,               -- Unit: MW
    MinLoading REAL,               -- Unit: MW
    AvgLoading REAL,               -- Unit: MW
    EnergyExchanged REAL,          -- Unit: MU
    PRIMARY KEY (DateID, LineID),
    FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
    FOREIGN KEY (LineID) REFERENCES DimTransmissionLines(LineID),
    FOREIGN KEY (CountryID) REFERENCES DimCountries(CountryID),
    FOREIGN KEY (StateID) REFERENCES DimStates(StateID),
    FOREIGN KEY (RegionID) REFERENCES DimRegions(RegionID)
);

-- Fact Table for DataFrame 6 (Transnational Exchange Details by Type like data)
CREATE TABLE FactTransnationalExchangeDetail (
    DateID INTEGER NOT NULL,
    CountryID INTEGER NOT NULL,
    MechanismID INTEGER NOT NULL,
    ExchangeDirection TEXT NOT NULL, -- 'Import' or 'Export'
    ExchangeValue REAL,           -- Unit: MU
    PRIMARY KEY (DateID, CountryID, MechanismID, ExchangeDirection),
    FOREIGN KEY (DateID) REFERENCES DimDates(DateID),
    FOREIGN KEY (CountryID) REFERENCES DimCountries(CountryID),
    FOREIGN KEY (MechanismID) REFERENCES DimExchangeMechanisms(MechanismID)
);

-- Fact Table for DataFrame 7 (All India Time Block Wise Data)
CREATE TABLE FactTimeBlockPowerData (
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

-- Related to FactTimeBlockPowerData for generation breakdown
CREATE TABLE FactTimeBlockGeneration (
    DateID INTEGER NOT NULL,
    BlockTime TEXT NOT NULL,
    BlockNumber INTEGER NOT NULL,
    GenerationSourceID INTEGER NOT NULL,
    GenerationOutput REAL,        -- Unit: MW
    PRIMARY KEY (DateID, BlockTime, GenerationSourceID),
    FOREIGN KEY (DateID, BlockTime) REFERENCES FactTimeBlockPowerData(DateID, BlockTime),
    FOREIGN KEY (GenerationSourceID) REFERENCES DimGenerationSources(GenerationSourceID)
);