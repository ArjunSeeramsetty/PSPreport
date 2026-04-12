-- ============================================
-- INSERT statements for dbo.DimCountries
-- Generated from: DimCountries.csv
-- Total rows: 8
-- Identity columns: CountryID
-- ============================================

USE [Powerflow];
GO

-- Enable identity insert for CountryID
SET IDENTITY_INSERT [dbo].[DimCountries] ON;
GO

INSERT INTO [dbo].[DimCountries] ([CountryID], [CountryName]) VALUES (1, N'Bhutan');
INSERT INTO [dbo].[DimCountries] ([CountryID], [CountryName]) VALUES (2, N'Nepal');
INSERT INTO [dbo].[DimCountries] ([CountryID], [CountryName]) VALUES (3, N'Bangladesh');
INSERT INTO [dbo].[DimCountries] ([CountryID], [CountryName]) VALUES (4, N'Myanmar');
INSERT INTO [dbo].[DimCountries] ([CountryID], [CountryName]) VALUES (5, N'Godda (Bangladesh)');
INSERT INTO [dbo].[DimCountries] ([CountryID], [CountryName]) VALUES (6, N'Total Export');
INSERT INTO [dbo].[DimCountries] ([CountryID], [CountryName]) VALUES (7, N'Total Import');
INSERT INTO [dbo].[DimCountries] ([CountryID], [CountryName]) VALUES (8, N'Total Net');

-- Disable identity insert for CountryID
SET IDENTITY_INSERT [dbo].[DimCountries] OFF;
GO

-- Total 8 rows inserted into dbo.DimCountries
GO