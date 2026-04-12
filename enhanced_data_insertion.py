#!/usr/bin/env python3
"""
Enhanced Data Insertion using Smart Table Classification
"""

import pandas as pd
import logging
from typing import List, Dict, Any, Optional
from smart_table_classifier import SmartTableClassifier, TableClassification

logger = logging.getLogger(__name__)

class EnhancedDataLoader:
    """Enhanced data loader with smart table classification"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.classifier = SmartTableClassifier()
        self.logger = logging.getLogger(self.__class__.__name__)
        
    def process_dataframes_with_classification(self, dataframes: List[pd.DataFrame], 
                                             table_names: List[str] = None) -> Dict[str, Any]:
        """
        Process dataframes using smart classification and return structured data
        """
        if not dataframes:
            self.logger.warning("No dataframes provided")
            return {}
        
        # Classify all tables
        classifications = self.classifier.classify_dataframes(dataframes, table_names)
        
        # Group dataframes by category
        categorized_data = {}
        for df, classification in zip(dataframes, classifications):
            if classification.confidence > 50:  # Only use confident classifications
                category = classification.category
                if category not in categorized_data:
                    categorized_data[category] = []
                
                # Apply column mappings
                mapped_df = self._apply_column_mappings(df, classification.column_mappings)
                categorized_data[category].append({
                    'dataframe': mapped_df,
                    'classification': classification,
                    'original_df': df
                })
                
                self.logger.info(f"Processed {classification.table_name} as {category} "
                               f"(confidence: {classification.confidence:.1f}%)")
            else:
                self.logger.warning(f"Low confidence classification for table: "
                                  f"{classification.table_name} ({classification.confidence:.1f}%)")
        
        return categorized_data
    
    def _apply_column_mappings(self, df: pd.DataFrame, mappings: Dict[str, str]) -> pd.DataFrame:
        """Apply column mappings to a dataframe"""
        if not mappings:
            return df
        
        # Create a copy to avoid modifying the original
        mapped_df = df.copy()
        
        # Rename columns based on mappings
        column_renames = {}
        for source_col, target_col in mappings.items():
            if source_col in mapped_df.columns:
                column_renames[source_col] = target_col
        
        if column_renames:
            mapped_df = mapped_df.rename(columns=column_renames)
            self.logger.debug(f"Renamed columns: {column_renames}")
        
        return mapped_df
    
    def get_standardized_dataframes(self, categorized_data: Dict[str, Any]) -> List[pd.DataFrame]:
        """
        Convert categorized data back to standardized dataframes for existing insertion logic
        """
        standardized_dfs = []
        
        # Define the expected order of table types
        expected_order = [
            'regional_summary',
            'state_energy', 
            'international_exchange',
            'transmission_flow',
            'generation_breakdown'
        ]
        
        # Create standardized dataframes in expected order
        for table_type in expected_order:
            if table_type in categorized_data:
                # Take the first (or best) dataframe of this type
                table_data = categorized_data[table_type][0]
                standardized_dfs.append(table_data['dataframe'])
                self.logger.info(f"Added {table_type} to standardized dataframes")
            else:
                # Add empty dataframe to maintain order
                standardized_dfs.append(pd.DataFrame())
                self.logger.warning(f"No {table_type} data found, adding empty dataframe")
        
        return standardized_dfs

# Integration function for existing code
def enhance_data_insertion(dataframes_list: List[pd.DataFrame], 
                          db_path: str = 'power_data.db') -> List[pd.DataFrame]:
    """
    Enhanced data insertion function that can be used as a drop-in replacement
    """
    enhanced_loader = EnhancedDataLoader(db_path)
    
    # Process with smart classification
    categorized_data = enhanced_loader.process_dataframes_with_classification(dataframes_list)
    
    # Convert back to standardized format
    standardized_dfs = enhanced_loader.get_standardized_dataframes(categorized_data)
    
    return standardized_dfs

# Example usage
if __name__ == "__main__":
    # Test with sample data
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
    
    # Process with enhanced insertion
    enhanced_dfs = enhance_data_insertion(sample_dfs)
    
    print(f"Enhanced processing complete. Output: {len(enhanced_dfs)} dataframes")
    for i, df in enumerate(enhanced_dfs):
        print(f"Dataframe {i}: {df.shape if not df.empty else 'Empty'}") 