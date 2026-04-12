#!/usr/bin/env python3
"""
Smart Table Classifier using Fuzzy Matching and LLM
Automatically categorizes tables and identifies column aliases
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Any, Optional
from difflib import SequenceMatcher
from fuzzywuzzy import fuzz
import re
import json
from dataclasses import dataclass

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

class SmartTableClassifier:
    """Smart table classifier using fuzzy matching and LLM"""
    
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
                'keywords': ['diversity', 'ddf', 'demand diversity factor', 'all india demand diversity', 'based on regional max demands', 'based on state max demands'],
                'required_columns': ['diversity', 'ddf', 'factor', 'demands'],
                'description': 'Demand diversity factor data'
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
            },
            'transmission_flow': {
                'Schedule': ['schedule', 'schedule(mu)'],
                'Actual': ['actual', 'actual(mu)'],
                'Import': ['import'],
                'Export': ['export'],
                'OverUnderDrawal': ['od/ud', 'over under drawal']
            },
            'international_exchange': {
                'State': ['state'],
                'Region': ['region'],
                'LineName': ['line name', 'line'],
                'MaxLoading': ['max', 'max loading', 'max (mw)'],
                'MinLoading': ['min', 'min loading', 'min (mw)'],
                'AvgLoading': ['avg', 'avg loading', 'avg (mw)'],
                'EnergyExchanged': ['energy exchange', 'energy exchanged']
            },
            'time_block': {
                'Time': ['time'],
                'Frequency': ['frequency', 'frequency\r(hz)'],
                'DemandMet': ['demand met', 'demand\rmet\r(mw)'],
                'Nuclear': ['nuclear', 'nuclear\r(mw)'],
                'Wind': ['wind', 'wind\r(mw)'],
                'Solar': ['solar', 'solar\r(mw)'],
                'Hydro': ['hydro', 'hydro**\r(mw)'],
                'Gas': ['gas', 'gas\r(mw)'],
                'Thermal': ['thermal', 'thermal\r(mw)'],
                'Others': ['others', 'others*\r(mw)']
            },
            'outage_data': {
                'VoltageLevel': ['voltage level'],
                'LineDetails': ['line details'],
                'NoOfCircuit': ['no. of circuit'],
                'MaxImport': ['max import (mw)'],
                'MaxExport': ['max export (mw)'],
                'Import': ['import (mu)'],
                'Export': ['export (mu)'],
                'Net': ['net (mu)']
            },
            'cross_border_schedule_1': {
                'Country': ['country'],
                'GNA': ['gna', 'gna(isgs/ppa)'],
                'Bilateral': ['bilateral'],
                'Total': ['total'],
                'Collective': ['collective']
            },
            'cross_border_schedule_2': {
                'Country': ['country'],
                'GNA': ['gna', 'gna(isgs/ppa)'],
                'Bilateral': ['bilateral'],
                'Total': ['total'],
                'Collective': ['collective']
            },
            'cross_border_schedule_3': {
                'Country': ['country'],
                'GNA': ['gna', 'gna(isgs/ppa)'],
                'Bilateral': ['bilateral'],
                'Total': ['total'],
                'Collective': ['collective']
            }
        }
    
    def classify_table(self, df: pd.DataFrame, table_name: str = None) -> TableClassification:
        """
        Classify a table using fuzzy matching and content analysis
        """
        if df.empty:
            return TableClassification("unknown", 0.0, "unknown", "Empty table", {})
        
        # Analyze table content
        table_text = self._extract_table_text(df, table_name)
        columns = list(df.columns)
        
        best_match = None
        best_score = 0
        best_category = "unknown"
        
        # Score each table pattern
        for category, pattern in self.table_patterns.items():
            score = self._calculate_table_score(table_text, columns, pattern)
            if score > best_score:
                best_score = score
                best_category = category
                best_match = pattern
        
        # Generate column mappings
        column_mappings = self._generate_column_mappings(df, best_category)
        
        return TableClassification(
            table_name=table_name or f"classified_{best_category}",
            confidence=best_score,
            category=best_category,
            description=best_match['description'] if best_match else "Unknown table type",
            column_mappings=column_mappings
        )
    
    def _extract_table_text(self, df: pd.DataFrame, table_name: str = None) -> str:
        """Extract text content from table for analysis"""
        text_parts = []
        
        # Add table name if available
        if table_name:
            text_parts.append(table_name.lower())
        
        # Add column names
        text_parts.extend([str(col).lower() for col in df.columns])
        
        # Add sample data (first few rows)
        if not df.empty:
            sample_data = df.head(3).astype(str).values.flatten()
            text_parts.extend([str(val).lower() for val in sample_data if pd.notna(val) and str(val).strip()])
        
        return " ".join(text_parts)
    
    def _calculate_table_score(self, table_text: str, columns: List[str], pattern: Dict) -> float:
        """Calculate how well a table matches a pattern"""
        score = 0.0
        
        # Check keyword matches in table text
        keyword_matches = 0
        for keyword in pattern['keywords']:
            if keyword.lower() in table_text:
                keyword_matches += 1
        
        keyword_score = keyword_matches / len(pattern['keywords']) * 50
        
        # Check required column matches
        column_matches = 0
        for required_col in pattern['required_columns']:
            for col in columns:
                if self._fuzzy_match(required_col, str(col), threshold=70):
                    column_matches += 1
                    break
        
        column_score = column_matches / len(pattern['required_columns']) * 50
        
        score = keyword_score + column_score
        return min(score, 100.0)
    
    def _fuzzy_match(self, target: str, source: str, threshold: float = 80) -> bool:
        """Check if two strings match using fuzzy logic"""
        if not target or not source:
            return False
        
        # Normalize strings
        target_norm = self._normalize_text(target)
        source_norm = self._normalize_text(source)
        
        # Calculate similarity scores
        ratio_score = fuzz.ratio(target_norm, source_norm)
        partial_score = fuzz.partial_ratio(target_norm, source_norm)
        token_sort_score = fuzz.token_sort_ratio(target_norm, source_norm)
        token_set_score = fuzz.token_set_ratio(target_norm, source_norm)
        
        # Use the highest score
        best_score = max(ratio_score, partial_score, token_sort_score, token_set_score)
        
        return best_score >= threshold
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for better matching"""
        if not text:
            return ""
        
        # Convert to lowercase
        normalized = text.lower()
        
        # Remove common prefixes
        prefixes = ['a_', 'b_', 'c_', 'd_', 'e_', 'f_', 'g_', 'h_', 'i_']
        for prefix in prefixes:
            normalized = re.sub(f'^{prefix}', '', normalized)
        
        # Remove line breaks and extra whitespace
        normalized = re.sub(r'[\r\n]', ' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        # Remove units in parentheses
        normalized = re.sub(r'\([^)]*\)', '', normalized)
        
        # Remove common unit abbreviations
        normalized = re.sub(r'\b(mw|mu|%|hz|kv)\b', '', normalized)
        
        # Handle special abbreviations and variations
        # OD/UD variations
        normalized = re.sub(r'od\([^)]*\)/ud\([^)]*\)', 'od/ud', normalized)
        normalized = re.sub(r'o/d/u/d', 'od/ud', normalized)
        normalized = re.sub(r'over\s*under\s*drawal', 'overunderdrawal', normalized)
        
        # Max variations
        normalized = re.sub(r'max\s*od', 'maxod', normalized)
        normalized = re.sub(r'max\s*over\s*drawal', 'maxoverdrawal', normalized)
        
        # Remove dots and special characters that don't affect meaning
        normalized = re.sub(r'\.', '', normalized)
        normalized = re.sub(r'[^\w\s]', '', normalized)
        
        return normalized.strip()
    
    def _generate_column_mappings(self, df: pd.DataFrame, table_category: str) -> Dict[str, str]:
        """Generate column mappings for a table category"""
        mappings = {}
        
        if table_category not in self.db_column_mappings:
            return mappings
        
        available_columns = list(df.columns)
        target_mappings = self.db_column_mappings[table_category]
        
        for db_column, aliases in target_mappings.items():
            best_match = None
            best_score = 0
            
            # Try exact match first
            for alias in aliases:
                for col in available_columns:
                    if self._fuzzy_match(alias, str(col), threshold=80):
                        best_match = col
                        best_score = 100
                        break
                if best_match:
                    break
            
            # Try fuzzy matching if no exact match
            if not best_match:
                for alias in aliases:
                    for col in available_columns:
                        score = self._calculate_similarity(alias, str(col))
                        if score > best_score and score >= 60:  # Lowered threshold from 70 to 60
                            best_score = score
                            best_match = col
            
            if best_match:
                mappings[best_match] = db_column
                logger.debug(f"Mapped column '{best_match}' -> '{db_column}' (score: {best_score})")
        
        return mappings
    
    def _calculate_similarity(self, target: str, source: str) -> float:
        """Calculate similarity between two strings"""
        if not target or not source:
            return 0.0
        
        target_norm = self._normalize_text(target)
        source_norm = self._normalize_text(source)
        
        # Calculate multiple similarity scores
        ratio_score = fuzz.ratio(target_norm, source_norm)
        partial_score = fuzz.partial_ratio(target_norm, source_norm)
        token_sort_score = fuzz.token_sort_ratio(target_norm, source_norm)
        token_set_score = fuzz.token_set_ratio(target_norm, source_norm)
        
        # Return the highest score
        return max(ratio_score, partial_score, token_sort_score, token_set_score)
    
    def classify_dataframes(self, dataframes: List[pd.DataFrame], table_names: List[str] = None) -> List[TableClassification]:
        """Classify multiple dataframes"""
        if table_names is None:
            table_names = [f"table_{i}" for i in range(len(dataframes))]
        
        classifications = []
        for df, table_name in zip(dataframes, table_names):
            if df is not None and not df.empty:
                classification = self.classify_table(df, table_name)
                classifications.append(classification)
                logger.info(f"Classified '{table_name}' as '{classification.category}' (confidence: {classification.confidence:.1f}%)")
            else:
                logger.warning(f"Skipping empty table: {table_name}")
        
        return classifications

# Example usage and testing
if __name__ == "__main__":
    # Test the classifier
    classifier = SmartTableClassifier()
    
    # Create sample dataframes
    sample_dfs = [
        pd.DataFrame({
            'A_Demand Met during Evening Peak hrs(MW) (at\r19:00 hrs; from RLDCs)': [52099, 61717],
            'A_Energy Met (MU)': [1169, 1511],
            'Region': ['NR', 'WR']
        }),
        pd.DataFrame({
            'States': ['Punjab', 'Haryana'],
            'Maximum Demand (MW)': [6996, 5000],
            'Energy Met (MU)': [142.7, 120.0]
        })
    ]
    
    table_names = ['Regional Summary', 'State Energy']
    
    # Classify the tables
    classifications = classifier.classify_dataframes(sample_dfs, table_names)
    
    for classification in classifications:
        print(f"\nTable: {classification.table_name}")
        print(f"Category: {classification.category}")
        print(f"Confidence: {classification.confidence:.1f}%")
        print(f"Description: {classification.description}")
        print(f"Column Mappings: {classification.column_mappings}") 