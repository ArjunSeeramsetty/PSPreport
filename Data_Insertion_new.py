#!/usr/bin/env python3
"""
Data Insertion with Smart Classification and Fuzzy Mapping
"""

import pandas as pd
import logging
from typing import List, Dict, Any, Optional
from enhanced_data_insertion import enhance_data_insertion

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DataLoaderNew:
    """Enhanced data loader with smart classification and fuzzy mapping"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path

    def process_pdf_dataframes(self, dataframes_list: List[pd.DataFrame]) -> List[pd.DataFrame]:
        """
        Process PDF dataframes using smart classification and fuzzy mapping.
        Returns standardized dataframes ready for DB insertion.
        """
        logger.info(f"Processing {len(dataframes_list)} dataframes with smart classification...")
        standardized_dfs = enhance_data_insertion(dataframes_list, db_path=self.db_path)
        logger.info(f"Standardized {len(standardized_dfs)} dataframes for DB insertion.")
        return standardized_dfs

    def insert_to_db(self, standardized_dfs: List[pd.DataFrame], date_to_id_map: Dict[Any, int]):
        """
        Insert standardized dataframes into the database using all the populate functions.
        This integrates the smart classification system with the existing database insertion logic.
        """
        logger.info("Starting database insertion with smart classification...")
        
        # Import the original DataLoader for database operations
        from Data_Insertion import DataLoader as OldDataLoader
        old_loader = OldDataLoader(self.db_path)
        
        # Connect to database
        if not old_loader._connect():
            logger.error("Failed to connect to database")
            return
        
        try:
            # Process each standardized dataframe based on its position/type
            # The enhanced_data_insertion.py returns dataframes in a specific order:
            # [regional_summary, state_energy, international_exchange, transmission_flow, generation_breakdown]
            
            for i, df in enumerate(standardized_dfs):
                if df.empty:
                    logger.warning(f"Dataframe {i} is empty, skipping...")
                    continue
                
                logger.info(f"Processing dataframe {i} with shape {df.shape}")
                
                # Determine table type based on position and content
                table_type = self._determine_table_type(df, i)
                logger.info(f"Identified table type: {table_type}")
                
                # Call appropriate populate function based on table type
                if table_type == "regional_summary":
                    logger.info("Populating FactAllIndiaDailySummary...")
                    old_loader.populate_fact_all_india_summary(df, date_to_id_map)
                    
                elif table_type == "state_energy":
                    logger.info("Populating FactStateEnergy...")
                    old_loader.populate_fact_state_energy(df, date_to_id_map)
                    
                elif table_type == "international_exchange":
                    logger.info("Populating FactCountryDailyExchange...")
                    old_loader.populate_fact_country_daily_exchange(df, date_to_id_map)
                    
                elif table_type == "transmission_flow":
                    logger.info("Populating FactTransmissionLinkFlow...")
                    old_loader.populate_fact_transmission_link_flow(df, date_to_id_map)
                    
                elif table_type == "generation_breakdown":
                    logger.info("Populating FactDailyGenerationBreakdown...")
                    old_loader.populate_fact_daily_generation_breakdown(df, date_to_id_map)
                    
                elif table_type == "re_share":
                    logger.info("Populating FactREShare...")
                    old_loader.populate_fact_re_share(df, date_to_id_map)
                    
                elif table_type == "time_block":
                    logger.info("Populating FactTimeBlockPower...")
                    old_loader.populate_fact_time_block_power(df, date_to_id_map)
                    
                elif table_type == "line_congestion":
                    logger.info("Populating FactLineCongestion...")
                    old_loader.populate_fact_line_congestion(df, date_to_id_map)
                    
                elif table_type == "transnational_exchange":
                    logger.info("Populating FactTransnationalExchangeDetail...")
                    old_loader.populate_fact_transnational_exchange_detail(df, date_to_id_map)
                    
                else:
                    logger.warning(f"Unknown table type: {table_type}, attempting generic processing...")
                    # Try to process with the most likely function based on column content
                    self._process_unknown_table(df, date_to_id_map, old_loader)
            
            logger.info("Database insertion completed successfully")
            
        except Exception as e:
            logger.error(f"Error during database insertion: {e}")
            raise
        finally:
            # Close database connection
            if old_loader.conn:
                old_loader.conn.close()
                logger.info("Database connection closed")

    def _determine_table_type(self, df: pd.DataFrame, position: int) -> str:
        """
        Determine the table type based on position and column content analysis.
        """
        if df.empty:
            return "unknown"
        
        columns = [str(col).lower() for col in df.columns]
        column_text = " ".join(columns)
        
        # Check for specific patterns in columns
        if any(keyword in column_text for keyword in ['demand met', 'energy met', 'peak demand']):
            return "regional_summary"
        elif any(keyword in column_text for keyword in ['states', 'maximum demand']):
            return "state_energy"
        elif any(keyword in column_text for keyword in ['bhutan', 'nepal', 'bangladesh', 'international']):
            return "international_exchange"
        elif any(keyword in column_text for keyword in ['transmission', 'import', 'export', 'schedule']):
            return "transmission_flow"
        elif any(keyword in column_text for keyword in ['coal', 'hydro', 'nuclear', 'generation']):
            return "generation_breakdown"
        elif any(keyword in column_text for keyword in ['re', 'renewable', 'share']):
            return "re_share"
        elif any(keyword in column_text for keyword in ['time block', 'frequency']):
            return "time_block"
        elif any(keyword in column_text for keyword in ['congestion', 'line']):
            return "line_congestion"
        elif any(keyword in column_text for keyword in ['transnational']):
            return "transnational_exchange"
        
        # Fallback based on position (as defined in enhanced_data_insertion.py)
        position_mapping = {
            0: "regional_summary",
            1: "state_energy", 
            2: "international_exchange",
            3: "transmission_flow",
            4: "generation_breakdown"
        }
        
        return position_mapping.get(position, "unknown")

    def _process_unknown_table(self, df: pd.DataFrame, date_to_id_map: Dict[Any, int], old_loader):
        """
        Process unknown table types by trying different populate functions.
        """
        columns = [str(col).lower() for col in df.columns]
        column_text = " ".join(columns)
        
        # Try to match based on column patterns
        if any(keyword in column_text for keyword in ['demand', 'energy', 'peak']):
            logger.info("Attempting FactAllIndiaDailySummary based on column content...")
            try:
                old_loader.populate_fact_all_india_summary(df, date_to_id_map)
                return
            except Exception as e:
                logger.warning(f"Failed to populate as FactAllIndiaDailySummary: {e}")
        
        if any(keyword in column_text for keyword in ['states', 'state']):
            logger.info("Attempting FactStateEnergy based on column content...")
            try:
                old_loader.populate_fact_state_energy(df, date_to_id_map)
                return
            except Exception as e:
                logger.warning(f"Failed to populate as FactStateEnergy: {e}")
        
        if any(keyword in column_text for keyword in ['coal', 'hydro', 'nuclear']):
            logger.info("Attempting FactDailyGenerationBreakdown based on column content...")
            try:
                old_loader.populate_fact_daily_generation_breakdown(df, date_to_id_map)
                return
            except Exception as e:
                logger.warning(f"Failed to populate as FactDailyGenerationBreakdown: {e}")
        
        logger.warning(f"Could not determine appropriate populate function for table with columns: {list(df.columns)}")

# Example usage
if __name__ == "__main__":
    from custom_pdf_parser import CustomPDFParser
    import os
    import sqlite3
    from datetime import datetime

    pdf_path = "Output/NLDC_PSP_URLS/2023-24/NOVEMBER/reports/01.11.23_NLDC_PSP.pdf"
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        exit(1)

    try:
        # Parse PDF
        parser = CustomPDFParser()
        dataframes_list = parser.process_pdf(pdf_path)
        logger.info(f"Parsed {len(dataframes_list)} tables from PDF")

        # Process with smart classification
        loader = DataLoaderNew(db_path='power_data.db')
        standardized_dfs = loader.process_pdf_dataframes(dataframes_list)
        logger.info(f"Standardized {len(standardized_dfs)} dataframes")

        # Create proper date_to_id_map from database
        date_to_id_map = {}
        try:
            conn = sqlite3.connect('power_data.db')
            cursor = conn.cursor()
            
            # Extract date from PDF filename
            filename = os.path.basename(pdf_path)
            date_str = filename.split('_')[0]  # Extract date part
            try:
                # Try different date formats
                for fmt in ['%d.%m.%y', '%d.%m.%Y', '%Y-%m-%d']:
                    try:
                        parsed_date = datetime.strptime(date_str, fmt).date()
                        break
                    except ValueError:
                        continue
                else:
                    logger.warning(f"Could not parse date from filename: {date_str}")
                    parsed_date = datetime.now().date()
                
                # Look up DateID in database
                cursor.execute("SELECT DateID FROM DimDates WHERE Date = ?", (parsed_date,))
                result = cursor.fetchone()
                if result:
                    date_to_id_map[parsed_date] = result[0]
                    logger.info(f"Found DateID {result[0]} for date {parsed_date}")
                else:
                    logger.warning(f"No DateID found for date {parsed_date}")
                    # Create a dummy mapping for testing
                    date_to_id_map[parsed_date] = 999
                    
            except Exception as e:
                logger.error(f"Error parsing date: {e}")
                # Create a dummy mapping for testing
                date_to_id_map[datetime.now().date()] = 999
                
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            # Create a dummy mapping for testing
            date_to_id_map[datetime.now().date()] = 999
        finally:
            if 'conn' in locals():
                conn.close()

        # Insert into database
        loader.insert_to_db(standardized_dfs, date_to_id_map)
        logger.info("Data insertion with smart classification complete.")
        
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        raise 