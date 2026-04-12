#!/usr/bin/env python3
"""
Enhanced Modular Database Insertion Script
Handles individual table insertion into the database using the modular parser output.
Enhanced with improved state name processing and fuzzy column matching.
"""

import sqlite3
import pandas as pd
import numpy as np
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import re
from pathlib import Path
from fuzzywuzzy import fuzz, process

# Import the modular parser
from modular_psp_parser import PSPReportParser

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATABASE_NAME = 'power_data.db'

class EnhancedModularDBInserter:
    """Enhanced database inserter with improved state name processing and fuzzy column matching"""
    
    def __init__(self, db_path: str = DATABASE_NAME):
        self.db_path = db_path
        self.conn = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self.dim_maps = {}
        
        # Enhanced state name mapping from PDFparser_Gemini.py
        self.state_mapping = {
            'Punjab': 'Punjab', 'Haryana': 'Haryana', 'Rajasthan': 'Rajasthan', 
            'Delhi': 'Delhi', 'UP': 'UP', 'Uttarakhand': 'Uttarakhand', 
            'HP': 'HP', 'J&K(UT) & Ladakh(UT)': 'J&K(UT) & Ladakh(UT)', 
            'J&K(UT) &.': 'J&K(UT) & Ladakh(UT)', 'Chandigarh': 'Chandigarh', 
            'Railways_NR ISTS': 'Railways_NR ISTS', 'RailwaysNR ISTS': 'Railways_NR ISTS', 
            'Railways_NR': 'Railways_NR ISTS',
            'Chhattisgarh': 'Chhattisgarh', 'Gujarat': 'Gujarat', 'MP': 'MP', 
            'Maharashtra': 'Maharashtra', 'Goa': 'Goa', 'DNHDDPDCL': 'DNHDDPDCL', 
            'AMNSIL': 'AMNSIL', 'BALCO': 'BALCO', 'RIL JAMNAGAR': 'RIL JAMNAGAR',
            'Andhra Pradesh': 'Andhra Pradesh', 'Telangana': 'Telangana', 
            'Karnataka': 'Karnataka', 'Kerala': 'Kerala', 'Tamil Nadu': 'Tamil Nadu', 
            'Puducherry': 'Puducherry',
            'Bihar': 'Bihar', 'DVC': 'DVC', 'Jharkhand': 'Jharkhand', 
            'Odisha': 'Odisha', 'West Bengal': 'West Bengal', 'Sikkim': 'Sikkim', 
            'Railways_ER ISTS': 'Railways_ER ISTS', 'RailwaysER ISTS': 'Railways_ER ISTS', 
            'Railways_ER': 'Railways_ER ISTS',
            'Arunachal Pradesh': 'Arunachal Pradesh', 'Arunachal': 'Arunachal Pradesh', 
            'Assam': 'Assam', 'Manipur': 'Manipur', 'Meghalaya': 'Meghalaya', 
            'Mizoram': 'Mizoram', 'Nagaland': 'Nagaland', 'Tripura': 'Tripura',
            'J&K(UT) &': 'J&K(UT) & Ladakh(UT)', 'J&K(UT)': 'J&K(UT) & Ladakh(UT)', 
            'JAMMU & KASHMIR (UT)': 'J&K(UT) & Ladakh(UT)'
        }
        
        # Column name mappings for fuzzy matching
        self.column_mappings = {
            'states': {
                'States': 'States',
                'State': 'States',
                'State Name': 'States',
                'Region': 'Region',
                'Maximum Demand (MW)': 'Maximum Demand (MW)',
                'Max Demand (MW)': 'Maximum Demand (MW)',
                'Demand (MW)': 'Maximum Demand (MW)',
                'Shortage (MW)': 'Shortage (MW)',
                'Energy Met (MU)': 'Energy Met (MU)',
                'Energy (MU)': 'Energy Met (MU)',
                'Drawal Schedule (MU)': 'Drawal Schedule (MU)',
                'Schedule (MU)': 'Drawal Schedule (MU)',
                'OD(+)/UD(-) (MU)': 'OD(+)/UD(-) (MU)',
                'Over/Under Drawal (MU)': 'OD(+)/UD(-) (MU)',
                'Max OD (MW)': 'Max OD (MW)',
                'Energy Shortage (MU)': 'Energy Shortage (MU)'
            },
            'regional_summary': {
                'Region': 'Region',
                'Maximum Demand (MW)': 'Maximum Demand (MW)',
                'Peak Demand Met (MW)': 'Peak Demand Met (MW)',
                'Peak Shortage (MW)': 'Peak Shortage (MW)',
                'Energy Met (MU)': 'Energy Met (MU)',
                'Energy Shortage (MU)': 'Energy Shortage (MU)',
                'Schedule Drawal (MU)': 'Schedule Drawal (MU)',
                'Actual Drawal (MU)': 'Actual Drawal (MU)',
                'Over/Under Drawal (MU)': 'Over/Under Drawal (MU)',
                'Max Demand SCADA (MW)': 'Max Demand SCADA (MW)',
                'Frequency Violation Index': 'Frequency Violation Index',
                'FVI': 'Frequency Violation Index',
                'Duration Frequency Below 49.7 (%)': 'Duration Frequency Below 49.7 (%)',
                'Duration Frequency 49.7-49.8 (%)': 'Duration Frequency 49.7-49.8 (%)',
                'Duration Frequency 49.8-49.9 (%)': 'Duration Frequency 49.8-49.9 (%)',
                'Duration Frequency Below 49.9 (%)': 'Duration Frequency Below 49.9 (%)',
                'Duration Frequency 49.9-50.05 (%)': 'Duration Frequency 49.9-50.05 (%)',
                'Duration Frequency Above 50.05 (%)': 'Duration Frequency Above 50.05 (%)',
                'Region DDF (%)': 'Region DDF (%)',
                'States DDF (%)': 'States DDF (%)',
                'Solar HR Max Demand (MW)': 'Solar HR Max Demand (MW)',
                'Solar HR Max Demand Time': 'Solar HR Max Demand Time',
                'Solar HR Shortage (MW)': 'Solar HR Shortage (MW)',
                'Non-Solar HR Max Demand (MW)': 'Non-Solar HR Max Demand (MW)',
                'Non-Solar HR Max Demand Time': 'Non-Solar HR Max Demand Time',
                'Non-Solar HR Shortage (MW)': 'Non-Solar HR Shortage (MW)'
            },
            'international_net': {
                'Country': 'Country',
                'Bhutan (MU)': 'Bhutan (MU)',
                'Nepal (MU)': 'Nepal (MU)',
                'Bangladesh (MU)': 'Bangladesh (MU)',
                'Godda (Bangladesh) (MU)': 'Godda (Bangladesh) (MU)',
                'Bhutan Peak (MW)': 'Bhutan Peak (MW)',
                'Nepal Peak (MW)': 'Nepal Peak (MW)',
                'Bangladesh Peak (MW)': 'Bangladesh Peak (MW)',
                'Godda (Bangladesh) Peak (MW)': 'Godda (Bangladesh) Peak (MW)',
                'Exchange (MU)': 'Exchange (MU)',
                'Import (+ve)': 'Import (+ve)',
                'Export (-ve)': 'Export (-ve)'
            },
            'generation_breakdown': {
                'Source': 'Source',
                'Generation (MW)': 'Generation (MW)',
                'Generation (MU)': 'Generation (MU)',
                'Source Name': 'Source',
                'Generation Amount': 'Generation (MW)'
            },
            'block_wise': {
                'TIME': 'TIME',
                'Time Block': 'TIME',
                'Time': 'TIME',
                'Frequency (Hz)': 'Frequency (Hz)',
                'Frequency': 'Frequency (Hz)',
                'DEMAND MET (MW)': 'Demand Met (MW)',
                'Demand Met (MW)': 'Demand Met (MW)',
                'Demand': 'Demand Met (MW)',
                'NET DEMAND MET (MW)': 'Net Demand Met (MW)',
                'Net Demand Met (MW)': 'Net Demand Met (MW)',
                'Net Demand': 'Net Demand Met (MW)',
                'TOTAL GENERATION (MW)': 'Total Generation (MW)',
                'Total Generation (MW)': 'Total Generation (MW)',
                'Generation': 'Total Generation (MW)',
                'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export': 'Net Transnational Exchange (MW)',
                'Net Transnational Exchange (MW)': 'Net Transnational Exchange (MW)',
                'Exchange': 'Net Transnational Exchange (MW)'
            },
            'inter_region': {
                'Line': 'Line',
                'Line Identifier': 'Line',
                'Transmission Line': 'Line',
                'Max Import (MW)': 'Max Import (MW)',
                'Max Export (MW)': 'Max Export (MW)',
                'Import Energy (MU)': 'Import Energy (MU)',
                'Export Energy (MU)': 'Export Energy (MU)',
                'Net Import Energy (MU)': 'Net Import Energy (MU)'
            },
            'international_exchange': {
                'Country': 'Country',
                'Country Name': 'Country',
                'Mechanism': 'Mechanism',
                'Exchange Mechanism': 'Mechanism',
                'Scheduled Energy (MU)': 'Scheduled Energy (MU)',
                'Actual Energy (MU)': 'Actual Energy (MU)',
                'Energy (MU)': 'Scheduled Energy (MU)'
            }
        }
        
        # Region abbreviation mapping
        self.region_abbrev_map = {
            'NR': 'Northern Region',
            'WR': 'Western Region',
            'SR': 'Southern Region',
            'ER': 'Eastern Region',
            'NER': 'North Eastern Region',
            'TOTAL': 'India'
        }
        
    def connect(self) -> bool:
        """Establish database connection and load dimension maps"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self.logger.info(f"Connected to database: {self.db_path}")
            self._load_dimension_maps()
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Database connection error: {e}")
            return False
    
    def _load_dimension_maps(self):
        """Load dimension tables into memory for fast lookups"""
        self.logger.info("Loading dimension maps...")
        cursor = self.conn.cursor()
        
        # Load all dimension tables
        dimension_tables = [
            ('regions', 'DimRegions', 'RegionID', 'RegionName'),
            ('states', 'DimStates', 'StateID', 'StateName'),
            ('countries', 'DimCountries', 'CountryID', 'CountryName'),
            ('sources', 'DimGenerationSources', 'GenerationSourceID', 'SourceName'),
            ('lines', 'DimTransmissionLines', 'LineID', 'LineIdentifier'),
            ('mechanisms', 'DimExchangeMechanisms', 'MechanismID', 'MechanismName'),
            ('units', 'DimUnits', 'UnitID', 'UnitSymbol')
        ]
        
        for map_name, table_name, id_col, name_col in dimension_tables:
            cursor.execute(f"SELECT {id_col}, {name_col} FROM {table_name}")
            self.dim_maps[map_name] = {row[1].upper(): row[0] for row in cursor.fetchall()}
        
        self.logger.info("Dimension maps loaded successfully")
    
    def _normalize_state_name(self, state_name: str) -> Optional[str]:
        """Enhanced state name normalization using logic from PDFparser_Gemini.py"""
        if pd.isna(state_name) or state_name == 'None' or not state_name:
            return None
        
        # Clean the state name
        state_name = str(state_name).strip()
        
        # Handle numeric state names
        if state_name.isdigit():
            self.logger.warning(f"Invalid state name detected: {state_name}")
            return None
        
        # Allow short state abbreviations (UP, HP, MP, etc.) but filter out non-alphabetic short names
        if len(state_name) <= 2 and not state_name.isalpha():
            self.logger.warning(f"Invalid state name detected: {state_name}")
            return None
        
        # Check if it's a region code
        region_codes = ['NR', 'WR', 'SR', 'ER', 'NER', 'ALL INDIA']
        if state_name.upper() in region_codes:
            return None
        
        # Check if it's a summary row
        if any(summary_keyword in state_name.upper() for summary_keyword in ["TOTAL", "ALL INDIA", "GRAND TOTAL"]):
            return None
        
        # Try exact match first
        if state_name in self.state_mapping:
            return self.state_mapping[state_name]
        
        # Try fuzzy matching for similar state names
        best_match = None
        best_ratio = 0
        
        for known_state in self.state_mapping.keys():
            ratio = fuzz.ratio(state_name.upper(), known_state.upper())
            if ratio > 85 and ratio > best_ratio:  # High confidence threshold
                best_match = known_state
                best_ratio = ratio
        
        if best_match:
            self.logger.info(f"Fuzzy matched state '{state_name}' to '{best_match}' (confidence: {best_ratio}%)")
            return self.state_mapping[best_match]
        
        # If no match found, log and return None
        self.logger.warning(f"No state mapping found for: {state_name}")
        return None
    
    def _fuzzy_match_columns(self, df: pd.DataFrame, table_type: str) -> pd.DataFrame:
        """Apply fuzzy matching to standardize column names"""
        if table_type not in self.column_mappings:
            return df
        
        mapping = self.column_mappings[table_type]
        new_columns = []
        
        for col in df.columns:
            col_str = str(col).strip()
            
            # Try exact match first
            if col_str in mapping:
                new_columns.append(mapping[col_str])
                continue
            
            # Try fuzzy matching
            best_match = None
            best_ratio = 0
            
            for known_col in mapping.keys():
                ratio = fuzz.ratio(col_str.upper(), known_col.upper())
                if ratio > 80 and ratio > best_ratio:  # Lower threshold for columns
                    best_match = known_col
                    best_ratio = ratio
            
            if best_match:
                new_columns.append(mapping[best_match])
                self.logger.info(f"Fuzzy matched column '{col_str}' to '{mapping[best_match]}' (confidence: {best_ratio}%)")
            else:
                new_columns.append(col_str)  # Keep original if no match
        
        df.columns = new_columns
        return df
    
    def get_or_insert_dimension_id(self, table_name: str, lookup_dict: dict, extra_data: dict = None) -> Optional[int]:
        """Get dimension ID for existing entries only - no new insertions"""
        cache_key = table_name.lower().replace('dim', '')
        
        # Create lookup tuple
        lookup_tuple = tuple(str(v).upper() for v in lookup_dict.values())
        
        # Check cache first
        if cache_key in self.dim_maps and lookup_tuple in self.dim_maps[cache_key]:
            return self.dim_maps[cache_key][lookup_tuple]
        
        # Not found in cache, check database
        cursor = self.conn.cursor()
        
        # Build WHERE clause for select
        where_clause = " AND ".join([f"{col} = ?" for col in lookup_dict.keys()])
        
        # Use a mapping for the correct ID column
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
        
        id_column = id_column_mapping.get(table_name)
        if not id_column:
            raise ValueError(f"No ID column mapping defined for table {table_name}")
        
        select_sql = f"SELECT {id_column} FROM {table_name} WHERE {where_clause}"
        cursor.execute(select_sql, list(lookup_dict.values()))
        row = cursor.fetchone()
        
        if row:
            # Update cache
            if cache_key not in self.dim_maps:
                self.dim_maps[cache_key] = {}
            self.dim_maps[cache_key][lookup_tuple] = row[0]
            self.logger.debug(f"Found {table_name} ID {row[0]} for {lookup_dict}")
            return row[0]
        else:
            # Not found - log warning and return None
            self.logger.warning(f"Dimension entry not found in {table_name} for {lookup_dict}")
            return None
    
    def get_date_id(self, date_str: str) -> Optional[int]:
        """Get or create DateID for a given date string"""
        try:
            # Parse date string (assuming format like "4/18/2025")
            if '/' in date_str:
                month, day, year = date_str.split('/')
                date_obj = datetime(int(year), int(month), int(day))
            else:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            
            # Create lookup dict
            lookup_dict = {'ActualDate': date_obj.strftime('%Y-%m-%d')}
            extra_data = {
                'DayOfWeek': date_obj.strftime('%A'),
                'DayOfMonth': date_obj.day,
                'Month': date_obj.month,
                'Quarter': (date_obj.month - 1) // 3 + 1,
                'Year': date_obj.year
            }
            
            # For dates, we allow creation of new entries
            cache_key = 'dates'
            lookup_tuple = tuple(str(v).upper() for v in lookup_dict.values())
            
            # Check cache first
            if cache_key in self.dim_maps and lookup_tuple in self.dim_maps[cache_key]:
                return self.dim_maps[cache_key][lookup_tuple]
            
            # Not found in cache, check database
            cursor = self.conn.cursor()
            
            # Build WHERE clause for select
            where_clause = " AND ".join([f"{col} = ?" for col in lookup_dict.keys()])
            select_sql = f"SELECT DateID FROM DimDates WHERE {where_clause}"
            cursor.execute(select_sql, list(lookup_dict.values()))
            row = cursor.fetchone()
            
            if row:
                # Update cache
                if cache_key not in self.dim_maps:
                    self.dim_maps[cache_key] = {}
                self.dim_maps[cache_key][lookup_tuple] = row[0]
                return row[0]
            else:
                # Not found, create new date entry
                insert_dict = dict(lookup_dict)
                insert_dict.update(extra_data)
                
                columns = list(insert_dict.keys())
                values = list(insert_dict.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"INSERT INTO DimDates ({', '.join(columns)}) VALUES ({placeholders})"
                cursor.execute(sql, values)
                self.conn.commit()
                
                # Get the inserted ID
                cursor.execute(select_sql, list(lookup_dict.values()))
                row = cursor.fetchone()
                
                if row:
                    # Update cache
                    if cache_key not in self.dim_maps:
                        self.dim_maps[cache_key] = {}
                    self.dim_maps[cache_key][lookup_tuple] = row[0]
                    self.logger.info(f"Created new DateID {row[0]} for date {date_obj.strftime('%Y-%m-%d')}")
                    return row[0]
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting date ID for {date_str}: {e}")
            return None
    
    def insert_regional_summary(self, df: pd.DataFrame) -> bool:
        """Insert Regional Summary data into FactAllIndiaDailySummary"""
        try:
            self.logger.info("Inserting Regional Summary data...")
            
            # Check if this is a long-format table (Region, Metric, Value)
            if 'Metric' in df.columns and 'Value' in df.columns:
                # Transform from long to wide format
                df = self._transform_regional_summary_long_to_wide(df)
            
            # Apply fuzzy column matching
            df = self._fuzzy_match_columns(df, 'regional_summary')
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in Regional Summary data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            inserted_count = 0
            
            for _, row in df.iterrows():
                # Get region ID
                region_name = row.get('Region', '')
                if pd.isna(region_name) or region_name == 'None':
                    continue
                
                # Map abbreviation to full name if needed
                region_full = self.region_abbrev_map.get(region_name.upper(), region_name)
                region_id = self.dim_maps['regions'].get(region_full.upper())
                
                if not region_id:
                    self.logger.warning(f"Skipping Regional Summary record - region not found: {region_name}")
                    continue
                
                # Prepare data for insertion
                data = {
                    'DateID': date_id,
                    'RegionID': region_id,
                    'ShareRESInTotalGeneration': self._clean_numeric_value(row.get('Share RES in Total Generation (%)', 0)),
                    'PeakDemandMet': self._clean_numeric_value(row.get('Peak Demand Met (MW)', 0)),
                    'PeakShortage': self._clean_numeric_value(row.get('Peak Shortage (MW)', 0)),
                    'EnergyMet': self._clean_numeric_value(row.get('Energy Met (MU)', 0)),
                    'EnergyShortage': self._clean_numeric_value(row.get('Energy Shortage (MU)', 0)),
                    'ScheduleDrawal': self._clean_numeric_value(row.get('Schedule Drawal (MU)', 0)),
                    'ActualDrawal': self._clean_numeric_value(row.get('Actual Drawal (MU)', 0)),
                    'OverUnderDrawal': self._clean_numeric_value(row.get('Over/Under Drawal (MU)', 0)),
                    'MaxDemandSCADA': self._clean_numeric_value(row.get('Max Demand SCADA (MW)', 0)),
                    'FrequencyViolationIndex': self._clean_numeric_value(row.get('Frequency Violation Index', 0)),
                    'DurationFrequencyBelow49_7': self._clean_numeric_value(row.get('Duration Frequency Below 49.7 (%)', 0)),
                    'DurationFrequency_49_7_to_49_8': self._clean_numeric_value(row.get('Duration Frequency 49.7-49.8 (%)', 0)),
                    'DurationFrequency_49_8_to_49_9': self._clean_numeric_value(row.get('Duration Frequency 49.8-49.9 (%)', 0)),
                    'DurationFrequencyBelow49_9': self._clean_numeric_value(row.get('Duration Frequency Below 49.9 (%)', 0)),
                    'DurationFrequency_49_9_to_50_05': self._clean_numeric_value(row.get('Duration Frequency 49.9-50.05 (%)', 0)),
                    'DurationFrequencyAbove50_05': self._clean_numeric_value(row.get('Duration Frequency Above 50.05 (%)', 0)),
                    'RegionDDF': self._clean_numeric_value(row.get('Region DDF (%)', 0)),
                    'StatesDDF': self._clean_numeric_value(row.get('States DDF (%)', 0)),
                    'SolarHRMaxDemand': self._clean_numeric_value(row.get('Solar HR Max Demand (MW)', 0)),
                    'SolarHRMaxDemandTime': row.get('Solar HR Max Demand Time', ''),
                    'SolarHRShortage': self._clean_numeric_value(row.get('Solar HR Shortage (MW)', 0)),
                    'NonSolarHRMaxDemand': self._clean_numeric_value(row.get('Non-Solar HR Max Demand (MW)', 0)),
                    'NonSolarHRMaxDemandTime': row.get('Non-Solar HR Max Demand Time', ''),
                    'NonSolarHRShortage': self._clean_numeric_value(row.get('Non-Solar HR Shortage (MW)', 0))
                }
                
                # Insert or update
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"""
                INSERT OR REPLACE INTO FactAllIndiaDailySummary 
                ({', '.join(columns)}) VALUES ({placeholders})
                """
                cursor.execute(sql, values)
                inserted_count += 1
            
            self.conn.commit()
            self.logger.info(f"Successfully inserted {inserted_count} Regional Summary records")
            return inserted_count > 0
            
        except Exception as e:
            self.logger.error(f"Error inserting Regional Summary data: {e}")
            return False
    
    def _transform_regional_summary_long_to_wide(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform regional summary data from long format (Region, Metric, Value) to wide format"""
        try:
            # Create a mapping from metric names to database column names
            metric_mapping = {
                'Demand Met during Evening Peak hrs(MW)': 'Peak Demand Met (MW)',
                'Demand Met during Evening Peak hrs(MW) (at': 'Peak Demand Met (MW)',
                'Schedule(MU)': 'Schedule Drawal (MU)',
                'Central Sector': 'Central Sector (MW)',
                'Coal': 'Coal Generation (MW)',
                'Hydro': 'Hydro Generation (MW)',
                'Nuclear': 'Nuclear Generation (MW)',
                'Gas': 'Gas Generation (MW)',
                'Wind': 'Wind Generation (MW)',
                'Solar': 'Solar Generation (MW)',
                'Others': 'Others Generation (MW)',
                'Total': 'Total Generation (MW)',
                'FVI': 'Frequency Violation Index',
                'Duration Frequency Below 49.7 (s)': 'Duration Frequency Below 49.7 (%)',
                'Duration Frequency 49.7-49.8 (s)': 'Duration Frequency 49.7-49.8 (%)',
                'Duration Frequency 49.8-49.9 (s)': 'Duration Frequency 49.8-49.9 (%)',
                'Duration Frequency Below 49.9 (s)': 'Duration Frequency Below 49.9 (%)',
                'Duration Frequency 49.9-50.05 (s)': 'Duration Frequency 49.9-50.05 (%)',
                'Duration Frequency Above 50.05 (s)': 'Duration Frequency Above 50.05 (%)',
                # Add specific mappings for the actual metrics we see
                'Hydro Gen (MU)': 'Hydro Generation (MU)',
                'Wind Gen (MU)': 'Wind Generation (MU)',
                'Solar Gen (MU)*': 'Solar Generation (MU)',
                'Energy Met (MU)': 'Energy Met (MU)',
                'Energy Shortage (MU)': 'Energy Shortage (MU)',
                'Peak Shortage (MW)': 'Peak Shortage (MW)',
                'Maximum Demand Met During the Day (MW)': 'Max Demand SCADA (MW)',
                'Maximum Demand Met During the Day (MW)\r(From NLDC SCADA)': 'Max Demand SCADA (MW)'
            }
            
            # Clean up metric names and map them
            df['Metric'] = df['Metric'].str.strip()
            
            # More flexible mapping - check if metric contains key phrases
            def map_metric(metric):
                metric_lower = metric.lower()
                if 'demand met' in metric_lower and 'peak' in metric_lower:
                    return 'Peak Demand Met (MW)'
                elif 'schedule' in metric_lower:
                    return 'Schedule Drawal (MU)'
                elif 'central sector' in metric_lower:
                    return 'Central Sector (MW)'
                elif metric in metric_mapping:
                    return metric_mapping[metric]
                else:
                    return metric
            
            df['MappedMetric'] = df['Metric'].apply(map_metric)
            
            # Pivot the data
            if 'MappedMetric' in df.columns:
                # Use mapped metric names
                pivot_df = df.pivot_table(
                    index=['Region', 'Date'], 
                    columns='MappedMetric', 
                    values='Value', 
                    aggfunc='first'
                ).reset_index()
            else:
                # Use original metric names
                pivot_df = df.pivot_table(
                    index=['Region', 'Date'], 
                    columns='Metric', 
                    values='Value', 
                    aggfunc='first'
                ).reset_index()
            
            # Flatten column names
            pivot_df.columns.name = None
            
            self.logger.info(f"Transformed regional summary from {len(df)} rows to {len(pivot_df)} rows")
            self.logger.info(f"Resulting columns: {pivot_df.columns.tolist()}")
            
            return pivot_df
            
        except Exception as e:
            self.logger.error(f"Error transforming regional summary data: {e}")
            return df
    
    def insert_states_data(self, df: pd.DataFrame) -> bool:
        """Insert States data into FactStateDailyEnergy with enhanced state name processing"""
        try:
            self.logger.info("Inserting States data...")
            
            # Apply fuzzy column matching
            df = self._fuzzy_match_columns(df, 'states')
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in States data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            inserted_count = 0
            skipped_count = 0
            
            for _, row in df.iterrows():
                # Enhanced state name processing
                raw_state_name = row.get('States', '')
                normalized_state_name = self._normalize_state_name(raw_state_name)
                
                if not normalized_state_name:
                    skipped_count += 1
                    continue
                
                state_id = self.get_or_insert_dimension_id('DimStates', {'StateName': normalized_state_name})
                if not state_id:
                    self.logger.warning(f"Skipping States record - state not found in database: {normalized_state_name}")
                    skipped_count += 1
                    continue
                
                # Prepare data for insertion
                data = {
                    'DateID': date_id,
                    'StateID': state_id,
                    'MaximumDemand': self._safe_float(row.get('Maximum Demand (MW)', 0)),
                    'Shortage': self._safe_float(row.get('Shortage (MW)', 0)),
                    'EnergyMet': self._safe_float(row.get('Energy Met (MU)', 0)),
                    'DrawalSchedule': self._safe_float(row.get('Drawal Schedule (MU)', 0)),
                    'OverUnderDrawal': self._safe_float(row.get('OD(+)/UD(-) (MU)', 0)),
                    'MaxOverDrawal': self._safe_float(row.get('Max OD (MW)', 0)),
                    'EnergyShortage': self._safe_float(row.get('Energy Shortage (MU)', 0))
                }
                
                # Insert or update
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"""
                INSERT OR REPLACE INTO FactStateDailyEnergy 
                ({', '.join(columns)}) VALUES ({placeholders})
                """
                cursor.execute(sql, values)
                inserted_count += 1
            
            self.conn.commit()
            self.logger.info(f"Successfully inserted {inserted_count} States records (skipped {skipped_count} invalid state names)")
            return inserted_count > 0
            
        except Exception as e:
            self.logger.error(f"Error inserting States data: {e}")
            return False
    
    def insert_international_net(self, df: pd.DataFrame) -> bool:
        """Insert International NET data into FactCountryDailyExchange"""
        try:
            self.logger.info("Inserting International NET data...")
            
            # Apply fuzzy column matching
            df = self._fuzzy_match_columns(df, 'international_net')
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in International NET data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            inserted_count = 0
            
            for _, row in df.iterrows():
                # Get country ID
                country_name = row.get('Country', '')
                if pd.isna(country_name) or country_name == 'None':
                    continue
                
                country_id = self.get_or_insert_dimension_id('DimCountries', {'CountryName': country_name})
                if not country_id:
                    self.logger.warning(f"Skipping International NET record - country not found: {country_name}")
                    continue
                
                # Prepare data for insertion
                data = {
                    'DateID': date_id,
                    'CountryID': country_id,
                    'TotalEnergyExchanged': self._safe_float(row.get('Exchange (MU)', 0)),
                    'PeakExchange': self._safe_float(row.get('Import (+ve)', 0)) - self._safe_float(row.get('Export (-ve)', 0))
                }
                
                # Insert or update
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"""
                INSERT OR REPLACE INTO FactCountryDailyExchange 
                ({', '.join(columns)}) VALUES ({placeholders})
                """
                cursor.execute(sql, values)
                inserted_count += 1
            
            self.conn.commit()
            self.logger.info(f"Successfully inserted {inserted_count} International NET records")
            return inserted_count > 0
            
        except Exception as e:
            self.logger.error(f"Error inserting International NET data: {e}")
            return False
    
    def insert_generation_breakdown(self, df: pd.DataFrame) -> bool:
        """Insert Generation Breakdown data into FactDailyGenerationBreakdown"""
        try:
            self.logger.info("Inserting Generation Breakdown data...")
            
            # Apply fuzzy column matching
            df = self._fuzzy_match_columns(df, 'generation_breakdown')
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in Generation Breakdown data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            inserted_count = 0
            
            for _, row in df.iterrows():
                # Get generation source ID
                source_name = row.get('Source', '')
                if pd.isna(source_name) or source_name == 'None':
                    continue
                
                source_id = self.get_or_insert_dimension_id('DimGenerationSources', {'SourceName': source_name})
                if not source_id:
                    self.logger.warning(f"Skipping Generation Breakdown record - source not found: {source_name}")
                    continue
                
                # Prepare data for insertion
                data = {
                    'DateID': date_id,
                    'RegionID': 1,  # Default to India region
                    'GenerationSourceID': source_id,
                    'GenerationAmount': self._safe_float(row.get('Generation (MW)', 0))
                }
                
                # Insert or update
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"""
                INSERT OR REPLACE INTO FactDailyGenerationBreakdown 
                ({', '.join(columns)}) VALUES ({placeholders})
                """
                cursor.execute(sql, values)
                inserted_count += 1
            
            self.conn.commit()
            self.logger.info(f"Successfully inserted {inserted_count} Generation Breakdown records")
            return inserted_count > 0
            
        except Exception as e:
            self.logger.error(f"Error inserting Generation Breakdown data: {e}")
            return False
    
    def insert_frequency_profile(self, df: pd.DataFrame) -> bool:
        """Insert Frequency Profile data into FactAllIndiaDailySummary"""
        try:
            self.logger.info("Inserting Frequency Profile data...")
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in Frequency Profile data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            
            for _, row in df.iterrows():
                # Update existing FactAllIndiaDailySummary record with frequency data
                data = {
                    'FrequencyViolationIndex': self._safe_float(row.get('FVI', 0)),
                    'DurationFrequencyBelow49_7': self._safe_float(row.get('Duration Frequency Below 49.7 (s)', 0)),
                    'DurationFrequency_49_7_to_49_8': self._safe_float(row.get('Duration Frequency 49.7-49.8 (s)', 0)),
                    'DurationFrequency_49_8_to_49_9': self._safe_float(row.get('Duration Frequency 49.8-49.9 (s)', 0)),
                    'DurationFrequencyBelow49_9': self._safe_float(row.get('Duration Frequency Below 49.9 (s)', 0)),
                    'DurationFrequency_49_9_to_50_05': self._safe_float(row.get('Duration Frequency 49.9-50.05 (s)', 0)),
                    'DurationFrequencyAbove50_05': self._safe_float(row.get('Duration Frequency Above 50.05 (s)', 0))
                }
                
                # Update existing record
                set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
                sql = f"""
                UPDATE FactAllIndiaDailySummary 
                SET {set_clause}
                WHERE DateID = ? AND RegionID = 1
                """
                values = list(data.values()) + [date_id]
                cursor.execute(sql, values)
            
            self.conn.commit()
            self.logger.info(f"Successfully updated Frequency Profile data")
            return True
            
        except Exception as e:
            self.logger.error(f"Error inserting Frequency Profile data: {e}")
            return False
    
    def insert_block_wise(self, df: pd.DataFrame) -> bool:
        """Insert Block-wise data into FactTimeBlockPowerData and FactTimeBlockGeneration"""
        try:
            self.logger.info("Inserting Block-wise data...")
            
            # Apply fuzzy column matching
            df = self._fuzzy_match_columns(df, 'block_wise')
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in Block-wise data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            inserted_count = 0
            
            for _, row in df.iterrows():
                # Get time block ID
                time_block = row.get('TIME', '')
                if pd.isna(time_block) or time_block == 'None':
                    continue
                
                # Ensure time format is HH:MM (remove seconds if present)
                time_str = str(time_block).strip()
                if ':' in time_str and len(time_str) > 5:
                    time_str = time_str[:5]  # Keep only HH:MM part
                
                # Create time block entry if it doesn't exist
                time_block_id = self._get_or_create_time_block(time_str)
                if not time_block_id:
                    continue
                
                # Prepare data for FactTimeBlockPowerData
                power_data = {
                    'DateID': date_id,
                    'TimeBlockID': time_block_id,
                    'Frequency': self._safe_float(row.get('Frequency (Hz)', 0)),
                    'DemandMet': self._safe_float(row.get('Demand Met (MW)', 0)),
                    'NetDemandMet': self._safe_float(row.get('Net Demand Met (MW)', 0)),
                    'TotalGeneration': self._safe_float(row.get('Total Generation (MW)', 0)),
                    'NetTransnationalExchange': self._safe_float(row.get('Net Transnational Exchange (MW)', 0))
                }
                
                # Insert into FactTimeBlockPowerData
                columns = list(power_data.keys())
                values = list(power_data.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"""
                INSERT OR REPLACE INTO FactTimeBlockPowerData 
                ({', '.join(columns)}) VALUES ({placeholders})
                """
                cursor.execute(sql, values)
                inserted_count += 1
            
            self.conn.commit()
            self.logger.info(f"Successfully inserted {inserted_count} Block-wise records")
            return inserted_count > 0
            
        except Exception as e:
            self.logger.error(f"Error inserting Block-wise data: {e}")
            return False
    
    def insert_import_export_regions(self, df: pd.DataFrame) -> bool:
        """Insert Import/Export Regions data into FactTransmissionLinkFlow"""
        try:
            self.logger.info("Inserting Import/Export Regions data...")
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in Import/Export Regions data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            inserted_count = 0
            
            for _, row in df.iterrows():
                # Get line ID
                line_name = row.get('Inter Region', '')
                if pd.isna(line_name) or line_name == 'None':
                    continue
                
                line_id = self.get_or_insert_dimension_id('DimTransmissionLines', {'LineIdentifier': line_name})
                if not line_id:
                    self.logger.warning(f"Skipping Import/Export Regions record - line not found: {line_name}")
                    continue
                
                # Prepare data for insertion
                data = {
                    'DateID': date_id,
                    'LineID': line_id,
                    'Inter_Region': line_name,
                    'MaxImport': self._safe_float(row.get('Max Import (MW)', 0)),
                    'MaxExport': self._safe_float(row.get('Max Export (MW)', 0)),
                    'ImportEnergy': self._safe_float(row.get('Import Energy (MU)', 0)),
                    'ExportEnergy': self._safe_float(row.get('Export Energy (MU)', 0)),
                    'NetImportEnergy': self._safe_float(row.get('Net Import Energy (MU)', 0))
                }
                
                # Insert or update
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"""
                INSERT OR REPLACE INTO FactTransmissionLinkFlow 
                ({', '.join(columns)}) VALUES ({placeholders})
                """
                cursor.execute(sql, values)
                inserted_count += 1
            
            self.conn.commit()
            self.logger.info(f"Successfully inserted {inserted_count} Import/Export Regions records")
            return inserted_count > 0
            
        except Exception as e:
            self.logger.error(f"Error inserting Import/Export Regions data: {e}")
            return False
    
    def insert_outage_data(self, df: pd.DataFrame) -> bool:
        """Insert Outage Data into FactAllIndiaDailySummary"""
        try:
            self.logger.info("Inserting Outage Data...")
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in Outage Data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            
            for _, row in df.iterrows():
                # Update existing FactAllIndiaDailySummary record with outage data
                data = {
                    'CentralSectorOutage': self._safe_float(row.get('Central Sector Outage (MW)', 0)),
                    'StateSectorOutage': self._safe_float(row.get('State Sector Outage (MW)', 0)),
                    'TotalOutage': self._safe_float(row.get('Total Outage (MW)', 0))
                }
                
                # Update existing record
                set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
                sql = f"""
                UPDATE FactAllIndiaDailySummary 
                SET {set_clause}
                WHERE DateID = ? AND RegionID = 1
                """
                values = list(data.values()) + [date_id]
                cursor.execute(sql, values)
            
            self.conn.commit()
            self.logger.info(f"Successfully updated Outage Data")
            return True
            
        except Exception as e:
            self.logger.error(f"Error inserting Outage Data: {e}")
            return False
    
    def insert_re_share(self, df: pd.DataFrame) -> bool:
        """Insert RE Share data into FactAllIndiaDailySummary"""
        try:
            self.logger.info("Inserting RE Share data...")
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in RE Share data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            
            for _, row in df.iterrows():
                # Update existing FactAllIndiaDailySummary record with RE share data
                data = {
                    'ShareRESInTotalGeneration': self._safe_float(row.get('RE Share (%)', 0)),
                    'ShareNonFossilInTotalGeneration': self._safe_float(row.get('Non-Fossil Share (%)', 0))
                }
                
                # Update existing record
                set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
                sql = f"""
                UPDATE FactAllIndiaDailySummary 
                SET {set_clause}
                WHERE DateID = ? AND RegionID = 1
                """
                values = list(data.values()) + [date_id]
                cursor.execute(sql, values)
            
            self.conn.commit()
            self.logger.info(f"Successfully updated RE Share data")
            return True
            
        except Exception as e:
            self.logger.error(f"Error inserting RE Share data: {e}")
            return False
    
    def insert_solar_non_solar_hour(self, df: pd.DataFrame) -> bool:
        """Insert Solar/Non-Solar Hour data into FactAllIndiaDailySummary"""
        try:
            self.logger.info("Inserting Solar/Non-Solar Hour data...")
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in Solar/Non-Solar Hour data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            
            for _, row in df.iterrows():
                # Update existing FactAllIndiaDailySummary record with solar/non-solar data
                data = {
                    'SolarHRMaxDemand': self._safe_float(row.get('Solar Hour Max Demand (MW)', 0)),
                    'SolarHRMaxDemandTime': str(row.get('Solar Hour Max Demand Time', '')),
                    'SolarHRShortage': self._safe_float(row.get('Solar Hour Shortage (MW)', 0)),
                    'NonSolarHRMaxDemand': self._safe_float(row.get('Non-Solar Hour Max Demand (MW)', 0)),
                    'NonSolarHRMaxDemandTime': str(row.get('Non-Solar Hour Max Demand Time', '')),
                    'NonSolarHRShortage': self._safe_float(row.get('Non-Solar Hour Shortage (MW)', 0))
                }
                
                # Update existing record
                set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
                sql = f"""
                UPDATE FactAllIndiaDailySummary 
                SET {set_clause}
                WHERE DateID = ? AND RegionID = 1
                """
                values = list(data.values()) + [date_id]
                cursor.execute(sql, values)
            
            self.conn.commit()
            self.logger.info(f"Successfully updated Solar/Non-Solar Hour data")
            return True
            
        except Exception as e:
            self.logger.error(f"Error inserting Solar/Non-Solar Hour data: {e}")
            return False
    
    def insert_inter_region(self, df: pd.DataFrame) -> bool:
        """Insert Inter-Region data into FactTransmissionLinkFlow"""
        try:
            self.logger.info("Inserting Inter Region data...")
            
            # Apply fuzzy column matching
            df = self._fuzzy_match_columns(df, 'inter_region')
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in Inter Region data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            inserted_count = 0
            
            for _, row in df.iterrows():
                # Get transmission line ID
                line_name = row.get('Line', '')
                if pd.isna(line_name) or line_name == 'None' or line_name == '':
                    self.logger.warning(f"Skipping Inter Region record - line not found: {line_name}")
                    continue
                
                line_id = self.get_or_insert_dimension_id('DimTransmissionLines', {'LineIdentifier': line_name})
                if not line_id:
                    self.logger.warning(f"Skipping Inter Region record - line not found: {line_name}")
                    continue
                
                # Prepare data for insertion
                data = {
                    'DateID': date_id,
                    'LineID': line_id,
                    'MaxImport': self._safe_float(row.get('Max Import (MW)', 0)),
                    'MaxExport': self._safe_float(row.get('Max Export (MW)', 0)),
                    'ImportEnergy': self._safe_float(row.get('Import Energy (MU)', 0)),
                    'ExportEnergy': self._safe_float(row.get('Export Energy (MU)', 0)),
                    'NetImportEnergy': self._safe_float(row.get('Net Import Energy (MU)', 0))
                }
                
                # Insert or update
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"""
                INSERT OR REPLACE INTO FactTransmissionLinkFlow 
                ({', '.join(columns)}) VALUES ({placeholders})
                """
                cursor.execute(sql, values)
                inserted_count += 1
            
            self.conn.commit()
            self.logger.info(f"Successfully inserted {inserted_count} Inter Region records")
            return inserted_count > 0
            
        except Exception as e:
            self.logger.error(f"Error inserting Inter Region data: {e}")
            return False

    def insert_international_exchange(self, df: pd.DataFrame) -> bool:
        """Insert International Exchange data into FactTransnationalExchangeDetail"""
        try:
            self.logger.info("Inserting International Exchange data...")
            
            # Apply fuzzy column matching
            df = self._fuzzy_match_columns(df, 'international_exchange')
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in International Exchange data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            inserted_count = 0
            
            for _, row in df.iterrows():
                # Get country ID
                country_name = row.get('Country', '')
                if pd.isna(country_name) or country_name == 'None' or country_name == '':
                    self.logger.warning(f"Skipping International Exchange record - country not found: {country_name}")
                    continue
                
                country_id = self.get_or_insert_dimension_id('DimCountries', {'CountryName': country_name})
                if not country_id:
                    self.logger.warning(f"Skipping International Exchange record - country not found: {country_name}")
                    continue
                
                # Get mechanism ID
                mechanism_name = row.get('Mechanism', '')
                if pd.isna(mechanism_name) or mechanism_name == 'None':
                    mechanism_name = 'Unknown'
                
                mechanism_id = self.get_or_insert_dimension_id('DimExchangeMechanisms', {'MechanismName': mechanism_name})
                if not mechanism_id:
                    self.logger.warning(f"Skipping International Exchange record - mechanism not found: {mechanism_name}")
                    continue
                
                # Determine exchange direction and value
                scheduled_val = self._safe_float(row.get('Scheduled Energy (MU)', 0))
                actual_val = self._safe_float(row.get('Actual Energy (MU)', 0))
                
                if scheduled_val > 0:
                    exchange_direction = 'Scheduled'
                    exchange_value = scheduled_val
                elif actual_val > 0:
                    exchange_direction = 'Actual'
                    exchange_value = actual_val
                else:
                    exchange_direction = 'Net'
                    exchange_value = actual_val - scheduled_val
                
                # Prepare data for insertion
                data = {
                    'DateID': date_id,
                    'CountryID': country_id,
                    'MechanismID': mechanism_id,
                    'ExchangeDirection': exchange_direction,
                    'ExchangeValue': exchange_value
                }
                
                # Insert or update
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"""
                INSERT OR REPLACE INTO FactTransnationalExchangeDetail 
                ({', '.join(columns)}) VALUES ({placeholders})
                """
                cursor.execute(sql, values)
                inserted_count += 1
            
            self.conn.commit()
            self.logger.info(f"Successfully inserted {inserted_count} International Exchange records")
            return inserted_count > 0
            
        except Exception as e:
            self.logger.error(f"Error inserting International Exchange data: {e}")
            return False
    
    def insert_cross_border_schedule(self, df: pd.DataFrame) -> bool:
        """Insert Cross Border Schedule data into FactTransnationalExchangeDetail"""
        try:
            self.logger.info("Inserting Cross Border Schedule data...")
            
            # Get date ID
            date_str = df['Date'].iloc[0] if 'Date' in df.columns else None
            if not date_str:
                self.logger.error("No date found in Cross Border Schedule data")
                return False
            
            date_id = self.get_date_id(date_str)
            if not date_id:
                return False
            
            cursor = self.conn.cursor()
            inserted_count = 0
            
            for _, row in df.iterrows():
                # Get country ID
                country_name = row.get('Country', '')
                if pd.isna(country_name) or country_name == 'None':
                    continue
                
                country_id = self.get_or_insert_dimension_id('DimCountries', {'CountryName': country_name})
                if not country_id:
                    self.logger.warning(f"Skipping Cross Border Schedule record - country not found: {country_name}")
                    continue
                
                # Get mechanism ID
                mechanism_name = row.get('Mechanism', '')
                if pd.isna(mechanism_name) or mechanism_name == 'None':
                    mechanism_name = 'Unknown'
                
                mechanism_id = self.get_or_insert_dimension_id('DimExchangeMechanisms', {'MechanismName': mechanism_name})
                if not mechanism_id:
                    self.logger.warning(f"Skipping Cross Border Schedule record - mechanism not found: {mechanism_name}")
                    continue
                
                # Determine exchange direction and value
                scheduled_val = self._safe_float(row.get('Scheduled Energy (MU)', 0))
                actual_val = self._safe_float(row.get('Actual Energy (MU)', 0))
                
                if scheduled_val > 0:
                    exchange_direction = 'Scheduled'
                    exchange_value = scheduled_val
                elif actual_val > 0:
                    exchange_direction = 'Actual'
                    exchange_value = actual_val
                else:
                    exchange_direction = 'Net'
                    exchange_value = actual_val - scheduled_val
                
                # Prepare data for insertion
                data = {
                    'DateID': date_id,
                    'CountryID': country_id,
                    'MechanismID': mechanism_id,
                    'ExchangeDirection': exchange_direction,
                    'ExchangeValue': exchange_value
                }
                
                # Insert or update
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ", ".join(["?"] * len(values))
                
                sql = f"""
                INSERT OR REPLACE INTO FactTransnationalExchangeDetail 
                ({', '.join(columns)}) VALUES ({placeholders})
                """
                cursor.execute(sql, values)
                inserted_count += 1
            
            self.conn.commit()
            self.logger.info(f"Successfully inserted {inserted_count} Cross Border Schedule records")
            return inserted_count > 0
            
        except Exception as e:
            self.logger.error(f"Error inserting Cross Border Schedule data: {e}")
            return False
    
    def _get_or_create_time_block(self, time_str: str) -> Optional[int]:
        """Get or create TimeBlockID for a given time string"""
        try:
            # Clean the time string
            time_str = str(time_str).strip()
            if not time_str or time_str == 'None':
                return None
            
            # Check if time block already exists
            cursor = self.conn.cursor()
            select_sql = "SELECT TimeBlockID FROM DimTimeBlocks WHERE BlockTime = ?"
            cursor.execute(select_sql, [time_str])
            row = cursor.fetchone()
            
            if row:
                return row[0]
            
            # Create new time block
            # Extract block number from time string or use a default
            block_number = 1
            if ':' in time_str:
                try:
                    # Try to extract hour and determine block number
                    hour = int(time_str.split(':')[0])
                    block_number = (hour // 6) + 1  # 6-hour blocks
                except:
                    block_number = 1
            
            insert_sql = "INSERT INTO DimTimeBlocks (BlockTime, BlockNumber) VALUES (?, ?)"
            cursor.execute(insert_sql, [time_str, block_number])
            self.conn.commit()
            
            # Get the inserted ID
            cursor.execute(select_sql, [time_str])
            row = cursor.fetchone()
            
            if row:
                self.logger.info(f"Created new TimeBlockID {row[0]} for time {time_str}")
                return row[0]
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting time block ID for {time_str}: {e}")
            return None

    def _safe_float(self, value) -> float:
        """Safely convert value to float, returning 0.0 if conversion fails"""
        try:
            if pd.isna(value) or value is None:
                return 0.0
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
    def _clean_numeric_value(self, value):
        """Clean numeric value by removing units and handling null values"""
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.replace('MW', '').replace('MU', '').replace('%', '').strip()
                if value.upper() in ['N', 'NA', 'N.A.', 'N/A', '']:
                    return None
            return float(value)
        except (ValueError, TypeError):
            self.logger.warning(f"Could not convert value '{value}' to numeric")
            return None
    
    def process_parser_results(self, results: Dict[str, Any]) -> bool:
        """Process all tables from parser results and insert into database"""
        try:
            if not results['success']:
                self.logger.error("Parser results indicate failure")
                return False
            
            self.logger.info(f"Processing {len(results['final_tables'])} tables for database insertion")
            
            success_count = 0
            total_count = len(results['final_tables'])
            
            for table in results['final_tables']:
                table_name = table['Table Name'].iloc[0] if 'Table Name' in table.columns else "Unknown"
                self.logger.info(f"Processing table: {table_name}")
                
                success = False
                
                # Route to appropriate insertion method based on table name
                if table_name == 'Regional Summary':
                    success = self.insert_regional_summary(table)
                elif table_name == 'States':
                    success = self.insert_states_data(table)
                elif table_name == 'International NET':
                    success = self.insert_international_net(table)
                elif table_name == 'Generation Breakdown':
                    success = self.insert_generation_breakdown(table)
                elif table_name == 'Frequency Profile':
                    success = self.insert_frequency_profile(table)
                elif table_name == 'Block-wise':
                    success = self.insert_block_wise(table)
                elif table_name == 'Import/Export Regions':
                    success = self.insert_import_export_regions(table)
                elif table_name == 'Outage Data':
                    success = self.insert_outage_data(table)
                elif table_name == 'RE Share':
                    success = self.insert_re_share(table)
                elif table_name == 'Solar/Non-Solar Hour':
                    success = self.insert_solar_non_solar_hour(table)
                elif table_name == 'Inter Region':
                    success = self.insert_inter_region(table)
                elif table_name == 'International Exchange':
                    success = self.insert_international_exchange(table)
                elif table_name == 'Cross Border Schedule (1)':
                    success = self.insert_cross_border_schedule(table)
                elif table_name.startswith('Cross Border Schedule'):
                    success = self.insert_cross_border_schedule(table)
                else:
                    self.logger.warning(f"No insertion handler for table: {table_name}")
                    continue
                
                if success:
                    success_count += 1
                    self.logger.info(f"Successfully inserted {table_name}")
                else:
                    self.logger.error(f"Failed to insert {table_name}")
            
            self.logger.info(f"Database insertion completed: {success_count}/{total_count} tables successful")
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"Error processing parser results: {e}")
            return False
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.logger.info("Database connection closed")

def main():
    """Main execution function"""
    # Test with a sample PDF
    pdf_path = "sample input/18.04.25_NLDC_PSP.pdf"
    
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        return
    
    try:
        # Parse PDF using modular parser
        parser = PSPReportParser()
        results = parser.parse_pdf(pdf_path)
        
        if not results['success']:
            logger.error("Failed to parse PDF")
            return
        
        logger.info(f"Successfully parsed PDF: {len(results['final_tables'])} tables extracted")
        
        # Insert into database
        inserter = EnhancedModularDBInserter()
        if inserter.connect():
            success = inserter.process_parser_results(results)
            if success:
                logger.info("Database insertion completed successfully")
            else:
                logger.error("Database insertion failed")
            inserter.close()
        else:
            logger.error("Failed to connect to database")
    
    except Exception as e:
        logger.error(f"Error in main execution: {e}")

if __name__ == "__main__":
    main() 