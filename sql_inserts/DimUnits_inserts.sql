-- ============================================
-- INSERT statements for dbo.DimUnits
-- Generated from: DimUnits.csv
-- Total rows: 9
-- Identity columns: UnitID
-- ============================================

USE [Powerflow];
GO

-- Enable identity insert for UnitID
SET IDENTITY_INSERT [dbo].[DimUnits] ON;
GO

INSERT INTO [dbo].[DimUnits] ([UnitID], [UnitName], [UnitSymbol], [UnitCategory], [Description]) VALUES (1, N'MegaWatts', N'MW', N'Power', N'Standard unit of active power');
INSERT INTO [dbo].[DimUnits] ([UnitID], [UnitName], [UnitSymbol], [UnitCategory], [Description]) VALUES (2, N'Million Units', N'MU', N'Energy', N'1 MU = 1 GWh, Standard unit of energy');
INSERT INTO [dbo].[DimUnits] ([UnitID], [UnitName], [UnitSymbol], [UnitCategory], [Description]) VALUES (3, N'Hertz', N'Hz', N'Frequency', N'Standard unit of electrical frequency');
INSERT INTO [dbo].[DimUnits] ([UnitID], [UnitName], [UnitSymbol], [UnitCategory], [Description]) VALUES (4, N'Percent', N'%', N'Ratio', N'Dimensionless unit for ratios or shares');
INSERT INTO [dbo].[DimUnits] ([UnitID], [UnitName], [UnitSymbol], [UnitCategory], [Description]) VALUES (5, N'Kilovolt', N'kV', N'Voltage', N'Unit of electrical potential');
INSERT INTO [dbo].[DimUnits] ([UnitID], [UnitName], [UnitSymbol], [UnitCategory], [Description]) VALUES (6, N'Index', N'Index', N'Index', N'Dimensionless index value');
INSERT INTO [dbo].[DimUnits] ([UnitID], [UnitName], [UnitSymbol], [UnitCategory], [Description]) VALUES (7, N'Hours', N'hrs', N'TimeDuration', N'Unit of time duration');
INSERT INTO [dbo].[DimUnits] ([UnitID], [UnitName], [UnitSymbol], [UnitCategory], [Description]) VALUES (8, N'Count', N'Count', N'Count', N'Simple count of items');
INSERT INTO [dbo].[DimUnits] ([UnitID], [UnitName], [UnitSymbol], [UnitCategory], [Description]) VALUES (9, N'Time', N'HH:MM:SS', N'Time', N'Time in hours:minutes:seconds format');

-- Disable identity insert for UnitID
SET IDENTITY_INSERT [dbo].[DimUnits] OFF;
GO

-- Total 9 rows inserted into dbo.DimUnits
GO