import sqlite3
import pandas as pd
import numpy as np
import logging
import os
from datetime import datetime
import PDFparser_Gemini as parser

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATABASE_NAME = "/usr/local/airflow/data/power_data.db"

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
        'FactTransmissionLinkFlow', 'FactLineCongestion',
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
    """Insert data into FactAllIndiaDailySummary and related tables"""
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
    
    # Region mapping
    region_mapping = {
        'NR': 'Northern Region',
        'WR': 'Western Region',
        'SR': 'Southern Region',
        'ER': 'Eastern Region',
        'NER': 'North Eastern Region',
        'India': 'India'  # All-India summary will have NULL RegionID
    }
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            
            # Get region ID if applicable
            region_name = row['Table Name']
            region_id = None
            if region_name in region_mapping:
                if region_mapping[region_name]:  # Not 'India'
                    region_id = get_or_insert_dimension_id(
                        conn,
                        'DimRegions',
                        {'RegionName': region_mapping[region_name]}
                    )
            
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
            
            # Remove None values except RegionID (which can be NULL for all-India summary)
            summary_data = {k: v for k, v in summary_data.items() 
                          if v is not None or k == 'RegionID'}
            
            if len(summary_data) > 2:  # Only insert if we have more than just DateID and RegionID
                columns = ", ".join(summary_data.keys())
                placeholders = ", ".join(["?" for _ in summary_data])
                cursor.execute(
                    f"INSERT INTO FactAllIndiaDailySummary ({columns}) VALUES ({placeholders})",
                    tuple(summary_data.values())
                )
                
                summary_id = cursor.lastrowid
                
                # Insert generation breakdown if available
                generation_columns = ['Coal', 'Lignite', 'Hydro', 'Nuclear', 'Gas, Naptha & Diesel', 
                                   'RES (Wind, Solar, Biomass & Others)']
                for source in generation_columns:
                    if source in row and pd.notna(row[source]):
                        source_id = get_or_insert_dimension_id(
                            conn, 
                            'DimGenerationSources',
                            {'SourceName': source}
                        )
                        
                        if source_id:
                            amount = clean_numeric_value(row[source])
                            if amount is not None:
                                cursor.execute('''
                                    INSERT INTO FactDailyGenerationBreakdown 
                                    (AllIndiaSummaryID, GenerationSourceID, GenerationAmount)
                                    VALUES (?, ?, ?)
                                ''', (summary_id, source_id, amount))
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
    Insert data into FactStateDailyEnergy table using pre-populated dimension tables.
    Note: This function assumes the connection is managed by the caller.
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
                        if value is not None:  # Only add non-None values
                            state_data[db_col] = value
                
                # Only proceed if we have more than just DateID and StateID
                if len(state_data) > 2:
                    columns = ", ".join(state_data.keys())
                    placeholders = ", ".join(["?" for _ in state_data])
                    values = tuple(state_data.values())
                    
                    try:
                        cursor.execute(
                            f"INSERT INTO FactStateDailyEnergy ({columns}) VALUES ({placeholders})",
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
        # Note: We don't close the connection here as it's managed by the caller

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

def populate_fact_transmission_link_flow(conn, df, date_to_id_map):
    """Insert data into FactTransmissionLinkFlow table"""
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
        # 'Line Details': ('LineIdentifier', None, str),
        'Voltage Level': ('VoltageLevel_kV', 'kV', str),
        'No. of Circuit': ('NumberOfCircuits', None, clean_circuit_value),
        'Max Import (MW)': ('MaxImport', 'MW', clean_numeric_value),
        'Max Export (MW)': ('MaxExport', 'MW', clean_numeric_value),
        'Import (MU)': ('ImportEnergy', 'MU', clean_numeric_value),
        'Export (MU)': ('ExportEnergy', 'MU', clean_numeric_value),
        'Net Import (MU)': ('NetImportEnergy', 'MU', clean_numeric_value)
    }
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            
            # Get or insert transmission line
            line_id = get_or_insert_dimension_id(
                conn,
                'DimTransmissionLines',
                {
                    'LineIdentifier': row['Line Details']
                }
            )
            
            if not line_id:
                logger.warning(f"Could not get/insert line: {row['Line Details']}")
                continue
            
            # Build link data with proper cleaning
            link_data = {'DateID': date_id, 'LineID': line_id}
            for df_col, (db_col, unit, clean_func) in column_mapping.items():
                if df_col in row:
                    value = clean_func(row[df_col])
                    link_data[db_col] = value
                else:
                    logger.debug(f"Column '{df_col}' not found in DataFrame")
            
            # Remove None values
            link_data = {k: v for k, v in link_data.items() if v is not None}
            
            if len(link_data) > 2:  # Only insert if we have more than just DateID and LineID
                columns = ", ".join(link_data.keys())
                placeholders = ", ".join(["?" for _ in link_data])
                cursor.execute(
                    f"INSERT INTO FactTransmissionLinkFlow ({columns}) VALUES ({placeholders})",
                    tuple(link_data.values())
                )
            
        except Exception as e:
            logger.error(f"Error processing row in FactTransmissionLinkFlow: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
            
    conn.commit()
    logger.info("FactTransmissionLinkFlow populated successfully")

def populate_fact_time_block_power(conn, df, date_to_id_map):
    """Insert data into FactTimeBlockPowerData and related tables"""
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
                # Remove any extra whitespace and newlines
                value = value.strip().replace('\r', '').replace('\n', '')
                # If it's just a time (HH:MM), add seconds
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
            
            # Build block data with proper cleaning
            block_data = {'DateID': date_id}
            for df_col, (db_col, unit, clean_func) in column_mapping.items():
                if df_col in row:
                    value = clean_func(row[df_col])
                    block_data[db_col] = value
                else:
                    logger.debug(f"Column '{df_col}' not found in DataFrame")
            
            # Remove None values
            block_data = {k: v for k, v in block_data.items() if v is not None}
            
            if len(block_data) > 1:  # Only insert if we have more than just DateID
                columns = ", ".join(block_data.keys())
                placeholders = ", ".join(["?" for _ in block_data])
                cursor.execute(
                    f"INSERT INTO FactTimeBlockPowerData ({columns}) VALUES ({placeholders})",
                    tuple(block_data.values())
                )
                
                block_id = cursor.lastrowid
                
                # Insert generation breakdown if available
                generation_columns = [col for col in df.columns if '(MW)' in col and col not in [
                    'DEMAND MET (MW)', 'NET DEMAND MET (MW)', 'TOTAL GENERATION (MW)', 
                    'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export'
                ]]
                
                for col in generation_columns:
                    source_name = col.split(' (')[0].strip()
                    source_id = get_or_insert_dimension_id(
                        conn,
                        'DimGenerationSources',
                        {'SourceName': source_name}
                    )
                    
                    if source_id and pd.notna(row[col]):
                        amount = clean_numeric_value(row[col])
                        if amount is not None:
                            cursor.execute('''
                                INSERT INTO FactTimeBlockGeneration 
                                (TimeBlockDataID, GenerationSourceID, GenerationOutput)
                                VALUES (?, ?, ?)
                            ''', (block_id, source_id, amount))
            
        except Exception as e:
            logger.error(f"Error processing row in FactTimeBlockPowerData: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
    
    conn.commit()
    logger.info("FactTimeBlockPowerData populated successfully")

def automate_data_insertion_from_list(dataframes_list, db_name=DATABASE_NAME):
    """
    Main function to automate data insertion from a list of DataFrames.
    
    Args:
        dataframes_list: List of pandas DataFrames in a known order:
            [0] - All India Summary
            [1] - State-wise Data
            [3] - Inter-Region Data
            [6] - Time Block Data
    """
    logger.info(f"Starting data insertion into {db_name} for {len(dataframes_list)} DataFrames.")
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
            if 'Date' in df.columns:
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
                if i == 0:  # All India Summary
                    populate_fact_all_india_summary(conn, df, date_to_id_map)
                elif i == 1:  # State-wise Data
                    populate_fact_state_energy(conn, df, date_to_id_map)
                elif i == 3:  # Inter-Region Data
                    populate_fact_transmission_link_flow(conn, df, date_to_id_map)
                elif i == 6:  # Time Block Data
                    populate_fact_time_block_power(conn, df, date_to_id_map)
                else:
                    logger.warning(f"Unknown DataFrame type at index {i}")
            except Exception as e:
                logger.error(f"Error processing DataFrame at index {i}: {e}")
                continue
        
        logger.info("Data insertion completed successfully")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error during data insertion: {str(e)}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    try:
        # Get DataFrames from PDF parser
        dataframes_list = parser.main_process()
        if dataframes_list:
            automate_data_insertion_from_list(dataframes_list)
        else:
            logger.error("No DataFrames returned from PDF parser")
    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")