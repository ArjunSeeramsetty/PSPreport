import sqlite3
import logging
import os

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages the initial setup and one-time population of the SQLite database."""
    
    def __init__(self, db_name: str, schema_file: str):
        """
        Initializes the DatabaseManager.

        Args:
            db_name: The filename for the SQLite database (e.g., 'power_data.db').
            schema_file: The path to the .sql file containing the DDL schema.
        """
        self.db_name = db_name
        self.schema_file = schema_file
        self.conn = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def _connect(self):
        """Establishes a database connection."""
        try:
            # Connect, creating the file if it doesn't exist
            self.conn = sqlite3.connect(self.db_name)
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self.logger.info(f"Successfully connected to database {self.db_name}")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Error connecting to database: {e}")
            return False

    def _execute_script(self, sql_script: str):
        """Executes a multi-statement SQL script."""
        try:
            self.conn.executescript(sql_script)
            self.conn.commit()
            self.logger.info("SQL script executed successfully.")
        except sqlite3.Error as e:
            self.logger.error(f"Error executing SQL script: {e}")
            raise

    def create_schema(self):
        """Creates database schema from the .sql file."""
        self.logger.info(f"Creating schema from {self.schema_file}...")
        try:
            if not os.path.exists(self.schema_file):
                raise FileNotFoundError(f"Schema file not found at path: {self.schema_file}")
            with open(self.schema_file, 'r') as f:
                schema_sql = f.read()
            self._execute_script(schema_sql)
        except (FileNotFoundError, Exception) as e:
            self.logger.error(f"Failed to create schema: {e}")
            raise

    def populate_all_dimensions(self):
        """Orchestrates the population of all dimension tables with seed data."""
        self.logger.info("Populating all dimension tables with initial data...")
        self._populate_dim_units()
        self._populate_dim_regions()
        self._populate_dim_states()
        self._populate_dim_countries()
        self._populate_dim_generation_sources()
        self._populate_dim_transmission_lines()
        self._populate_dim_exchange_mechanisms()
        self._populate_meta_table_column_units()
        self.logger.info("All dimension tables populated.")

    def _populate_dim_units(self):
        """Populates the DimUnits table with predefined units."""
        self.logger.info("Populating DimUnits...")
        cursor = self.conn.cursor()
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
            self.conn.commit()
            self.logger.info("DimUnits populated successfully")
        except sqlite3.Error as e:
            self.logger.error(f"Error populating DimUnits: {e}")
            raise

    def _populate_dim_regions(self):
        """Populates DimRegions with canonical region names."""
        self.logger.info("Populating DimRegions...")
        cursor = self.conn.cursor()
        regions = [
            ('Northern Region',),
            ('Western Region',),
            ('Southern Region',),
            ('Eastern Region',),
            ('North Eastern Region',),
            ('India',)
        ]
        try:
            cursor.executemany(
                "INSERT OR IGNORE INTO DimRegions (RegionName) VALUES (?)", regions
            )
            self.conn.commit()
            self.logger.info("DimRegions populated successfully")
        except sqlite3.Error as e:
            self.logger.error(f"Error populating DimRegions: {e}")
            raise

    def _populate_dim_states(self):
        """Populates DimStates with state data mapped to regions."""
        self.logger.info("Populating DimStates...")
        cursor = self.conn.cursor()
        
        # Get region mapping
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
        try:
            cursor.executemany(
                "INSERT OR IGNORE INTO DimStates (StateName, RegionID) VALUES (?, ?)", states
            )
            self.conn.commit()
            self.logger.info("DimStates populated successfully")
        except sqlite3.Error as e:
            self.logger.error(f"Error populating DimStates: {e}")
            raise

    def _populate_dim_countries(self):
        """Populates DimCountries with international country data."""
        self.logger.info("Populating DimCountries...")
        cursor = self.conn.cursor()
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
        try:
            cursor.executemany(
                "INSERT OR IGNORE INTO DimCountries (CountryName) VALUES (?)", countries
            )
            self.conn.commit()
            self.logger.info("DimCountries populated successfully")
        except sqlite3.Error as e:
            self.logger.error(f"Error populating DimCountries: {e}")
            raise

    def _populate_dim_generation_sources(self):
        """Populates DimGenerationSources with canonical generation sources."""
        self.logger.info("Populating DimGenerationSources...")
        cursor = self.conn.cursor()
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
            ('RE', 'Renewable'),
            ('Total', 'Total')
        ]
        try:
            cursor.executemany(
                "INSERT OR IGNORE INTO DimGenerationSources (SourceName, SourceCategory) VALUES (?, ?)", sources
            )
            self.conn.commit()
            self.logger.info("DimGenerationSources populated successfully")
        except sqlite3.Error as e:
            self.logger.error(f"Error populating DimGenerationSources: {e}")
            raise

    def _populate_dim_transmission_lines(self):
        """Populates DimTransmissionLines with transmission line data."""
        self.logger.info("Populating DimTransmissionLines...")
        cursor = self.conn.cursor()
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
            ('XELDEM-AMBEWADI', '220 kV', 1.0),
            ('Total', None, None)
        ]
        try:
            cursor.executemany(
                "INSERT OR IGNORE INTO DimTransmissionLines (LineIdentifier, VoltageLevel_kV, NumberOfCircuits) VALUES (?, ?, ?)", lines
            )
            self.conn.commit()
            self.logger.info("DimTransmissionLines populated successfully")
        except sqlite3.Error as e:
            self.logger.error(f"Error populating DimTransmissionLines: {e}")
            raise

    def _populate_dim_exchange_mechanisms(self):
        """Populates DimExchangeMechanisms with exchange mechanism data."""
        self.logger.info("Populating DimExchangeMechanisms...")
        cursor = self.conn.cursor()
        mechanisms = [
            ('PPA',),
            ('Bilateral',),
            ('DAM IEX',),
            ('DAM PXIL',),
            ('DAM HPX',),
            ('RTM IEX',),
            ('RTM PXIL',),
            ('RTM HPX',),
            ('TOTAL',)
        ]
        try:
            cursor.executemany(
                "INSERT OR IGNORE INTO DimExchangeMechanisms (MechanismName) VALUES (?)", mechanisms
            )
            self.conn.commit()
            self.logger.info("DimExchangeMechanisms populated successfully")
        except sqlite3.Error as e:
            self.logger.error(f"Error populating DimExchangeMechanisms: {e}")
            raise

    def _populate_meta_table_column_units(self):
        """Populates the MetaTableColumnUnits table with column-to-unit mappings."""
        self.logger.info("Populating MetaTableColumnUnits...")
        cursor = self.conn.cursor()
        
        # Fetch UnitIDs
        cursor.execute("SELECT UnitSymbol, UnitID FROM DimUnits")
        unit_map = {row[0]: row[1] for row in cursor.fetchall()}

        # List of (TableName, ColumnName, UnitSymbol)
        mappings = [
            # FactAllIndiaDailySummary
            ('FactAllIndiaDailySummary', 'ShareRESInTotalGeneration', unit_map.get('%')),
            ('FactAllIndiaDailySummary', 'EveningPeakDemandMet', unit_map.get('MW')),
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
            
            # FactCountryDailyExchange
            ('FactCountryDailyExchange', 'TotalEnergyExchanged', unit_map.get('MU')),
            ('FactCountryDailyExchange', 'PeakExchange', unit_map.get('MW')),
            
            # FactInternationalTransmissionLinkFlow
            ('FactInternationalTransmissionLinkFlow', 'MaxLoading', unit_map.get('MW')),
            ('FactInternationalTransmissionLinkFlow', 'MinLoading', unit_map.get('MW')),
            ('FactInternationalTransmissionLinkFlow', 'AvgLoading', unit_map.get('MW')),
            ('FactInternationalTransmissionLinkFlow', 'EnergyExchanged', unit_map.get('MU')),
            
            # FactTransnationalExchangeDetail
            ('FactTransnationalExchangeDetail', 'ExchangeValue', unit_map.get('MU'))
        ]
        
        try:
            cursor.executemany(
                "INSERT OR IGNORE INTO MetaTableColumnUnits (TableName, ColumnName, UnitID) VALUES (?, ?, ?)", mappings
            )
            self.conn.commit()
            self.logger.info("MetaTableColumnUnits populated successfully")
        except sqlite3.Error as e:
            self.logger.error(f"Error populating MetaTableColumnUnits: {e}")
            raise
    
    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.logger.info("Database connection closed.")

    def run_setup(self):
        """Executes the full database setup process: connect, create, populate, and close."""
        self.logger.info("--- Starting Database Setup ---")
        if self._connect():
            try:
                self.create_schema()
                self.populate_all_dimensions()
                self.logger.info("--- Database Setup Completed Successfully ---")
            except Exception as e:
                self.logger.error(f"--- Database Setup Failed: {e} ---", exc_info=True)
            finally:
                self.close()

def main():
    """Main function to set up the database and populate initial data"""
    # Create a database connection
    db_manager = DatabaseManager(db_name='power_data.db', schema_file='SQL_power_data.sql')
    db_manager.run_setup()

if __name__ == '__main__':
    main()