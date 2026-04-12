#!/usr/bin/env python3
"""
Improved column mapping for PSP report tables.
Handles actual column names from PDF extraction.
"""

import pandas as pd
import numpy as np
import re
from typing import Dict, List, Tuple, Optional
from fuzzywuzzy import fuzz

class ImprovedColumnMapper:
    """Improved column mapping for PSP tables"""
    
    def __init__(self):
        # Define column mappings for each table type
        self.column_mappings = {
            'regional_summary': {
                'Peak Demand Met (MW)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Energy Met (MU)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Energy Shortage (MU)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Max Demand SCADA (MW)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Peak Shortage (MW)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Schedule Drawal (MU)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Actual Drawal (MU)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Over/Under Drawal (MU)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL']
            },
            'state_energy': {
                'Maximum Demand (MW)': ['Max.Demand\rMet during the\rday (MW)', 'Max.Demand Met during the day (MW)'],
                'Shortage (MW)': ['Shortage during\rmaximum\rDemand (MW)', 'Shortage during maximum Demand (MW)'],
                'Energy Met (MU)': ['Energy Met\r(MU)', 'Energy Met (MU)'],
                'Drawal Schedule (MU)': ['Drawal\rSchedule\r(MU)', 'Drawal Schedule (MU)'],
                'OD(+)/UD(-) (MU)': ['OD(+)/UD(-)\r(MU)', 'OD(+)/UD(-) (MU)'],
                'Max OD (MW)': ['Max OD\r(MW)', 'Max OD (MW)'],
                'Energy Shortage (MU)': ['Energy\rShortage (MU)', 'Energy Shortage (MU)']
            },
            'frequency_profile': {
                'FVI': ['FVI'],
                'Duration Frequency Below 49.7 (s)': ['< 49.7'],
                'Duration Frequency 49.7-49.8 (s)': ['49.7 - 49.8'],
                'Duration Frequency 49.8-49.9 (s)': ['49.8 - 49.9'],
                'Duration Frequency Below 49.9 (s)': ['< 49.9'],
                'Duration Frequency 49.9-50.05 (s)': ['49.9 - 50.05'],
                'Duration Frequency Above 50.05 (s)': ['> 50.05']
            },
            'transnational_exchange': {
                'Bhutan': ['Bhutan'],
                'Nepal': ['Nepal'],
                'Bangladesh': ['Bangladesh'],
                'GoddaBangladesh': ['Godda -> Bangladesh']
            },
            'import_export_regions': {
                'Schedule (MU)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Actual (MU)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Import (MU)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Export (MU)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL']
            },
            'outage_data': {
                'Total Outage (MW)': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
                'Share (%)': ['% Share']
            },
            'generation_breakdown': {
                'Generation (MW)': ['NR', 'WR', 'SR', 'ER', 'NER', 'All India'],
                'Share (%)': ['% Share']
            },
            're_share': {
                'RE Share': ['Share of RES in total generation (%)'],
                'Non-Fossil Share': ['Share of RES in total generation (%)']
            },
            'solar_nonsolar_hour': {
                'Solar HR Max Demand (MW)': ['Max Demand Met(MW)'],
                'Solar HR Shortage (MW)': ['Shortage(MW)'],
                'Non-Solar HR Max Demand (MW)': ['Max Demand Met(MW)'],
                'Non-Solar HR Shortage (MW)': ['Shortage(MW)']
            },
            'transmission_flow': {
                'Max Import (MW)': ['Max Import (MW)'],
                'Max Export (MW)': ['Max Export (MW)'],
                'Import (MU)': ['Import (MU)'],
                'Export (MU)': ['Export (MU)'],
                'NET (MU)': ['NET (MU)']
            },
            'cross_border_schedule_1': {
                'GNA': ['GNA\r(ISGS/PPA)', 'GNA\r(ISGA/PPA)', 'T-GNA'],
                'Bilateral': ['T-GNA'],
                'Total': ['TOTAL']
            },
            'time_block': {
                'TIME': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'FREQUENCY (Hz)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'DEMAND MET (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'NUCLEAR (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'WIND (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'SOLAR (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'HYDRO (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'GAS (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'THERMAL (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'OTHERS* (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'NET DEMAND MET (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'TOTAL GENERATION (MW)': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11'],
                'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export': ['Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7', 'Unnamed: 8', 'Unnamed: 9', 'Unnamed: 10', 'Unnamed: 11']
            }
        }
    
    def map_columns(self, df: pd.DataFrame, category: str) -> pd.DataFrame:
        """Map actual columns to expected columns for a table category"""
        if category not in self.column_mappings:
            return df
        
        mapped_df = df.copy()
        mappings = self.column_mappings[category]
        
        # For each expected column, find the best matching actual column
        for expected_col, possible_actual_cols in mappings.items():
            best_match = self._find_best_column_match(possible_actual_cols, df.columns)
            if best_match:
                # Rename the column
                mapped_df = mapped_df.rename(columns={best_match: expected_col})
        
        return mapped_df
    
    def _find_best_column_match(self, possible_cols: List[str], actual_cols: List[str]) -> Optional[str]:
        """Find the best matching column from possible columns"""
        best_match = None
        best_score = 0
        
        for possible_col in possible_cols:
            for actual_col in actual_cols:
                # Exact match
                if possible_col == actual_col:
                    return actual_col
                
                # Fuzzy match
                score = fuzz.ratio(possible_col.lower(), actual_col.lower())
                if score > best_score and score > 80:  # 80% similarity threshold
                    best_score = score
                    best_match = actual_col
        
        return best_match
    
    def extract_numeric_data(self, df: pd.DataFrame, category: str) -> pd.DataFrame:
        """Extract numeric data from tables based on category"""
        if category == 'regional_summary':
            return self._extract_regional_summary_data(df)
        elif category == 'state_energy':
            return self._extract_state_energy_data(df)
        elif category == 'frequency_profile':
            return self._extract_frequency_profile_data(df)
        elif category == 'transnational_exchange':
            return self._extract_transnational_exchange_data(df)
        elif category == 'import_export_regions':
            return self._extract_import_export_regions_data(df)
        elif category == 'outage_data':
            return self._extract_outage_data_data(df)
        elif category == 'generation_breakdown':
            return self._extract_generation_breakdown_data(df)
        elif category == 're_share':
            return self._extract_re_share_data(df)
        elif category == 'solar_nonsolar_hour':
            return self._extract_solar_nonsolar_hour_data(df)
        elif category == 'transmission_flow':
            return self._extract_transmission_flow_data(df)
        elif category == 'cross_border_schedule_1':
            return self._extract_cross_border_schedule_data(df)
        elif category == 'time_block':
            return self._extract_time_block_data(df)
        else:
            return df
    
    def _extract_regional_summary_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from regional summary table"""
        # This table has regions as columns and metrics as rows
        # We need to transpose and extract the numeric values
        result_rows = []
        
        # Look for rows that contain numeric data
        for idx, row in df.iterrows():
            row_values = row.values
            # Check if this row contains numeric data
            numeric_count = 0
            for val in row_values:
                try:
                    float(str(val).replace(',', ''))
                    numeric_count += 1
                except:
                    pass
            
            if numeric_count >= 3:  # At least 3 numeric values
                # Extract the metric name and values
                metric_name = str(row.iloc[0]) if len(row) > 0 else f"Metric_{idx}"
                values = []
                for i in range(1, len(row)):
                    try:
                        val = float(str(row.iloc[i]).replace(',', ''))
                        values.append(val)
                    except:
                        values.append(0.0)
                
                # Create a row for each region
                regions = ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL']
                for i, region in enumerate(regions):
                    if i < len(values):
                        result_rows.append({
                            'Region': region,
                            'Metric': metric_name,
                            'Value': values[i]
                        })
        
        return pd.DataFrame(result_rows)
    
    def _extract_state_energy_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from state energy table"""
        # This table has states as rows and metrics as columns
        result_rows = []
        
        for idx, row in df.iterrows():
            if len(row) >= 3:  # At least region, state, and one metric
                region = str(row.iloc[0]) if len(row) > 0 else ""
                state = str(row.iloc[1]) if len(row) > 1 else ""
                
                # Extract numeric values
                numeric_values = []
                for i in range(2, len(row)):
                    try:
                        val = float(str(row.iloc[i]).replace(',', ''))
                        numeric_values.append(val)
                    except:
                        numeric_values.append(0.0)
                
                # Map to expected columns
                if len(numeric_values) >= 6:
                    result_rows.append({
                        'Region': region,
                        'States': state,
                        'Maximum Demand (MW)': numeric_values[0] if len(numeric_values) > 0 else 0.0,
                        'Shortage (MW)': numeric_values[1] if len(numeric_values) > 1 else 0.0,
                        'Energy Met (MU)': numeric_values[2] if len(numeric_values) > 2 else 0.0,
                        'Drawal Schedule (MU)': numeric_values[3] if len(numeric_values) > 3 else 0.0,
                        'OD(+)/UD(-) (MU)': numeric_values[4] if len(numeric_values) > 4 else 0.0,
                        'Max OD (MW)': numeric_values[5] if len(numeric_values) > 5 else 0.0,
                        'Energy Shortage (MU)': numeric_values[6] if len(numeric_values) > 6 else 0.0
                    })
        
        return pd.DataFrame(result_rows)
    
    def _extract_frequency_profile_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from frequency profile table"""
        result_rows = []
        
        for idx, row in df.iterrows():
            if len(row) >= 2:  # At least region and FVI
                region = str(row.iloc[0]) if len(row) > 0 else ""
                
                # Extract numeric values
                numeric_values = []
                for i in range(1, len(row)):
                    try:
                        val = float(str(row.iloc[i]).replace(',', ''))
                        numeric_values.append(val)
                    except:
                        numeric_values.append(0.0)
                
                if len(numeric_values) >= 7:
                    result_rows.append({
                        'Region': region,
                        'FVI': numeric_values[0] if len(numeric_values) > 0 else 0.0,
                        'Duration Frequency Below 49.7 (s)': numeric_values[1] if len(numeric_values) > 1 else 0.0,
                        'Duration Frequency 49.7-49.8 (s)': numeric_values[2] if len(numeric_values) > 2 else 0.0,
                        'Duration Frequency 49.8-49.9 (s)': numeric_values[3] if len(numeric_values) > 3 else 0.0,
                        'Duration Frequency Below 49.9 (s)': numeric_values[4] if len(numeric_values) > 4 else 0.0,
                        'Duration Frequency 49.9-50.05 (s)': numeric_values[5] if len(numeric_values) > 5 else 0.0,
                        'Duration Frequency Above 50.05 (s)': numeric_values[6] if len(numeric_values) > 6 else 0.0
                    })
        
        return pd.DataFrame(result_rows)
    
    def _extract_transnational_exchange_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from transnational exchange table"""
        result_rows = []
        
        # This table has countries as columns
        countries = ['Bhutan', 'Nepal', 'Bangladesh', 'Godda -> Bangladesh']
        
        for idx, row in df.iterrows():
            if len(row) >= 2:  # At least metric and one country
                metric = str(row.iloc[0]) if len(row) > 0 else ""
                
                # Extract values for each country
                for i, country in enumerate(countries):
                    if i + 1 < len(row):
                        try:
                            val = float(str(row.iloc[i + 1]).replace(',', ''))
                        except:
                            val = 0.0
                        
                        result_rows.append({
                            'Country': country,
                            'Metric': metric,
                            'Value': val
                        })
        
        return pd.DataFrame(result_rows)
    
    def _extract_import_export_regions_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from import/export regions table"""
        return self._extract_regional_summary_data(df)  # Similar structure
    
    def _extract_outage_data_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from outage data table"""
        return self._extract_regional_summary_data(df)  # Similar structure
    
    def _extract_generation_breakdown_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from generation breakdown table"""
        return self._extract_regional_summary_data(df)  # Similar structure
    
    def _extract_re_share_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from RE share table"""
        result_rows = []
        
        for idx, row in df.iterrows():
            if len(row) >= 2:
                metric = str(row.iloc[0]) if len(row) > 0 else ""
                try:
                    value = float(str(row.iloc[1]).replace(',', ''))
                except:
                    value = 0.0
                
                result_rows.append({
                    'Metric': metric,
                    'Value': value
                })
        
        return pd.DataFrame(result_rows)
    
    def _extract_solar_nonsolar_hour_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from solar/non-solar hour table"""
        result_rows = []
        
        for idx, row in df.iterrows():
            if len(row) >= 3:
                period = str(row.iloc[0]) if len(row) > 0 else ""
                try:
                    max_demand = float(str(row.iloc[1]).replace(',', ''))
                except:
                    max_demand = 0.0
                try:
                    shortage = float(str(row.iloc[3]).replace(',', ''))
                except:
                    shortage = 0.0
                
                result_rows.append({
                    'Period': period,
                    'Max Demand Met(MW)': max_demand,
                    'Shortage(MW)': shortage
                })
        
        return pd.DataFrame(result_rows)
    
    def _extract_transmission_flow_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from transmission flow table"""
        result_rows = []
        
        for idx, row in df.iterrows():
            if len(row) >= 5:  # At least line details and some metrics
                line_details = str(row.iloc[2]) if len(row) > 2 else ""
                
                # Extract numeric values
                numeric_values = []
                for i in range(4, len(row)):  # Start from column 4 (Max Import)
                    try:
                        val = float(str(row.iloc[i]).replace(',', ''))
                        numeric_values.append(val)
                    except:
                        numeric_values.append(0.0)
                
                if len(numeric_values) >= 5:
                    result_rows.append({
                        'Line Details': line_details,
                        'Max Import (MW)': numeric_values[0] if len(numeric_values) > 0 else 0.0,
                        'Max Export (MW)': numeric_values[1] if len(numeric_values) > 1 else 0.0,
                        'Import (MU)': numeric_values[2] if len(numeric_values) > 2 else 0.0,
                        'Export (MU)': numeric_values[3] if len(numeric_values) > 3 else 0.0,
                        'NET (MU)': numeric_values[4] if len(numeric_values) > 4 else 0.0
                    })
        
        return pd.DataFrame(result_rows)
    
    def _extract_cross_border_schedule_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from cross border schedule table"""
        result_rows = []
        
        for idx, row in df.iterrows():
            if len(row) >= 2:
                country = str(row.iloc[0]) if len(row) > 0 else ""
                
                # Extract numeric values
                numeric_values = []
                for i in range(1, len(row)):
                    try:
                        val = float(str(row.iloc[i]).replace(',', ''))
                        numeric_values.append(val)
                    except:
                        numeric_values.append(0.0)
                
                if len(numeric_values) >= 3:
                    result_rows.append({
                        'Country': country,
                        'GNA': numeric_values[0] if len(numeric_values) > 0 else 0.0,
                        'Bilateral': numeric_values[1] if len(numeric_values) > 1 else 0.0,
                        'Total': numeric_values[2] if len(numeric_values) > 2 else 0.0
                    })
        
        return pd.DataFrame(result_rows)
    
    def _extract_time_block_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from time block table"""
        result_rows = []
        
        for idx, row in df.iterrows():
            if len(row) >= 2:  # At least time and one metric
                time_str = str(row.iloc[0]) if len(row) > 0 else ""
                
                # Extract numeric values
                numeric_values = []
                for i in range(1, len(row)):
                    try:
                        val = float(str(row.iloc[i]).replace(',', ''))
                        numeric_values.append(val)
                    except:
                        numeric_values.append(0.0)
                
                if len(numeric_values) >= 12:
                    result_rows.append({
                        'TIME': time_str,
                        'FREQUENCY (Hz)': numeric_values[0] if len(numeric_values) > 0 else 0.0,
                        'DEMAND MET (MW)': numeric_values[1] if len(numeric_values) > 1 else 0.0,
                        'NUCLEAR (MW)': numeric_values[2] if len(numeric_values) > 2 else 0.0,
                        'WIND (MW)': numeric_values[3] if len(numeric_values) > 3 else 0.0,
                        'SOLAR (MW)': numeric_values[4] if len(numeric_values) > 4 else 0.0,
                        'HYDRO (MW)': numeric_values[5] if len(numeric_values) > 5 else 0.0,
                        'GAS (MW)': numeric_values[6] if len(numeric_values) > 6 else 0.0,
                        'THERMAL (MW)': numeric_values[7] if len(numeric_values) > 7 else 0.0,
                        'OTHERS* (MW)': numeric_values[8] if len(numeric_values) > 8 else 0.0,
                        'NET DEMAND MET (MW)': numeric_values[9] if len(numeric_values) > 9 else 0.0,
                        'TOTAL GENERATION (MW)': numeric_values[10] if len(numeric_values) > 10 else 0.0,
                        'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export': numeric_values[11] if len(numeric_values) > 11 else 0.0
                    })
        
        return pd.DataFrame(result_rows) 