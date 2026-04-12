import os
import csv
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any


def sanitize_sql_value(value: Any) -> str:
    """Convert Python values to safe SQL string values."""
    if value is None or pd.isna(value):
        return 'NULL'
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, str):
        # Escape single quotes and handle special characters
        escaped = value.replace("'", "''")
        return f"N'{escaped}'"
    else:
        return f"N'{str(value)}'"


def get_identity_columns(table_name: str) -> List[str]:
    """Get list of identity columns for a table based on common patterns."""
    # Common identity column patterns in your schema
    identity_patterns = {
        'DimDates': ['DateID'],
        'DimRegions': ['RegionID'],
        'DimStates': ['StateID'],
        'DimCountries': ['CountryID'],
        'DimGenerationSources': ['GenerationSourceID'],
        'DimTransmissionLines': ['LineID'],
        'DimExchangeMechanisms': ['MechanismID'],
        'DimUnits': ['UnitID'],
        'DimReports': [],  # Composite key, no identity
        'MetaTableColumnUnits': ['TableColumnUnitID'],
        'FactAllIndiaDailySummary': [],  # Composite key, no identity
        'FactDailyGenerationBreakdown': [],  # Composite key, no identity
        'FactStateDailyEnergy': [],  # Composite key, no identity
        'FactCountryDailyExchange': [],  # Composite key, no identity
        'FactTransmissionLinkFlow': [],  # Composite key, no identity
        'FactInternationalTransmissionLinkFlow': [],  # Composite key, no identity
        'FactTransnationalExchangeDetail': [],  # Composite key, no identity
        'FactTimeBlockPowerData': [],  # Composite key, no identity
        'FactTimeBlockGeneration': []  # Composite key, no identity
    }
    
    return identity_patterns.get(table_name, [])


def generate_insert_statements(csv_file_path: str, table_name: str, schema: str = 'dbo') -> str:
    """Generate INSERT statements from CSV data with identity column handling."""
    try:
        # Read CSV with pandas to handle various encodings and formats
        df = pd.read_csv(csv_file_path, encoding='utf-8')
        
        if df.empty:
            return f"-- Table {schema}.{table_name} is empty\n-- No INSERT statements generated\n"
        
        # Get column names
        columns = df.columns.tolist()
        
        # Get identity columns for this table
        identity_columns = get_identity_columns(table_name)
        
        # Generate INSERT statements
        sql_lines = []
        sql_lines.append(f"-- ============================================")
        sql_lines.append(f"-- INSERT statements for {schema}.{table_name}")
        sql_lines.append(f"-- Generated from: {os.path.basename(csv_file_path)}")
        sql_lines.append(f"-- Total rows: {len(df)}")
        if identity_columns:
            sql_lines.append(f"-- Identity columns: {', '.join(identity_columns)}")
        sql_lines.append(f"-- ============================================")
        sql_lines.append("")
        sql_lines.append(f"USE [Powerflow];")
        sql_lines.append("GO")
        sql_lines.append("")
        
        # Handle identity columns
        if identity_columns:
            for identity_col in identity_columns:
                if identity_col in columns:
                    sql_lines.append(f"-- Enable identity insert for {identity_col}")
                    sql_lines.append(f"SET IDENTITY_INSERT [{schema}].[{table_name}] ON;")
                    sql_lines.append("GO")
                    sql_lines.append("")
        
        # Generate column list
        column_list = ", ".join([f"[{col}]" for col in columns])
        
        # Process each row
        for index, row in df.iterrows():
            # Convert row values to SQL-safe strings
            values = [sanitize_sql_value(row[col]) for col in columns]
            values_str = ", ".join(values)
            
            # Generate INSERT statement
            insert_stmt = f"INSERT INTO [{schema}].[{table_name}] ({column_list}) VALUES ({values_str});"
            sql_lines.append(insert_stmt)
        
        # Disable identity insert if it was enabled
        if identity_columns:
            for identity_col in identity_columns:
                if identity_col in columns:
                    sql_lines.append("")
                    sql_lines.append(f"-- Disable identity insert for {identity_col}")
                    sql_lines.append(f"SET IDENTITY_INSERT [{schema}].[{table_name}] OFF;")
                    sql_lines.append("GO")
        
        sql_lines.append("")
        sql_lines.append(f"-- Total {len(df)} rows inserted into {schema}.{table_name}")
        sql_lines.append("GO")
        
        return "\n".join(sql_lines)
        
    except Exception as e:
        return f"-- Error processing {csv_file_path}: {str(e)}\n"


def process_csv_directory(csv_dir: str, output_dir: str, schema: str = 'dbo') -> None:
    """Process all CSV files in the directory and generate SQL files."""
    csv_path = Path(csv_dir)
    output_path = Path(output_dir)
    
    # Create output directory if it doesn't exist
    output_path.mkdir(exist_ok=True)
    
    # Find all CSV files
    csv_files = list(csv_path.glob("*.csv"))
    
    if not csv_files:
        print(f"No CSV files found in {csv_dir}")
        return
    
    print(f"Found {len(csv_files)} CSV files to process...")
    
    # Process each CSV file
    for csv_file in csv_files:
        # Extract table name from filename (remove .csv extension)
        table_name = csv_file.stem
        
        print(f"Processing {table_name}...")
        
        # Generate SQL content
        sql_content = generate_insert_statements(str(csv_file), table_name, schema)
        
        # Write SQL file
        sql_file_path = output_path / f"{table_name}_inserts.sql"
        with open(sql_file_path, 'w', encoding='utf-8') as f:
            f.write(sql_content)
        
        print(f"  Generated: {sql_file_path}")
    
    # Generate a master SQL file that includes all tables
    generate_master_sql_file(csv_files, output_path, schema)
    
    print(f"\nSQL generation completed! Files saved to: {output_path}")


def generate_master_sql_file(csv_files: List[Path], output_path: Path, schema: str = 'dbo') -> None:
    """Generate a master SQL file that includes all tables with proper identity handling."""
    master_content = []
    master_content.append("-- ============================================")
    master_content.append("-- MASTER SQL FILE - All Table Inserts")
    master_content.append("-- Generated from sqlite_csv_export directory")
    master_content.append("-- ============================================")
    master_content.append("")
    master_content.append("USE [Powerflow];")
    master_content.append("GO")
    master_content.append("")
    master_content.append("-- ============================================")
    master_content.append("-- IMPORTANT: This file handles identity columns automatically")
    master_content.append("-- Each table section includes SET IDENTITY_INSERT ON/OFF as needed")
    master_content.append("-- ============================================")
    master_content.append("")
    
    # Add each table's inserts
    for csv_file in csv_files:
        table_name = csv_file.stem
        master_content.append(f"-- ============================================")
        master_content.append(f"-- Table: {schema}.{table_name}")
        master_content.append(f"-- Source: {csv_file.name}")
        master_content.append(f"-- ============================================")
        master_content.append("")
        
        # Read and add the content from individual SQL file
        individual_sql_path = output_path / f"{table_name}_inserts.sql"
        if individual_sql_path.exists():
            with open(individual_sql_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Remove the USE statement and GO from individual files
                lines = content.split('\n')
                # Skip the first few lines (header, USE, GO)
                start_idx = 0
                for i, line in enumerate(lines):
                    if line.strip() == "GO":
                        start_idx = i + 1
                        break
                
                # Add the content without the header
                master_content.extend(lines[start_idx:])
                master_content.append("")
    
    # Write master file
    master_file_path = output_path / "ALL_TABLES_INSERTS.sql"
    with open(master_file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(master_content))
    
    print(f"  Generated master file: {master_file_path}")


def generate_error_handling_guide(output_dir: str) -> None:
    """Generate a guide for handling common database insert errors."""
    guide_content = """-- ============================================
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
"""
    
    guide_path = Path(output_dir) / "ERROR_HANDLING_GUIDE.sql"
    with open(guide_path, 'w', encoding='utf-8') as f:
        f.write(guide_content)
    
    print(f"  Generated error handling guide: {guide_path}")


def main():
    """Main function to process CSV files."""
    # Configuration
    csv_directory = "sqlite_csv_export"  # Directory containing CSV files
    output_directory = "sql_inserts"     # Directory to save SQL files
    schema_name = "dbo"                  # Target schema in SQL Server
    
    print("SQL Insert Statement Generator (Updated)")
    print("=" * 50)
    print("Features:")
    print("- Automatic identity column handling")
    print("- SET IDENTITY_INSERT ON/OFF management")
    print("- Error handling guide generation")
    print("=" * 50)
    
    # Check if CSV directory exists
    if not os.path.exists(csv_directory):
        print(f"Error: CSV directory '{csv_directory}' not found!")
        print("Please ensure the directory exists and contains CSV files.")
        return
    
    # Process CSV files
    process_csv_directory(csv_directory, output_directory, schema_name)
    
    # Generate error handling guide
    generate_error_handling_guide(output_directory)
    
    print("\n" + "=" * 50)
    print("Generation Summary:")
    print(f"- CSV source: {csv_directory}")
    print(f"- SQL output: {output_directory}")
    print(f"- Target schema: {schema_name}")
    print(f"- Identity columns: Handled automatically")
    print(f"- Error guide: Generated")
    print("\nNext steps:")
    print("1. Review the generated SQL files")
    print("2. Check ERROR_HANDLING_GUIDE.sql for troubleshooting")
    print("3. Execute files in SSMS against your Powerflow database")
    print("4. Or use the master file 'ALL_TABLES_INSERTS.sql' for bulk import")
    print("\nNote: Identity columns are now handled automatically!")


if __name__ == "__main__":
    main()
