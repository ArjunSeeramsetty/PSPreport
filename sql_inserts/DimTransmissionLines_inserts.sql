-- ============================================
-- INSERT statements for dbo.DimTransmissionLines
-- Generated from: DimTransmissionLines.csv
-- Total rows: 94
-- Identity columns: LineID
-- ============================================

USE [Powerflow];
GO

-- Enable identity insert for LineID
SET IDENTITY_INSERT [dbo].[DimTransmissionLines] ON;
GO

INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (1, N'ALIPURDUAR-AGRA', N'HVDC', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (2, N'PUSAULI  B/B', N'HVDC', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (3, N'GAYA-VARANASI', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (4, N'SASARAM-FATEHPUR', N'765 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (5, N'GAYA-BALIA', N'765 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (6, N'PUSAULI-VARANASI', N'400 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (7, N'PUSAULI -ALLAHABAD', N'400 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (8, N'MUZAFFARPUR-GORAKHPUR', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (9, N'PATNA-BALIA', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (10, N'NAUBATPUR-BALIA', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (11, N'BIHARSHARIFF-BALIA', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (12, N'MOTIHARI-GORAKHPUR', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (13, N'BIHARSARIFF-SAHUPURI', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (14, N'SAHUPURI-KARAMNASA', N'220 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (15, N'NAGAR UNTARI-RIHAND', N'132 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (16, N'GARWAH-RIHAND', N'132 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (17, N'KARMANASA-SAHUPURI', N'132 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (18, N'KARMANASA-CHANDAULI', N'132 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (19, N'JHARSUGUDA-DHARAMJAIGARH', N'765 kV', 4.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (20, N'NEW RANCHI-DHARAMJAIGARH', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (21, N'JHARSUGUDA-DURG', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (22, N'JHARSUGUDA-RAIGARH', N'400 kV', 4.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (23, N'RANCHI-SIPAT', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (24, N'BUDHIPADAR-RAIGARH', N'220 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (25, N'BUDHIPADAR-KORBA', N'220 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (26, N'JEYPORE-GAZUWAKA B/B', N'HVDC', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (27, N'TALCHER-KOLAR BIPOLE', N'HVDC', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (28, N'ANGUL-SRIKAKULAM', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (29, N'TALCHER-I/C', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (30, N'BALIMELA-UPPER-SILERRU', N'220 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (31, N'BINAGURI-BONGAIGAON', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (32, N'ALIPURDUAR-BONGAIGAON', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (33, N'ALIPURDUAR-SALAKATI', N'220 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (34, N'BISWANATH CHARIALI-AGRA', N'HVDC', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (35, N'CHAMPA-KURUKSHETRA', N'HVDC', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (36, N'VINDHYACHAL B/B', N'HVDC', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (37, N'MUNDRA-MOHINDERGARH', N'HVDC', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (38, N'GWALIOR-AGRA', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (39, N'GWALIOR-PHAGI', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (40, N'JABALPUR-ORAI', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (41, N'GWALIOR-ORAI', N'765 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (42, N'SATNA-ORAI', N'765 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (43, N'BANASKANTHA-CHITORGARH', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (44, N'VINDHYACHAL-VARANASI', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (45, N'ZERDA-KANKROLI', N'400 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (46, N'ZERDA -BHINMAL', N'400 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (47, N'VINDHYACHAL -RIHAND', N'400 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (48, N'RAPP-SHUJALPUR', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (49, N'NEEMUCH-Chittorgarh', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (50, N'BHANPURA-RANPUR', N'220 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (51, N'BHANPURA-MORAK', N'220 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (52, N'MEHGAON-AURAIYA', N'220 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (53, N'MALANPUR-AURAIYA', N'220 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (54, N'GWALIOR-SAWAI MADHOPUR', N'132 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (55, N'RAJGHAT-LALITPUR', N'132 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (56, N'BHADRAWATI B/B', N'HVDC', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (57, N'RAIGARH-PUGALUR', N'HVDC', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (58, N'SOLAPUR-RAICHUR', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (59, N'WARDHA-NIZAMABAD', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (60, N'WARORA-WARANGAL(NEW)', N'765 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (61, N'KOLHAPUR-KUDGI', N'400 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (62, N'KOLHAPUR-CHIKODI', N'220 kV', 2.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (63, N'PONDA-AMBEWADI', N'220 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (64, N'XELDEM-AMBEWADI', N'220 kV', 1.0, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (65, N'Total', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (66, N'400kV MANGDECHHU-ALIPURDUAR 1,2&3 i.e.ALIPURDUAR RECEIPT (from MANGDECHUHEP 4*180MW)', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (67, N'400kV TALA-BINAGURI 1,2,4 (& 400kVMALBASE  -  BINAGURI) i.e. BINAGURIRECEIPT (from TALA HEP 6*170MW)', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (68, N'220kV CHUKHA-BIRPARA 1&2 (& 220kVMALBASE - BIRPARA) i.e. BIRPARA RECEIPT(from CHUKHA HEP 4*84MW)', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (69, N'132kV GELEPHU-SALAKATI', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (70, N'132kV MOTANGA-RANGIA', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (71, N'132kV MAHENDRANAGAR-TANAKPUR(NHPC)', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (72, N'NEPAL IMPORT (FROM BIHAR)', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (73, N'400kV DHALKEBAR-MUZAFFARPUR 1&2', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (74, N'BHERAMARA B/B HVDC (B''DESH)', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (75, N'400kV GODDA_TPS-RAHANPUR (B''DESH) D/C', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (76, N'132kV COMILLA-SURAJMANI NAGAR 1&2', NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (77, N'Line Name', N'Region', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (78, N'-1244', N'400kV GODDA_TPS-RAHANPUR (B''DESH) D/C', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (79, N'-171', N'132kV COMILLA-SURAJMANI NAGAR 1&2', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (80, N'-726', N'400kV GODDA_TPS-RAHANPUR (B''DESH) D/C', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (81, N'-79', N'132kV COMILLA-SURAJMANI NAGAR 1&2', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (82, N'-63', N'132kV COMILLA-SURAJMANI NAGAR 1&2', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (83, N'-77', N'132kV COMILLA-SURAJMANI NAGAR 1&2', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (84, NULL, NULL, NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (85, N'JEYPORE-JAGDALPUR', N'400 kV', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (86, N'MOTIHARI-', N'400 kV', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (87, N'SAHUPURI-', N'220 kV', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (88, N'NEW RANCHI-', N'765 kV', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (89, N'JEYPORE-', N'400 kV', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (90, N'BINAGURI-', N'400 kV', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (91, N'BISWANATH', N'HVDC', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (92, N'CHAMPA-', N'HVDC', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (93, N'MUNDRA-', N'HVDC', NULL, NULL);
INSERT INTO [dbo].[DimTransmissionLines] ([LineID], [LineIdentifier], [VoltageLevel_kV], [NumberOfCircuits], [CountryID]) VALUES (94, N'WARDHA-', N'765 kV', NULL, NULL);

-- Disable identity insert for LineID
SET IDENTITY_INSERT [dbo].[DimTransmissionLines] OFF;
GO

-- Total 94 rows inserted into dbo.DimTransmissionLines
GO