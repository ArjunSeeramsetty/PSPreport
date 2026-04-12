#!/usr/bin/env python3
"""
Debug script to examine parsed table data structure
"""

import os
import logging
import pandas as pd
from modular_psp_parser import PSPReportParser

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def debug_table_data(pdf_path):
    """Debug the actual data structure of parsed tables"""
    
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        return
    
    try:
        # Parse PDF using modular parser
        logger.info(f"Parsing PDF: {pdf_path}")
        parser = PSPReportParser()
        results = parser.parse_pdf(pdf_path)
        
        if not results['success']:
            logger.error("Failed to parse PDF")
            return
        
        logger.info(f"Successfully parsed PDF: {len(results['final_tables'])} tables extracted")
        
        # Count tables with actual data
        tables_with_data = 0
        total_tables = len(results['final_tables'])
        
        # Examine each table's structure
        for i, table in enumerate(results['final_tables']):
            table_name = table['Table Name'].iloc[0] if 'Table Name' in table.columns else f"Table_{i}"
            
            logger.info(f"\n=== Table {i+1}: {table_name} ===")
            logger.info(f"Shape: {table.shape}")
            logger.info(f"Columns: {list(table.columns)}")
            
            # Check if table has actual data (non-zero values)
            has_data = False
            for col in table.columns:
                if col not in ['Date', 'Table Name']:
                    if table[col].dtype in ['float64', 'int64']:
                        if table[col].sum() > 0:
                            has_data = True
                            break
                    elif table[col].dtype == 'object':
                        non_null_count = table[col].notna().sum()
                        if non_null_count > 0:
                            has_data = True
                            break
            
            if has_data:
                tables_with_data += 1
                logger.info("✅ Table has actual data")
            else:
                logger.warning("❌ Table has no actual data (all zeros/null)")
            
            # Show first few rows
            logger.info(f"First few rows:")
            for idx, row in table.head(2).iterrows():
                logger.info(f"Row {idx}: {dict(row)}")
            
            # Check for empty or problematic data
            empty_cols = []
            for col in table.columns:
                if table[col].isna().all() or (table[col] == '').all():
                    empty_cols.append(col)
            
            if empty_cols:
                logger.warning(f"Empty columns: {empty_cols}")
            
            logger.info("-" * 50)
        
        logger.info(f"\n=== SUMMARY ===")
        logger.info(f"Total tables: {total_tables}")
        logger.info(f"Tables with data: {tables_with_data}")
        logger.info(f"Tables without data: {total_tables - tables_with_data}")
        logger.info(f"Data availability: {tables_with_data/total_tables*100:.1f}%")
    
    except Exception as e:
        logger.error(f"Error in debug: {e}")

if __name__ == "__main__":
    # Test with multiple PDF files
    pdf_files = [
        "sample input/18.04.25_NLDC_PSP.pdf",
        "sample input/19.04.25_NLDC_PSP.pdf",
        "sample input/01.04.23_NLDC_PSP.pdf"
    ]
    
    for pdf_file in pdf_files:
        if os.path.exists(pdf_file):
            logger.info(f"\n{'='*60}")
            logger.info(f"TESTING: {pdf_file}")
            logger.info(f"{'='*60}")
            debug_table_data(pdf_file)
        else:
            logger.warning(f"File not found: {pdf_file}") 