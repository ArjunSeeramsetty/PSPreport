-- ============================================
-- INSERT statements for dbo.DimRegions
-- Generated from: DimRegions.csv
-- Total rows: 6
-- Identity columns: RegionID
-- ============================================

USE [Powerflow];
GO

-- Enable identity insert for RegionID
SET IDENTITY_INSERT [dbo].[DimRegions] ON;
GO

INSERT INTO [dbo].[DimRegions] ([RegionID], [RegionName]) VALUES (1, N'Northern Region');
INSERT INTO [dbo].[DimRegions] ([RegionID], [RegionName]) VALUES (2, N'Western Region');
INSERT INTO [dbo].[DimRegions] ([RegionID], [RegionName]) VALUES (3, N'Southern Region');
INSERT INTO [dbo].[DimRegions] ([RegionID], [RegionName]) VALUES (4, N'Eastern Region');
INSERT INTO [dbo].[DimRegions] ([RegionID], [RegionName]) VALUES (5, N'North Eastern Region');
INSERT INTO [dbo].[DimRegions] ([RegionID], [RegionName]) VALUES (6, N'India');

-- Disable identity insert for RegionID
SET IDENTITY_INSERT [dbo].[DimRegions] OFF;
GO

-- Total 6 rows inserted into dbo.DimRegions
GO