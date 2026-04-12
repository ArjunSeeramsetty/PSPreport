import sqlite3
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATABASE_NAME = 'power_data.db'

def create_connection(db_file):
    """ Create a database connection to a SQLite database """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        # Enable foreign key constraint enforcement
        conn.execute("PRAGMA foreign_keys = ON;")
        logger.info(f"SQLite version: {sqlite3.sqlite_version}")
        logger.info(f"Successfully connected to database {db_file}")
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database: {e}")
    return conn

def execute_sql_from_string(conn, sql_string):
    """ Execute a multi-statement SQL string """
    try:
        cursor = conn.cursor()
        cursor.executescript(sql_string)  # Use executescript for multi-statement SQL
        conn.commit()
        logger.info("SQL script executed successfully.")
    except sqlite3.Error as e:
        logger.error(f"Error executing SQL script: {e}")
        raise

def get_schema_sql():
    """ Returns the entire DDL schema as a single string """
    # The schema SQL is now loaded from SQL_power_data.sql
    try:
        with open('SQL_power_data.sql', 'r') as sql_file:
            return sql_file.read()
    except FileNotFoundError:
        logger.error("SQL_power_data.sql file not found")
        raise

def populate_dim_units(conn):
    """Populates the DimUnits table with predefined units."""
    cursor = conn.cursor()
    units_data = [
        ('MegaWatts', 'MW', 'Power', 'Standard unit of active power'),
        ('Million Units', 'MU', 'Energy', '1 MU = 1 GWh, Standard unit of energy'),
        ('Hertz', 'Hz', 'Frequency', 'Standard unit of electrical frequency'),
        ('Percent', '%', 'Ratio', 'Dimensionless unit for ratios or shares'),
        ('Kilovolt', 'kV', 'Voltage', 'Unit of electrical potential'),
        ('Index', 'Index', 'Index', 'Dimensionless index value'),
        ('Hours', 'hrs', 'TimeDuration', 'Unit of time duration'),
        ('Count', 'Count', 'Count', 'Simple count of items'),
        ('Time', 'HH:MM:SS', 'Time', 'Time in hours:minutes:seconds format')
    ]
    try:
        cursor.executemany(
            "INSERT OR IGNORE INTO DimUnits (UnitName, UnitSymbol, UnitCategory, Description) VALUES (?, ?, ?, ?)",
            units_data
        )
        conn.commit()
        logger.info("DimUnits populated successfully")
    except sqlite3.Error as e:
        logger.error(f"Error populating DimUnits: {e}")
        raise

def populate_dim_regions(conn):
    cursor = conn.cursor()
    regions = [
        ('Northern Region',),
        ('Western Region',),
        ('Southern Region',),
        ('Eastern Region',),
        ('North Eastern Region',),
        ('India',)  # If you use 'India' as a region
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO DimRegions (RegionName) VALUES (?)", regions
    )
    conn.commit()

def populate_dim_states(conn):
    cursor = conn.cursor()
    # Example: (StateName, RegionID)
    # You must first ensure regions are populated and get their IDs
    region_map = {}
    cursor.execute("SELECT RegionID, RegionName FROM DimRegions")
    for rid, rname in cursor.fetchall():
        region_map[rname] = rid

    states = [
        ### Northern Region
        ('Punjab', region_map['Northern Region']),
        ('Haryana', region_map['Northern Region']),
        ('Rajasthan', region_map['Northern Region']),
        ('Delhi', region_map['Northern Region']),
        ('UP', region_map['Northern Region']),
        ('Uttarakhand', region_map['Northern Region']),
        ('HP', region_map['Northern Region']),
        ('J&K(UT) & Ladakh(UT)', region_map['Northern Region']),
        ('Chandigarh', region_map['Northern Region']),
        ('Railways_NR ISTS', region_map['Northern Region']),
        
        ### Western Region
        ('Chhattisgarh', region_map['Western Region']),
        ('Gujarat', region_map['Western Region']),
        ('MP', region_map['Western Region']),
        ('Maharashtra', region_map['Western Region']),
        ('Goa', region_map['Western Region']),
        ('DNHDDPDCL', region_map['Western Region']),
        ('AMNSIL', region_map['Western Region']),
        ('BALCO', region_map['Western Region']),
        ('RIL JAMNAGAR', region_map['Western Region']),

        ### Southern Region
        ('Andhra Pradesh', region_map['Southern Region']),
        ('Telangana', region_map['Southern Region']),
        ('Karnataka', region_map['Southern Region']),
        ('Kerala', region_map['Southern Region']),
        ('Tamil Nadu', region_map['Southern Region']),
        ('Puducherry', region_map['Southern Region']),

        ### Eastern Region
        ('Bihar', region_map['Eastern Region']),
        ('DVC', region_map['Eastern Region']),
        ('Jharkhand', region_map['Eastern Region']),
        ('Odisha', region_map['Eastern Region']),
        ('West Bengal', region_map['Eastern Region']),
        ('Sikkim', region_map['Eastern Region']),
        ('Railways_ER ISTS', region_map['Eastern Region']),

        ### North-Eastern Region
        ('Arunachal Pradesh', region_map['North Eastern Region']),
        ('Assam', region_map['North Eastern Region']),
        ('Manipur', region_map['North Eastern Region']),
        ('Meghalaya', region_map['North Eastern Region']),
        ('Mizoram', region_map['North Eastern Region']),
        ('Nagaland', region_map['North Eastern Region']),
        ('Tripura', region_map['North Eastern Region'])

    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO DimStates (StateName, RegionID) VALUES (?, ?)", states
    )
    conn.commit()

def populate_dim_countries(conn):
    cursor = conn.cursor()
    countries = [
        ('Bhutan',),
        ('Nepal',),
        ('Bangladesh',),
        ('Myanmar',),
        ('Godda (Bangladesh)',),
        ('Total Export',),
        ('Total Import',),
        ('Total Net',)
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO DimCountries (CountryName) VALUES (?)", countries
    )
    conn.commit()

def populate_dim_generation_sources(conn):
    cursor = conn.cursor()
    # Canonical list: single source of truth for generation sources and categories
    sources = [
        ('Coal', 'Thermal'),
        ('Lignite', 'Thermal'),
        ('Gas', 'Thermal'),
        ('Naptha', 'Thermal'),
        ('Diesel', 'Thermal'),
        ('Gas, Naptha & Diesel', 'Thermal'),
        ('Thermal', 'Thermal'),
        ('Hydro', 'Hydro'),
        ('Nuclear', 'Nuclear'),
        ('Solar', 'Renewable'),
        ('Wind', 'Renewable'),
        ('Biomass', 'Renewable'),
        ('Others', 'Renewable'),
        ('RE', 'Renewable')
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO DimGenerationSources (SourceName, SourceCategory) VALUES (?, ?)", sources
    )
    conn.commit()

def populate_dim_transmission_lines(conn):
    cursor = conn.cursor()
    # Example: (LineIdentifier, VoltageLevel_kV, NumberOfCircuits)
    lines = [
        ('ALIPURDUAR-AGRA', 'HVDC', 2.0),
        ('PUSAULI  B/B', 'HVDC', None),
        ('GAYA-VARANASI', '765 kV', 2.0),
        ('SASARAM-FATEHPUR', '765 kV', 1.0),
        ('GAYA-BALIA', '765 kV', 1.0),
        ('PUSAULI-VARANASI', '400 kV', 1.0),
        ('PUSAULI -ALLAHABAD', '400 kV', 1.0),
        ('MUZAFFARPUR-GORAKHPUR', '400 kV', 2.0),
        ('PATNA-BALIA', '400 kV', 2.0),
        ('NAUBATPUR-BALIA', '400 kV', 2.0),
        ('BIHARSHARIFF-BALIA', '400 kV', 2.0),
        ('MOTIHARI-GORAKHPUR', '400 kV', 2.0),
        ('BIHARSARIFF-SAHUPURI', '400 kV', 2.0),
        ('SAHUPURI-KARAMNASA', '220 kV', 1.0),
        ('NAGAR UNTARI-RIHAND', '132 kV', 1.0),
        ('GARWAH-RIHAND', '132 kV', 1.0),
        ('KARMANASA-SAHUPURI', '132 kV', 1.0),
        ('KARMANASA-CHANDAULI', '132 kV', 1.0),
        ('JHARSUGUDA-DHARAMJAIGARH', '765 kV', 4.0),
        ('NEW RANCHI-DHARAMJAIGARH', '765 kV', 2.0),
        ('JHARSUGUDA-DURG', '765 kV', 2.0),
        ('JHARSUGUDA-RAIGARH', '400 kV', 4.0),
        ('RANCHI-SIPAT', '400 kV', 2.0),
        ('BUDHIPADAR-RAIGARH', '220 kV', 1.0),
        ('BUDHIPADAR-KORBA', '220 kV', 2.0),
        ('JEYPORE-GAZUWAKA B/B', 'HVDC', 2.0),
        ('TALCHER-KOLAR BIPOLE', 'HVDC', 2.0),
        ('ANGUL-SRIKAKULAM', '765 kV', 2.0),
        ('TALCHER-I/C', '400 kV', 2.0),
        ('BALIMELA-UPPER-SILERRU', '220 kV', 1.0),
        ('BINAGURI-BONGAIGAON', '400 kV', 2.0),
        ('ALIPURDUAR-BONGAIGAON', '400 kV', 2.0),
        ('ALIPURDUAR-SALAKATI', '220 kV', 2.0),
        ('BISWANATH CHARIALI-AGRA', 'HVDC', 2.0),
        ('CHAMPA-KURUKSHETRA', 'HVDC', 2.0),
        ('VINDHYACHAL B/B', 'HVDC', None),
        ('MUNDRA-MOHINDERGARH', 'HVDC', 2.0),
        ('GWALIOR-AGRA', '765 kV', 2.0),
        ('GWALIOR-PHAGI', '765 kV', 2.0),
        ('JABALPUR-ORAI', '765 kV', 2.0),
        ('GWALIOR-ORAI', '765 kV', 1.0),
        ('SATNA-ORAI', '765 kV', 1.0),
        ('BANASKANTHA-CHITORGARH', '765 kV', 2.0),
        ('VINDHYACHAL-VARANASI', '765 kV', 2.0),
        ('ZERDA-KANKROLI', '400 kV', 1.0),
        ('ZERDA -BHINMAL', '400 kV', 1.0),
        ('VINDHYACHAL -RIHAND', '400 kV', 1.0),
        ('RAPP-SHUJALPUR', '400 kV', 2.0),
        ('NEEMUCH-Chittorgarh', '400 kV', 2.0),
        ('BHANPURA-RANPUR', '220 kV', 1.0),
        ('BHANPURA-MORAK', '220 kV', 1.0),
        ('MEHGAON-AURAIYA', '220 kV', 1.0),
        ('MALANPUR-AURAIYA', '220 kV', 1.0),
        ('GWALIOR-SAWAI MADHOPUR', '132 kV', 1.0),
        ('RAJGHAT-LALITPUR', '132 kV', 2.0),
        ('BHADRAWATI B/B', 'HVDC', None),
        ('RAIGARH-PUGALUR', 'HVDC', 2.0),
        ('SOLAPUR-RAICHUR', '765 kV', 2.0),
        ('WARDHA-NIZAMABAD', '765 kV', 2.0),
        ('WARORA-WARANGAL(NEW)', '765 kV', 2.0),
        ('KOLHAPUR-KUDGI', '400 kV', 2.0),
        ('KOLHAPUR-CHIKODI', '220 kV', 2.0),
        ('PONDA-AMBEWADI', '220 kV', 1.0),
        ('XELDEM-AMBEWADI', '220 kV', 1.0)
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO DimTransmissionLines (LineIdentifier, VoltageLevel_kV, NumberOfCircuits) VALUES (?, ?, ?)", lines
    )
    conn.commit()

def populate_dim_exchange_mechanisms(conn):
    cursor = conn.cursor()
    mechanisms = [
        ('PPA',),
        ('Bilateral',),
        ('DAM IEX',),
        ('DAM PXIL',),
        ('DAM HPX',),
        ('RTM IEX',),
        ('RTM PXIL',),
        ('RTM HPX',)
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO DimExchangeMechanisms (MechanismName) VALUES (?)", mechanisms
    )
    conn.commit()

def populate_meta_table_column_units(conn):
    """Populates the MetaTableColumnUnits table with column-to-unit mappings."""
    cursor = conn.cursor()
    # Fetch UnitIDs
    cursor.execute("SELECT UnitSymbol, UnitID FROM DimUnits")
    unit_map = {row[0]: row[1] for row in cursor.fetchall()}

    # List of (TableName, ColumnName, UnitSymbol)
    mappings = [
        # FactAllIndiaDailySummary
        ('FactAllIndiaDailySummary', 'ShareRESInTotalGeneration', unit_map.get('%')),
        ('FactAllIndiaDailySummary', 'PeakDemandMet', unit_map.get('MW')),
        ('FactAllIndiaDailySummary', 'PeakShortage', unit_map.get('MW')),
        ('FactAllIndiaDailySummary', 'EnergyMet', unit_map.get('MU')),
        ('FactAllIndiaDailySummary', 'EnergyShortage', unit_map.get('MU')),
        ('FactAllIndiaDailySummary', 'MaxDemandSCADA', unit_map.get('MW')),
        ('FactAllIndiaDailySummary', 'ScheduleDrawal', unit_map.get('MU')),
        ('FactAllIndiaDailySummary', 'ActualDrawal', unit_map.get('MU')),
        ('FactAllIndiaDailySummary', 'OverUnderDrawal', unit_map.get('MU')),
        ('FactAllIndiaDailySummary', 'FrequencyViolationIndex', unit_map.get('Index')),
        ('FactAllIndiaDailySummary', 'DurationFrequencyBelow49_7', unit_map.get('%')),
        ('FactAllIndiaDailySummary', 'DurationFrequency_49_7_to_49_8', unit_map.get('%')),
        ('FactAllIndiaDailySummary', 'DurationFrequency_49_8_to_49_9', unit_map.get('%')),
        ('FactAllIndiaDailySummary', 'DurationFrequencyBelow49_9', unit_map.get('%')),
        ('FactAllIndiaDailySummary', 'DurationFrequency_49_9_to_50_05', unit_map.get('%')),
        ('FactAllIndiaDailySummary', 'DurationFrequencyAbove50_05', unit_map.get('%')),
        ('FactAllIndiaDailySummary', 'RegionDDF', unit_map.get('%')),
        ('FactAllIndiaDailySummary', 'StatesDDF', unit_map.get('%')),
        ('FactAllIndiaDailySummary', 'SolarHRMaxDemand', unit_map.get('MW')),
        ('FactAllIndiaDailySummary', 'SolarHRMaxDemandTime', unit_map.get('HH:MM:SS')),
        ('FactAllIndiaDailySummary', 'SolarHRShortage', unit_map.get('MW')),
        ('FactAllIndiaDailySummary', 'NonSolarHRMaxDemand', unit_map.get('MW')),
        ('FactAllIndiaDailySummary', 'NonSolarHRMaxDemandTime', unit_map.get('HH:MM:SS')),
        ('FactAllIndiaDailySummary', 'NonSolarHRShortage', unit_map.get('MW')),
        
        # FactStateDailyEnergy
        ('FactStateDailyEnergy', 'MaximumDemand', unit_map.get('MW')),
        ('FactStateDailyEnergy', 'Shortage', unit_map.get('MW')),
        ('FactStateDailyEnergy', 'EnergyMet', unit_map.get('MU')),
        ('FactStateDailyEnergy', 'DrawalSchedule', unit_map.get('MU')),
        ('FactStateDailyEnergy', 'OverUnderDrawal', unit_map.get('MU')),
        ('FactStateDailyEnergy', 'MaxOverDrawal', unit_map.get('MW')),
        ('FactStateDailyEnergy', 'EnergyShortage', unit_map.get('MU')),
        
        # FactTransmissionLinkFlow
        ('FactTransmissionLinkFlow', 'MaxImport', unit_map.get('MW')),
        ('FactTransmissionLinkFlow', 'MaxExport', unit_map.get('MW')),
        ('FactTransmissionLinkFlow', 'ImportEnergy', unit_map.get('MU')),
        ('FactTransmissionLinkFlow', 'ExportEnergy', unit_map.get('MU')),
        ('FactTransmissionLinkFlow', 'NetImportEnergy', unit_map.get('MU')),
        
        # FactTimeBlockPowerData
        ('FactTimeBlockPowerData', 'Frequency', unit_map.get('Hz')),
        ('FactTimeBlockPowerData', 'DemandMet', unit_map.get('MW')),
        ('FactTimeBlockPowerData', 'NetDemandMet', unit_map.get('MW')),
        ('FactTimeBlockPowerData', 'TotalGeneration', unit_map.get('MW')),
        ('FactTimeBlockPowerData', 'NetTransnationalExchange', unit_map.get('MW')),
        
        # FactTimeBlockGeneration
        ('FactTimeBlockGeneration', 'GenerationOutput', unit_map.get('MW')),
        
        # FactDailyGenerationBreakdown
        ('FactDailyGenerationBreakdown', 'GenerationAmount', unit_map.get('MU')),
        ('FactDailyGenerationBreakdown', 'InstalledCapacity', unit_map.get('MW')),
        
        # FactCountryDailyExchange
        ('FactCountryDailyExchange', 'TotalEnergyExchanged', unit_map.get('MU')),
        ('FactCountryDailyExchange', 'PeakExchange', unit_map.get('MW')),
        
        # FactLineCongestion
        ('FactLineCongestion', 'MaxLoading', unit_map.get('MW')),
        ('FactLineCongestion', 'MinLoading', unit_map.get('MW')),
        ('FactLineCongestion', 'AvgLoading', unit_map.get('MW')),
        ('FactLineCongestion', 'EnergyExchanged', unit_map.get('MU')),
        
        # FactTransnationalExchangeDetail
        ('FactTransnationalExchangeDetail', 'ExchangeValue', unit_map.get('MU'))

    ]
    
    try:
        cursor.executemany(
            "INSERT OR IGNORE INTO MetaTableColumnUnits (TableName, ColumnName, UnitID) VALUES (?, ?, ?)", mappings
        )
        conn.commit()
        logger.info("MetaTableColumnUnits populated successfully")
    except sqlite3.Error as e:
        logger.error(f"Error populating MetaTableColumnUnits: {e}")
        raise

def main():
    """Main function to set up the database and populate initial data"""
    # Create a database connection
    conn = create_connection(DATABASE_NAME)

    if conn is not None:
        try:
            # Get the DDL schema from SQL file
            schema_sql = get_schema_sql()
            
            # Create tables
            execute_sql_from_string(conn, schema_sql)
            
            # Populate dimension tables with initial data
            populate_dim_units(conn)
            populate_dim_regions(conn)
            populate_dim_states(conn)
            populate_dim_countries(conn)
            populate_dim_generation_sources(conn)
            populate_dim_transmission_lines(conn)
            populate_dim_exchange_mechanisms(conn)
            populate_meta_table_column_units(conn)
            
            logger.info(f"Database {DATABASE_NAME} setup completed successfully.")
        except Exception as e:
            logger.error(f"Error during database setup: {e}")
            raise
        finally:
            conn.close()
    else:
        logger.error("Error! Cannot create the database connection.")

if __name__ == '__main__':
    main()