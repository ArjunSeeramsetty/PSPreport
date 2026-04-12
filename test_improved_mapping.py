#!/usr/bin/env python3
"""
Test script for improved column mapping.
"""

import pandas as pd
import numpy as np
import logging
import sys
from pathlib import Path
from improved_column_mapping import ImprovedColumnMapper
from modular_psp_parser import PDFExtractor, TableIdentifier

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_improved_mapping(pdf_path: str):
    """Test the improved column mapping on a PDF"""
    
    # Initialize components
    extractor = PDFExtractor()
    identifier = TableIdentifier()
    mapper = ImprovedColumnMapper()
    
    print(f"Testing improved column mapping on {pdf_path}")
    
    # Extract raw tables
    print("1. Extracting raw tables...")
    raw_tables, report_date = extractor.extract_tables_from_pdf(pdf_path)
    print(f"   Extracted {len(raw_tables)} tables")
    
    # Classify tables
    print("2. Classifying tables...")
    classifications = {}
    for table_key, table_df in raw_tables.items():
        classification = identifier.classify_table(table_df, table_key)
        classifications[table_key] = classification
        print(f"   {table_key}: {classification.category} (confidence: {classification.confidence:.2f})")
    
    # Test improved mapping
    print("3. Testing improved column mapping...")
    results = {}
    
    for table_key, table_df in raw_tables.items():
        classification = classifications[table_key]
        category = classification.category
        
        print(f"\n   Processing {table_key} ({category})...")
        print(f"   Original columns: {list(table_df.columns)}")
        
        # Apply improved mapping
        mapped_df = mapper.map_columns(table_df, category)
        print(f"   After mapping: {list(mapped_df.columns)}")
        
        # Extract numeric data
        extracted_df = mapper.extract_numeric_data(mapped_df, category)
        print(f"   Extracted data shape: {extracted_df.shape}")
        
        # Check for non-zero data
        if not extracted_df.empty:
            numeric_cols = extracted_df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                non_zero_count = (extracted_df[numeric_cols] != 0).sum().sum()
                print(f"   Non-zero numeric values: {non_zero_count}")
                
                # Show sample data
                if non_zero_count > 0:
                    print(f"   Sample data:")
                    print(extracted_df.head(3).to_string())
                else:
                    print(f"   All numeric values are zero")
            else:
                print(f"   No numeric columns found")
        else:
            print(f"   No data extracted")
        
        results[table_key] = {
            'category': category,
            'original_shape': table_df.shape,
            'mapped_shape': mapped_df.shape,
            'extracted_shape': extracted_df.shape,
            'non_zero_count': non_zero_count if not extracted_df.empty and len(numeric_cols) > 0 else 0
        }
    
    # Summary
    print(f"\n=== SUMMARY ===")
    total_non_zero = sum(r['non_zero_count'] for r in results.values())
    print(f"Total non-zero values across all tables: {total_non_zero}")
    
    tables_with_data = sum(1 for r in results.values() if r['non_zero_count'] > 0)
    print(f"Tables with non-zero data: {tables_with_data}/{len(results)}")
    
    for table_key, result in results.items():
        print(f"{table_key}: {result['non_zero_count']} non-zero values")
    
    return results

def main():
    """Main execution function"""
    if len(sys.argv) < 2:
        print("Usage: python test_improved_mapping.py <pdf_path>")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    # Run test
    results = test_improved_mapping(pdf_path)
    
    return results

if __name__ == "__main__":
    main() 