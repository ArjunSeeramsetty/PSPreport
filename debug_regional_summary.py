#!/usr/bin/env python3
"""
Debug script to examine regional summary table data and column mapping.
"""

import pandas as pd
import logging
from improved_modular_psp_parser import ImprovedPSPReportParser
import numpy as np

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def debug_regional_summary(pdf_path: str):
    """Debug regional summary table extraction and processing"""
    
    print(f"Debugging regional summary for {pdf_path}")
    
    # Parse PDF
    parser = ImprovedPSPReportParser()
    results = parser.parse_pdf(pdf_path)
    
    if not results['success']:
        print(f"❌ PDF parsing failed: {results['errors']}")
        return
    
    print(f"✅ PDF parsed successfully")
    print(f"   - Report Date: {results['report_date']}")
    print(f"   - Tables extracted: {len(results['raw_tables'])}")
    print(f"   - Tables processed: {len(results['final_tables'])}")
    
    # Find regional summary tables
    regional_tables = []
    for i, table_df in enumerate(results['final_tables']):
        if table_df.empty:
            continue
            
        table_name = table_df['Table Name'].iloc[0] if 'Table Name' in table_df.columns else f"table_{i}"
        
        # Check if this looks like a regional summary table
        columns = table_df.columns.tolist()
        if 'Region' in columns:
            regional_tables.append((table_name, table_df))
    
    print(f"\nFound {len(regional_tables)} regional summary tables:")
    
    for table_name, table_df in regional_tables:
        print(f"\n=== {table_name} ===")
        print(f"Shape: {table_df.shape}")
        print(f"Columns: {table_df.columns.tolist()}")
        
        # Show first few rows
        print(f"\nFirst 5 rows:")
        print(table_df.head())
        
        # Check for non-zero values
        numeric_columns = table_df.select_dtypes(include=[np.number]).columns
        print(f"\nNumeric columns: {numeric_columns.tolist()}")
        
        for col in numeric_columns:
            non_zero_count = (table_df[col] != 0).sum()
            total_count = len(table_df)
            print(f"  {col}: {non_zero_count}/{total_count} non-zero values")
        
        # Check for null values
        null_counts = table_df.isnull().sum()
        print(f"\nNull value counts:")
        for col, count in null_counts.items():
            if count > 0:
                print(f"  {col}: {count} null values")
        
        # Show sample data with actual values
        print(f"\nSample data with values:")
        for idx, row in table_df.head(3).iterrows():
            print(f"  Row {idx}:")
            for col in table_df.columns:
                value = row[col]
                print(f"    {col}: {value} (type: {type(value)})")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python debug_regional_summary.py <pdf_path>")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    debug_regional_summary(pdf_path) 