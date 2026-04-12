-- ============================================
-- INSERT statements for dbo.DimStates
-- Generated from: DimStates.csv
-- Total rows: 39
-- Identity columns: StateID
-- ============================================

USE [Powerflow];
GO

-- Enable identity insert for StateID
SET IDENTITY_INSERT [dbo].[DimStates] ON;
GO

INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (1, N'Punjab', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (2, N'Haryana', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (3, N'Rajasthan', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (4, N'Delhi', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (5, N'UP', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (6, N'Uttarakhand', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (7, N'HP', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (8, N'J&K(UT) & Ladakh(UT)', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (9, N'Chandigarh', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (10, N'Railways_NR ISTS', 1);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (11, N'Chhattisgarh', 2);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (12, N'Gujarat', 2);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (13, N'MP', 2);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (14, N'Maharashtra', 2);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (15, N'Goa', 2);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (16, N'DNHDDPDCL', 2);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (17, N'AMNSIL', 2);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (18, N'BALCO', 2);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (19, N'RIL JAMNAGAR', 2);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (20, N'Andhra Pradesh', 3);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (21, N'Telangana', 3);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (22, N'Karnataka', 3);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (23, N'Kerala', 3);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (24, N'Tamil Nadu', 3);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (25, N'Puducherry', 3);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (26, N'Bihar', 4);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (27, N'DVC', 4);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (28, N'Jharkhand', 4);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (29, N'Odisha', 4);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (30, N'West Bengal', 4);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (31, N'Sikkim', 4);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (32, N'Railways_ER ISTS', 4);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (33, N'Arunachal Pradesh', 5);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (34, N'Assam', 5);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (35, N'Manipur', 5);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (36, N'Meghalaya', 5);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (37, N'Mizoram', 5);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (38, N'Nagaland', 5);
INSERT INTO [dbo].[DimStates] ([StateID], [StateName], [RegionID]) VALUES (39, N'Tripura', 5);

-- Disable identity insert for StateID
SET IDENTITY_INSERT [dbo].[DimStates] OFF;
GO

-- Total 39 rows inserted into dbo.DimStates
GO