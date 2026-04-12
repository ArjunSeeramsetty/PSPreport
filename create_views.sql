-- ============================================
-- ANALYTICAL VIEWS
-- This script creates views for easier data analysis.
-- It is idempotent and can be run multiple times.
-- ============================================

-- Drop views if they already exist to allow for recreation
DROP VIEW IF EXISTS VwStateDailyEnergyDetails;
DROP VIEW IF EXISTS VwDailySummary;
DROP VIEW IF EXISTS VwDailyGenerationDetails;
DROP VIEW IF EXISTS VwTimeBlockGenerationDetails;
DROP VIEW IF EXISTS VwColumnUnitMapping;
DROP VIEW IF EXISTS VwInternationalLinkFlowDetails;
DROP VIEW IF EXISTS VwTransnationalExchangeDetails;
DROP VIEW IF EXISTS VwTransmissionLinkFlowDetails;


-- View 1: Detailed State-wise Daily Energy
-- Combines state daily facts with date, state, and region names.
CREATE VIEW VwStateDailyEnergyDetails AS
SELECT
    fse.DateID,
    d.ActualDate,
    fse.StateID,
    s.StateName,
    r.RegionName,
    fse.MaximumDemand,
    fse.Shortage,
    fse.EnergyMet,
    fse.DrawalSchedule,
    fse.OverUnderDrawal,
    fse.MaxOverDrawal,
    fse.EnergyShortage
FROM
    FactStateDailyEnergy AS fse
JOIN
    DimDates AS d ON fse.DateID = d.DateID
JOIN
    DimStates AS s ON fse.StateID = s.StateID
LEFT JOIN
    DimRegions AS r ON s.RegionID = r.RegionID;


-- View 2: Detailed National and Regional Daily Summary
-- Combines the all-India/regional summary facts with date and region names.
-- This view will show 'India' as the RegionName for the national summary.
CREATE VIEW VwDailySummary AS
SELECT
    fais.DateID,
    d.ActualDate,
    fais.RegionID,
    r.RegionName,
    fais.PeakDemandMet,
    fais.PeakShortage,
    fais.EnergyMet,
    fais.EnergyShortage,
    fais.MaxDemandSCADA,
    fais.TimeOfMaxDemandMet,
    fais.ScheduleDrawal,
    fais.ActualDrawal,
    fais.OverUnderDrawal,
    fais.CentralSectorOutage,
    fais.StateSectorOutage,
    fais.TotalOutage,
    fais.ShareRESInTotalGeneration,
    fais.ShareNonFossilInTotalGeneration,
    fais.FrequencyViolationIndex,
    fais.DurationFrequencyBelow49_9,
    fais.DurationFrequency_49_9_to_50_05,
    fais.DurationFrequencyAbove50_05,
    fais.RegionDDF,
    fais.StatesDDF,
    fais.SolarHRMaxDemand,
    fais.SolarHRMaxDemandTime,
    fais.SolarHRShortage,
    fais.NonSolarHRMaxDemand,
    fais.NonSolarHRMaxDemandTime,
    fais.NonSolarHRShortage
FROM
    FactAllIndiaDailySummary AS fais
JOIN
    DimDates AS d ON fais.DateID = d.DateID
JOIN
    DimRegions AS r ON fais.RegionID = r.RegionID;


-- View 3: Detailed Daily Generation Breakdown
-- Shows generation amounts per source for each region/nation per day.
CREATE VIEW VwDailyGenerationDetails AS
SELECT
    fdgb.DateID,
    d.ActualDate,
    fdgb.RegionID,
    r.RegionName,
    fdgb.GenerationSourceID,
    gs.SourceName,
    gs.SourceCategory,
    fdgb.GenerationAmount
FROM
    FactDailyGenerationBreakdown AS fdgb
JOIN
    DimDates AS d ON fdgb.DateID = d.DateID
JOIN
    DimRegions AS r ON fdgb.RegionID = r.RegionID
JOIN
    DimGenerationSources AS gs ON fdgb.GenerationSourceID = gs.GenerationSourceID;


-- View 4: Detailed Time Block Generation Breakdown
-- Shows generation output per source for each 15-minute time block.
CREATE VIEW VwTimeBlockGenerationDetails AS
SELECT
    ftbg.DateID,
    d.ActualDate,
    ftbg.BlockTime,
    ftbg.BlockNumber,
    pwr.Frequency,
    pwr.DemandMet,
    ftbg.GenerationSourceID,
    gs.SourceName,
    gs.SourceCategory,
    ftbg.GenerationOutput
FROM
    FactTimeBlockGeneration AS ftbg
JOIN
    DimDates AS d ON ftbg.DateID = d.DateID
JOIN
    FactTimeBlockPowerData AS pwr ON ftbg.DateID = pwr.DateID AND ftbg.BlockTime = pwr.BlockTime
JOIN
    DimGenerationSources AS gs ON ftbg.GenerationSourceID = gs.GenerationSourceID;

-- View 5: Domestic Inter-Regional Transmission Link Flow
CREATE VIEW VwTransmissionLinkFlowDetails AS
SELECT
    ftlf.DateID,
    d.ActualDate,
    ftlf.LineID,
    tl.LineIdentifier,
    tl.VoltageLevel_kV,
    ftlf.Inter_Region,
    ftlf.MaxImport,
    ftlf.MaxExport,
    ftlf.ImportEnergy,
    ftlf.ExportEnergy,
    ftlf.NetImportEnergy
FROM
    FactTransmissionLinkFlow as ftlf
JOIN
    DimDates as d ON ftlf.DateID = d.DateID
JOIN
    DimTransmissionLines as tl ON ftlf.LineID = tl.LineID;

-- View 6: International Transmission Link Flow Details
CREATE VIEW VwInternationalLinkFlowDetails AS
SELECT
    fitlf.DateID,
    d.ActualDate,
    fitlf.LineID,
    tl.LineIdentifier,
    tl.VoltageLevel_kV,
    fitlf.CountryID,
    c.CountryName,
    fitlf.StateID,
    s.StateName,
    fitlf.RegionID,
    r.RegionName,
    fitlf.MaxLoading,
    fitlf.MinLoading,
    fitlf.AvgLoading,
    fitlf.EnergyExchanged
FROM
    FactInternationalTransmissionLinkFlow as fitlf
JOIN
    DimDates as d ON fitlf.DateID = d.DateID
JOIN
    DimTransmissionLines as tl ON fitlf.LineID = tl.LineID
LEFT JOIN
    DimCountries as c ON fitlf.CountryID = c.CountryID
LEFT JOIN
    DimStates as s ON fitlf.StateID = s.StateID
LEFT JOIN
    DimRegions as r ON fitlf.RegionID = r.RegionID;


-- View 7: Detailed Transnational Exchange by Mechanism
CREATE VIEW VwTransnationalExchangeDetails AS
SELECT
    fdt.DateID,
    d.ActualDate,
    fdt.CountryID,
    c.CountryName,
    fdt.MechanismID,
    em.MechanismName,
    fdt.ExchangeDirection,
    fdt.ExchangeValue
FROM
    FactTransnationalExchangeDetail as fdt
JOIN
    DimDates as d ON fdt.DateID = d.DateID
JOIN
    DimCountries as c ON fdt.CountryID = c.CountryID
JOIN
    DimExchangeMechanisms as em ON fdt.MechanismID = em.MechanismID;


-- View 8: Utility View for Column Units
-- A metadata view that clearly maps table columns to their units of measurement.
CREATE VIEW VwColumnUnitMapping AS
SELECT
    m.TableName,
    m.ColumnName,
    u.UnitName,
    u.UnitSymbol,
    u.UnitCategory,
    u.Description
FROM
    MetaTableColumnUnits AS m
JOIN
    DimUnits AS u ON m.UnitID = u.UnitID;

