-- ============================================
-- INSERT statements for dbo.DimGenerationSources
-- Generated from: DimGenerationSources.csv
-- Total rows: 15
-- Identity columns: GenerationSourceID
-- ============================================

USE [Powerflow];
GO

-- Enable identity insert for GenerationSourceID
SET IDENTITY_INSERT [dbo].[DimGenerationSources] ON;
GO

INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (1, N'Coal', N'Thermal');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (2, N'Lignite', N'Thermal');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (3, N'Gas', N'Thermal');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (4, N'Naptha', N'Thermal');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (5, N'Diesel', N'Thermal');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (6, N'Gas, Naptha & Diesel', N'Thermal');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (7, N'Thermal', N'Thermal');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (8, N'Hydro', N'Hydro');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (9, N'Nuclear', N'Nuclear');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (10, N'Solar', N'Renewable');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (11, N'Wind', N'Renewable');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (12, N'Biomass', N'Renewable');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (13, N'Others', N'Renewable');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (14, N'RE', N'Renewable');
INSERT INTO [dbo].[DimGenerationSources] ([GenerationSourceID], [SourceName], [SourceCategory]) VALUES (15, N'Total', N'Total');

-- Disable identity insert for GenerationSourceID
SET IDENTITY_INSERT [dbo].[DimGenerationSources] OFF;
GO

-- Total 15 rows inserted into dbo.DimGenerationSources
GO