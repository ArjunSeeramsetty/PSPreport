import sqlite3
import pandas as pd
import numpy as np
import logging
import os
from datetime import datetime
import re
from fuzzywuzzy import fuzz
from modular_psp_parser import PSPReportParser

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
    'Total': 'India',
    'TOTAL': 'India',
    'INDIA': 'India',
    'ALL INDIA': 'India',
    'ALL-INDIA': 'India',
    '% SHARE': 'India',
    '% Share': 'India'
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
}

STATE_ALIAS = {
    'J&K(UT) &': 'J&K(UT) & Ladakh(UT)',
    'J&K(UT) &.': 'J&K(UT) & Ladakh(UT)',
    'J&K(UT)': 'J&K(UT) & Ladakh(UT)',
    'JAMMU & KASHMIR (UT)': 'J&K(UT) & Ladakh(UT)',
    'RAILWAYS_NR': 'Railways_NR ISTS',
    'RAILWAYS_ER': 'Railways_ER ISTS',
    'RAILWAYS WR': 'Railways_WR ISTS',
    'RAILWAYS SR': 'Railways_SR ISTS',
    'RAILWAYS NER': 'Railways_NER ISTS',
    'Arunachal': 'Arunachal Pradesh'
}

def get_canonical_region_name(raw_name):
    """Get canonical region name from raw input"""
    if not raw_name:
        return raw_name
    key = str(raw_name).upper()
    key = re.sub(r'[\r\n\t]', ' ', key)
    key = re.sub(r'[()]', '', key)
    key = key.replace('(MU)', '').replace('(MW)', '').strip()
    key = re.sub(r'\s+', ' ', key)
    logger.debug(f"Canonical region lookup: raw='{raw_name}', final_key='{key}'")
    return REGION_ALIAS.get(key, raw_name)

def get_canonical_generation_source(raw_name):
    """Get canonical generation source name"""
    key = raw_name.upper().replace('(MU)', '').replace('(MW)', '').replace('  ', ' ')
    key = key.strip()
    key = re.sub(r'^[^A-Z0-9(\)]+|[^A-Z0-9(\)]+$', '', key)
    return GEN_SOURCE_CANONICAL.get(key, (raw_name, None))

def get_canonical_country_name(raw_name):
    """Get canonical country name"""
    if not raw_name:
        return raw_name
    key = raw_name.upper().replace('(MU)', '').replace('(MW)', '').replace('  ', ' ')
    key = key.strip()
    key = re.sub(r'^[^A-Z0-9(\)]+|[^A-Z0-9(\)]+$', '', key)
    canonical = COUNTRY_ALIAS.get(key, raw_name)
    logger.debug(f"Country mapping: '{raw_name}' -> '{key}' -> '{canonical}'")
    return canonical

def get_canonical_state_name(raw_name):
    """Get canonical state name"""
    if not raw_name:
        return raw_name
    key = raw_name.upper().replace('(MU)', '').replace('(MW)', '').replace('  ', ' ')
    key = key.strip()
    key = re.sub(r'^[^A-Z0-9(\)]+|[^A-Z0-9(\)]+$', '', key)
    canonical = STATE_ALIAS.get(key, raw_name)
    logger.debug(f"State mapping: '{raw_name}' -> '{key}' -> '{canonical}'")
    return canonical

def check_database_exists():
    """Check if the database file exists"""
    return os.path.exists(DATABASE_NAME)

def verify_database_schema(conn):
    """Verify that the database has the required tables"""
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
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = {row[0] for row in cursor.fetchall()}
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
    """Get or insert a dimension ID"""
    if id_column_name is None:
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
    where_clause = " AND ".join([f"{col} = ?" for col in value_dict.keys()])
    values = tuple(value_dict.values())
    
    cursor.execute(f"SELECT {id_column_name} FROM {table_name} WHERE {where_clause}", values)
    result = cursor.fetchone()
    if result:
        return result[0]
    
    if table_name == 'DimDates':
        columns = ', '.join(value_dict.keys())
        placeholders = ', '.join(['?'] * len(value_dict))
        cursor.execute(f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})", values)
        conn.commit()
        cursor.execute(f"SELECT {id_column_name} FROM {table_name} WHERE {where_clause}", values)
        result = cursor.fetchone()
        if result:
            return result[0]
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

def clean_numeric_value(value):
    """Clean and convert value to numeric"""
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

def populate_fact_all_india_summary(conn, df, date_to_id_map):
    """Transform melted dataframe to wide format and insert data into FactAllIndiaDailySummary and FactDailyGenerationBreakdown"""
    cursor = conn.cursor()
    
    logger.info("Transforming melted Regional Summary DataFrame to wide format")
    logger.info(f"Original columns: {df.columns.tolist()}")
    logger.info(f"Original shape: {df.shape}")
    
    # Transform melted dataframe to wide format
    if 'Metric' in df.columns and 'Value' in df.columns:
        # Pivot the melted dataframe to wide format
        wide_df = df.pivot_table(
            index=['Date', 'Region'], 
            columns='Metric', 
            values='Value', 
            aggfunc='first'
        ).reset_index()
        
        # Rename the index column to 'Table Name' for compatibility with stable code
        wide_df = wide_df.rename(columns={'Region': 'Table Name'})
        
        logger.info(f"Transformed columns: {wide_df.columns.tolist()}")
        logger.info(f"Transformed shape: {wide_df.shape}")
        logger.info(f"First row: {wide_df.iloc[0].to_dict() if not wide_df.empty else 'Empty DataFrame'}")
    else:
        logger.error("DataFrame does not have expected melted format (Metric, Value columns)")
        return
    
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
    
    # Map of actual DataFrame columns to database columns (only available metrics)
    column_mapping = {
        # Evening Peak Demand - match the actual metric name from 2023-24 PDFs
        'Demand Met during Evening Peak hrs(MW) (at 20:00 hrs; from RLDCs)': ('EveningPeakDemandMet', 'MW', clean_numeric_value),
        'Demand Met during Evening Peak hrs(MW) (at\r20:00 hrs; from RLDCs)': ('EveningPeakDemandMet', 'MW', clean_numeric_value),
        'Demand Met during Evening Peak hrs(MW) (at\r19:00 hrs; from RLDCs)': ('EveningPeakDemandMet', 'MW', clean_numeric_value),
        
        # Maximum Demand SCADA - match the actual metric name from 2023-24 PDFs
        'Maximum Demand Met During the Day (MW) (From NLDC SCADA)': ('MaxDemandSCADA', 'MW', clean_numeric_value),
        'Maximum Demand Met During the Day (MW)\r(From NLDC SCADA)': ('MaxDemandSCADA', 'MW', clean_numeric_value),
        
        # Time of Maximum Demand - match the actual metric name from 2023-24 PDFs
        'Time Of Maximum Demand Met (From NLDC SCADA)': ('TimeOfMaxDemandMet', None, clean_time_value),
        'Time Of Maximum Demand Met': ('TimeOfMaxDemandMet', None, clean_time_value),
        
        # Share of NonFossil - match the actual metric name from 2023-24 PDFs
        'Share of Non-fossil fuel (Hydro,Nuclear and RES) in total generation(%)': ('ShareNonFossilInTotalGeneration', '%', clean_numeric_value),
        'Share of Non-fossil fuel (Hydro,Nuclear and RES) in\rtotal generation(%)': ('ShareNonFossilInTotalGeneration', '%', clean_numeric_value),
        
        # Other metrics
        'Peak Shortage (MW)': ('PeakShortage', 'MW', clean_numeric_value),
        'Energy Met (MU)': ('EnergyMet', 'MU', clean_numeric_value),
        'Energy Shortage (MU)': ('EnergyShortage', 'MU', clean_numeric_value),
        'Schedule(MU)': ('ScheduleDrawal', 'MU', clean_numeric_value),
        'Actual(MU)': ('ActualDrawal', 'MU', clean_numeric_value),
        'O/D/U/D(MU)': ('OverUnderDrawal', 'MU', clean_numeric_value),
        'Share of RES in total generation (%)': ('ShareRESInTotalGeneration', '%', clean_numeric_value),
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
        'SolarHR Max Demand Time': ('SolarHRMaxDemandTime', None, clean_time_value),
        'SolarHR Shortage': ('SolarHRShortage', 'MW', clean_numeric_value),
        'Non-SolarHR Max Demand': ('NonSolarHRMaxDemand', 'MW', clean_numeric_value),
        'Non-SolarHR Max Demand Time': ('NonSolarHRMaxDemandTime', None, clean_time_value),
        'Non-SolarHR Shortage': ('NonSolarHRShortage', 'MW', clean_numeric_value),
        # Outage metrics
        'Central Sector': ('CentralSectorOutage', 'MW', clean_numeric_value),
        'State Sector': ('StateSectorOutage', 'MW', clean_numeric_value),
        'Total': ('TotalOutage', 'MW', clean_numeric_value),
    }
    
    for _, row in wide_df.iterrows():
        try:
            # Handle date conversion more robustly
            try:
                date_obj = pd.to_datetime(row['Date']).date()
                date_id = date_to_id_map.get(date_obj)
                if date_id is None:
                    # Try to insert the date if it doesn't exist
                    date_id = insert_date_dimension(conn, str(date_obj))
                    if date_id:
                        date_to_id_map[date_obj] = date_id
                    else:
                        logger.error(f"Could not get or create DateID for date: {row['Date']}")
                        continue
            except Exception as e:
                logger.error(f"Error processing date '{row['Date']}': {e}")
                continue
            
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
                if value is not None:  # Only add non-None values
                    summary_data[db_col] = value
                else:
                    logger.debug(f"Column '{df_col}' not found in DataFrame")
            
            # Only proceed if we have more than just DateID and RegionID
            if len(summary_data) > 2:
                columns = ", ".join(summary_data.keys())
                placeholders = ", ".join(["?" for _ in summary_data])
                cursor.execute(
                    f"INSERT OR REPLACE INTO FactAllIndiaDailySummary ({columns}) VALUES ({placeholders})",
                    tuple(summary_data.values())
                )
                # Insert generation breakdown if available
                generation_columns = ['Hydro Gen (MU)', 'Wind Gen (MU)', 'Solar Gen (MU)*', 'Coal', 'Lignite', 'Nuclear', 'Gas, Naptha & Diesel', 'RES (Wind, Solar, Biomass & Others)']
                for source in generation_columns:
                    if source in row and pd.notna(row[source]):
                        # Map the generation source names to canonical names
                        source_mapping = {
                            'Hydro Gen (MU)': 'Hydro',
                            'Wind Gen (MU)': 'Wind',
                            'Solar Gen (MU)*': 'Solar',
                            'Coal': 'Coal',
                            'Lignite': 'Lignite',
                            'Nuclear': 'Nuclear',
                            'Gas, Naptha & Diesel': 'Gas, Naptha & Diesel',
                            'RES (Wind, Solar, Biomass & Others)': 'RE'
                        }
                        canonical = source_mapping.get(source, source)
                        # Fix: include 'Gas, Naptha & Diesel' in Thermal category
                        if canonical in ['Wind', 'Solar', 'RE']:
                            category = 'Renewable'
                        elif canonical in ['Coal', 'Lignite', 'Gas', 'Gas, Naptha & Diesel']:
                            category = 'Thermal'
                        elif canonical == 'Nuclear':
                            category = 'Nuclear'
                        else:
                            category = 'Hydro'
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

# Helper function for fuzzy matching
def fuzzy_match_name(cursor, table_name, column_name, target_name, threshold=80):
    """Fuzzy match a name against a dimension table"""
    cursor.execute(f"SELECT * FROM {table_name}")
    all_records = cursor.fetchall()
    
    best_match = None
    best_score = 0
    
    for record in all_records:
        # Get the name column value
        name_value = record[1]  # Assuming name is the second column (after ID)
        score = fuzz.ratio(target_name.lower(), str(name_value).lower())
        if score > best_score and score >= threshold:
            best_score = score
            best_match = record
    
    return best_match

# Insert Regional Summary data
def insert_regional_summary_data(cursor, df, date_to_id_map):
    """Insert Regional Summary data into FactAllIndiaDailySummary table"""
    logger.info("Processing Regional Summary DataFrame")
    logger.info(f"Columns: {list(df.columns)}")
    logger.info(f"Shape: {df.shape}")
    
    for index, row in df.iterrows():
        try:
            # Get date ID
            date_str = str(row['Date']).strip()
            date_id = date_to_id_map.get(date_str)
            
            if not date_id:
                logger.warning(f"Date not found in DimDates: {date_str}")
                continue
            
            # Get region ID (if applicable)
            region_id = None
            if 'Region' in row and pd.notna(row['Region']):
                region_name = str(row['Region']).strip()
                if region_name != 'India' and region_name != 'ALL INDIA':
                    cursor.execute("SELECT RegionID FROM DimRegions WHERE RegionName = ?", (region_name,))
                    region_result = cursor.fetchone()
                    if region_result:
                        region_id = region_result[0]
            
            # Get metric and value
            metric = str(row['Metric']).strip()
            
            # Determine if this is a time value or numeric value
            time_metrics = [
                'Time Of Maximum Demand Met', 'SolarHR Max Demand Time', 'Non-SolarHR Max Demand Time'
            ]
            
            if metric in time_metrics:
                value = clean_time_value(row['Value'])
            else:
                value = clean_numeric_value(row['Value'])
            
            if value is None:
                continue
            
            # Map metrics to database columns
            metric_mapping = {
                'Demand Met during Evening Peak hrs(MW) (at\r20:00 hrs; from RLDCs)': 'EveningPeakDemandMet',
                'Demand Met during Evening Peak hrs(MW) (at\r19:00 hrs; from RLDCs)': 'EveningPeakDemandMet',
                'Peak Shortage (MW)': 'PeakShortage',
                'Energy Met (MU)': 'EnergyMet',
                'Energy Shortage (MU)': 'EnergyShortage',
                'Maximum Demand Met During the Day (MW)\r(From NLDC SCADA)': 'MaxDemandSCADA',
                'Time Of Maximum Demand Met': 'TimeOfMaxDemandMet',
                'Schedule(MU)': 'ScheduleDrawal',
                'Actual(MU)': 'ActualDrawal',
                'O/D/U/D(MU)': 'OverUnderDrawal',
                'Share of RES in total generation (%)': 'ShareRESInTotalGeneration',
                'Share of Non-fossil fuel (Hydro,Nuclear and RES) in\rtotal generation(%)': 'ShareNonFossilInTotalGeneration',
                'FVI': 'FrequencyViolationIndex',
                'Frequency (<49.7)': 'DurationFrequencyBelow49_7',
                'Frequency (49.7 - 49.8)': 'DurationFrequency_49_7_to_49_8',
                'Frequency (49.8 - 49.9)': 'DurationFrequency_49_8_to_49_9',
                'Frequency (< 49.9)': 'DurationFrequencyBelow49_9',
                'Frequency (49.9 - 50.05)': 'DurationFrequency_49_9_to_50_05',
                'Frequency (> 50.05)': 'DurationFrequencyAbove50_05',
                'Region DDF': 'RegionDDF',
                'States DDF': 'StatesDDF',
                'SolarHR Max Demand': 'SolarHRMaxDemand',
                'SolarHR Max Demand Time': 'SolarHRMaxDemandTime',
                'SolarHR Shortage': 'SolarHRShortage',
                'Non-SolarHR Max Demand': 'NonSolarHRMaxDemand',
                'Non-SolarHR Max Demand Time': 'NonSolarHRMaxDemandTime',
                'Non-SolarHR Shortage': 'NonSolarHRShortage',
                # Generation breakdown metrics
                'Hydro Gen (MU)': 'HydroGen',
                'Wind Gen (MU)': 'WindGen',
                'Solar Gen (MU)*': 'SolarGen',
                'Coal': 'CoalGen',
                'Lignite': 'LigniteGen',
                'Nuclear': 'NuclearGen',
                'Gas, Naptha & Diesel': 'GasNapthaDieselGen',
                'RES (Wind, Solar, Biomass & Others)': 'RESGen',
                'Hydro': 'HydroGen',  # Add the missing mapping
                # Outage metrics
                'Central Sector': 'CentralSectorOutage',
                'State Sector': 'StateSectorOutage',
                'Total': 'TotalOutage',
            }
            
            db_column = metric_mapping.get(metric)
            if not db_column:
                logger.warning(f"Unknown metric: {metric}")
                continue
            
            # Insert into FactAllIndiaDailySummary
            cursor.execute(f"""
                INSERT OR REPLACE INTO FactAllIndiaDailySummary 
                (DateID, RegionID, {db_column})
                VALUES (?, ?, ?)
            """, (date_id, region_id, value))
            
        except Exception as e:
            logger.error(f"Error processing Regional Summary row: {e}")

# Enhanced fuzzy matching for state names
def get_or_create_state_id(cursor, state_name):
    """Get or create StateID with enhanced fuzzy matching"""
    # Handle special cases first
    state_mapping = {
        'Railways_NR ISTS': 'Railways NR ISTS',
        'RailwaysNR ISTS': 'Railways NR ISTS', 
        'Railways_NR': 'Railways NR ISTS',
        'Railways_ER ISTS': 'Railways ER ISTS',
        'RailwaysER ISTS': 'Railways ER ISTS',
        'Railways_ER': 'Railways ER ISTS',
        'DNHDDPDCL': 'DNHDDPDCL',
        'AMNSIL': 'AMNSIL',
        'BALCO': 'BALCO',
        'RIL JAMNAGAR': 'RIL JAMNAGAR',
        'J&K(UT) &': 'J&K(UT) & Ladakh(UT)',
        'J&K(UT) &.': 'J&K(UT) & Ladakh(UT)',
        'J&K(UT)': 'J&K(UT) & Ladakh(UT)',
        'JAMMU & KASHMIR (UT)': 'J&K(UT) & Ladakh(UT)',
        'Arunachal': 'Arunachal Pradesh'
    }
    
    # Apply mapping
    mapped_name = state_mapping.get(state_name, state_name)
    
    # Try exact match first
    cursor.execute("SELECT StateID FROM DimStates WHERE StateName = ?", (mapped_name,))
    state_result = cursor.fetchone()
    
    if state_result:
        return state_result[0]
    
    # Try fuzzy matching
    fuzzy_match = fuzzy_match_name(cursor, 'DimStates', 'StateName', mapped_name, threshold=70)
    if fuzzy_match:
        logger.info(f"Fuzzy matched state '{state_name}' to '{fuzzy_match[1]}'")
        return fuzzy_match[0]
    
    # If still not found, try to create it
    logger.warning(f"State not found in DimStates (exact or fuzzy): {state_name}")
    return None

# Enhanced fuzzy matching for transmission lines
def get_or_create_line_id(cursor, line_details, voltage_level=None, num_circuits=None):
    """Get or create LineID with auto-insertion"""
    # Try exact match first
    cursor.execute("SELECT LineID FROM DimTransmissionLines WHERE LineIdentifier = ?", (line_details,))
    line_result = cursor.fetchone()
    
    if line_result:
        return line_result[0]
    
    # Try fuzzy matching
    fuzzy_match = fuzzy_match_name(cursor, 'DimTransmissionLines', 'LineIdentifier', line_details, threshold=70)
    if fuzzy_match:
        logger.info(f"Fuzzy matched line '{line_details}' to '{fuzzy_match[1]}'")
        return fuzzy_match[0]
    
    # Create new transmission line
    cursor.execute("""
        INSERT INTO DimTransmissionLines (LineIdentifier, VoltageLevel_kV, NumberOfCircuits)
        VALUES (?, ?, ?)
    """, (line_details, voltage_level, num_circuits))
    line_id = cursor.lastrowid
    logger.info(f"Created new transmission line: {line_details}")
    return line_id

# Fix the States table insertion - use enhanced fuzzy matching
def insert_states_data(cursor, df, date_to_id_map):
    """Insert States data into FactStateDailyEnergy table"""
    logger.info("Processing States DataFrame")
    logger.info(f"Columns: {list(df.columns)}")
    logger.info(f"Shape: {df.shape}")
    
    for index, row in df.iterrows():
        try:
            # Get date ID
            date_str = str(row['Date']).strip()
            date_id = date_to_id_map.get(date_str)
            
            if not date_id:
                logger.warning(f"Date not found in DimDates: {date_str}")
                continue
            
            # Get state name and look up StateID with enhanced fuzzy matching
            state_name = str(row['States']).strip()
            state_id = get_or_create_state_id(cursor, state_name)
            
            if not state_id:
                continue
            
            # Clean numeric values
            max_demand = clean_numeric_value(row['Maximum Demand (MW)'])
            shortage = clean_numeric_value(row['Shortage (MW)'])
            energy_met = clean_numeric_value(row['Energy Met (MU)'])
            drawal_schedule = clean_numeric_value(row['Drawal Schedule (MU)'])
            over_under_drawal = clean_numeric_value(row['OD(+)/UD(-) (MU)'])
            max_over_drawal = clean_numeric_value(row['Max OD (MW)'])
            energy_shortage = clean_numeric_value(row['Energy Shortage (MU)'])
            
            # Insert into FactStateDailyEnergy (without RegionID)
            cursor.execute("""
                INSERT OR REPLACE INTO FactStateDailyEnergy 
                (DateID, StateID, MaximumDemand, Shortage, EnergyMet, DrawalSchedule, 
                 OverUnderDrawal, MaxOverDrawal, EnergyShortage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (date_id, state_id, max_demand, shortage, energy_met, drawal_schedule,
                  over_under_drawal, max_over_drawal, energy_shortage))
            
        except Exception as e:
            logger.error(f"Error processing States row: {e}")

# Fix the Inter-Region table insertion - handle B/B lines, HVDC, and auto-insert lines
def insert_inter_region_data(cursor, df, date_to_id_map):
    """Insert Inter-Region data into FactTransmissionLinkFlow table"""
    logger.info("Processing Inter-Region DataFrame")
    logger.info(f"Columns: {list(df.columns)}")
    logger.info(f"Shape: {df.shape}")
    
    for index, row in df.iterrows():
        try:
            # Get date ID
            date_str = str(row['Date']).strip()
            date_id = date_to_id_map.get(date_str)
            
            if not date_id:
                logger.warning(f"Date not found in DimDates: {date_str}")
                continue
            
            # Get line details and look up or create LineID
            line_details = str(row['Line Details']).strip()
            voltage_level = str(row.get('Voltage Level', '')).strip()
            num_circuits = clean_numeric_value(row.get('No. of Circuit', None))
            
            # Handle B/B lines and HVDC - these are valid
            line_id = get_or_create_line_id(cursor, line_details, voltage_level, num_circuits)
            
            # Get inter-region value - accept formats like 'ER-NER', 'NER-NR'
            inter_region = str(row['Import']).strip()
            if not inter_region or inter_region == 'nan':
                logger.warning(f"Invalid Inter_Region value: {inter_region}")
                continue
            
            # Clean numeric values
            max_import = clean_numeric_value(row['Max Import (MW)'])
            max_export = clean_numeric_value(row['Max Export (MW)'])
            import_energy = clean_numeric_value(row['Import (MU)'])
            export_energy = clean_numeric_value(row['Export (MU)'])
            net_import_energy = clean_numeric_value(row['NET Import (MU)'])
            
            # Insert into FactTransmissionLinkFlow
            cursor.execute("""
                INSERT OR REPLACE INTO FactTransmissionLinkFlow 
                (DateID, LineID, Inter_Region, MaxImport, MaxExport, ImportEnergy, ExportEnergy, NetImportEnergy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date_id, line_id, inter_region, max_import, max_export, import_energy, export_energy, net_import_energy))
            
        except Exception as e:
            logger.error(f"Error processing Inter-Region row: {e}")

# Fix the International table insertion - handle ER isolated case and auto-insert lines
def insert_international_data(cursor, df, date_to_id_map):
    """Insert International data into FactInternationalTransmissionLinkFlow table"""
    logger.info("Processing International DataFrame")
    logger.info(f"Columns: {list(df.columns)}")
    logger.info(f"Shape: {df.shape}")
    
    for index, row in df.iterrows():
        try:
            # Get date ID
            date_str = str(row['Date']).strip()
            date_id = date_to_id_map.get(date_str)
            
            if not date_id:
                logger.warning(f"Date not found in DimDates: {date_str}")
                continue
            
            # Get line name and look up or create LineID
            line_name = str(row['Line Name']).strip()
            line_id = get_or_create_line_id(cursor, line_name)
            
            # Get country name and look up CountryID (if applicable)
            country_id = None
            if 'Country' in row and pd.notna(row['Country']):
                country_name = str(row['Country']).strip()
                # Handle ER isolated case
                if 'ER\r(Isolated from Indian Grid)' in country_name or 'ER (Isolated from Indian Grid)' in country_name:
                    country_name = 'ER'
                
                cursor.execute("SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country_name,))
                country_result = cursor.fetchone()
                if country_result:
                    country_id = country_result[0]
            
            # Get state name and look up StateID (if applicable)
            # Note: In International table, 'State' column often contains country names, not state names
            state_id = None
            if 'State' in row and pd.notna(row['State']):
                state_name = str(row['State']).strip()
                
                # Check if this is actually a country name
                country_names = ['NEPAL', 'BANGLADESH', 'BHUTAN', 'MYANMAR']
                if state_name.upper() in country_names:
                    # Look up in DimCountries instead
                    cursor.execute("SELECT CountryID FROM DimCountries WHERE CountryName = ?", (state_name,))
                    country_result = cursor.fetchone()
                    if country_result:
                        country_id = country_result[0]
                        logger.info(f"Found country '{state_name}' in State column, using as CountryID")
                else:
                    # It's actually a state name
                    state_id = get_or_create_state_id(cursor, state_name)
            
            # Clean numeric values
            max_loading = clean_numeric_value(row['Max (MW)'])
            min_loading = clean_numeric_value(row['Min (MW)'])
            avg_loading = clean_numeric_value(row['Avg (MW)'])
            energy_exchanged = clean_numeric_value(row['Energy Exchange (MU)'])
            
            # Insert into FactInternationalTransmissionLinkFlow
            cursor.execute("""
                INSERT OR REPLACE INTO FactInternationalTransmissionLinkFlow 
                (DateID, LineID, CountryID, StateID, MaxLoading, MinLoading, AvgLoading, EnergyExchanged)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date_id, line_id, country_id, state_id, max_loading, min_loading, avg_loading, energy_exchanged))
            
        except Exception as e:
            logger.error(f"Error processing International row: {e}")

# Fix the Transnational Exchange table insertion - use International NET dataframe
def insert_transnational_exchange_data(cursor, df, date_to_id_map):
    """Insert Transnational Exchange data into FactCountryDailyExchange table"""
    logger.info("Processing Transnational Exchange DataFrame")
    logger.info(f"Columns: {list(df.columns)}")
    logger.info(f"Shape: {df.shape}")
    
    for index, row in df.iterrows():
        try:
            # Get date ID
            date_str = str(row['Date']).strip()
            date_id = date_to_id_map.get(date_str)
            
            if not date_id:
                logger.warning(f"Date not found in DimDates: {date_str}")
                continue
            
            # Process each country
            countries = ['Bhutan', 'Nepal', 'Bangladesh', 'Godda (Bangladesh)']
            
            for country in countries:
                # Get country ID
                cursor.execute("SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country,))
                country_result = cursor.fetchone()
                
                if not country_result:
                    logger.warning(f"Country not found in DimCountries: {country}")
                    continue
                    
                country_id = country_result[0]
                
                # Get energy and peak values
                energy_col = f"{country} (MU)"
                peak_col = f"{country} Peak (MW)"
                
                if energy_col in row and peak_col in row:
                    total_energy = clean_numeric_value(row[energy_col])
                    peak_exchange = clean_numeric_value(row[peak_col])
                    
                    if total_energy is not None or peak_exchange is not None:
                        # Insert into FactCountryDailyExchange
                        cursor.execute("""
                            INSERT OR REPLACE INTO FactCountryDailyExchange 
                            (DateID, CountryID, TotalEnergyExchanged, PeakExchange)
                            VALUES (?, ?, ?, ?)
                        """, (date_id, country_id, total_energy, peak_exchange))
            
        except Exception as e:
            logger.error(f"Error processing Transnational Exchange row: {e}")

# Fix the Exchange table insertion - handle total rows
def insert_exchange_data(cursor, df, date_to_id_map):
    """Insert Exchange data into FactTransnationalExchangeDetail table"""
    logger.info("Processing Exchange DataFrame")
    logger.info(f"Columns: {list(df.columns)}")
    logger.info(f"Shape: {df.shape}")
    
    for index, row in df.iterrows():
        try:
            # Get date ID
            date_str = str(row['Date']).strip()
            date_id = date_to_id_map.get(date_str)
            
            if not date_id:
                logger.warning(f"Date not found in DimDates: {date_str}")
                continue
            
            # Get country name and look up CountryID
            country_name = str(row['Country']).strip()
            
            # Handle total rows - skip them as they are summary rows
            if country_name in ['Total Export', 'Total Import', 'Total Net']:
                logger.info(f"Skipping summary row: {country_name}")
                continue
            
            cursor.execute("SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country_name,))
            country_result = cursor.fetchone()
            
            if not country_result:
                logger.warning(f"Country not found in DimCountries: {country_name}")
                continue
                
            country_id = country_result[0]
            
            # Process each exchange mechanism
            mechanisms = ['PPA', 'Bilateral', 'DAM IEX', 'DAM PXIL', 'DAM HPX', 'RTM IEX', 'RTM PXIL', 'RTM HPX']
            
            for mechanism in mechanisms:
                if mechanism in row and pd.notna(row[mechanism]):
                    # Get mechanism ID
                    cursor.execute("SELECT MechanismID FROM DimExchangeMechanisms WHERE MechanismName = ?", (mechanism,))
                    mechanism_result = cursor.fetchone()
                    
                    if not mechanism_result:
                        logger.warning(f"Mechanism not found in DimExchangeMechanisms: {mechanism}")
                        continue
                        
                    mechanism_id = mechanism_result[0]
                    
                    # Determine exchange direction based on type
                    exchange_direction = 'Import' if row['Type'] == 'Import' else 'Export'
                    exchange_value = clean_numeric_value(row[mechanism])
                    
                    if exchange_value is not None:
                        # Insert into FactTransnationalExchangeDetail
                        cursor.execute("""
                            INSERT OR REPLACE INTO FactTransnationalExchangeDetail 
                            (DateID, CountryID, MechanismID, ExchangeDirection, ExchangeValue)
                            VALUES (?, ?, ?, ?, ?)
                        """, (date_id, country_id, mechanism_id, exchange_direction, exchange_value))
            
        except Exception as e:
            logger.error(f"Error processing Exchange row: {e}")

# Fix the Block-wise table insertion - use correct column names
def insert_blockwise_data(cursor, df, date_to_id_map):
    """Insert Block-wise data into FactTimeBlockPowerData table"""
    logger.info("Processing Block-wise DataFrame")
    logger.info(f"Columns: {list(df.columns)}")
    logger.info(f"Shape: {df.shape}")

    # --- Static mapping from 'HH:MM' to block number (1-96) ---
    block_time_to_number = {f"{hour:02d}:{minute:02d}": block_num+1 for block_num, (hour, minute) in enumerate([(h, m) for h in range(24) for m in [0, 15, 30, 45]])}

    for index, row in df.iterrows():
        try:
            # Get date ID
            date_str = str(row['Date']).strip()
            date_id = date_to_id_map.get(date_str)
            
            if not date_id:
                logger.warning(f"Date not found in DimDates: {date_str}")
                continue
            
            # Get time and convert to block number using static mapping
            time_str = str(row['TIME']).strip()
            # TIME is already in HH:MM format, use it directly
            block_time = time_str
            time_key = time_str  # Use the time string directly as key
            
            block_number = block_time_to_number.get(time_key)
            if block_number is None:
                # If time mapping fails, try to parse the time and calculate block number
                try:
                    if ':' in time_str:
                        hour, minute = map(int, time_str.split(':'))
                        # Calculate block number: (hour * 4) + (minute // 15) + 1
                        block_number = (hour * 4) + (minute // 15) + 1
                        if block_number < 1 or block_number > 96:
                            logger.warning(f"Calculated block number {block_number} out of range for time {time_str}, using index + 1")
                            block_number = index + 1
                    else:
                        logger.warning(f"Invalid time format '{time_str}', using index + 1")
                        block_number = index + 1
                except Exception as e:
                    logger.warning(f"Error calculating block number for time '{time_str}': {e}, using index + 1")
                    block_number = index + 1

            # Clean numeric values
            frequency = clean_numeric_value(row['FREQUENCY (Hz)'])
            demand_met = clean_numeric_value(row['DEMAND MET (MW)'])
            net_demand_met = clean_numeric_value(row['NET DEMAND MET (MW)'])
            total_generation = clean_numeric_value(row['TOTAL GENERATION (MW)'])
            net_transnational_exchange = clean_numeric_value(row['NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export'])
            
            # Insert into FactTimeBlockPowerData
            cursor.execute("""
                INSERT OR REPLACE INTO FactTimeBlockPowerData 
                (DateID, BlockTime, BlockNumber, Frequency, DemandMet, NetDemandMet, TotalGeneration, NetTransnationalExchange)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date_id, block_time, block_number, frequency, demand_met, net_demand_met, total_generation, net_transnational_exchange))
            
            # Insert generation breakdown data
            generation_sources = {
                'Nuclear': row.get('NUCLEAR (MW)', None),
                'Wind': row.get('WIND (MW)', None),
                'Solar': row.get('SOLAR (MW)', None),
                'Hydro': row.get('HYDRO (MW)', None),
                'Gas': row.get('GAS (MW)', None),
                'Thermal': row.get('THERMAL (MW)', None),
                'Others': row.get('OTHERS* (MW)', None)
            }
            
            for source_name, value in generation_sources.items():
                if pd.notna(value):
                    # Get generation source ID
                    cursor.execute("SELECT GenerationSourceID FROM DimGenerationSources WHERE SourceName = ?", (source_name,))
                    source_result = cursor.fetchone()
                    
                    if source_result:
                        source_id = source_result[0]
                        generation_output = clean_numeric_value(value)
                        
                        if generation_output is not None:
                            cursor.execute("""
                                INSERT OR REPLACE INTO FactTimeBlockGeneration 
                                (DateID, BlockTime, BlockNumber, GenerationSourceID, GenerationOutput)
                                VALUES (?, ?, ?, ?, ?)
                            """, (date_id, block_time, block_number, source_id, generation_output))
        except Exception as e:
            logger.error(f"Error processing Block-wise row: {e}")

# Helper function to ensure required countries exist in DimCountries
def ensure_required_countries(cursor):
    """Ensure all required countries exist in DimCountries table"""
    required_countries = [
        'Bhutan', 'Nepal', 'Bangladesh', 'Myanmar', 
        'Godda (Bangladesh)', 'Total Export', 'Total Import', 'Total Net'
    ]
    
    for country_name in required_countries:
        cursor.execute("SELECT CountryID FROM DimCountries WHERE CountryName = ?", (country_name,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO DimCountries (CountryName) VALUES (?)", (country_name,))
            logger.info(f"Added missing country: {country_name}")

# Helper function to ensure required states exist in DimStates
# def ensure_required_states(cursor):
    # """Ensure all required states exist in DimStates table"""
    # required_states = [
    #     'Railways NR ISTS', 'Railways ER ISTS', 'DNHDDPDCL', 'AMNSIL', 'BALCO', 'RIL JAMNAGAR',
    #     'J&K(UT) & Ladakh(UT)', 'Arunachal Pradesh'
    # ]
    
    # for state_name in required_states:
    #     cursor.execute("SELECT StateID FROM DimStates WHERE StateName = ?", (state_name,))
    #     if not cursor.fetchone():
    #         cursor.execute("INSERT INTO DimStates (StateName) VALUES (?)", (state_name,))
    #         logger.info(f"Added missing state: {state_name}")

# Helper function to ensure required mechanisms exist in DimExchangeMechanisms
def ensure_required_mechanisms(cursor):
    """Ensure all required exchange mechanisms exist in DimExchangeMechanisms table"""
    required_mechanisms = [
        'PPA', 'Bilateral', 'DAM IEX', 'DAM PXIL', 'DAM HPX', 'RTM IEX', 'RTM PXIL', 'RTM HPX'
    ]
    
    for mechanism_name in required_mechanisms:
        cursor.execute("SELECT MechanismID FROM DimExchangeMechanisms WHERE MechanismName = ?", (mechanism_name,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO DimExchangeMechanisms (MechanismName) VALUES (?)", (mechanism_name,))
            logger.info(f"Added missing mechanism: {mechanism_name}")

# Helper function to ensure required generation sources exist in DimGenerationSources
def ensure_required_generation_sources(cursor):
    """Ensure all required generation sources exist in DimGenerationSources table"""
    required_sources = [
        ('Nuclear', 'Nuclear'),
        ('Wind', 'Renewable'),
        ('Solar', 'Renewable'),
        ('Hydro', 'Hydro'),
        ('Gas', 'Thermal'),
        ('Thermal', 'Thermal'),
        ('Others', 'Renewable')
    ]
    
    for source_name, category in required_sources:
        cursor.execute("SELECT GenerationSourceID FROM DimGenerationSources WHERE SourceName = ?", (source_name,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO DimGenerationSources (SourceName, SourceCategory) VALUES (?, ?)", 
                         (source_name, category))
            logger.info(f"Added missing generation source: {source_name}")

def populate_fact_state_energy(conn, df, date_to_id_map):
    """Insert data into FactStateDailyEnergy table using composite keys (DateID, StateID)."""
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

def populate_fact_country_daily_exchange(conn, df, date_to_id_map):
    """Insert data into FactCountryDailyExchange table."""
    cursor = conn.cursor()
    
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
    
    # Map of column names to country names
    country_column_mapping = {
        'Bhutan (MU)': 'Bhutan',
        'Nepal (MU)': 'Nepal', 
        'Bangladesh (MU)': 'Bangladesh',
        'Godda (Bangladesh) (MU)': 'Godda (Bangladesh)',
        'Bhutan Peak (MW)': 'Bhutan',
        'Nepal Peak (MW)': 'Nepal',
        'Bangladesh Peak (MW)': 'Bangladesh',
        'Godda (Bangladesh) Peak (MW)': 'Godda (Bangladesh)'
    }
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            
            # Group columns by country to combine (MU) and (MW) data
            country_data = {}
            
            for col_name, country_name in country_column_mapping.items():
                if col_name in row and pd.notna(row[col_name]):
                    if country_name not in country_data:
                        country_data[country_name] = {'energy': None, 'peak': None}
                    
                    # Determine if this is energy (MU) or peak (MW) data
                    if '(MU)' in col_name:
                        country_data[country_name]['energy'] = clean_numeric_value(row[col_name])
                    elif '(MW)' in col_name:
                        country_data[country_name]['peak'] = clean_numeric_value(row[col_name])
            
            # Insert combined data for each country
            for country_name, data in country_data.items():
                # Get or insert country using canonical mapping
                canonical_country = get_canonical_country_name(country_name)
                country_id = get_or_insert_dimension_id(
                    conn,
                    'DimCountries',
                    {'CountryName': canonical_country}
                )
                if not country_id:
                    logger.warning(f"Could not get/insert country: {canonical_country} (original: {country_name})")
                    continue
                
                total_energy = data['energy']
                peak_exchange = data['peak']
                
                # Only insert if we have at least one non-None value
                if total_energy is not None or peak_exchange is not None:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO FactCountryDailyExchange 
                        (DateID, CountryID, TotalEnergyExchanged, PeakExchange)
                        VALUES (?, ?, ?, ?)
                        """,
                        (date_id, country_id, total_energy, peak_exchange)
                    )
        except Exception as e:
            logger.error(f"Error processing row in FactCountryDailyExchange: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
    
    conn.commit()
    logger.info("FactCountryDailyExchange populated successfully")

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
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            
            # Get or create line ID
            line_details = row.get('Line Details', '')
            voltage_level = row.get('Voltage Level', '')
            num_circuits = clean_numeric_value(row.get('No. of Circuits', ''))
            
            line_id = get_or_create_line_id(cursor, line_details, voltage_level, num_circuits)
            if not line_id:
                logger.warning(f"Could not get/create line ID for: {line_details}")
                continue
            
            # Get inter-region information
            inter_region = row.get('Import', '')  # Use 'Import' column if available
            if not inter_region or pd.isna(inter_region):
                inter_region = row.get('Inter_Region', '')  # Fallback to 'Inter_Region' if present
            if not inter_region or pd.isna(inter_region):
                # Try to construct from other columns if possible (e.g., 'From' and 'To')
                from_region = row.get('From', '')
                to_region = row.get('To', '')
                if from_region and to_region:
                    inter_region = f"{from_region}-{to_region}"
            
            # Process flow values
            max_import = clean_numeric_value(row.get('Max Import (MW)', ''))
            max_export = clean_numeric_value(row.get('Max Export (MW)', ''))
            import_energy = clean_numeric_value(row.get('Import Energy (MU)', ''))
            export_energy = clean_numeric_value(row.get('Export Energy (MU)', ''))
            net_import_energy = clean_numeric_value(row.get('Net Import Energy (MU)', ''))
            
            if any(v is not None for v in [max_import, max_export, import_energy, export_energy, net_import_energy]):
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO FactTransmissionLinkFlow 
                    (DateID, LineID, Inter_Region, MaxImport, MaxExport, ImportEnergy, ExportEnergy, NetImportEnergy)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (date_id, line_id, inter_region, max_import, max_export, import_energy, export_energy, net_import_energy)
                )
        except Exception as e:
            logger.error(f"Error processing row in FactTransmissionLinkFlow: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
            
    conn.commit()
    logger.info("FactTransmissionLinkFlow populated successfully")

def populate_fact_line_congestion(conn, df, date_to_id_map):
    """Insert data into FactInternationalTransmissionLinkFlow table."""
    cursor = conn.cursor()
    
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
            
            # Get or create line ID using Line Name (not Line Details)
            line_name = row.get('Line Name', '')
            # For international lines, we don't have voltage level and circuits info
            # So we'll create a line ID based on the line name
            line_id = get_or_create_line_id(cursor, line_name, None, None)
            if not line_id:
                logger.warning(f"Could not get/create line ID for: {line_name}")
                continue
            
            # Get country ID from State column (which contains country names)
            country_id = None
            if 'State' in row and pd.notna(row['State']):
                # The State column contains country names like 'BHUTAN', 'NEPAL', etc.
                country_name = get_canonical_country_name(row['State'])
                country_id = get_or_insert_dimension_id(
                    conn,
                    'DimCountries',
                    {'CountryName': country_name}
                )
            
            # For international lines, we don't have state information
            state_id = None
            
            # Get region ID from Region column
            region_id = None
            if 'Region' in row and pd.notna(row['Region']):
                region_name = get_canonical_region_name(row['Region'])
                region_id = get_or_insert_dimension_id(
                    conn,
                    'DimRegions',
                    {'RegionName': region_name}
                )
            
            # Process flow values using correct column names
            max_loading = clean_numeric_value(row.get('Max (MW)', ''))
            min_loading = clean_numeric_value(row.get('Min (MW)', ''))
            avg_loading = clean_numeric_value(row.get('Avg (MW)', ''))
            energy_exchanged = clean_numeric_value(row.get('Energy Exchange (MU)', ''))
            
            if any(v is not None for v in [max_loading, min_loading, avg_loading, energy_exchanged]):
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO FactInternationalTransmissionLinkFlow 
                    (DateID, LineID, CountryID, StateID, RegionID, MaxLoading, MinLoading, AvgLoading, EnergyExchanged)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (date_id, line_id, country_id, state_id, region_id, max_loading, min_loading, avg_loading, energy_exchanged)
                )
        except Exception as e:
            logger.error(f"Error processing row in FactInternationalTransmissionLinkFlow: {e}")
            logger.error(f"Row data: {row.to_dict()}")
            continue
    
    conn.commit()
    logger.info("FactInternationalTransmissionLinkFlow populated successfully")

def populate_fact_transnational_exchange_detail(conn, df, date_to_id_map):
    """Insert data into FactTransnationalExchangeDetail table."""
    cursor = conn.cursor()
    
    logger.info("DataFrame Info for Transnational Exchange Detail:")
    logger.info(f"Columns: {df.columns.tolist()}")
    logger.info(f"Shape: {df.shape}")
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

def populate_fact_time_block_power(conn, df, date_to_id_map):
    """Insert data into FactTimeBlockPowerData and FactTimeBlockGeneration tables."""
    cursor = conn.cursor()
    
    # --- Static mapping from 'HH:MM' to block number (1-96) ---
    block_time_to_number = {f"{hour:02d}:{minute:02d}": block_num+1 for block_num, (hour, minute) in enumerate([(h, m) for h in range(24) for m in [0, 15, 30, 45]])}
    
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
                # Remove seconds if present (keep only HH:MM)
                if ':' in value and len(value) > 5:
                    value = value[:5]  # Keep only HH:MM part
            return value
        except Exception as e:
            logger.warning(f"Could not clean time value '{value}': {e}")
            return None
    
    for _, row in df.iterrows():
        try:
            date_id = date_to_id_map[pd.to_datetime(row['Date']).date()]
            
            # Get time block information
            block_time = clean_time_value(row.get('TIME', ''))
            
            # Get time and convert to block number using static mapping
            time_str = str(row.get('TIME', '')).strip()
            block_number = block_time_to_number.get(time_str, 0)
            
            if not block_time:
                logger.warning(f"Invalid time block for row: {row}")
                continue
            
            # Process power data values
            frequency = clean_numeric_value(row.get('FREQUENCY (Hz)', ''))
            demand_met = clean_numeric_value(row.get('DEMAND MET (MW)', ''))
            net_demand_met = clean_numeric_value(row.get('NET DEMAND MET (MW)', ''))
            total_generation = clean_numeric_value(row.get('TOTAL GENERATION (MW)', ''))
            net_transnational_exchange = clean_numeric_value(row.get('NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export', ''))
            
            # Insert into FactTimeBlockPowerData
            cursor.execute("""
                INSERT OR REPLACE INTO FactTimeBlockPowerData 
                (DateID, BlockTime, BlockNumber, Frequency, DemandMet, NetDemandMet, TotalGeneration, NetTransnationalExchange)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date_id, block_time, block_number, frequency, demand_met, net_demand_met, total_generation, net_transnational_exchange))
            
            # Insert generation breakdown data
            generation_sources = {
                'Nuclear': row.get('NUCLEAR (MW)', None),
                'Wind': row.get('WIND (MW)', None),
                'Solar': row.get('SOLAR (MW)', None),
                'Hydro': row.get('HYDRO (MW)', None),
                'Gas': row.get('GAS (MW)', None),
                'Thermal': row.get('THERMAL (MW)', None),
                'Others': row.get('OTHERS* (MW)', None)
            }
            
            for source_name, value in generation_sources.items():
                if pd.notna(value):
                    # Get generation source ID
                    cursor.execute("SELECT GenerationSourceID FROM DimGenerationSources WHERE SourceName = ?", (source_name,))
                    source_result = cursor.fetchone()
                    
                    if source_result:
                        source_id = source_result[0]
                        generation_output = clean_numeric_value(value)
                        
                        if generation_output is not None:
                            cursor.execute("""
                                INSERT OR REPLACE INTO FactTimeBlockGeneration 
                                (DateID, BlockTime, BlockNumber, GenerationSourceID, GenerationOutput)
                                VALUES (?, ?, ?, ?, ?)
                            """, (date_id, block_time, block_number, source_id, generation_output))
            
        except Exception as e:
            logger.error(f"Error processing Block-wise row: {e}")
    
    conn.commit()
    logger.info("FactTimeBlockPowerData and FactTimeBlockGeneration populated successfully")

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

def process_pdf_and_insert_data(pdf_path, db_name=DATABASE_NAME):
    """Main function to process PDF and insert data into database using stable approach"""
    try:
        # Create database connection
        conn = create_connection(db_name)
        if not conn:
            logger.error("Failed to create database connection")
            return False
        
        # Ensure required dimension data exists
        cursor = conn.cursor()
        ensure_required_countries(cursor)
        # ensure_required_states(cursor)
        ensure_required_mechanisms(cursor)
        ensure_required_generation_sources(cursor)
        conn.commit()
        
        # Parse PDF using modular parser
        parser = PSPReportParser()
        results = parser.parse_pdf(pdf_path)
        
        if not results['success']:
            logger.error("PDF parsing failed")
            return False
        
        dataframes = results['final_tables']
        report_date = results['report_date']
        
        logger.info(f"Report Date: {report_date}")
        logger.info(f"Tables extracted: {len([df for df in dataframes if df is not None])}/{len(dataframes)}")
        
        # Get all unique dates from dataframes
        all_dates = set()
        for df in dataframes:
            if df is not None and not df.empty and 'Date' in df.columns:
                all_dates.update(pd.to_datetime(df['Date']).dt.date)
        
        # Create date mapping
        date_to_id_map = {
            date: insert_date_dimension(conn, date)
            for date in sorted(all_dates)
        }
        
        # Insert reports into DimReports
        for date in sorted(all_dates):
            date_id = date_to_id_map[date]
            report_name = f"PSP_Report_{date.strftime('%Y_%m_%d')}"
            cursor.execute("""
                INSERT OR REPLACE INTO DimReports (DateID, ReportName, ReportPath, Source)
                VALUES (?, ?, ?, ?)
            """, (date_id, report_name, pdf_path, 'NLDC'))
            logger.info(f"Inserted report record: {report_name}")
        
        # Process each dataframe using stable approach
        for i, df in enumerate(dataframes):
            if df is None or df.empty:
                logger.warning(f"Skipping empty DataFrame at index {i}")
                continue
                
            try:
                if i == 0:  # Regional Summary (All India Summary)
                    logger.info(f"Processing DataFrame {i}: Regional Summary")
                    populate_fact_all_india_summary(conn, df, date_to_id_map)
                elif i == 1:  # States Data
                    logger.info(f"Processing DataFrame {i}: States Data")
                    populate_fact_state_energy(conn, df, date_to_id_map)
                elif i == 2:  # Transnational Exchange (International Net)
                    logger.info(f"Processing DataFrame {i}: Transnational Exchange")
                    populate_fact_country_daily_exchange(conn, df, date_to_id_map)
                elif i == 3:  # Inter-Region Transmission Flow
                    logger.info(f"Processing DataFrame {i}: Inter-Region Transmission Flow")
                    populate_fact_transmission_link_flow(conn, df, date_to_id_map)
                elif i == 4:  # International Transmission Flow
                    logger.info(f"Processing DataFrame {i}: International Transmission Flow")
                    populate_fact_line_congestion(conn, df, date_to_id_map)
                elif i == 5:  # Cross Border Exchange
                    logger.info(f"Processing DataFrame {i}: Cross Border Exchange")
                    populate_fact_transnational_exchange_detail(conn, df, date_to_id_map)
                elif i == 6:  # Blockwise Data
                    logger.info(f"Processing DataFrame {i}: Blockwise Data")
                    populate_fact_time_block_power(conn, df, date_to_id_map)
                else:
                    logger.warning(f"Unknown DataFrame type at index {i}")
            except Exception as e:
                logger.error(f"Error processing DataFrame at index {i}: {e}")
                continue
        
        # Ensure all regions and countries are present in dimension tables
        ensure_all_regions_countries(conn, dataframes)
        
        logger.info("Data insertion completed successfully")
        conn.commit()
        conn.close()
        
        logger.info("✅ PDF processing and data insertion completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_pdf_and_insert_data: {e}")
        return False

if __name__ == "__main__":
    # Example usage
    pdf_path = "sample input/19.04.25_NLDC_PSP.pdf"
    success = process_pdf_and_insert_data(pdf_path)
    
    if success:
        logger.info("✅ PDF processing and data insertion completed successfully!")
    else:
        logger.error("❌ PDF processing and data insertion failed!")
    
    # Keep console open for inspection
    input("\nPress Enter to exit...")