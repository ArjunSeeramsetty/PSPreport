-- ============================================
-- INSERT statements for dbo.DimExchangeMechanisms
-- Generated from: DimExchangeMechanisms.csv
-- Total rows: 9
-- Identity columns: MechanismID
-- ============================================

USE [Powerflow];
GO

-- Enable identity insert for MechanismID
SET IDENTITY_INSERT [dbo].[DimExchangeMechanisms] ON;
GO

INSERT INTO [dbo].[DimExchangeMechanisms] ([MechanismID], [MechanismName]) VALUES (1, N'PPA');
INSERT INTO [dbo].[DimExchangeMechanisms] ([MechanismID], [MechanismName]) VALUES (2, N'Bilateral');
INSERT INTO [dbo].[DimExchangeMechanisms] ([MechanismID], [MechanismName]) VALUES (3, N'DAM IEX');
INSERT INTO [dbo].[DimExchangeMechanisms] ([MechanismID], [MechanismName]) VALUES (4, N'DAM PXIL');
INSERT INTO [dbo].[DimExchangeMechanisms] ([MechanismID], [MechanismName]) VALUES (5, N'DAM HPX');
INSERT INTO [dbo].[DimExchangeMechanisms] ([MechanismID], [MechanismName]) VALUES (6, N'RTM IEX');
INSERT INTO [dbo].[DimExchangeMechanisms] ([MechanismID], [MechanismName]) VALUES (7, N'RTM PXIL');
INSERT INTO [dbo].[DimExchangeMechanisms] ([MechanismID], [MechanismName]) VALUES (8, N'RTM HPX');
INSERT INTO [dbo].[DimExchangeMechanisms] ([MechanismID], [MechanismName]) VALUES (9, N'TOTAL');

-- Disable identity insert for MechanismID
SET IDENTITY_INSERT [dbo].[DimExchangeMechanisms] OFF;
GO

-- Total 9 rows inserted into dbo.DimExchangeMechanisms
GO