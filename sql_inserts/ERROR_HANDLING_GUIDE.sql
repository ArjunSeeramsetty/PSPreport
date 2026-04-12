-- ============================================
-- DATABASE INSERT ERROR HANDLING GUIDE
-- ============================================

-- Common Issues and Solutions:

-- 1. IDENTITY COLUMN ERRORS
-- If you see: "Cannot insert explicit value for identity column"
-- Solution: The script now handles this automatically with SET IDENTITY_INSERT ON/OFF

-- 2. FOREIGN KEY CONSTRAINT ERRORS
-- If you see: "The INSERT statement conflicted with the FOREIGN KEY constraint"
-- Solution: Ensure dimension tables are populated before fact tables
-- Recommended order:
--   a) DimUnits, DimRegions, DimCountries, DimStates, DimGenerationSources
--   b) DimTransmissionLines, DimExchangeMechanisms, DimDates, DimReports
--   c) Fact tables (in any order)

-- 3. DUPLICATE KEY ERRORS
-- If you see: "Violation of PRIMARY KEY constraint"
-- Solution: Clear existing data first or use MERGE statements

-- 4. DATA TYPE CONVERSION ERRORS
-- If you see: "Conversion failed when converting date/time"
-- Solution: Check date formats in CSV files

-- 5. COLUMN COUNT MISMATCH
-- If you see: "Column name or number of supplied values does not match"
-- Solution: Verify CSV column headers match table schema

-- ============================================
-- TROUBLESHOOTING STEPS:
-- ============================================

-- Step 1: Check table structure
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'YourTableName'
ORDER BY ORDINAL_POSITION;

-- Step 2: Check existing data
SELECT COUNT(*) FROM dbo.YourTableName;

-- Step 3: Check identity column settings
SELECT 
    t.name AS TableName,
    c.name AS ColumnName,
    c.is_identity,
    c.seed_value,
    c.increment_value
FROM sys.tables t
JOIN sys.columns c ON t.object_id = c.object_id
WHERE c.is_identity = 1
ORDER BY t.name, c.name;

-- Step 4: Clear table if needed (BE CAREFUL!)
-- DELETE FROM dbo.YourTableName;
-- DBCC CHECKIDENT ('dbo.YourTableName', RESEED, 0);

-- ============================================
-- SAFE EXECUTION ORDER:
-- ============================================

-- 1. Execute individual table files in this order:
--    DimUnits_inserts.sql
--    DimRegions_inserts.sql
--    DimCountries_inserts.sql
--    DimStates_inserts.sql
--    DimGenerationSources_inserts.sql
--    DimTransmissionLines_inserts.sql
--    DimExchangeMechanisms_inserts.sql
--    DimDates_inserts.sql
--    DimReports_inserts.sql
--    MetaTableColumnUnits_inserts.sql
--    [Then any Fact table files]

-- 2. Or use the master file: ALL_TABLES_INSERTS.sql
--    This handles the order automatically

-- ============================================
-- PERFORMANCE TIPS:
-- ============================================

-- 1. For large tables, consider using BULK INSERT instead of individual INSERTs
-- 2. Disable indexes before bulk insert, re-enable after
-- 3. Use minimal logging if possible
-- 4. Consider batching large inserts into smaller transactions

-- ============================================
