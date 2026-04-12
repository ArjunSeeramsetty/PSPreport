-- ============================================
-- INSERT statements for dbo.MetaTableColumnUnits
-- Generated from: MetaTableColumnUnits.csv
-- Total rows: 50
-- Identity columns: TableColumnUnitID
-- ============================================

USE [Powerflow];
GO

-- Enable identity insert for TableColumnUnitID
SET IDENTITY_INSERT [dbo].[MetaTableColumnUnits] ON;
GO

INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (1, N'main', N'FactAllIndiaDailySummary', N'ShareRESInTotalGeneration', 4);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (2, N'main', N'FactAllIndiaDailySummary', N'EveningPeakDemandMet', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (3, N'main', N'FactAllIndiaDailySummary', N'PeakShortage', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (4, N'main', N'FactAllIndiaDailySummary', N'EnergyMet', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (5, N'main', N'FactAllIndiaDailySummary', N'EnergyShortage', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (6, N'main', N'FactAllIndiaDailySummary', N'MaxDemandSCADA', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (7, N'main', N'FactAllIndiaDailySummary', N'ScheduleDrawal', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (8, N'main', N'FactAllIndiaDailySummary', N'ActualDrawal', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (9, N'main', N'FactAllIndiaDailySummary', N'OverUnderDrawal', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (10, N'main', N'FactAllIndiaDailySummary', N'FrequencyViolationIndex', 6);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (11, N'main', N'FactAllIndiaDailySummary', N'DurationFrequencyBelow49_7', 4);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (12, N'main', N'FactAllIndiaDailySummary', N'DurationFrequency_49_7_to_49_8', 4);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (13, N'main', N'FactAllIndiaDailySummary', N'DurationFrequency_49_8_to_49_9', 4);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (14, N'main', N'FactAllIndiaDailySummary', N'DurationFrequencyBelow49_9', 4);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (15, N'main', N'FactAllIndiaDailySummary', N'DurationFrequency_49_9_to_50_05', 4);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (16, N'main', N'FactAllIndiaDailySummary', N'DurationFrequencyAbove50_05', 4);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (17, N'main', N'FactAllIndiaDailySummary', N'RegionDDF', 4);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (18, N'main', N'FactAllIndiaDailySummary', N'StatesDDF', 4);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (19, N'main', N'FactAllIndiaDailySummary', N'SolarHRMaxDemand', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (20, N'main', N'FactAllIndiaDailySummary', N'SolarHRMaxDemandTime', 9);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (21, N'main', N'FactAllIndiaDailySummary', N'SolarHRShortage', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (22, N'main', N'FactAllIndiaDailySummary', N'NonSolarHRMaxDemand', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (23, N'main', N'FactAllIndiaDailySummary', N'NonSolarHRMaxDemandTime', 9);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (24, N'main', N'FactAllIndiaDailySummary', N'NonSolarHRShortage', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (25, N'main', N'FactStateDailyEnergy', N'MaximumDemand', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (26, N'main', N'FactStateDailyEnergy', N'Shortage', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (27, N'main', N'FactStateDailyEnergy', N'EnergyMet', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (28, N'main', N'FactStateDailyEnergy', N'DrawalSchedule', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (29, N'main', N'FactStateDailyEnergy', N'OverUnderDrawal', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (30, N'main', N'FactStateDailyEnergy', N'MaxOverDrawal', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (31, N'main', N'FactStateDailyEnergy', N'EnergyShortage', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (32, N'main', N'FactTransmissionLinkFlow', N'MaxImport', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (33, N'main', N'FactTransmissionLinkFlow', N'MaxExport', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (34, N'main', N'FactTransmissionLinkFlow', N'ImportEnergy', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (35, N'main', N'FactTransmissionLinkFlow', N'ExportEnergy', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (36, N'main', N'FactTransmissionLinkFlow', N'NetImportEnergy', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (37, N'main', N'FactTimeBlockPowerData', N'Frequency', 3);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (38, N'main', N'FactTimeBlockPowerData', N'DemandMet', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (39, N'main', N'FactTimeBlockPowerData', N'NetDemandMet', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (40, N'main', N'FactTimeBlockPowerData', N'TotalGeneration', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (41, N'main', N'FactTimeBlockPowerData', N'NetTransnationalExchange', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (42, N'main', N'FactTimeBlockGeneration', N'GenerationOutput', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (43, N'main', N'FactDailyGenerationBreakdown', N'GenerationAmount', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (44, N'main', N'FactCountryDailyExchange', N'TotalEnergyExchanged', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (45, N'main', N'FactCountryDailyExchange', N'PeakExchange', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (46, N'main', N'FactInternationalTransmissionLinkFlow', N'MaxLoading', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (47, N'main', N'FactInternationalTransmissionLinkFlow', N'MinLoading', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (48, N'main', N'FactInternationalTransmissionLinkFlow', N'AvgLoading', 1);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (49, N'main', N'FactInternationalTransmissionLinkFlow', N'EnergyExchanged', 2);
INSERT INTO [dbo].[MetaTableColumnUnits] ([TableColumnUnitID], [SchemaName], [TableName], [ColumnName], [UnitID]) VALUES (50, N'main', N'FactTransnationalExchangeDetail', N'ExchangeValue', 2);

-- Disable identity insert for TableColumnUnitID
SET IDENTITY_INSERT [dbo].[MetaTableColumnUnits] OFF;
GO

-- Total 50 rows inserted into dbo.MetaTableColumnUnits
GO