import sqlite3
import pandas as pd
import numpy as np
import logging
import os
from datetime import datetime
import PDFparser_Gemini as parser
import re

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATABASE_NAME = 'power_data.db'

# Canonical mapping for all possible source name variations to canonical names/categories
GEN_SOURCE_CANONICAL = {
    # Thermal
    "COAL": ("Coal", "Thermal"),
    "LIGNITE": ("Lignite", "Thermal"),
    "GAS": ("Gas", "Thermal"),
    "NAPTHA": ("Naptha", "Thermal"),
    "DIESEL": ("Diesel", "Thermal"),
    "GAS, NAPTHA & DIESEL": ("Gas, Naptha & Diesel", "Thermal"),
    "THERMAL": ("Thermal", "Thermal"),
    # Hydro
    "HYDRO": ("Hydro", "Hydro"),
    # Nuclear
    "NUCLEAR": ("Nuclear", "Nuclear"),
    # Renewables
    "SOLAR": ("Solar", "Renewable"),
    "WIND": ("Wind", "Renewable"),
    "BIOMASS": ("Biomass", "Renewable"),
    "OTHERS": ("Others", "Renewable"),
    "RE": ("RE", "Renewable"),
    "RES": ("RE", "Renewable"),
    "RENEWABLE": ("RE", "Renewable"),
    "RES (WIND, SOLAR, BIOMASS & OTHERS)": ("RE", "Renewable"),
}

REGION_ALIAS = {
    'NR': 'Northern Region',
    'NORTHERN REGION': 'Northern Region',
    'WR': 'Western Region',
    'WESTERN REGION': 'Western Region',
    'SR': 'Southern Region',
    'SOUTHERN REGION': 'Southern Region',
    'ER': 'Eastern Region',
    'EASTERN REGION': 'Eastern Region',
    'ER ISOLATED FROM INDIAN GRID': 'Eastern Region',
    'NER': 'North Eastern Region',
    'NORTH EASTERN REGION': 'North Eastern Region',
    'NORTH-EASTERN REGION': 'North Eastern Region',
    'INDIA': 'India',
    'ALL INDIA': 'India',
    'ALL-INDIA': 'India'
    # Add more aliases as needed
}

COUNTRY_ALIAS = {
    'BHUTAN': 'Bhutan',
    'NEPAL': 'Nepal',
    'BANGLADESH': 'Bangladesh',
    'MYANMAR': 'Myanmar',
    'GODDA (BANGLADESH)': 'Godda (Bangladesh)',
    'GODDA': 'Godda (Bangladesh)',
    'TOTAL EXPORT': 'Total Export',
    'TOTAL IMPORT': 'Total Import',
    'TOTAL NET': 'Total Net'
    # Add more aliases as needed
}

def get_canonical_region_name(raw_name):
    if not raw_name:
        return raw_name
    # Normalize whitespace, remove parentheses and other artifacts, and convert to uppercase
    key = str(raw_name).upper()
    key = re.sub(r'[\r\n\t]', ' ', key)  # Replace newline/tab with space
    key = re.sub(r'[()]', '', key)  # Remove parentheses
    key = key.replace('(MU)', '').replace('(MW)', '').strip()
    key = re.sub(r'\s+', ' ', key)  # Condense multiple spaces to one
    
    logger.debug(f"Canonical region lookup: raw='{raw_name}', final_key='{key}'")
    return REGION_ALIAS.get(key, raw_name)

def get_canonical_generation_source(raw_name):
    key = raw_name.upper().replace('(MU)', '').replace('(MW)', '').replace('  ', ' ')
    key = key.strip()
    # Remove special characters from start and end, but keep parentheses
    key = re.sub(r'^[^A-Z0-9(\)]+|[^A-Z0-9(\)]+$', '', key)
    return GEN_SOURCE_CANONICAL.get(key, (raw_name, None))  # fallback to raw_name if not found

def get_canonical_country_name(raw_name):
    if not raw_name:
        return raw_name
    key = raw_name.upper().replace('(MU)', '').replace('(MW)', '').replace('  ', ' ')
    key = key.strip()
    key = re.sub(r'^[^A-Z0-9(\)]+|[^A-Z0-9(\)]+$', '', key)
    canonical = COUNTRY_ALIAS.get(key, raw_name)
    logger.debug(f"Country mapping: '{raw_name}' -> '{key}' -> '{canonical}'")
    return canonical

def check_database_exists():
    """Check if the database file exists"""
    return os.path.exists(DATABASE_NAME)

def verify_database_schema(conn):
    """
    Verify that the database has the required tables.
    Returns True if all required tables exist, False otherwise.
    """
    required_tables = [
        'DimUnits', 'MetaTableColumnUnits', 'DimDates', 'DimRegions', 
        'DimStates', 'DimCountries', 'DimGenerationSources', 
        'DimTransmissionLines', 'DimExchangeMechanisms',
        'FactAllIndiaDailySummary', 'FactDailyGenerationBreakdown',
        'FactStateDailyEnergy', 'FactCountryDailyExchange',
        'FactTransmissionLinkFlow', 'FactInternationalTransmissionLinkFlow',
        'FactTransnationalExchangeDetail', 'FactTimeBlockPowerData',
        'FactTimeBlockGeneration'
    ]
    
    cursor = conn.cursor()
    try:
        # Get list of existing tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = {row[0] for row in cursor.fetchall()}
        
        # Check if all required tables exist
        missing_tables = set(required_tables) - existing_tables
        if missing_tables:
            logger.error(f"Missing required tables: {missing_tables}")
            return False
        return True
    except sqlite3.Error as e:
        logger.error(f"Error verifying database schema: {e}")
        return False

def create_connection(db_file):
    """Create a database connection to a SQLite database"""
    if not check_database_exists():
        logger.error(f"Database file {db_file} does not exist")
        return None
        
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA foreign_keys = ON;")
        
        # Verify schema
        if not verify_database_schema(conn):
            logger.error("Database schema verification failed")
            conn.close()
            return None
            
        logger.info(f"Successfully connected to database {db_file}")
        return conn
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database: {e}")
        return None

def get_or_insert_dimension_id(conn, table_name, value_dict, id_column_name=None):
    """
    Get or insert a dimension ID. For DimDates, allows insertion of new dates.
    For all other dimension tables, only performs SELECT operations.
    
    Args:
        conn: SQLite connection
        table_name: Name of the dimension table
        value_dict: Dictionary of column names and values to look up/insert
        id_column_name: Name of the ID column (defaults to table_name + 'ID')
    """
    if id_column_name is None:
        # Mapping of table names to their correct ID column names
        id_column_mapping = {
            'DimDates': 'DateID',
            'DimRegions': 'RegionID',
            'DimStates': 'StateID',
            'DimCountries': 'CountryID',
            'DimGenerationSources': 'GenerationSourceID',
            'DimTransmissionLines': 'LineID',
            'DimExchangeMechanisms': 'MechanismID',
            'DimUnits': 'UnitID'
        }
        id_column_name = id_column_mapping.get(table_name)
        if id_column_name is None:
            raise ValueError(f"No ID column mapping defined for table {table_name}")
    
    cursor = conn.cursor()
    
    # Build WHERE clause for checking existing record
    where_clause = " AND ".join([f"{col} = ?" for col in value_dict.keys()])
    values = tuple(value_dict.values())
    
    # First try to get existing ID
    cursor.execute(f"SELECT {id_column_name} FROM {table_name} WHERE {where_clause}", values)
    result = cursor.fetchone()
    
    if result:
        return result[0]
    
    # Only allow insertion for DimDates
    if table_name == 'DimDates':
        try:
            columns = ", ".join(value_dict.keys())
            placeholders = ", ".join(["?" for _ in value_dict])
            cursor.execute(
                f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
                values
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError as e:
            logger.warning(f"Integrity error while inserting into {table_name}: {e}")
            # Try to get the ID again in case of race condition
            cursor.execute(f"SELECT {id_column_name} FROM {table_name} WHERE {where_clause}", values)
            result = cursor.fetchone()
            return result[0] if result else None
    else:
        logger.warning(f"No matching record found in {table_name} for values: {value_dict}")
        return None

def insert_date_dimension(conn, date):
    """Insert a date into DimDates table"""
    date_obj = pd.to_datetime(date).date()
    date_dict = {
        'ActualDate': date_obj.strftime('%Y-%m-%d'),
        'DayOfWeek': date_obj.strftime('%A'),
        'DayOfMonth': date_obj.day,
        'Month': date_obj.month,
        'Quarter': (date_obj.month - 1) // 3 + 1,
        'Year': date_obj.year
    }
    return get_or_insert_dimension_id(conn, 'DimDates', date_dict)

def populate_fact_all_india_summary(conn, df, date_to_id_map):
    """Insert data into FactAllIndiaDailySummary and related tables using composite keys."""
    cursor = conn.cursor()
    
    # Log the actual DataFrame structure
    logger.info("DataFrame Info for All India Summary:")
    logger.info(f"Columns: {df.columns.tolist()}")
    logger.info(f"First row: {df.iloc[0].to_dict() if not df.empty else 'Empty DataFrame'}")
    
    def clean_numeric_value(value):
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.replace('MW', '').replace('MU', '').replace('%', '').strip()
                if value.upper() in ['N', 'NA', 'N.A.', 'N/A', '']:
                    return None
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert value '{value}' to numeric")
            return None
    
    def clean_time_value(value):
        """Clean and format time value"""
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.strip().replace('\r', '').replace('\n', '')
                if len(value.split(':')) == 2:
                    value = value + ':00'
            return value
        except Exception as e:
            logger.warning(f"Could not clean time value '{value}': {e}")
            return None
    
    # Map of actual DataFrame columns to database columns
    column_mapping = {
        'Share of RES in total generation (%)': ('ShareRESInTotalGeneration', '%', clean_numeric_value),
        'Demand Met during Evening Peak hrs(MW) (at\r20:00 hrs; from RLDCs)': ('PeakDemandMet', 'MW', clean_numeric_value),
        'Peak Shortage (MW)': ('PeakShortage', 'MW', clean_numeric_value),
        'Energy Met (MU)': ('EnergyMet', 'MU', clean_numeric_value),
        'Energy Shortage (MU)': ('EnergyShortage', 'MU', clean_numeric_value),
        'Maximum Demand Met During the Day (MW)\r(From NLDC SCADA)': ('MaxDemandSCADA', 'MW', clean_numeric_value),
        'Time Of Maximum Demand Met': ('TimeOfMaxDemandMet', None, clean_time_value),
        'Schedule(MU)': ('ScheduleDrawal', 'MU', clean_numeric_value),
        'Actual(MU)': ('ActualDrawal', 'MU', clean_numeric_value),
        'O/D/U/D(MU)': ('OverUnderDrawal', 'MU', clean_numeric_value),
        'FVI': ('FrequencyViolationIndex', None, clean_numeric_value),
        'Frequency (<49.7)': ('DurationFrequencyBelow49_7', '%', clean_numeric_value),
        'Frequency (49.7 - 49.8)': ('DurationFrequency_49_7_to_49_8', '%', clean_numeric_value),
        'Frequency (49.8 - 49.9)': ('DurationFrequency_49_8_to_49_9', '%', clean_numeric_value),
        'Frequency (< 49.9)': ('DurationFrequencyBelow49_9', '%', clean_numeric_value),
        'Frequency (49.9 - 50.05)': ('DurationFrequency_49_9_to_50_05', '%', clean_numeric_value),
        'Frequency (> 50.05)': ('DurationFrequencyAbove50_05', '%', clean_numeric_value),
        'Region DDF': ('RegionDDF', '%', clean_numeric_value),
        'States DDF': ('StatesDDF', '%', clean_numeric_value),
        'SolarHR Max Demand': ('SolarHRMaxDemand', 'MW', clean_numeric_value),
        'SolarHR Max Demand Time': ('SolarHRMaxDemandTime', 'HH:MM:SS', clean_time_value),
        'SolarHR Shortage': ('SolarHRShortage', 'MW', clean_numeric_value),
        'Non-SolarHR Max Demand': ('NonSolarHRMaxDemand', 'MW', clean_numeric_value),
        'Non-SolarHR Max Demand Time': ('NonSolarHRMaxDemandTime', 'HH:MM:SS', clean_time_value),
        'Non-SolarHR Shortage': ('NonSolarHRShortage', 'MW', clean_numeric_value),
    }
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            
            # Always use canonical region name
            region_name = get_canonical_region_name(row['Table Name'])

            region_id = get_or_insert_dimension_id(
                conn,
                'DimRegions',
                {'RegionName': region_name}
            )
            if region_id is None:
                logger.error(f"Region '{region_name}' not found in DimRegions. Skipping row.")
                continue
            
            # Build summary data with proper cleaning
            summary_data = {
                'DateID': date_id,
                'RegionID': region_id
            }
            
            for df_col, (db_col, unit, clean_func) in column_mapping.items():
                if df_col in row:
                    value = clean_func(row[df_col])
                    summary_data[db_col] = value
                else:
                    logger.debug(f"Column '{df_col}' not found in DataFrame")
            summary_data = {k: v for k, v in summary_data.items() if v is not None or k == 'RegionID'}
            if len(summary_data) > 2:
                columns = ", ".join(summary_data.keys())
                placeholders = ", ".join(["?" for _ in summary_data])
                cursor.execute(
                    f"INSERT OR REPLACE INTO FactAllIndiaDailySummary ({columns}) VALUES ({placeholders})",
                    tuple(summary_data.values())
                )
                # Insert generation breakdown if available
                generation_columns = ['Coal', 'Lignite', 'Hydro', 'Nuclear', 'Gas, Naptha & Diesel', 'RES (Wind, Solar, Biomass & Others)']
                for source in generation_columns:
                    if source in row and pd.notna(row[source]):
                        canonical, category = get_canonical_generation_source(source)
                        source_id = get_or_insert_dimension_id(
                            conn, 
                            'DimGenerationSources',
                            {'SourceName': canonical, 'SourceCategory': category}
                        )
                        if source_id:
                            amount = clean_numeric_value(row[source])
                            if amount is not None:
                                # Insert using composite key
                                cursor.execute(
                                    """
                                    INSERT OR REPLACE INTO FactDailyGenerationBreakdown (DateID, RegionID, GenerationSourceID, GenerationAmount)
                                    VALUES (?, ?, ?, ?)
                                    """,
                                    (date_id, region_id, source_id, amount)
                                )
            else:
                logger.warning(f"Skipping row with insufficient data: {date_id}, Region: {region_name}")
        except Exception as e:
            logger.error(f"Error processing row in FactAllIndiaDailySummary: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
    conn.commit()
    logger.info("FactAllIndiaDailySummary populated successfully")

def populate_fact_state_energy(conn, df, date_to_id_map):
    """
    Insert data into FactStateDailyEnergy table using composite keys (DateID, StateID).
    """
    if df.empty:
        logger.warning("Empty DataFrame provided for FactStateDailyEnergy")
        return

    cursor = None
    try:
        cursor = conn.cursor()
        
        # Log the actual DataFrame structure
        logger.info("DataFrame Info for State Energy:")
        logger.info(f"Columns: {df.columns.tolist()}")
        logger.info(f"Shape: {df.shape}")
        logger.info(f"First row: {df.iloc[0].to_dict() if not df.empty else 'Empty DataFrame'}")
        
        def clean_numeric_value(value):
            if pd.isna(value):
                return None
            try:
                if isinstance(value, str):
                    # Remove units and clean the string
                    value = value.replace('MW', '').replace('MU', '').replace('%', '').strip()
                    # Handle various forms of NULL/NA values
                    if value.upper() in ['N', 'NA', 'N.A.', 'N/A', '', '-']:
                        return None
                return float(value)
            except (ValueError, TypeError):
                logger.warning(f"Could not convert value '{value}' to numeric")
                return None
        
        # Map of actual DataFrame columns to database columns
        column_mapping = {
            'Maximum Demand (MW)': ('MaximumDemand', 'MW', clean_numeric_value),
            'Shortage (MW)': ('Shortage', 'MW', clean_numeric_value),
            'Energy Met (MU)': ('EnergyMet', 'MU', clean_numeric_value),
            'Drawal Schedule (MU)': ('DrawalSchedule', 'MU', clean_numeric_value),
            'OD(+)/UD(-) (MU)': ('OverUnderDrawal', 'MU', clean_numeric_value),
            'Max OD (MW)': ('MaxOverDrawal', 'MW', clean_numeric_value),
            'Energy Shortage (MU)': ('EnergyShortage', 'MU', clean_numeric_value)
        }
        
        # Verify required columns exist
        required_columns = ['Date', 'States'] + list(column_mapping.keys())
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns: {missing_columns}")
            return

        # Track statistics for logging
        stats = {
            'total_rows': len(df),
            'processed_rows': 0,
            'skipped_rows': 0,
            'error_rows': 0
        }
        
        for idx, row in df.iterrows():
            try:
                # Get DateID from the mapping
                try:
                    date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
                except (KeyError, ValueError) as e:
                    logger.warning(f"Invalid or missing date for row {idx}: {row['Date']}")
                    stats['skipped_rows'] += 1
                    continue
                
                # Lookup StateID from DimStates table
                cursor.execute(
                    "SELECT StateID FROM DimStates WHERE StateName = ?",
                    (row['States'],)
                )
                state_result = cursor.fetchone()
                
                if not state_result:
                    logger.warning(f"State not found in DimStates: {row['States']}")
                    stats['skipped_rows'] += 1
                    continue
                    
                state_id = state_result[0]
                
                # Build the data dict for insertion
                state_data = {'DateID': date_id, 'StateID': state_id}
                
                # Process each column according to the mapping
                for df_col, (db_col, unit, clean_func) in column_mapping.items():
                    if df_col in row:
                        value = clean_func(row[df_col])
                        if value is not None:
                            state_data[db_col] = value
                
                # Only proceed if we have more than just DateID and StateID
                if len(state_data) > 2:
                    columns = ", ".join(state_data.keys())
                    placeholders = ", ".join(["?" for _ in state_data])
                    values = tuple(state_data.values())
                    
                    try:
                        cursor.execute(
                            f"INSERT OR REPLACE INTO FactStateDailyEnergy ({columns}) VALUES ({placeholders})",
                            values
                        )
                        stats['processed_rows'] += 1
                    except sqlite3.IntegrityError as e:
                        logger.error(f"Integrity error inserting state data: {e}")
                        logger.error(f"Data: {state_data}")
                        stats['error_rows'] += 1
                        continue
                else:
                    logger.warning(f"Skipping row {idx} for state {row['States']} - insufficient data")
                    stats['skipped_rows'] += 1
            except Exception as e:
                logger.error(f"Error processing row {idx} in FactStateDailyEnergy: {e}")
                logger.error(f"Row data: {row.to_dict()}")
                stats['error_rows'] += 1
                continue
        
        # Commit the transaction
        conn.commit()
        
        # Log final statistics
        logger.info(f"FactStateDailyEnergy population completed:")
        logger.info(f"Total rows: {stats['total_rows']}")
        logger.info(f"Successfully processed: {stats['processed_rows']}")
        logger.info(f"Skipped rows: {stats['skipped_rows']}")
        logger.info(f"Error rows: {stats['error_rows']}")
    except Exception as e:
        logger.error(f"Unexpected error in populate_fact_state_energy: {e}")
        if cursor:
            conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()

def clean_circuit_value(value):
    """Clean and convert circuit value, handling NaN values"""
    if pd.isna(value):
        return None
    try:
        if isinstance(value, str):
            value = value.strip()
            if value.upper() in ['N', 'NA', 'N.A.', 'N/A', '', '-']:
                return None
        # Convert to float first to handle decimal strings, then to int
        return int(float(value))
    except (ValueError, TypeError):
        logger.warning(f"Could not convert circuit value '{value}' to integer")
        return None

def extract_voltage_and_circuits(line_name):
    # Extract voltage level (e.g., 400KV, 220 KV, 765kV, etc.)
    voltage_match = re.search(r'(\d{2,4}\s?KV)', line_name, re.IGNORECASE)
    voltage = voltage_match.group(1).replace(' ', '').upper() if voltage_match else None
    # Extract number of circuits (e.g., 1&2, 2C, 1C, etc.)
    circuit_match = re.search(r'(\d+\s?&\s?\d+|\d+C?)', line_name)
    circuits = circuit_match.group(1).replace(' ', '') if circuit_match else None
    # Remove voltage and circuit info from line name
    cleaned_name = line_name
    if voltage:
        cleaned_name = re.sub(re.escape(voltage), '', cleaned_name, flags=re.IGNORECASE)
    if circuits:
        cleaned_name = re.sub(re.escape(circuits), '', cleaned_name, flags=re.IGNORECASE)
    cleaned_name = re.sub(r'\s+', ' ', cleaned_name).strip().upper()
    return cleaned_name, voltage, circuits

def populate_fact_transmission_link_flow(conn, df, date_to_id_map):
    """Insert data into FactTransmissionLinkFlow table using composite keys (DateID, LineID)."""
    cursor = conn.cursor()
    
    # Log the actual DataFrame structure
    logger.info("DataFrame Info for Transmission Link Flow:")
    logger.info(f"Columns: {df.columns.tolist()}")
    logger.info(f"First row: {df.iloc[0].to_dict() if not df.empty else 'Empty DataFrame'}")
    
    def clean_numeric_value(value):
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.replace('MW', '').replace('MU', '').replace('%', '').strip()
                if value.upper() in ['N', 'NA', 'N.A.', 'N/A', '']:
                    return None
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert value '{value}' to numeric")
            return None
    
    # Map of actual DataFrame columns to database columns
    column_mapping = {
        'Max Import (MW)': ('MaxImport', 'MW', clean_numeric_value),
        'Max Export (MW)': ('MaxExport', 'MW', clean_numeric_value),
        'Import (MU)': ('ImportEnergy', 'MU', clean_numeric_value),
        'Export (MU)': ('ExportEnergy', 'MU', clean_numeric_value),
        'NET Import (MU)': ('NetImportEnergy', 'MU', clean_numeric_value)
    }
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            line_identifier = row['Line Details']
            cursor.execute("SELECT LineID FROM DimTransmissionLines WHERE LineIdentifier = ?", (line_identifier,))
            result = cursor.fetchone()
            if result:
                line_id = result[0]
            else:
                voltage_level = row.get('Voltage Level') if 'Voltage Level' in row else None
                num_circuits = row.get('No. of Circuit') if 'No. of Circuit' in row else None
                cursor.execute(
                    "INSERT INTO DimTransmissionLines (LineIdentifier, VoltageLevel_kV, NumberOfCircuits) VALUES (?, ?, ?)",
                    (line_identifier, voltage_level, num_circuits)
                )
                line_id = cursor.lastrowid
                logger.info(f"Inserted new line into DimTransmissionLines: {line_identifier}")
            link_data = {'DateID': date_id, 'LineID': line_id}
            for df_col, (db_col, unit, clean_func) in column_mapping.items():
                if df_col in row:
                    value = clean_func(row[df_col])
                    link_data[db_col] = value
                else:
                    logger.debug(f"Column '{df_col}' not found in DataFrame")
            
            # Remove None values
            link_data = {k: v for k, v in link_data.items() if v is not None}
            if len(link_data) > 2:
                columns = ", ".join(link_data.keys())
                placeholders = ", ".join(["?" for _ in link_data])
                cursor.execute(
                    f"INSERT OR REPLACE INTO FactTransmissionLinkFlow ({columns}) VALUES ({placeholders})",
                    tuple(link_data.values())
                )
        except Exception as e:
            logger.error(f"Error processing row in FactTransmissionLinkFlow: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
            
    conn.commit()
    logger.info("FactTransmissionLinkFlow populated successfully")

def populate_fact_time_block_power(conn, df, date_to_id_map):
    """Insert data into FactTimeBlockPowerData and related tables using composite keys (DateID, BlockTime)."""
    cursor = conn.cursor()
    
    # Log the actual DataFrame structure
    logger.info("DataFrame Info for Time Block Power:")
    logger.info(f"Columns: {df.columns.tolist()}")
    logger.info(f"First row: {df.iloc[0].to_dict() if not df.empty else 'Empty DataFrame'}")
    
    def clean_numeric_value(value):
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.replace('MW', '').replace('MU', '').replace('%', '').strip()
                if value.upper() in ['N', 'NA', 'N.A.', 'N/A', '']:
                    return None
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert value '{value}' to numeric")
            return None
    
    def clean_time_value(value):
        """Clean and format time value"""
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.strip().replace('\r', '').replace('\n', '')
                if len(value.split(':')) == 2:
                    value = value + ':00'
            return value
        except Exception as e:
            logger.warning(f"Could not clean time value '{value}': {e}")
            return None
    
    # Map of actual DataFrame columns to database columns
    column_mapping = {
        'TIME': ('BlockTime', None, clean_time_value),
        'FREQUENCY (Hz)': ('Frequency', 'Hz', clean_numeric_value),
        'DEMAND MET (MW)': ('DemandMet', 'MW', clean_numeric_value),
        'NET DEMAND MET (MW)': ('NetDemandMet', 'MW', clean_numeric_value),
        'TOTAL GENERATION (MW)': ('TotalGeneration', 'MW', clean_numeric_value),
        'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export': ('NetTransnationalExchange', 'MW', clean_numeric_value)
    }
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            block_time = clean_time_value(row['TIME']) if 'TIME' in row else None
            if not block_time:
                logger.warning(f"Missing or invalid BlockTime for row: {row.to_dict()}")
                continue
            block_data = {'DateID': date_id, 'BlockTime': block_time}
            for df_col, (db_col, unit, clean_func) in column_mapping.items():
                if df_col in row:
                    value = clean_func(row[df_col])
                    block_data[db_col] = value
                else:
                    logger.debug(f"Column '{df_col}' not found in DataFrame")
            
            # Remove None values
            block_data = {k: v for k, v in block_data.items() if v is not None}
            if len(block_data) > 2:
                columns = ", ".join(block_data.keys())
                placeholders = ", ".join(["?" for _ in block_data])
                cursor.execute(
                    f"INSERT OR REPLACE INTO FactTimeBlockPowerData ({columns}) VALUES ({placeholders})",
                    tuple(block_data.values())
                )
                # Insert generation breakdown if available
                generation_columns = [col for col in df.columns if '(MW)' in col and col not in [
                    'DEMAND MET (MW)', 'NET DEMAND MET (MW)', 'TOTAL GENERATION (MW)', 
                    'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export'
                ]]
                
                for col in generation_columns:
                    base_name = col.split(' (')[0].strip().upper()
                    canonical, category = get_canonical_generation_source(base_name)
                    if not canonical:
                        logger.warning(f"Unknown generation source in blockwise: {base_name}")
                        continue
                    source_id = get_or_insert_dimension_id(
                        conn,
                        'DimGenerationSources',
                        {'SourceName': canonical, 'SourceCategory': category}
                    )
                    if source_id and pd.notna(row[col]):
                        amount = clean_numeric_value(row[col])
                        if amount is not None:
                            cursor.execute(
                                '''
                                INSERT OR REPLACE INTO FactTimeBlockGeneration 
                                (DateID, BlockTime, GenerationSourceID, GenerationOutput)
                                VALUES (?, ?, ?, ?)
                                ''', (date_id, block_time, source_id, amount)
                            )
        except Exception as e:
            logger.error(f"Error processing row in FactTimeBlockPowerData: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
    
    conn.commit()
    logger.info("FactTimeBlockPowerData populated successfully")

def populate_fact_country_daily_exchange(conn, df, date_to_id_map):
    """Insert data into FactCountryDailyExchange table from wide format (one row, multiple country columns) using composite keys."""
    cursor = conn.cursor()
    logger.info("DataFrame Info for Country Daily Exchange:")
    logger.info(f"Columns: {df.columns.tolist()}")
    logger.info(f"First row: {df.iloc[0].to_dict() if not df.empty else 'Empty DataFrame'}")

    def clean_numeric_value(value):
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.replace('MW', '').replace('MU', '').replace('%', '').strip()
                if value.upper() in ['N', 'NA', 'N.A.', 'N/A', '']:
                    return None
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert value '{value}' to numeric")
            return None

    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            # Loop through all columns to find country (MU) columns
            for col in row.index:
                if col.endswith('(MU)'):
                    # Extract country name (remove ' (MU)' and possible extra spaces)
                    country_name = col.replace('(MU)', '').strip()
                    # Special handling for Godda (Bangladesh)
                    if 'Godda' in country_name:
                        country_name = 'Godda (Bangladesh)'
                    # Remove trailing/leading spaces
                    country_name = country_name.strip()
                    # Get or insert country
                    country_id = get_or_insert_dimension_id(
                        conn,
                        'DimCountries',
                        {'CountryName': country_name}
                    )
                    if not country_id:
                        logger.warning(f"Could not get/insert country: {country_name}")
                        continue
                    # Get MU value
                    mu_value = clean_numeric_value(row[col])
                    # Find corresponding Peak (MW) column
                    peak_col = col.replace('(MU)', 'Peak (MW)').replace('  ', ' ').strip()
                    peak_value = None
                    if peak_col in row:
                        peak_value = clean_numeric_value(row[peak_col])
                    # Insert into FactCountryDailyExchange
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO FactCountryDailyExchange (DateID, CountryID, TotalEnergyExchanged, PeakExchange)
                        VALUES (?, ?, ?, ?)
                        """,
                        (date_id, country_id, mu_value, peak_value)
                    )
        except Exception as e:
            logger.error(f"Error processing row in FactCountryDailyExchange: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
    conn.commit()
    logger.info("FactCountryDailyExchange populated successfully")

def standardize_line_name(line_name):
    if not line_name:
        return line_name
    return line_name.strip().upper()

def populate_fact_line_congestion(conn, df, date_to_id_map):
    """Insert data into FactInternationalTransmissionLinkFlow table using composite keys (DateID, LineID)."""
    cursor = conn.cursor()
    
    # Log the actual DataFrame structure
    logger.info("DataFrame Info for Line Congestion:")
    logger.info(f"Columns: {df.columns.tolist()}")
    logger.info(f"First row: {df.iloc[0].to_dict() if not df.empty else 'Empty DataFrame'}")
    
    def clean_numeric_value(value):
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.replace('MW', '').replace('MU', '').replace('%', '').strip()
                if value.upper() in ['N', 'NA', 'N.A.', 'N/A', '']:
                    return None
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert value '{value}' to numeric")
            return None
    
    # Map of actual DataFrame columns to database columns
    column_mapping = {
        'Max (MW)': ('MaxLoading', 'MW', clean_numeric_value),
        'Min (MW)': ('MinLoading', 'MW', clean_numeric_value),
        'Avg (MW)': ('AvgLoading', 'MW', clean_numeric_value),
        'Energy Exchange (MU)': ('EnergyExchanged', 'MU', clean_numeric_value)
    }
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            
            # Extract voltage and circuit info from line name
            line_identifier = row['Line Name']
            line_identifier_clean, voltage_level, num_circuits = extract_voltage_and_circuits(line_identifier)
            cursor.execute("SELECT LineID FROM DimTransmissionLines WHERE LineIdentifier = ?", (line_identifier_clean,))
            result = cursor.fetchone()
            if result:
                line_id = result[0]
            else:
                # Special handling: In DataFrame 4, 'State' column contains country names, not Indian states
                country_id_from_state = None
                if 'State' in row and pd.notna(row['State']):
                    country_name_from_state = get_canonical_country_name(row['State'])
                    country_id_from_state = get_or_insert_dimension_id(
                        conn,
                        'DimCountries',
                        {'CountryName': country_name_from_state}
                    )
                    if country_id_from_state is None:
                        logger.warning(f"Country not found in DimCountries (from 'State' column): {country_name_from_state}")
                        continue
                cursor.execute(
                    "INSERT INTO DimTransmissionLines (LineIdentifier, VoltageLevel_kV, NumberOfCircuits, CountryID) VALUES (?, ?, ?, ?)",
                    (line_identifier_clean, voltage_level, num_circuits, country_id_from_state)
                )
                line_id = cursor.lastrowid
                logger.info(f"Inserted new line into DimTransmissionLines: {line_identifier_clean}")
            
            # In DataFrame 4, 'State' column contains country names, not Indian states
            # So we don't need to look up StateID from DimStates
            state_id = None
            
            # Get region ID if available
            region_id = None
            if 'Region' in row and pd.notna(row['Region']):
                region_name = get_canonical_region_name(row['Region'])
                region_id = get_or_insert_dimension_id(
                    conn,
                    'DimRegions',
                    {'RegionName': region_name}
                )
                if region_id is None:
                    logger.warning(f"Region not found in DimRegions: {region_name}")
                    continue
            
            # Get country ID from 'State' column (which contains country names in DataFrame 4)
            country_id = None
            if 'State' in row and pd.notna(row['State']):
                country_name = get_canonical_country_name(row['State'])
                country_id = get_or_insert_dimension_id(
                    conn,
                    'DimCountries',
                    {'CountryName': country_name}
                )
                if country_id is None:
                    logger.warning(f"Country not found in DimCountries: {country_name} (from 'State' column)")
                    continue
            congestion_data = {'DateID': date_id, 'LineID': line_id}
            
            if state_id:
                congestion_data['StateID'] = state_id
            if region_id:
                congestion_data['RegionID'] = region_id
            if country_id:
                congestion_data['CountryID'] = country_id
            for df_col, (db_col, unit, clean_func) in column_mapping.items():
                if df_col in row:
                    value = clean_func(row[df_col])
                    if value is not None:
                        congestion_data[db_col] = value
                else:
                    logger.debug(f"Column '{df_col}' not found in DataFrame")
            
            # Remove None values
            congestion_data = {k: v for k, v in congestion_data.items() if v is not None}
            if len(congestion_data) > 2:
                columns = ", ".join(congestion_data.keys())
                placeholders = ", ".join(["?" for _ in congestion_data])
                cursor.execute(
                    f"INSERT OR REPLACE INTO FactInternationalTransmissionLinkFlow ({columns}) VALUES ({placeholders})",
                    tuple(congestion_data.values())
                )
            
        except Exception as e:
            logger.error(f"Error processing row in FactInternationalTransmissionLinkFlow: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
            
    conn.commit()
    logger.info("FactInternationalTransmissionLinkFlow populated successfully")

def populate_fact_transnational_exchange_detail(conn, df, date_to_id_map):
    """Insert data into FactTransnationalExchangeDetail table using composite keys (DateID, CountryID, MechanismID)."""
    cursor = conn.cursor()
    
    # Log the actual DataFrame structure
    logger.info("DataFrame Info for Transnational Exchange Detail:")
    logger.info(f"Columns: {df.columns.tolist()}")
    logger.info(f"First row: {df.iloc[0].to_dict() if not df.empty else 'Empty DataFrame'}")
    
    def clean_numeric_value(value):
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.replace('MW', '').replace('MU', '').replace('%', '').strip()
                if value.upper() in ['N', 'NA', 'N.A.', 'N/A', '']:
                    return None
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert value '{value}' to numeric")
            return None
    
    # Exchange mechanism mapping
    mechanism_mapping = {
        'PPA': 'PPA',
        'Bilateral': 'Bilateral',
        'DAM IEX': 'DAM IEX',
        'DAM PXIL': 'DAM PXIL',
        'DAM HPX': 'DAM HPX',
        'RTM IEX': 'RTM IEX',
        'RTM PXIL': 'RTM PXIL',
        'RTM HPX': 'RTM HPX'
    }
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            
            # Get or insert country using canonical mapping
            country_name = get_canonical_country_name(row['Country'])
            country_id = get_or_insert_dimension_id(
                conn,
                'DimCountries',
                {'CountryName': country_name}
            )
            if not country_id:
                logger.warning(f"Could not get/insert country: {country_name} (original: {row['Country']})")
                continue
            
            # Process each exchange mechanism
            for mechanism_name, db_mechanism_name in mechanism_mapping.items():
                if mechanism_name in row and pd.notna(row[mechanism_name]):
                    # Get or insert mechanism
                    mechanism_id = get_or_insert_dimension_id(
                        conn,
                        'DimExchangeMechanisms',
                        {'MechanismName': db_mechanism_name}
                    )
                    if mechanism_id:
                        exchange_value = clean_numeric_value(row[mechanism_name])
                        if exchange_value is not None:
                            # Determine exchange direction based on Type column
                            exchange_direction = row.get('Type', '')
                            cursor.execute(
                                '''
                                INSERT OR REPLACE INTO FactTransnationalExchangeDetail 
                                (DateID, CountryID, MechanismID, ExchangeDirection, ExchangeValue)
                                VALUES (?, ?, ?, ?, ?)
                                ''', (date_id, country_id, mechanism_id, exchange_direction, exchange_value)
                            )
        except Exception as e:
            logger.error(f"Error processing row in FactTransnationalExchangeDetail: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
            
    conn.commit()
    logger.info("FactTransnationalExchangeDetail populated successfully")

def ensure_all_regions_countries(conn, dataframes_list):
    cursor = conn.cursor()
    # Canonical region names allowed in DimRegions
    allowed_regions = set(REGION_ALIAS.values())
    allowed_regions.add("India")  # If not already present

    regions = set()
    countries = set()
    for df in dataframes_list:
        if df is not None and not df.empty:
            if 'Region' in df.columns:
                # Filter out garbage values before mapping
                clean_regions = df['Region'].dropna()
                clean_regions = clean_regions[~clean_regions.str.contains('States', case=False, na=False)]
                regions.update(clean_regions.map(get_canonical_region_name))
            if 'Table Name' in df.columns:
                regions.update(df['Table Name'].dropna().map(get_canonical_region_name))
            if 'Country' in df.columns:
                countries.update(df['Country'].dropna().map(get_canonical_country_name))
    # Only insert allowed canonical regions
    for region in regions:
        if region in allowed_regions:
            cursor.execute("SELECT RegionID FROM DimRegions WHERE RegionName = ?", (region,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO DimRegions (RegionName) VALUES (?)", (region,))
                logger.info(f"Inserted missing region into DimRegions: {region}")
        elif region: # Log warning only if region is not an empty string
            logger.warning(f"Skipping non-canonical region: '{region}'")
    # Insert missing countries
    for country in countries:
        cursor.execute("SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO DimCountries (CountryName) VALUES (?)", (country,))
            logger.info(f"Inserted missing country into DimCountries: {country}")
    conn.commit()

def automate_data_insertion_from_list(dataframes_list, db_name=DATABASE_NAME):
    """
    Main function to automate data insertion from a list of DataFrames.
    
    Args:
        dataframes_list: List of pandas DataFrames in a known order:
            [0] - All India Summary (Regional Summary)
            [1] - State-wise Data
            [2] - International Net (Country Daily Exchange)
            [3] - Inter-Region Data (Transmission Link Flow)
            [4] - International Exchange (Line Congestion)
            [5] - Exchange (Transnational Exchange Detail)
            [6] - Time Block Data
    """
    logger.info(f"Airflow task: Starting data insertion into {db_name} for {len(dataframes_list)} DataFrames.")
    if not dataframes_list:
        logger.error("No DataFrames provided for insertion")
        return

    conn = create_connection(db_name)
    if not conn:
        logger.error("Failed to create database connection. Aborting insertion.")
        return

    try:
        # Get all unique dates from dataframes
        all_dates = set()
        for df in dataframes_list:
            if df is not None and not df.empty and 'Date' in df.columns:
                all_dates.update(pd.to_datetime(df['Date']).dt.date)
        
        # Create date mapping
        date_to_id_map = {
            date: insert_date_dimension(conn, date)
            for date in sorted(all_dates)
        }
        
        # Process each dataframe
        for i, df in enumerate(dataframes_list):
            if df is None or df.empty:
                logger.warning(f"Skipping empty DataFrame at index {i}")
                continue
                
            try:
                if i == 0:  # All India Summary (Regional Summary)
                    logger.info(f"Processing DataFrame {i}: All India Summary")
                    populate_fact_all_india_summary(conn, df, date_to_id_map)
                elif i == 1:  # State-wise Data
                    logger.info(f"Processing DataFrame {i}: State-wise Data")
                    populate_fact_state_energy(conn, df, date_to_id_map)
                elif i == 2:  # International Net (Country Daily Exchange)
                    logger.info(f"Processing DataFrame {i}: International Net")
                    populate_fact_country_daily_exchange(conn, df, date_to_id_map)
                elif i == 3:  # Inter-Region Data (Transmission Link Flow)
                    logger.info(f"Processing DataFrame {i}: Inter-Region Data")
                    populate_fact_transmission_link_flow(conn, df, date_to_id_map)
                elif i == 4:  # International Exchange (Line Congestion)
                    logger.info(f"Processing DataFrame {i}: International Exchange")
                    populate_fact_line_congestion(conn, df, date_to_id_map)
                elif i == 5:  # Exchange (Transnational Exchange Detail)
                    logger.info(f"Processing DataFrame {i}: Exchange")
                    populate_fact_transnational_exchange_detail(conn, df, date_to_id_map)
                elif i == 6:  # Time Block Data
                    logger.info(f"Processing DataFrame {i}: Time Block Data")
                    populate_fact_time_block_power(conn, df, date_to_id_map)
                else:
                    logger.warning(f"Unknown DataFrame type at index {i}")
            except Exception as e:
                logger.error(f"Error processing DataFrame at index {i}: {e}")
                continue
        
        # Ensure all regions and countries are present in dimension tables
        ensure_all_regions_countries(conn, dataframes_list)
        
        logger.info(f"Airflow task: Data insertion into {db_name} completed.")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error during data insertion: {str(e)}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    try:
        # Get DataFrames from PDF parser
        dataframes_list = parser.main_pdf_processing_logic(pdf_path="sample input/19.04.25_NLDC_PSP.pdf")
        if dataframes_list:
            automate_data_insertion_from_list(dataframes_list)
        else:
            logger.error("No DataFrames returned from PDF parser")
    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")