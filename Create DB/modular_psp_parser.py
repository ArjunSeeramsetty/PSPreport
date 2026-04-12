#!/usr/bin/env python3
"""
Modular PSP (Power Supply Position) Report Parser
Combines table identification and processing logic in a single file with clear separation of concerns.

This module provides:
1. Table Identification: Smart classification of tables from PDF extraction
2. Table Processing: Transformation of raw tables into standardized formats
3. Main Orchestrator: Coordinates identification and processing workflows
"""

import pandas as pd
import numpy as np
import logging
import re
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional, Union
from difflib import SequenceMatcher
from fuzzywuzzy import fuzz
import json
from dataclasses import dataclass
from PyPDF2 import PdfReader
import tabula

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class TableClassification:
    """Represents a table classification result"""
    table_name: str
    confidence: float
    category: str
    description: str
    column_mappings: Dict[str, str]

@dataclass
class ColumnMapping:
    """Represents a column mapping result"""
    source_column: str
    target_column: str
    confidence: float
    mapping_type: str  # 'exact', 'fuzzy', 'llm'

@dataclass
class ProcessingResult:
    """Represents the result of processing a table"""
    table_name: str
    success: bool
    processed_df: Optional[pd.DataFrame]
    error_message: Optional[str]
    source_tables: List[str]

# ============================================================================
# TABLE IDENTIFICATION MODULE
# ============================================================================

class TableIdentifier:
    """
    Responsible for identifying and classifying tables from raw PDF extraction.
    Uses pattern matching, fuzzy logic, and content analysis.
    """
    
    def __init__(self):
        self.table_patterns = {
            'regional_summary': {
                'keywords': ['regional', 'summary', 'all india', 'power supply', 'demand met', 'peak demand', 'energy met'],
                'required_columns': ['demand', 'energy', 'peak', 'nr', 'wr', 'sr', 'er', 'ner'],
                'description': 'Regional power supply and demand summary'
            },
            'frequency_profile': {
                'keywords': ['frequency', 'fvi', '49.7', '50.05', 'frequency profile'],
                'required_columns': ['frequency', 'fvi', '49.7', '50.05'],
                'description': 'Frequency profile and violation index'
            },
            'state_energy': {
                'keywords': ['state', 'states', 'power supply position in states', 'maximum demand', 'energy met'],
                'required_columns': ['states', 'maximum demand', 'energy met', 'shortage'],
                'description': 'State-wise power supply and demand data'
            },
            'transnational_exchange': {
                'keywords': ['transnational', 'bhutan', 'nepal', 'bangladesh', 'godda', 'exchange', 'country', 'gna', 'bilateral', 'total', 'collective'],
                'required_columns': ['bhutan', 'nepal', 'bangladesh', 'exchange', 'country', 'gna'],
                'description': 'Transnational power exchange data'
            },
            'import_export_regions': {
                'keywords': ['import', 'export', 'regions', 'schedule', 'actual', 'od/ud', 'schedule(mu)', 'actual(mu)', 'o/d/u/d(mu)'],
                'required_columns': ['schedule', 'actual', 'import', 'export', 'nr', 'wr', 'sr', 'er', 'ner'],
                'description': 'Import/Export by regions data'
            },
            'outage_data': {
                'keywords': ['outage', 'central sector', 'state sector', 'generation outage', 'sector', 'total', '% share'],
                'required_columns': ['outage', 'sector', 'central sector', 'state sector', 'total'],
                'description': 'Generation outage information'
            },
            'generation_breakdown': {
                'keywords': ['sourcewise', 'generation', 'coal', 'hydro', 'nuclear', 'wind', 'solar', 'sourcewise generation', 'lignite', 'gas naptha diesel', 'all india', '% share'],
                'required_columns': ['coal', 'hydro', 'nuclear', 'generation', 'all india'],
                'description': 'Generation breakdown by source'
            },
            're_share': {
                'keywords': ['re', 'renewable', 'share', 'non-fossil', 'res', 'share of re', 'share of res in total generation', 'non-fossil fuel'],
                'required_columns': ['re', 'share', 'non-fossil', 'res'],
                'description': 'Renewable energy share data'
            },
            'demand_diversity_factor_ddf': {
                'keywords': ['diversity', 'ddf', 'demand diversity factor', 'all india demand diversity', 'based on regional max demands', 'based on state max demands', 'regional max demands', 'state max demands', 'demands'],
                'required_columns': ['diversity', 'ddf', 'factor', 'demands', 'regional', 'state', 'max demands'],
                'description': 'Demand diversity factor data',
                'priority': 1  # Higher priority than state_energy
            },
            'solar_nonsolar_hour': {
                'keywords': ['solar', 'non-solar', 'peak demand', 'solar hour', 'non-solar hour', 'solar hr', 'non-solar hr', 'max demand met', 'shortage', 'time'],
                'required_columns': ['solar', 'non-solar', 'peak demand', 'time', 'shortage'],
                'description': 'Solar and non-solar hour peak demand data'
            },
            'transmission_flow': {
                'keywords': ['transmission', 'import', 'export', 'schedule', 'actual', 'line', 'import/export of er', 'with nr'],
                'required_columns': ['schedule', 'actual', 'import', 'export', 'line'],
                'description': 'Transmission and inter-regional exchange data'
            },
            'international_exchange': {
                'keywords': ['international', 'bhutan', 'nepal', 'bangladesh', 'exchange', 'international exchanges', 'state', 'region', 'line name', 'max (mw)', 'min (mw)', 'avg (mw)'],
                'required_columns': ['state', 'region', 'line name', 'max', 'min', 'avg'],
                'description': 'International power exchange data'
            },
            'cross_border_schedule_1': {
                'keywords': ['cross border', 'schedule', 'export', 'import', 'bilateral', 'total', 'collective'],
                'required_columns': ['country', 'gna', 'bilateral', 'total'],
                'description': 'Cross border schedule table 1'
            },
            'cross_border_schedule_2': {
                'keywords': ['cross border', 'schedule', 'export', 'import', 'bilateral', 'total', 'collective'],
                'required_columns': ['country', 'gna', 'bilateral', 'total'],
                'description': 'Cross border schedule table 2'
            },
            'cross_border_schedule_3': {
                'keywords': ['cross border', 'schedule', 'export', 'import', 'bilateral', 'total', 'collective'],
                'required_columns': ['country', 'gna', 'bilateral', 'total'],
                'description': 'Cross border schedule table 3'
            },
            'time_block': {
                'keywords': ['time block', 'block time', 'frequency', 'demand met', '15 min', 'instantaneous'],
                'required_columns': ['time', 'frequency', 'demand'],
                'description': 'Time block wise power data'
            }
        }
        
        # Database column mappings for each table type
        self.db_column_mappings = {
            'regional_summary': {
                'PeakDemandMet': ['demand met during evening peak hrs', 'peak demand met', 'demand met'],
                'EnergyMet': ['energy met', 'energy met (mu)'],
                'EnergyShortage': ['energy shortage', 'energy shortage (mu)'],
                'MaxDemandSCADA': ['maximum demand met during the day', 'max demand scada'],
                'PeakShortage': ['peak shortage', 'peak shortage (mw)'],
                'TimeOfMaxDemandMet': ['time of maximum demand met', 'time of max demand met'],
                'ScheduleDrawal': ['schedule(mu)', 'schedule drawal'],
                'ActualDrawal': ['actual(mu)', 'actual drawal'],
                'OverUnderDrawal': ['o/d/u/d(mu)', 'over under drawal'],
                'ShareRESInTotalGeneration': ['share of res in total generation', 'res share'],
                'ShareNonFossilInTotalGeneration': ['share of non-fossil', 'non-fossil share'],
                'FrequencyViolationIndex': ['fvi', 'frequency violation index'],
                'DurationFrequencyBelow49_7': ['frequency (<49.7)', 'frequency below 49.7'],
                'DurationFrequency_49_7_to_49_8': ['frequency (49.7 - 49.8)', 'frequency 49.7 to 49.8'],
                'DurationFrequency_49_8_to_49_9': ['frequency (49.8 - 49.9)', 'frequency 49.8 to 49.9'],
                'DurationFrequencyBelow49_9': ['frequency (< 49.9)', 'frequency below 49.9'],
                'DurationFrequency_49_9_to_50_05': ['frequency (49.9 - 50.05)', 'frequency 49.9 to 50.05'],
                'DurationFrequencyAbove50_05': ['frequency (> 50.05)', 'frequency above 50.05'],
                'RegionDDF': ['region ddf', 'regional ddf'],
                'StatesDDF': ['states ddf', 'state ddf'],
                'SolarHRMaxDemand': ['solarhr max demand', 'solar hr max demand'],
                'SolarHRMaxDemandTime': ['solarhr max demand time', 'solar hr max demand time'],
                'SolarHRShortage': ['solarhr shortage', 'solar hr shortage'],
                'NonSolarHRMaxDemand': ['non-solarhr max demand', 'non solar hr max demand'],
                'NonSolarHRMaxDemandTime': ['non-solarhr max demand time', 'non solar hr max demand time'],
                'NonSolarHRShortage': ['non-solarhr shortage', 'non solar hr shortage']
            },
            'state_energy': {
                'MaximumDemand': ['maximum demand', 'max demand', 'max.demand', 'maximumdemand', 'maximum demand (mw)'],
                'Shortage': ['shortage', 'shortage (mw)', 'shortage during', 'energy shortage', 'energy shortage (mu)'],
                'EnergyMet': ['energy met', 'energy met (mu)', 'energymet'],
                'DrawalSchedule': ['drawal schedule', 'schedule (mu)', 'drawal\rSchedule', 'drawalschedule'],
                'OverUnderDrawal': ['od/ud', 'over under drawal', 'od(+)/ud(-)', 'overunderdrawal', 'od(+)/ud(-) (mu)', 'o/d/u/d(mu)'],
                'MaxOverDrawal': ['max od', 'max over drawal', 'max od\r(mw)', 'maxoverdrawal', 'max od (mw)'],
                'EnergyShortage': ['energy shortage', 'energy shortage (mu)', 'energyshortage']
            },
            'transnational_exchange': {
                'Bhutan': ['bhutan'],
                'Nepal': ['nepal'],
                'Bangladesh': ['bangladesh'],
                'GoddaBangladesh': ['godda', 'godda -> bangladesh']
            },
            'import_export_regions': {
                'Schedule': ['schedule', 'schedule(mu)'],
                'Actual': ['actual', 'actual(mu)'],
                'Import': ['import'],
                'Export': ['export']
            },
            'generation_breakdown': {
                'Coal': ['coal', 'main coal'],
                'Lignite': ['lignite', 'main lignite'],
                'Hydro': ['hydro', 'main hydro'],
                'Nuclear': ['nuclear', 'main nuclear'],
                'GasNapthaDiesel': ['gas, naptha & diesel', 'main gas naptha diesel'],
                'RES': ['res (wind, solar, biomass & others)', 'main res'],
                'Total': ['total', 'main total']
            },
            're_share': {
                'REShare': ['re', 'renewable', 'share of re'],
                'NonFossilShare': ['non-fossil', 'non fossil share']
            },
            'demand_diversity_factor_ddf': {
                'RegionDDF': ['region ddf', 'regional ddf'],
                'StatesDDF': ['states ddf', 'state ddf']
            },
            'solar_nonsolar_hour': {
                'SolarHRMaxDemand': ['solarhr max demand', 'solar hr max demand'],
                'SolarHRShortage': ['solarhr shortage', 'solar hr shortage'],
                'NonSolarHRMaxDemand': ['non-solarhr max demand', 'non solar hr max demand'],
                'NonSolarHRShortage': ['non-solarhr shortage', 'non solar hr shortage']
            }
        }
    
    def classify_table(self, df: pd.DataFrame, table_name: str = None) -> TableClassification:
        """
        Classify a table based on its content and structure.
        
        Args:
            df: DataFrame to classify
            table_name: Optional name for the table
            
        Returns:
            TableClassification object with classification results
        """
        if df.empty:
            return TableClassification(
                table_name=table_name or "unknown",
                confidence=0.0,
                category="empty",
                description="Empty table",
                column_mappings={}
            )
        
        # Extract table text for analysis
        table_text = self._extract_table_text(df, table_name)
        columns = [str(col).lower() for col in df.columns]
        
        # Find best matching pattern
        best_match = None
        best_score = 0.0
        
        for category, pattern in self.table_patterns.items():
            score = self._calculate_table_score(table_text, columns, pattern)
            if score > best_score:
                best_score = score
                best_match = category
        
        if best_match and best_score > 0.2:  # Lowered threshold from 0.3 to 0.2
            # Generate column mappings
            column_mappings = self._generate_column_mappings(df, best_match)
            
            return TableClassification(
                table_name=table_name or best_match,
                confidence=best_score,
                category=best_match,
                description=self.table_patterns[best_match]['description'],
                column_mappings=column_mappings
            )
        else:
            return TableClassification(
                table_name=table_name or "unknown",
                confidence=best_score,
                category="unknown",
                description="Unknown table type",
                column_mappings={}
            )
    
    def _extract_table_text(self, df: pd.DataFrame, table_name: str = None) -> str:
        """Extract text content from DataFrame for analysis"""
        text_parts = []
        
        # Add table name if provided
        if table_name:
            text_parts.append(table_name.lower())
        
        # Add column names
        text_parts.extend([str(col).lower() for col in df.columns])
        
        # Add first few rows of data
        for i in range(min(3, len(df))):
            row_text = " ".join([str(val).lower() for val in df.iloc[i].values if pd.notna(val)])
            text_parts.append(row_text)
        
        return " ".join(text_parts)
    
    def _calculate_table_score(self, table_text: str, columns: List[str], pattern: Dict) -> float:
        """Calculate similarity score between table and pattern"""
        score = 0.0
        
        # Check keyword matches
        keyword_matches = 0
        for keyword in pattern['keywords']:
            if self._fuzzy_match(keyword, table_text, threshold=60):  # Lowered threshold for better matching
                keyword_matches += 1
        
        keyword_score = keyword_matches / len(pattern['keywords']) if pattern['keywords'] else 0
        
        # Check required column matches
        column_matches = 0
        for required_col in pattern['required_columns']:
            for col in columns:
                if self._fuzzy_match(required_col, col, threshold=70):  # Lowered threshold
                    column_matches += 1
                    break
        
        column_score = column_matches / len(pattern['required_columns']) if pattern['required_columns'] else 0
        
        # Combine scores (weighted average) - give more weight to keyword matches
        score = (keyword_score * 0.7) + (column_score * 0.3)
        
        # Apply priority boost if pattern has priority
        if 'priority' in pattern:
            score += (pattern['priority'] * 0.1)  # Boost score by priority * 0.1
        
        return score
    
    def _fuzzy_match(self, target: str, source: str, threshold: float = 80) -> bool:
        """Check if target string matches source using fuzzy matching"""
        target_norm = self._normalize_text(target)
        source_norm = self._normalize_text(source)
        
        # Try different matching strategies
        if target_norm in source_norm:
            return True
        
        if fuzz.partial_ratio(target_norm, source_norm) >= threshold:
            return True
        
        if fuzz.token_sort_ratio(target_norm, source_norm) >= threshold:
            return True
        
        return False
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison"""
        if not text:
            return ""
        
        # Convert to lowercase
        text = text.lower()
        
        # Remove special characters and extra whitespace
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    def _generate_column_mappings(self, df: pd.DataFrame, table_category: str) -> Dict[str, str]:
        """Generate column mappings for the given table category"""
        mappings = {}
        
        if table_category not in self.db_column_mappings:
            return mappings
        
        target_mappings = self.db_column_mappings[table_category]
        
        for target_col, source_aliases in target_mappings.items():
            best_match = None
            best_score = 0
            
            for col in df.columns:
                col_str = str(col).lower()
                
                for alias in source_aliases:
                    score = self._calculate_similarity(alias.lower(), col_str)
                    if score > best_score and score > 0.7:
                        best_score = score
                        best_match = col
            
            if best_match:
                mappings[best_match] = target_col
        
        return mappings
    
    def _calculate_similarity(self, target: str, source: str) -> float:
        """Calculate similarity between two strings"""
        return fuzz.ratio(target, source) / 100.0
    
    def classify_dataframes(self, dataframes: List[pd.DataFrame], table_names: List[str] = None) -> List[TableClassification]:
        """Classify multiple DataFrames"""
        results = []
        
        for i, df in enumerate(dataframes):
            table_name = table_names[i] if table_names and i < len(table_names) else None
            classification = self.classify_table(df, table_name)
            results.append(classification)
        
        return results

# ============================================================================
# TABLE PROCESSING MODULE (Using PSPTransformer from PDFparser_Gemini.py)
# ============================================================================

class PSPTransformer:
    def __init__(self, report_date):
        self.report_date = report_date
        self.logger = logging.getLogger(self.__class__.__name__)

    def _clean_column_names(self, df_columns):
        cleaned_cols = []
        for col in df_columns:
            cleaned_col = str(col).strip().replace('\n', ' ', -1)
            cleaned_col = cleaned_col.replace('*', '', -1).replace('(', '', -1).replace(')', '', -1)
            cleaned_cols.append(cleaned_col)
        return cleaned_cols

    def _add_common_cols(self, df, table_name):
        df_out = df.copy()
        df_out['Date'] = self.report_date
        df_out['Table Name'] = table_name
        return df_out

    def transform_comprehensive_regional_summary(self, raw_df_A, raw_df_B, raw_df_E, raw_df_F, 
                                                 raw_df_G_main, raw_df_G_share, raw_df_H, raw_df_I, report_date):
        """
        Transform regional summary using comprehensive merging logic from stable version.
        Combines data from all available regional tables into a comprehensive dataset.
        """
        melted_data_list = []
        transformer = PSPTransformer(report_date)

        # --- Process G_Share using G_Main's column structure ---
        if raw_df_G_share is not None and not raw_df_G_share.empty and raw_df_G_main is not None and not raw_df_G_main.empty:
            df_g_main_for_cols = raw_df_G_main.copy()
            cleaned_g_main_cols = transformer._clean_column_names(df_g_main_for_cols.columns)
            
            df_g_share_copy = raw_df_G_share.copy()
            original_g_share_header_as_data = df_g_share_copy.columns.tolist()
            
            # Create a new DataFrame for G_Share starting with its "original header" as the first data row
            df_g_share_transformed = pd.DataFrame([original_g_share_header_as_data], 
                                                columns=cleaned_g_main_cols[:len(original_g_share_header_as_data)])
            
            # Append the rest of G_Share's data
            if df_g_share_copy.shape[0] > 0:
                g_share_data_df = pd.DataFrame(data=df_g_share_copy.values, 
                                             columns=cleaned_g_main_cols[:df_g_share_copy.shape[1]])
                df_g_share_transformed = pd.concat([df_g_share_transformed, g_share_data_df], ignore_index=True)
            
            # Melt G_Share data
            if df_g_share_transformed.shape[1] >= 2:
                g_share_metrics_col = df_g_share_transformed.columns[0]
                g_share_region_cols = df_g_share_transformed.columns[1:]
                df_g_share_melted = df_g_share_transformed.melt(
                    id_vars=[g_share_metrics_col], value_vars=g_share_region_cols,
                    var_name='Region', value_name='Value'
                )
                df_g_share_melted.rename(columns={g_share_metrics_col: 'Metric'}, inplace=True)
                df_g_share_melted['Region'] = df_g_share_melted['Region'].astype(str).str.strip().replace(
                    {'TOTAL': 'TOTAL', 'All India': 'TOTAL'}, regex=False
                )
                melted_data_list.append(df_g_share_melted[['Metric', 'Region', 'Value']])

        # --- Process Tables A, E, F, G_main ---
        data_sources_for_melt = [
            (raw_df_A, 'A'), (raw_df_E, 'E'), (raw_df_F, 'F'), (raw_df_G_main, 'G_Main')
        ]
        
        for df_source, source_name in data_sources_for_melt:
            if df_source is not None and not df_source.empty and df_source.shape[1] >= 2:
                df_temp = df_source.copy()
                df_temp.columns = transformer._clean_column_names(df_temp.columns)
                
                metrics_col_name = df_temp.columns[0]
                region_col_names = df_temp.columns[1:]
                df_melted = df_temp.melt(
                    id_vars=[metrics_col_name], value_vars=region_col_names,
                    var_name='Region', value_name='Value'
                )
                df_melted.rename(columns={metrics_col_name: 'Metric'}, inplace=True)
                df_melted['Region'] = df_melted['Region'].astype(str).str.strip().replace(
                    {'TOTAL': 'TOTAL', 'All India': 'TOTAL'}, regex=False
                )
                melted_data_list.append(df_melted[['Metric', 'Region', 'Value']])

        # Combine all melted data
        if not melted_data_list:
            self.logger.warning("No melted data available for regional summary")
            return None
            
        combined_melted_df = pd.concat(melted_data_list, ignore_index=True)
        additional_rows = []

        # --- Process Table B: Frequency Profile (%) ---
        if raw_df_B is not None and not raw_df_B.empty:
            df_b = raw_df_B.copy()
            all_india_mask = df_b.iloc[:, 0].astype(str).str.contains('All India', case=False, na=False)
            
            if any(all_india_mask):
                all_india_row = df_b[all_india_mask].iloc[0]
                freq_metrics = [
                    ('FVI', 1), ('Frequency (<49.7)', 2), ('Frequency (49.7 - 49.8)', 3),
                    ('Frequency (49.8 - 49.9)', 4), ('Frequency (< 49.9)', 5),
                    ('Frequency (49.9 - 50.05)', 6), ('Frequency (> 50.05)', 7)
                ]
                
                for metric_name, col_idx in freq_metrics:
                    if col_idx < len(all_india_row):
                        value = all_india_row.iloc[col_idx]
                        try:
                            value = pd.to_numeric(str(value).replace('%', '').strip(), errors='coerce')
                        except:
                            value = None
                        
                        if value is not None:
                            combined_melted_df.loc[len(combined_melted_df)] = {
                                'Metric': metric_name,
                                'Region': 'TOTAL',
                                'Value': value
                            }

        # --- Process Table H: All India Demand Diversity Factor ---
        if raw_df_H is not None and not raw_df_H.empty:
            df_h_copy = raw_df_H.copy()
            
            # Check if the table has the expected structure (2 columns)
            if df_h_copy.shape[1] == 2:
                # Get the column names (which might contain the first metric)
                col_names = df_h_copy.columns.tolist()
                self.logger.debug(f"Table H columns: {col_names}")
                
                # Check if the first column name contains a metric
                first_col_name = str(col_names[0]).strip()
                if 'regional' in first_col_name.lower() and len(col_names) > 1:
                    # The first column name contains the Region DDF metric
                    try:
                        region_ddf_value = pd.to_numeric(str(col_names[1]).replace('%', '').strip(), errors='coerce')
                        if region_ddf_value is not None:
                            additional_rows.append({
                                'Metric': 'Region DDF', 'Region': 'TOTAL', 'Value': region_ddf_value
                            })
                    except:
                        pass
                
                # Process the data rows
                for row_idx in range(len(df_h_copy)):
                    if row_idx < len(df_h_copy):
                        row = df_h_copy.iloc[row_idx]
                        if len(row) >= 2:
                            # Get the metric name and value
                            metric_name = str(row.iloc[0]).strip()
                            value = row.iloc[1]
                            
                            # Clean and convert the value
                            try:
                                value = pd.to_numeric(str(value).replace('%', '').strip(), errors='coerce')
                            except:
                                value = None
                            
                            if value is not None:
                                # Determine if this is Region DDF or States DDF based on the metric name
                                if 'regional' in metric_name.lower():
                                    additional_rows.append({
                                        'Metric': 'Region DDF', 'Region': 'TOTAL', 'Value': value
                                    })
                                elif 'state' in metric_name.lower():
                                    additional_rows.append({
                                        'Metric': 'States DDF', 'Region': 'TOTAL', 'Value': value
                                    })

        # --- Process Table I: All India Peak Demand and shortage ---
        if raw_df_I is not None and not raw_df_I.empty:
            df_i_copy = raw_df_I.copy()
            expected_rows, expected_cols_raw = 2, 4
            
            if df_i_copy.shape[0] == expected_rows and df_i_copy.shape[1] == expected_cols_raw:
                numeric_list = df_i_copy.iloc[0, 1:expected_cols_raw].tolist() + df_i_copy.iloc[1, 1:expected_cols_raw].tolist()
                target_columns = [
                    'SolarHR Max Demand', 'SolarHR Max Demand Time', 'SolarHR Shortage',
                    'Non-SolarHR Max Demand', 'Non-SolarHR Max Demand Time', 'Non-SolarHR Shortage'
                ]
                
                if len(numeric_list) == len(target_columns):
                    df_processed = pd.DataFrame([numeric_list], columns=target_columns)
                    
                    for metric_name in target_columns:
                        combined_melted_df.loc[len(combined_melted_df)] = {
                            'Metric': metric_name,
                            'Region': 'TOTAL',
                            'Value': df_processed.loc[0, metric_name]
                        }

        # Add additional rows
        if additional_rows:
            df_additional_rows = pd.DataFrame(additional_rows)
            combined_melted_df = pd.concat([combined_melted_df, df_additional_rows], ignore_index=True)

        # Convert to wide format for validation
        if combined_melted_df.empty:
            self.logger.warning("No data available for regional summary after processing")
            return None

        # Add Date and Table Name columns
        combined_melted_df.insert(0, 'Date', report_date)
        combined_melted_df.insert(1, 'Table Name', 'Regional Summary')
        
        return combined_melted_df

    def transform_states(self, raw_df):
        df = raw_df.copy()
        target_csv_columns = [
            'Region', 'States', 'Maximum Demand (MW)', 'Shortage (MW)', 'Energy Met (MU)',
            'Drawal Schedule (MU)', 'OD(+)/UD(-) (MU)', 'Max OD (MW)', 'Energy Shortage (MU)'
        ]

        # Build set of all valid state names from region_mapping
        region_mapping = {
            'Punjab': 'NR', 'Haryana': 'NR', 'Rajasthan': 'NR', 'Delhi': 'NR', 'UP': 'NR',
            'Uttarakhand': 'NR', 'HP': 'NR', 'J&K(UT) & Ladakh(UT)': 'NR', 'J&K(UT) &.': 'NR', 'Chandigarh': 'NR', 'Railways_NR ISTS': 'NR',
            'RailwaysNR ISTS': 'NR', 'Railways_NR': 'NR',
            'Chhattisgarh': 'WR', 'Gujarat': 'WR', 'MP': 'WR', 'Maharashtra': 'WR', 'Goa': 'WR',
            'DNHDDPDCL': 'WR', 'AMNSIL': 'WR', 'BALCO': 'WR', 'RIL JAMNAGAR': 'WR',
            'Andhra Pradesh': 'SR', 'Telangana': 'SR', 'Karnataka': 'SR', 'Kerala': 'SR', 'Tamil Nadu': 'SR', 'Puducherry': 'SR',
            'Bihar': 'ER', 'DVC': 'ER', 'Jharkhand': 'ER', 'Odisha': 'ER', 'West Bengal': 'ER', 'Sikkim': 'ER', 'Railways_ER ISTS': 'ER', 'RailwaysER ISTS': 'ER', 'Railways_ER': 'ER',
            'Arunachal Pradesh': 'NER', 'Arunachal': 'NER', 'Assam': 'NER', 'Manipur': 'NER', 'Meghalaya': 'NER', 'Mizoram': 'NER', 'Nagaland': 'NER', 'Tripura': 'NER',
            # Add missing state mappings
            'J&K(UT) &': 'NR',
            'J&K(UT)': 'NR',
            'JAMMU & KASHMIR (UT)': 'NR',
            'Railways_NR': 'NR',
            'Railways_ER': 'ER',
            # Add RIL Jamnagar mapping
            'RIL Jamnagar': 'WR'
        }
        state_names = set(region_mapping.keys())
        region_codes = ['NR', 'WR', 'SR', 'ER', 'NER', 'ALL INDIA']

        # Always check for misaligned state names in the first column and shift right if found
        for i in range(df.shape[0]):
            first_val = str(df.iloc[i,0]).strip()
            if first_val in state_names:
                # Debug print
                print(f"Row {i} before shift: {df.iloc[i].tolist()}")
                df.iloc[i, 1:] = df.iloc[i, :-1]
                df.iloc[i, 0] = pd.NA
                print(f"Row {i} after shift:  {df.iloc[i].tolist()}")

        # If shape mismatch, try to fix by shifting right for rows with unmatched region codes
        if df.shape[1] != len(target_csv_columns):
            for i in range(df.shape[0]):
                first_val = str(df.iloc[i,0]).strip()
                if first_val not in region_codes and first_val != '' and not pd.isna(first_val) and first_val != 'ER\rNER':
                    df.iloc[i, 1:] = df.iloc[i, :-1]
                    df.iloc[i, 0] = pd.NA
            if df.shape[1] != len(target_csv_columns):
                raise ValueError(
                    f"Error (States Table): Column count mismatch after shifting. "
                    f"Expected {len(target_csv_columns)}, got {df.shape[1]}."
                )
        df.columns = target_csv_columns

        # Convert numeric columns to float64 at the start
        numeric_cols = [
            'Maximum Demand (MW)', 'Shortage (MW)', 'Energy Met (MU)',
            'Drawal Schedule (MU)', 'OD(+)/UD(-) (MU)', 'Max OD (MW)', 'Energy Shortage (MU)'
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')

        # NEW APPROACH: Drop the Region column from raw data and derive it purely from state mapping
        if 'States' in df.columns:
            # Create a new Region column based purely on state mapping
            df['Region'] = df['States'].map(region_mapping)
            
            # Check for unmapped states AFTER mapping
            unmapped_states = []
            for state in df['States'].dropna().astype(str).str.strip().unique():
                if state and state not in region_mapping:
                    # Ignore region codes that appear in States column
                    if state in ['ER', 'WR', 'SR', 'NR', 'NER']:
                        continue
                    if not any(summary_keyword in state.upper() for summary_keyword in ["TOTAL", "ALL INDIA"]):
                        unmapped_states.append(state)
            
            # Handle unmapped states gracefully by filtering them out
            if unmapped_states:
                print(f"Warning: Found unmapped states after processing: {unmapped_states}")
                # Filter out rows with unmapped states
                mask = ~df['States'].isin(unmapped_states)
                df = df[mask]
                print(f"Filtered out {len(unmapped_states)} rows with unmapped states")
                
                # If dataframe becomes empty after filtering, return empty dataframe
                if df.empty:
                    print("Warning: No valid rows remaining after filtering unmapped states")
                    # Return empty dataframe with correct columns
                    empty_df = pd.DataFrame(columns=['Date', 'Table Name'] + target_csv_columns)
                    return empty_df
        else:
            raise ValueError("Error (States Table): 'States' column not found for mapping.")

        # Clean and convert numeric columns one final time
        for col in numeric_cols:
            if col in df.columns:
                # Remove commas and clean up decimal points
                df[col] = df[col].astype(str).str.replace(',', '', regex=False).str.strip()
                df[col] = df[col].str.replace(r'\.+', '.', regex=True).str.rstrip('.')
                # Convert to float64
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')

        df = self._add_common_cols(df, 'States')
        final_ordered_columns = ['Date', 'Table Name'] + target_csv_columns
        return df[final_ordered_columns]

    def transform_international_net(self, raw_df):
        df = raw_df.copy()

        # Correction: Raw table from tabula should have 2 rows and 5 columns.
        expected_rows, expected_cols_raw = 2, 5
        if not (df.shape[0] == expected_rows and df.shape[1] == expected_cols_raw):
            raise ValueError(
                f"Error (International NET): Raw table shape mismatch. "
                f"Expected ({expected_rows} rows, {expected_cols_raw} cols), got {df.shape}. "
                f"Check PDF structure or tabula extraction."
            )
        
        # Values from 2nd to 5th column (index 1 to 4) for both rows
        numeric_list = df.iloc[0, 1:expected_cols_raw].tolist() + df.iloc[1, 1:expected_cols_raw].tolist()

        target_columns = [ # 8 target columns
            'Bhutan (MU)', 'Nepal (MU)', 'Bangladesh (MU)', 'Godda (Bangladesh) (MU)', 
            'Bhutan Peak (MW)', 'Nepal Peak (MW)', 'Bangladesh Peak (MW)', 'Godda (Bangladesh) Peak (MW)'
        ]
        
        if len(numeric_list) != len(target_columns):
            # This should not happen if raw table shape is (2,5) and numeric_list extraction is correct (4+4=8)
            raise ValueError(
                f"Error (International NET): Mismatch between extracted values ({len(numeric_list)}) "
                f"and target columns ({len(target_columns)}). Logic error in numeric_list creation."
            )
        
        df_processed = pd.DataFrame([numeric_list], columns=target_columns)
        
        for col in target_columns:
            df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce')
        
        df_processed = self._add_common_cols(df_processed, 'International NET')
        
        final_ordered_columns = ['Date', 'Table Name'] + target_columns
        # Correction: Final processed table must have all columns as in final_ordered_columns.
        if not all(col in df_processed.columns for col in final_ordered_columns) or \
           len(df_processed.columns) != len(final_ordered_columns):
            # This check is somewhat redundant if df_processed is built correctly above.
            raise ValueError(
                f"Error (International NET): Final processed table columns mismatch. "
                f"Expected {len(final_ordered_columns)} columns: {final_ordered_columns}, "
                f"Got {len(df_processed.columns)} columns: {df_processed.columns.tolist()}."
            )
        return df_processed[final_ordered_columns]

    def transform_inter_region(self, raw_df_orig):
        # Do NOT drop the first column yet
        df = raw_df_orig.copy()  # Keep all columns
        processed_rows_data = []
        for i in range(df.shape[0]):
            try:
                row_series = df.iloc[i]
                row_values = row_series.tolist()
                non_na_values = [v for v in row_values if pd.notna(v) and str(v).strip() != ""]
                current_row_values = [pd.NA] * 10  # 1 extra for serial number
                if len(non_na_values) == 4:
                    import_value = str(non_na_values[0]).strip()
                    for j in range(3):
                        current_row_values[6 + j] = non_na_values[1 + j]  # shift by 1 for serial number
                    current_row_values[9] = import_value  # Import column at the end
                    current_row_values[2] = 'Total'
                else:
                    for idx in range(min(9, len(row_values))):
                        current_row_values[idx] = row_values[idx]
                    current_row_values[9] = pd.NA
                processed_rows_data.append(current_row_values)
            except Exception as e:
                self.logger.error(f"Error processing row {i}: {str(e)}")
                continue
        # Now drop the serial number column (index 0) before assigning column names
        df_processed = pd.DataFrame(processed_rows_data)
        df_processed = df_processed.iloc[:, 1:]  # Drop serial number
        target_csv_cols = ['Voltage Level', 'Line Details', 'No. of Circuit', 
                          'Max Import (MW)', 'Max Export (MW)', 'Import (MU)', 
                          'Export (MU)', 'NET Import (MU)', 'Import']
        df_processed.columns = target_csv_cols
        # Backfill the Import column with the last known import region header
        df_processed['Import'] = df_processed['Import'].bfill()
        df_processed = df_processed.dropna(thresh=max(1, len(target_csv_cols) - 5))
        numeric_cols = ['No. of Circuit', 'Max Import (MW)', 'Max Export (MW)', 
                       'Import (MU)', 'Export (MU)', 'NET Import (MU)']
        for col in numeric_cols:
            if col in df_processed.columns:
                df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce')
        df_processed = self._add_common_cols(df_processed, 'Inter-Region')
        final_ordered_columns = ['Date', 'Table Name', 'Import'] + \
                              [col for col in target_csv_cols if col != 'Import']
        # Correction: Ensure final table has columns exactly as in final_ordered_columns
        if not all(col in df_processed.columns for col in final_ordered_columns) or \
           len(df_processed.columns) != len(final_ordered_columns):
            missing_cols = [col for col in final_ordered_columns if col not in df_processed.columns]
            extra_cols = [col for col in df_processed.columns if col not in final_ordered_columns]
            raise ValueError(
                f"Error (Inter-Region): Final column structure mismatch. "
                f"Expected: {final_ordered_columns}. Got: {df_processed.columns.tolist()}. "
                f"Missing: {missing_cols}, Extra: {extra_cols}."
            )
        return df_processed[final_ordered_columns]

    def transform_international_exchange(self, raw_df):
        df = raw_df.copy()
        if df.empty:
            # raise ValueError("Error (International Exchange): Raw table is empty.")
            print("Warning (International Exchange): Raw table is empty. Returning empty DataFrame.")
            return self._add_common_cols(pd.DataFrame(), 'International')

        # Assumes header is in the first row of tabula's output
        df_header = self._clean_column_names(df.iloc[0])
        df_data = df.iloc[1:].copy() # Make a copy for modification
        df_data.columns = df_header # Assign cleaned header to the rest of the data
        df = df_data.reset_index(drop=True)

        target_cols_final = ['State', 'Region', 'Line Name', 'Max (MW)', 
                             'Min (MW)', 'Avg (MW)', 'Energy Exchange (MU)']

        # Correction: Direct column assignment if count matches, else error.
        if df.shape[1] != len(target_cols_final):
            raise ValueError(
                f"Error (International Exchange): Column count mismatch after header assignment. "
                f"Expected {len(target_cols_final)} based on target, got {df.shape[1]} from data ({df.columns.tolist()})."
            )
        df.columns = target_cols_final # Assign target names, assuming order is correct

        if 'State' in df.columns: # Now 'State' is a target column name
            idx_to_shift = df.index[df['State'].astype(str).str.contains('ER', na=False)]
            for i in idx_to_shift:
                df.iloc[i,:] = df.iloc[i,:].astype(str).shift(1, fill_value=pd.NA)
            df['State'] = df['State'].replace('', pd.NA).ffill()
            if 'Region' in df.columns:
                df['Region'] = df['Region'].replace('', pd.NA).ffill()
        
        if 'State' in df.columns:
             df = df[~df['State'].astype(str).str.contains('Total', na=False, case=False)].copy()
        
        numeric_cols = ['Max (MW)', 'Min (MW)', 'Avg (MW)', 'Energy Exchange (MU)']
        for col in numeric_cols:
            if col in df.columns: # Should exist due to direct assignment
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df = self._add_common_cols(df, 'International')
        final_ordered_columns = ['Date', 'Table Name'] + target_cols_final
        # Final check already implicitly handled by df.columns = target_cols_final if counts match
        return df[final_ordered_columns]

    def transform_exchange(self, raw_df_export, raw_df_import, raw_df_net):
        all_exchange_dfs = []

        def process_single_exchange_table(df_raw_single, exchange_type):
            df_single_processed = df_raw_single.copy()
            if df_single_processed.shape[0] <= 3: # Need more than 3 rows to skip 3
                 print(f"Warning (Exchange - {exchange_type}): Not enough rows (<=3) to process. Skipping.")
                 return pd.DataFrame()
            
            df_single_processed = df_single_processed.iloc[3:, :].reset_index(drop=True)
            if df_single_processed.empty: # check if empty after slicing
                print(f"Warning (Exchange - {exchange_type}): Became empty after skipping first 3 rows. Skipping.")
                return pd.DataFrame()

            raw_cols_exchange = ['Country', 'PPA', 'Bilateral', 'DAM IEX', 'DAM PXIL', 
                                 'DAM HPX', 'RTM IEX', 'RTM PXIL', 'RTM HPX', 'Total']
            
            if df_single_processed.shape[1] != len(raw_cols_exchange):
                raise ValueError(
                    f"Error (Exchange - {exchange_type}): Column count mismatch. "
                    f"Expected {len(raw_cols_exchange)}, got {df_single_processed.shape[1]}."
                )
            df_single_processed.columns = raw_cols_exchange

            # Correction: Do NOT filter out "Total" in 'Country' column.
            # df_single_processed = df_single_processed[~df_single_processed['Country'].astype(str).str.contains('Total', na=False, case=False)].copy()

            df_single_processed['Type'] = exchange_type
             # Correction: Use 'Exchange' not 'Excchange'
            df_single_processed = self._add_common_cols(df_single_processed, 'Exchange')
            
            expected_cols_sub_table = ['Date', 'Table Name', 'Type'] + raw_cols_exchange
            # Ensure all columns are present (should be, due to assignment and addition)
            for col in expected_cols_sub_table:
                if col not in df_single_processed.columns: # Should not happen
                    df_single_processed[col] = pd.NA 
            return df_single_processed[expected_cols_sub_table]

        # (Processing logic for each exchange type, appending to all_exchange_dfs)
        # ... (similar to previous, calling process_single_exchange_table)
        df_export = process_single_exchange_table(raw_df_export, 'Export')
        if not df_export.empty: all_exchange_dfs.append(df_export)
        df_import = process_single_exchange_table(raw_df_import, 'Import')
        if not df_import.empty: all_exchange_dfs.append(df_import)
        df_net = process_single_exchange_table(raw_df_net, 'NET')
        if not df_net.empty: all_exchange_dfs.append(df_net)

        if not all_exchange_dfs:
            # raise ValueError("Error (Exchange): All sub-tables (Export, Import, NET) resulted in empty DataFrames.")
            print("Warning (Exchange): All sub-tables (Export, Import, NET) were empty or malformed. Returning empty DataFrame.")
            return pd.DataFrame()

        combined_df = pd.concat(all_exchange_dfs, ignore_index=True)
        numeric_cols_exchange = ['PPA', 'Bilateral', 'DAM IEX', 'DAM PXIL', 'DAM HPX', 
                                 'RTM IEX', 'RTM PXIL', 'RTM HPX', 'Total']
        for col in numeric_cols_exchange:
            if col in combined_df.columns:
                combined_df[col] = pd.to_numeric(combined_df[col], errors='coerce')
        return combined_df

    def transform_block_wise(self, raw_df):
        df = raw_df.copy()
        
        # Debug: Print original data structure
        self.logger.debug(f"Original blockwise table shape: {df.shape}")
        self.logger.debug(f"Original columns: {list(df.columns)}")
        
        # Directly assign standard column names based on expected structure
        standard_columns = [
            'TIME',
            'FREQUENCY (Hz)',
            'DEMAND MET (MW)',
            'NUCLEAR (MW)',
            'WIND (MW)',
            'SOLAR (MW)',
            'HYDRO (MW)',
            'GAS (MW)',
            'THERMAL (MW)',
            'OTHERS (MW)',
            'NET DEMAND MET (MW)',
            'TOTAL GENERATION (MW)',
            'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export'
        ]
        
        # Ensure we have the right number of columns
        if len(standard_columns) == len(df.columns):
            # Assign standard column names
            df.columns = standard_columns
        else:
            raise ValueError(f"Error (Block-wise): Column count mismatch. Expected {len(standard_columns)}, got {len(df.columns)}.")
        
        # Remove any header rows that contain non-time data
        # Look for the first row that contains a time pattern (HH:MM)
        data_start_row = 0
        for i in range(min(10, len(df))):
            time_col = df.iloc[i, 0] if len(df.columns) > 0 else None
            if time_col is not None:
                time_str = str(time_col).strip()
                # Check if this looks like a time value (HH:MM format)
                if re.match(r'\d{1,2}:\d{2}', time_str):
                    data_start_row = i
                    break
        
        # Extract data starting from the identified row
        df = df.iloc[data_start_row:].reset_index(drop=True)
        
        # Debug: Print mapped columns
        self.logger.debug(f"Standard columns assigned: {list(df.columns)}")
        self.logger.debug(f"Data shape after header removal: {df.shape}")

        # Define all possible numeric columns
        all_numeric_cols = [
            'FREQUENCY (Hz)', 'DEMAND MET (MW)', 'NUCLEAR (MW)', 'WIND (MW)', 'SOLAR (MW)',
            'HYDRO (MW)', 'GAS (MW)', 'THERMAL (MW)', 'OTHERS (MW)', 'NET DEMAND MET (MW)',
            'TOTAL GENERATION (MW)', 'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export'
        ]
        
        # Process only the numeric columns that exist in the dataframe
        for col in all_numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '', regex=False).str.strip()
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # Format TIME column to HH:MM format (remove seconds if present)
        if 'TIME' in df.columns:
            df['TIME'] = df['TIME'].astype(str).apply(lambda x: x[:5] if ':' in x else x)

        # Add common columns
        df = self._add_common_cols(df, 'Block-wise')
        
        # Create final column list with only existing columns
        final_cols = ['Date', 'Table Name']
        if 'TIME' in df.columns:
            final_cols.append('TIME')
        final_cols.extend([col for col in all_numeric_cols if col in df.columns])
        
        # Debug: Print final columns
        self.logger.debug(f"Final columns: {final_cols}")
        self.logger.debug(f"Final dataframe shape: {df[final_cols].shape}")
        
        return df[final_cols]

    def validate_and_clean_table(self, df: pd.DataFrame, table_type: str) -> pd.DataFrame:
        """
        Validate and clean table data according to specific requirements for each table type.
        
        Args:
            df: DataFrame to validate
            table_type: Type of table ('regional_summary', 'states', 'international_net', etc.)
            
        Returns:
            Validated and cleaned DataFrame, or None if validation fails
        """
        if df is None or df.empty:
            self.logger.warning(f"Validation failed for {table_type}: DataFrame is None or empty")
            return None
            
        try:
            if table_type == 'regional_summary':
                return self._validate_regional_summary(df)
            elif table_type == 'states':
                return self._validate_states_table(df)
            elif table_type == 'international_net':
                return self._validate_international_net(df)
            elif table_type == 'inter_region':
                return self._validate_inter_region_table(df)
            elif table_type == 'international':
                return self._validate_international_table(df)
            elif table_type == 'exchange':
                return self._validate_exchange_table(df)
            elif table_type == 'block_wise':
                return self._validate_block_wise_table(df)
            else:
                self.logger.warning(f"Unknown table type for validation: {table_type}")
                return df
                
        except Exception as e:
            self.logger.error(f"Validation error for {table_type}: {e}")
            return None
    
    def _validate_regional_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate Regional Summary table: 67 rows, 5 columns including Date and Table Name"""
        try:
            # Check if Date and Table Name columns exist
            if 'Date' not in df.columns or 'Table Name' not in df.columns:
                self.logger.error("Regional Summary validation failed: Missing Date or Table Name columns")
                return None
            
            # Check row count (should be around 67 rows)
            if len(df) < 60 or len(df) > 80:  # Allow some flexibility
                self.logger.warning(f"Regional Summary row count ({len(df)}) is outside expected range (60-80)")
            
            # Check column count (should be 5 including Date and Table Name)
            if len(df.columns) != 5:
                self.logger.error(f"Regional Summary validation failed: Expected 5 columns, got {len(df.columns)}")
                return None
            
            # Ensure Date and Table Name are in the first two columns
            if df.columns[0] != 'Date' or df.columns[1] != 'Table Name':
                self.logger.warning("Regional Summary: Date and Table Name should be first two columns")
            
            self.logger.info(f"Regional Summary validation passed: {len(df)} rows, {len(df.columns)} columns")
            return df
            
        except Exception as e:
            self.logger.error(f"Regional Summary validation error: {e}")
            return None
    
    def _validate_states_table(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate States table: 11 columns, valid Region and State names, >10 non-null values per row"""
        try:
            # Check column count
            if len(df.columns) != 11:
                self.logger.error(f"States table validation failed: Expected 11 columns, got {len(df.columns)}")
                return None
            
            # Define valid region names
            valid_regions = ['NR', 'WR', 'SR', 'ER', 'NER', 'ALL INDIA']
            
            # Define valid state names (partial list - can be expanded)
            valid_states = [
                'Punjab', 'Haryana', 'Rajasthan', 'Delhi', 'UP', 'Uttarakhand', 'HP', 
                'J&K(UT) & Ladakh(UT)', 'Chandigarh', 'Chhattisgarh', 'Gujarat', 'MP', 
                'Maharashtra', 'Goa', 'Andhra Pradesh', 'Telangana', 'Karnataka', 
                'Kerala', 'Tamil Nadu', 'Puducherry', 'Bihar', 'DVC', 'Jharkhand', 
                'Odisha', 'West Bengal', 'Sikkim', 'Arunachal Pradesh', 'Assam', 
                'Manipur', 'Meghalaya', 'Mizoram', 'Nagaland', 'Tripura'
            ]
            
            # Validate Region column
            if 'Region' in df.columns:
                invalid_regions = df[~df['Region'].isin(valid_regions)]['Region'].unique()
                if len(invalid_regions) > 0:
                    self.logger.warning(f"States table: Invalid regions found: {invalid_regions}")
            
            # Validate States column
            if 'States' in df.columns:
                invalid_states = []
                for state in df['States'].dropna().unique():
                    if not any(valid_state.lower() in str(state).lower() for valid_state in valid_states):
                        invalid_states.append(state)
                if len(invalid_states) > 0:
                    self.logger.warning(f"States table: Invalid states found: {invalid_states}")
            
            # Check non-null values per row
            for idx, row in df.iterrows():
                non_null_count = row.notna().sum()
                if non_null_count < 10:
                    self.logger.warning(f"States table row {idx}: Only {non_null_count} non-null values (expected >10)")
            
            self.logger.info(f"States table validation passed: {len(df)} rows, {len(df.columns)} columns")
            return df
            
        except Exception as e:
            self.logger.error(f"States table validation error: {e}")
            return None
    
    def _validate_international_net(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate International NET table: 1 row, 10 columns, 10 non-null values"""
        try:
            # Check row count
            if len(df) != 1:
                self.logger.error(f"International NET validation failed: Expected 1 row, got {len(df)}")
                return None
            
            # Check column count
            if len(df.columns) != 10:
                self.logger.error(f"International NET validation failed: Expected 10 columns, got {len(df.columns)}")
                return None
            
            # Check non-null values in the single row
            non_null_count = df.iloc[0].notna().sum()
            if non_null_count < 10:
                self.logger.warning(f"International NET: Only {non_null_count} non-null values (expected 10)")
            
            self.logger.info(f"International NET validation passed: {len(df)} rows, {len(df.columns)} columns")
            return df
            
        except Exception as e:
            self.logger.error(f"International NET validation error: {e}")
            return None
    
    def _validate_inter_region_table(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate Inter-Region table: 11 columns, valid Import format, Voltage level, etc."""
        try:
            # Check column count
            if len(df.columns) != 11:
                self.logger.error(f"Inter-Region table validation failed: Expected 11 columns, got {len(df.columns)}")
                return None
            
            # Validate Import column format (should be like 'ER-NR', 'ER-WR', etc.)
            if 'Import' in df.columns:
                import_pattern = r'^[A-Z]{2}-[A-Z]{2}$'
                invalid_imports = []
                for import_val in df['Import'].dropna().unique():
                    if not re.match(import_pattern, str(import_val)):
                        invalid_imports.append(import_val)
                if len(invalid_imports) > 0:
                    self.logger.warning(f"Inter-Region table: Invalid Import format found: {invalid_imports}")
            
            # Validate Voltage Level (should contain 'kV')
            if 'Voltage Level' in df.columns:
                invalid_voltage = []
                for voltage in df['Voltage Level'].dropna().unique():
                    if 'kV' not in str(voltage):
                        invalid_voltage.append(voltage)
                if len(invalid_voltage) > 0:
                    self.logger.warning(f"Inter-Region table: Invalid Voltage Level format found: {invalid_voltage}")
            
            # Validate Line Details (should contain "From - To" format)
            if 'Line Details' in df.columns:
                invalid_lines = []
                for line in df['Line Details'].dropna().unique():
                    if '-' not in str(line) or len(str(line).split('-')) < 2:
                        invalid_lines.append(line)
                if len(invalid_lines) > 0:
                    self.logger.warning(f"Inter-Region table: Invalid Line Details format found: {invalid_lines}")
            
            # Validate No. of Circuit (should be numeric)
            if 'No. of Circuit' in df.columns:
                invalid_circuits = []
                for circuit in df['No. of Circuit'].dropna().unique():
                    try:
                        float(circuit)
                    except (ValueError, TypeError):
                        invalid_circuits.append(circuit)
                if len(invalid_circuits) > 0:
                    self.logger.warning(f"Inter-Region table: Invalid No. of Circuit values found: {invalid_circuits}")
            
            # Check non-null values per row
            for idx, row in df.iterrows():
                non_null_count = row.notna().sum()
                if non_null_count < 5:
                    self.logger.warning(f"Inter-Region table row {idx}: Only {non_null_count} non-null values (expected >5)")
            
            self.logger.info(f"Inter-Region table validation passed: {len(df)} rows, {len(df.columns)} columns")
            return df
            
        except Exception as e:
            self.logger.error(f"Inter-Region table validation error: {e}")
            return None
    
    def _validate_international_table(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate International table: 9 columns, valid Country and Region names, 9 non-null values per row"""
        try:
            # Check column count
            if len(df.columns) != 9:
                self.logger.error(f"International table validation failed: Expected 9 columns, got {len(df.columns)}")
                return None
            
            # Define valid country names
            valid_countries = ['BHUTAN', 'NEPAL', 'BANGLADESH', 'MYANMAR', 'CHINA', 'PAKISTAN']
            
            # Define valid region names
            valid_regions = ['NR', 'WR', 'SR', 'ER', 'NER']
            
            # Validate State column (should contain country names)
            if 'State' in df.columns:
                invalid_countries = []
                for state in df['State'].dropna().unique():
                    if not any(country.lower() in str(state).lower() for country in valid_countries):
                        invalid_countries.append(state)
                if len(invalid_countries) > 0:
                    self.logger.warning(f"International table: Invalid country names found: {invalid_countries}")
            
            # Validate Region column
            if 'Region' in df.columns:
                invalid_regions = df[~df['Region'].isin(valid_regions)]['Region'].unique()
                if len(invalid_regions) > 0:
                    self.logger.warning(f"International table: Invalid regions found: {invalid_regions}")
            
            # Check non-null values per row
            for idx, row in df.iterrows():
                non_null_count = row.notna().sum()
                if non_null_count < 9:
                    self.logger.warning(f"International table row {idx}: Only {non_null_count} non-null values (expected 9)")
            
            self.logger.info(f"International table validation passed: {len(df)} rows, {len(df.columns)} columns")
            return df
            
        except Exception as e:
            self.logger.error(f"International table validation error: {e}")
            return None
    
    def _validate_exchange_table(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate Exchange table: 15 rows, 13 columns, valid Country names, 13 non-null values per row"""
        try:
            # Check row count
            if len(df) != 15:
                self.logger.warning(f"Exchange table: Expected 15 rows, got {len(df)}")
            
            # Check column count
            if len(df.columns) != 13:
                self.logger.error(f"Exchange table validation failed: Expected 13 columns, got {len(df.columns)}")
                return None
            
            # Define valid country names
            valid_countries = ['Bhutan', 'Nepal', 'Bangladesh', 'Myanmar', 'China', 'Pakistan']
            
            # Validate Country column
            if 'Country' in df.columns:
                invalid_countries = []
                for country in df['Country'].dropna().unique():
                    if not any(valid_country.lower() in str(country).lower() for valid_country in valid_countries):
                        invalid_countries.append(country)
                if len(invalid_countries) > 0:
                    self.logger.warning(f"Exchange table: Invalid country names found: {invalid_countries}")
            
            # Check non-null values per row
            for idx, row in df.iterrows():
                non_null_count = row.notna().sum()
                if non_null_count < 13:
                    self.logger.warning(f"Exchange table row {idx}: Only {non_null_count} non-null values (expected 13)")
            
            self.logger.info(f"Exchange table validation passed: {len(df)} rows, {len(df.columns)} columns")
            return df
            
        except Exception as e:
            self.logger.error(f"Exchange table validation error: {e}")
            return None
    
    def _validate_block_wise_table(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate Block-wise table: 96 rows, 15 columns (including Date and Table Name), valid TIME values"""
        try:
            # Check row count
            if len(df) != 96:
                self.logger.error(f"Block-wise table validation failed: Expected 96 rows, got {len(df)}")
                return None
            
            # Check column count (should be 15: Date, Table Name, TIME, and 12 numeric columns)
            if len(df.columns) != 15:
                self.logger.error(f"Block-wise table validation failed: Expected 15 columns (including Date and Table Name), got {len(df.columns)}")
                return None
            
            # Verify Date and Table Name columns are present
            if 'Date' not in df.columns or 'Table Name' not in df.columns:
                self.logger.error(f"Block-wise table validation failed: Missing Date or Table Name columns")
                return None
            
            # Generate expected time blocks (00:00 to 23:45 in 15-minute intervals)
            expected_times = []
            for hour in range(24):
                for minute in [0, 15, 30, 45]:
                    expected_times.append(f"{hour:02d}:{minute:02d}")
            
            # Validate TIME column
            if 'TIME' in df.columns:
                invalid_times = []
                corrected_times = []
                
                for idx, time_val in enumerate(df['TIME']):
                    time_str = str(time_val).strip()
                    if time_str not in expected_times:
                        invalid_times.append(time_str)
                        # Try to correct the time value
                        try:
                            # Parse time and round to nearest 15-minute interval
                            if ':' in time_str:
                                hour, minute = map(int, time_str.split(':'))
                                minute = round(minute / 15) * 15
                                if minute == 60:
                                    minute = 0
                                    hour = (hour + 1) % 24
                                corrected_time = f"{hour:02d}:{minute:02d}"
                                if corrected_time in expected_times:
                                    corrected_times.append((idx, corrected_time))
                        except:
                            pass
                
                if len(invalid_times) > 0:
                    self.logger.warning(f"Block-wise table: Invalid TIME values found: {invalid_times}")
                    
                    # Apply corrections
                    for idx, corrected_time in corrected_times:
                        df.at[idx, 'TIME'] = corrected_time
                        self.logger.info(f"Corrected TIME at row {idx} to {corrected_time}")
                
                # Verify we have all 96 unique time blocks
                unique_times = df['TIME'].unique()
                if len(unique_times) != 96:
                    self.logger.error(f"Block-wise table: Expected 96 unique TIME values, got {len(unique_times)}")
                    return None
            
            self.logger.info(f"Block-wise table validation passed: {len(df)} rows, {len(df.columns)} columns")
            return df
            
        except Exception as e:
            self.logger.error(f"Block-wise table validation error: {e}")
            return None

# ============================================================================
# PDF EXTRACTION MODULE
# ============================================================================

class PDFExtractor:
    """
    Responsible for extracting raw tables from PDF files.
    Handles PDF reading, table extraction, and basic cleaning.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def extract_tables_from_pdf(self, pdf_path: str) -> Tuple[Dict[str, pd.DataFrame], str]:
        """
        Extract tables from PDF file.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Tuple of (tables_dict, report_date)
        """
        try:
            # Get report date
            report_date = self._get_report_date_from_pdf(pdf_path)
            
            # Extract raw tables
            raw_tables = self._extract_raw_tables(pdf_path)
            
            # Clean and filter tables
            cleaned_tables = self._clean_and_filter_tables(raw_tables, pdf_path)
            
            return cleaned_tables, report_date
            
        except Exception as e:
            self.logger.error(f"Error extracting tables from {pdf_path}: {e}")
            return {}, "Unknown Date"
    
    def _get_report_date_from_pdf(self, pdf_path: str) -> str:
        """Extract report date from PDF content or filename"""
        try:
            reader = PdfReader(pdf_path)
            first_page_text = reader.pages[0].extract_text()
            
            # Try to find date in first page text
            match = re.search(r"Sub: Daily PSP Report for the date\s*(\d{1,2})\s*\.(\d{2})\.(\d{4})", first_page_text)
            if match:
                day = int(match.group(1))
                month = int(match.group(2))
                year = int(match.group(3))
                return f"{month}/{day}/{year}"
            
            # Fallback: Extract from filename
            filename = os.path.basename(pdf_path)
            filename_match = re.search(r"(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", filename)
            if filename_match:
                day = int(filename_match.group(1))
                month = int(filename_match.group(2))
                year = 2000 + int(filename_match.group(3))
                return f"{month}/{day}/{year}"
            
            self.logger.warning("Could not find report date in PDF or filename.")
            return "Unknown Date"
            
        except Exception as e:
            self.logger.error(f"Error extracting report date: {e}")
            return "Unknown Date"
    
    def _extract_raw_tables(self, pdf_path: str) -> Dict[str, pd.DataFrame]:
        """Extract raw tables from PDF using tabula"""
        raw_tables = {}
        
        try:
            reader = PdfReader(pdf_path)
            num_pages = len(reader.pages)
            
            for page_num in range(1, num_pages + 1):
                max_retries = 3
                for retry in range(max_retries):
                    try:
                        # Use different settings for different pages
                        if page_num == 5:  # Blockwise table page
                            tables_on_page = tabula.read_pdf(
                                pdf_path,
                                pages=page_num,
                                multiple_tables=True,
                                guess=False,
                                lattice=True,
                                stream=False,
                                silent=True,
                                java_options=["-Dfile.encoding=UTF8", "-Xmx2g"]
                            )
                        else:
                            tables_on_page = tabula.read_pdf(
                                pdf_path,
                                pages=page_num,
                                multiple_tables=True,
                                guess=True,
                                lattice=True,
                                stream=True,
                                silent=True
                            )
                        
                        # Process extracted tables
                        for table_idx, table_df in enumerate(tables_on_page):
                            if isinstance(table_df, pd.DataFrame) and not table_df.empty:
                                key = f"page_{page_num}_table_{table_idx}"
                                raw_tables[key] = table_df
                        
                        break  # Success, exit retry loop
                        
                    except Exception as e:
                        self.logger.error(f"Error processing page {page_num} (attempt {retry + 1}/{max_retries}): {e}")
                        if retry < max_retries - 1:
                            import time
                            time.sleep(1)
                        else:
                            self.logger.error(f"Failed to extract tables from page {page_num} after {max_retries} attempts")
            
            return raw_tables
            
        except Exception as e:
            self.logger.error(f"Error reading PDF: {e}")
            return {}
    
    def _clean_and_filter_tables(self, raw_tables: Dict[str, pd.DataFrame], pdf_path: str) -> Dict[str, pd.DataFrame]:
        """Clean and filter tables, removing garbage and merging split tables"""
        cleaned_tables = {}
        
        # Group tables by page
        tables_by_page = {}
        for key, df in raw_tables.items():
            page_num = int(key.split('_')[1])
            if page_num not in tables_by_page:
                tables_by_page[page_num] = []
            tables_by_page[page_num].append((key, df))
        
        # Process each page
        for page_num, page_tables in tables_by_page.items():
            page_cleaned_tables = []
            
            for table_idx, (key, df) in enumerate(page_tables):
                # Check if it's a garbage table
                is_garbage, reason = self._is_garbage_table(df, page_num, table_idx)
                if is_garbage:
                    self.logger.info(f"Skipping garbage table {key}: {reason}")
                    continue
                
                # Check if it's a blockwise table continuation
                if self._is_blockwise_continuation(df):
                    # Try to merge with previous table
                    if page_cleaned_tables and self._is_blockwise_table(page_cleaned_tables[-1][1]):
                        merged_df = pd.concat([page_cleaned_tables[-1][1], df], ignore_index=True)
                        page_cleaned_tables[-1] = (page_cleaned_tables[-1][0], merged_df)
                        self.logger.info(f"Merged blockwise continuation {key} with previous table")
                        continue
                
                # Check if it's a blockwise table
                if self._is_blockwise_table(df):
                    # Handle special case for December 1, 2024 PDF
                    if self._is_december_1_2024_exception(pdf_path, page_num):
                        split_tables = self._split_december_1_2024_table(df)
                        for split_idx, split_df in enumerate(split_tables):
                            split_key = f"{key}_split_{split_idx}"
                            page_cleaned_tables.append((split_key, split_df))
                        continue
                
                # Regular table
                page_cleaned_tables.append((key, df))
            
            # Add cleaned tables to result
            for key, df in page_cleaned_tables:
                cleaned_tables[key] = df
        
        return cleaned_tables
    
    def _is_garbage_table(self, df: pd.DataFrame, page_num: int, table_idx: int) -> Tuple[bool, str]:
        """Check if table is garbage (empty, Hindi text, etc.)"""
        if df.empty:
            return True, "Empty table"
        
        # Check for very small tables (likely garbage) - be less aggressive
        if df.shape[0] < 1 or df.shape[1] < 1:
            return True, "Too small table"
        
        # Check for Hindi text (common in garbage tables) - be more lenient
        first_row_text = " ".join(df.iloc[0].astype(str).fillna('').tolist())
        hindi_chars = re.findall(r'[\u0900-\u097F]', first_row_text)
        if len(hindi_chars) > 10:  # More than 10 Hindi characters (increased threshold)
            return True, "Hindi text table"
        
        # Check for tables that are mostly empty
        non_empty_cells = df.notna().sum().sum()
        total_cells = df.shape[0] * df.shape[1]
        if total_cells > 0 and non_empty_cells / total_cells < 0.1:  # Less than 10% non-empty
            return True, "Mostly empty table"
        
        return False, ""
    
    def _is_blockwise_table(self, df: pd.DataFrame) -> bool:
        """Check if table is a blockwise table"""
        if df.empty:
            return False
        
        # Check for blockwise table indicators
        first_row_text = " ".join(df.iloc[0].astype(str).fillna('').tolist()).lower()
        if "15 min" in first_row_text and "frequency" in first_row_text:
            return True
        
        if "time" in first_row_text and "demand met" in first_row_text:
            return True
        
        return False
    
    def _is_blockwise_continuation(self, df: pd.DataFrame) -> bool:
        """Check if table is a continuation of blockwise table"""
        if df.empty:
            return False
        
        # Check for continuation indicators (time values)
        first_col = df.iloc[:, 0].astype(str).fillna('')
        time_pattern = re.compile(r'\d{2}:\d{2}')
        time_matches = sum(1 for val in first_col if time_pattern.search(str(val)))
        
        return time_matches > 0
    
    def _is_december_1_2024_exception(self, pdf_path: str, page_num: int) -> bool:
        """Check if this is the December 1, 2024 PDF exception"""
        filename = os.path.basename(pdf_path)
        return "01.12.24_NLDC_PSP" in filename and page_num == 3
    
    def _split_december_1_2024_table(self, df: pd.DataFrame) -> List[pd.DataFrame]:
        """Split the merged table on page 3 of December 1, 2024 PDF"""
        split_tables = []
        
        # Find the row containing "INTERNATIONAL EXCHANGES"
        split_row = -1
        for idx, row in df.iterrows():
            row_text = " ".join(row.astype(str).fillna('').tolist())
            if "INTERNATIONAL EXCHANGES" in row_text:
                split_row = idx
                break
        
        if split_row > 0:
            # Split the table
            table1 = df.iloc[:split_row].copy()
            table2 = df.iloc[split_row:].copy()
            split_tables = [table1, table2]
        else:
            # If split point not found, return original table
            split_tables = [df]
        
        return split_tables

# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

class PSPReportParser:
    """
    Main orchestrator that coordinates table identification and processing.
    Provides a unified interface for parsing PSP reports.
    """
    
    def __init__(self):
        self.extractor = PDFExtractor()
        self.identifier = TableIdentifier()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def parse_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """
        Parse a PSP report PDF and return processed results using PSPTransformer logic.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Dictionary containing:
            - 'success': Boolean indicating overall success
            - 'report_date': Extracted report date
            - 'raw_tables': Dictionary of raw extracted tables
            - 'classifications': Dictionary of table classifications
            - 'processed_results': List of processing results
            - 'final_tables': List of successfully processed DataFrames (with None for missing tables)
            - 'errors': List of error messages
        """
        try:
            # Step 1: Extract tables from PDF
            self.logger.info(f"Extracting tables from {pdf_path}")
            raw_tables, report_date = self.extractor.extract_tables_from_pdf(pdf_path)
            
            if not raw_tables:
                return {
                    'success': False,
                    'report_date': report_date,
                    'raw_tables': {},
                    'classifications': {},
                    'processed_results': [],
                    'final_tables': [],
                    'errors': ['No tables extracted from PDF']
                }
            
            # Step 2: Identify and classify tables
            self.logger.info("Classifying extracted tables")
            classifications = {}
            raw_tables_by_category = {}
            
            for table_key, table_df in raw_tables.items():
                classification = self.identifier.classify_table(table_df, table_key)
                if classification.confidence > 0.15:  # Lowered threshold to capture more tables
                    classifications[table_key] = classification
                    
                    # Store raw table by category for processing
                    category = classification.category
                    if category not in raw_tables_by_category:
                        raw_tables_by_category[category] = []
                    raw_tables_by_category[category].append({
                        'key': table_key,
                        'data': table_df,
                        'confidence': classification.confidence,
                        'classification': classification
                    })
            
            # Step 3: Process tables using PSPTransformer logic
            self.logger.info("Processing classified tables using PSPTransformer")
            transformer = PSPTransformer(report_date)
            final_dataframes = [None] * 7  # Initialize with None for all 7 expected tables
            errors = []

            # Process regional summary with all available tables (Index 0)
            if 'regional_summary' in raw_tables_by_category:
                self.logger.info("Processing regional summary tables...")
                
                # Get the main regional summary table
                main_regional_table = max(raw_tables_by_category['regional_summary'], key=lambda x: x['confidence'])
                
                # Collect all supporting tables
                supporting_tables = {}
                
                # Map table categories to the expected table names from stable version
                table_mapping = {
                    'frequency_profile': 'B. Frequency Profile (%)',
                    'import_export_regions': 'E. Import/Export by Regions (in MU) - Import(+ve)/Export(-ve); OD(+)/UD(-)',
                    'outage_data': 'F. Generation Outage(MW)',
                    'generation_breakdown': 'G. Sourcewise generation (Gross) (MU)',
                    're_share': 'G. Share of RE and Non-fossil',
                    'demand_diversity_factor_ddf': 'H. All India Demand Diversity Factor',
                    'solar_nonsolar_hour': 'I. All India Peak Demand and shortage at Solar and Non-Solar Hour'
                }
                
                # Collect all available supporting tables
                for category, table_name in table_mapping.items():
                    if category in raw_tables_by_category:
                        supporting_tables[table_name] = max(raw_tables_by_category[category], key=lambda x: x['confidence'])['data']
                
                try:
                    # Use the comprehensive regional summary transformation logic
                    df_regional = transformer.transform_comprehensive_regional_summary(
                        main_regional_table['data'],  # A. Power Supply Position
                        supporting_tables.get('B. Frequency Profile (%)'),
                        supporting_tables.get('E. Import/Export by Regions (in MU) - Import(+ve)/Export(-ve); OD(+)/UD(-)'),
                        supporting_tables.get('F. Generation Outage(MW)'),
                        supporting_tables.get('G. Sourcewise generation (Gross) (MU)'),
                        supporting_tables.get('G. Share of RE and Non-fossil'),
                        supporting_tables.get('H. All India Demand Diversity Factor'),
                        supporting_tables.get('I. All India Peak Demand and shortage at Solar and Non-Solar Hour'),
                        report_date
                    )
                    
                    if df_regional is not None and not df_regional.empty:
                        # Validate regional summary table
                        validated_df = transformer.validate_and_clean_table(df_regional, 'regional_summary')
                        final_dataframes[0] = validated_df  # Index 0: Regional Summary
                        if validated_df is not None:
                            self.logger.info("Regional summary processed and validated successfully with comprehensive data")
                        else:
                            self.logger.warning("Regional summary validation failed")
                    else:
                        self.logger.warning("Regional summary processing resulted in empty dataframe")
                        
                except Exception as e:
                    self.logger.error(f"Error processing regional summary: {e}")
                    errors.append(f"Regional Summary: {e}")
            else:
                self.logger.warning("Regional summary tables not available - setting to None")
                final_dataframes[0] = None  # Index 0: None for missing Regional Summary

            # Process individual tables by category in specific order
            self.logger.info("Processing individual tables by category...")
            
            # 1. States data (Index 1)
            if 'state_energy' in raw_tables_by_category:
                for table_info in raw_tables_by_category['state_energy']:
                    try:
                        df = transformer.transform_states(table_info['data'])
                        # Validate states table
                        validated_df = transformer.validate_and_clean_table(df, 'states')
                        final_dataframes[1] = validated_df  # Index 1: States
                        if validated_df is not None:
                            self.logger.info(f"States table processed and validated from {table_info['key']}")
                        else:
                            self.logger.warning(f"States table validation failed from {table_info['key']}")
                        break  # Use the first successful states table
                    except Exception as e:
                        self.logger.error(f"Error processing states table from {table_info['key']}: {e}")
                        errors.append(f"States Table: {e}")
            
            # 2. Transnational Exchange (Index 2)
            if 'transnational_exchange' in raw_tables_by_category:
                for table_info in raw_tables_by_category['transnational_exchange']:
                    try:
                        df = transformer.transform_international_net(table_info['data'])
                        # Validate international net table
                        validated_df = transformer.validate_and_clean_table(df, 'international_net')
                        final_dataframes[2] = validated_df  # Index 2: Transnational Exchange
                        if validated_df is not None:
                            self.logger.info(f"Transnational exchange processed and validated from {table_info['key']}")
                        else:
                            self.logger.warning(f"Transnational exchange validation failed from {table_info['key']}")
                        break  # Use the first successful transnational table
                    except Exception as e:
                        self.logger.error(f"Error processing transnational exchange from {table_info['key']}: {e}")
                        errors.append(f"Transnational Exchange: {e}")
            
            # 3. Inter-Region Transmission Flow (Index 3)
            if 'transmission_flow' in raw_tables_by_category:
                for table_info in raw_tables_by_category['transmission_flow']:
                    try:
                        df = transformer.transform_inter_region(table_info['data'])
                        # Validate inter-region table
                        validated_df = transformer.validate_and_clean_table(df, 'inter_region')
                        final_dataframes[3] = validated_df  # Index 3: Inter-Region Transmission Flow
                        if validated_df is not None:
                            self.logger.info(f"Inter-region transmission flow processed and validated from {table_info['key']}")
                        else:
                            self.logger.warning(f"Inter-region transmission flow validation failed from {table_info['key']}")
                        break  # Use the first successful transmission flow table
                    except Exception as e:
                        self.logger.error(f"Error processing transmission flow from {table_info['key']}: {e}")
                        errors.append(f"Transmission Flow: {e}")
            
            # 4. International Transmission Flow (Index 4)
            if 'international_exchange' in raw_tables_by_category:
                for table_info in raw_tables_by_category['international_exchange']:
                    try:
                        df = transformer.transform_international_exchange(table_info['data'])
                        # Validate international table
                        validated_df = transformer.validate_and_clean_table(df, 'international')
                        final_dataframes[4] = validated_df  # Index 4: International Transmission Flow
                        if validated_df is not None:
                            self.logger.info(f"International transmission flow processed and validated from {table_info['key']}")
                        else:
                            self.logger.warning(f"International transmission flow validation failed from {table_info['key']}")
                        break  # Use the first successful international exchange table
                    except Exception as e:
                        self.logger.error(f"Error processing international exchange from {table_info['key']}: {e}")
                        errors.append(f"International Exchange: {e}")
            
            # 5. Cross Border Exchange (Index 5) - Return None if not available
            cross_border_categories = ['cross_border_schedule_1', 'cross_border_schedule_2', 'cross_border_schedule_3']
            cross_border_tables = []
            
            for category in cross_border_categories:
                if category in raw_tables_by_category:
                    cross_border_tables.extend(raw_tables_by_category[category])
            
            if cross_border_tables:
                # Collect all cross border schedule tables
                export_tables = []
                import_tables = []
                net_tables = []
                
                for table_info in cross_border_tables:
                    # Determine table type based on content
                    table_text = " ".join([str(cell) for cell in table_info['data'].values.flatten() if pd.notna(cell)])
                    if 'export' in table_text.lower():
                        export_tables.append(table_info['data'])
                    elif 'import' in table_text.lower():
                        import_tables.append(table_info['data'])
                    else:
                        net_tables.append(table_info['data'])
                
                # Process exchange tables if we have the required combination
                if export_tables and import_tables and net_tables:
                    try:
                        df = transformer.transform_exchange(export_tables[0], import_tables[0], net_tables[0])
                        # Validate exchange table
                        validated_df = transformer.validate_and_clean_table(df, 'exchange')
                        final_dataframes[5] = validated_df  # Index 5: Cross Border Exchange
                        if validated_df is not None:
                            self.logger.info("Cross border exchange tables processed and validated successfully")
                        else:
                            self.logger.warning("Cross border exchange tables validation failed")
                    except Exception as e:
                        self.logger.error(f"Error processing cross border exchange tables: {e}")
                        errors.append(f"Cross Border Exchange: {e}")
                else:
                    self.logger.info("Cross border exchange tables not available - setting to None")
                    final_dataframes[5] = None  # Index 5: None for missing Cross Border Exchange
            else:
                self.logger.info("Cross border exchange tables not available - setting to None")
                final_dataframes[5] = None  # Index 5: None for missing Cross Border Exchange
            
            # 6. Block-Wise data (Index 6) - Return None if duration expectations not met
            if 'time_block' in raw_tables_by_category:
                blockwise_processed = False
                for table_info in raw_tables_by_category['time_block']:
                    try:
                        # Check if blockwise table meets duration expectations
                        df = table_info['data']
                        table_content = " ".join(df.astype(str).fillna('').values.flatten())
                        
                        # Duration validation: should have around 96 time blocks (24 hours * 4 blocks per hour)
                        # Allow flexibility: minimum 90 rows for a full day of 15-minute data
                        has_time_content = ('TIME' in table_content or 'FREQUENCY' in table_content or 
                                          'THERMAL' in table_content or 'HYDRO' in table_content)
                        has_sufficient_rows = df.shape[0] >= 90  # Should have around 96 time blocks
                        has_sufficient_columns = df.shape[1] >= 3  # Should have at least TIME, FREQUENCY, and one other column
                        
                        if has_time_content and has_sufficient_rows and has_sufficient_columns:
                            df_processed = transformer.transform_block_wise(df)
                            # Validate block-wise table
                            validated_df = transformer.validate_and_clean_table(df_processed, 'block_wise')
                            final_dataframes[6] = validated_df  # Index 6: Block-Wise data
                            if validated_df is not None:
                                self.logger.info(f"Block-wise data processed and validated from {table_info['key']} (rows: {df.shape[0]}, columns: {df.shape[1]})")
                            else:
                                self.logger.warning(f"Block-wise data validation failed from {table_info['key']}")
                            blockwise_processed = True
                            break  # Use the first successful blockwise table
                        else:
                            self.logger.warning(f"Skipping blockwise table from {table_info['key']} - duration expectations not met: "
                                              f"time_content={has_time_content}, rows={df.shape[0]}>=90={has_sufficient_rows}, "
                                              f"columns={df.shape[1]}>=3={has_sufficient_columns}")
                    except Exception as e:
                        self.logger.error(f"Error processing time block from {table_info['key']}: {e}")
                        errors.append(f"Time Block: {e}")
                
                if not blockwise_processed:
                    self.logger.info("No valid blockwise table found - setting to None")
                    final_dataframes[6] = None  # Index 6: None for missing Block-Wise data
            else:
                self.logger.info("Blockwise tables not available - setting to None")
                final_dataframes[6] = None  # Index 6: None for missing Block-Wise data

            # Step 4: Collect results
            processing_results = []
            for i, df in enumerate(final_dataframes):
                if df is not None:
                    processing_results.append(ProcessingResult(
                        table_name=f"Table_{i}",
                        success=True,
                        processed_df=df,
                        error_message=None,
                        source_tables=[f"processed_table_{i}"]
                    ))
                else:
                    processing_results.append(ProcessingResult(
                        table_name=f"Table_{i}",
                        success=False,
                        processed_df=None,
                        error_message="Table not available for this duration",
                        source_tables=[]
                    ))
            
            # Check if we have at least some successful tables
            successful_tables = [df for df in final_dataframes if df is not None]
            
            return {
                'success': len(successful_tables) > 0,
                'report_date': report_date,
                'raw_tables': raw_tables,
                'classifications': classifications,
                'processed_results': processing_results,
                'final_tables': final_dataframes,  # Now includes None values for missing tables
                'errors': errors
            }
            
        except Exception as e:
            self.logger.error(f"Error parsing PDF {pdf_path}: {e}")
            return {
                'success': False,
                'report_date': "Unknown Date",
                'raw_tables': {},
                'classifications': {},
                'processed_results': [],
                'final_tables': [],
                'errors': [str(e)]
            }
    
    def save_results(self, results: Dict[str, Any], output_path: str = None) -> str:
        """
        Save processing results to CSV file.
        
        Args:
            results: Results from parse_pdf method
            output_path: Optional output path, defaults to timestamped filename
            
        Returns:
            Path to saved file
        """
        if not results['success'] or not results['final_tables']:
            self.logger.warning("No tables to save")
            return ""
        
        # Generate output path if not provided
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"processed_psp_report_{timestamp}.csv"
        
        # Combine all tables
        combined_df = pd.concat(results['final_tables'], ignore_index=True)
        
        # Save to CSV
        combined_df.to_csv(output_path, index=False)
        self.logger.info(f"Results saved to {output_path}")
        
        return output_path

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_expected_tables(date: datetime) -> int:
    """Get expected number of tables based on date"""
    if date < datetime(2023, 5, 1):
        return 11  # Before Solar/Non-Solar Hour table
    elif date < datetime(2023, 7, 30):
        return 12  # After Solar/Non-Solar Hour table, before cross-border schedules
    elif date < datetime(2024, 11, 4):
        return 15  # After cross-border schedules, before blockwise (excluding garbage)
    else:
        return 16  # After blockwise table (excluding garbage, with merged blockwise)

def extract_date_from_path(pdf_path: str) -> Optional[datetime]:
    """Extract date from PDF path"""
    filename = Path(pdf_path).name
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", filename)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = 2000 + int(match.group(3))
        return datetime(year, month, day)
    return None

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""
    if len(sys.argv) < 2:
        print("Usage: python modular_psp_parser.py <pdf_path> [output_path]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    # Initialize parser
    parser = PSPReportParser()
    
    # Parse PDF
    print(f"Parsing {pdf_path}...")
    results = parser.parse_pdf(pdf_path)
    
    # Display results
    print(f"\n=== PARSING RESULTS ===")
    print(f"Success: {results['success']}")
    print(f"Report Date: {results['report_date']}")
    print(f"Raw Tables Extracted: {len(results['raw_tables'])}")
    print(f"Tables Classified: {len(results['classifications'])}")
    print(f"Tables Processed Successfully: {len([df for df in results['final_tables'] if df is not None])}")
    
    if results['errors']:
        print(f"\nErrors:")
        for error in results['errors']:
            print(f"  - {error}")
    
    # Save results if successful
    if results['success']:
        saved_path = parser.save_results(results, output_path)
        if saved_path:
            print(f"\nResults saved to: {saved_path}")
    
    return results

if __name__ == "__main__":
    main() 