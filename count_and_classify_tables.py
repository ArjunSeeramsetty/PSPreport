#!/usr/bin/env python3
"""
Script to count and classify all tables in a PDF
"""

import pandas as pd
import logging
from custom_pdf_parser import CustomPDFParser
from smart_table_classifier import SmartTableClassifier

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def analyze_pdf_tables(pdf_path, silent=False):
    """Analyze all tables in a PDF and provide detailed classification"""
    
    if not silent:
        print("=" * 80)
        print(f"ANALYZING TABLES IN: {pdf_path}")
        print("=" * 80)
    
    # Parse PDF using custom parser
    parser = CustomPDFParser()
    
    # First, let's see what raw tables are extracted
    if not silent:
        print("\n🔍 STEP 1: RAW TABLE EXTRACTION")
        print("-" * 80)
    
    raw_tables, report_date = parser._extract_raw_tables(pdf_path)
    
    if not silent:
        print(f"📊 RAW TABLES EXTRACTED BY TABULA: {len(raw_tables)}")
        print(f"📅 Report Date: {report_date}")
        
        for key, df in raw_tables.items():
            if df is not None and not df.empty:
                print(f"   {key}: {df.shape[0]} rows, {df.shape[1]} cols")
                # Show first few characters of first row
                first_row_str = " ".join(df.iloc[0].astype(str).fillna('').str.strip().tolist())
                print(f"      Preview: {first_row_str[:80]}...")
    
    # Now let's see what tables are identified
    if not silent:
        print("\n🔍 STEP 2: TABLE IDENTIFICATION")
        print("-" * 80)
    
    page_structure = parser._detect_page_structure(pdf_path)
    identified_tables = parser._identify_tables_dynamic(raw_tables, page_structure)
    
    if not silent:
        print(f"📊 TABLES IDENTIFIED: {len(identified_tables)}")
        for table_name in identified_tables.keys():
            print(f"   ✓ {table_name}")
    
    # Show missed tables
    missed_tables = []
    for key, df in raw_tables.items():
        if df is not None and not df.empty:
            # Check if this table was identified
            identified = False
            for identified_name, identified_df in identified_tables.items():
                if df.equals(identified_df):
                    identified = True
                    break
            if not identified:
                missed_tables.append((key, df))
    
    if not silent:
        print(f"\n❌ MISSED TABLES: {len(missed_tables)}")
        for key, df in missed_tables:
            print(f"   {key}: {df.shape[0]} rows, {df.shape[1]} cols")
            # Show content preview
            content_str = " ".join(df.astype(str).fillna('').values.flatten())
            print(f"      Content: {content_str[:100]}...")
    
    # Now let's see what final dataframes are produced
    if not silent:
        print("\n🔍 STEP 3: FINAL PROCESSED TABLES")
        print("-" * 80)
    
    final_dataframes = parser.process_pdf(pdf_path)
    
    if not silent:
        print(f"📊 FINAL PROCESSED DATAFRAMES: {len(final_dataframes)}")
        
        for i, df in enumerate(final_dataframes):
            if df is not None and not df.empty:
                print(f"   DataFrame {i}: {df.shape[0]} rows, {df.shape[1]} cols")
                print(f"      Columns: {list(df.columns)}")
                print(f"      Sample data:")
                print(df.head(2).to_string())
                print("-" * 40)
    
    # Initialize classifier for detailed analysis
    if not silent:
        print("\n🔍 STEP 4: SMART CLASSIFICATION ANALYSIS")
        print("-" * 80)
    
    classifier = SmartTableClassifier()
    
    # Analyze each identified table with the smart classifier
    table_analysis = []
    
    for table_name, df in identified_tables.items():
        if df is not None and not df.empty:
            # Classify the table
            classification = classifier.classify_table(df, table_name)
            
            # Get table info
            table_info = {
                'table_name': table_name,
                'shape': df.shape,
                'columns': list(df.columns),
                'classification': classification.category,
                'confidence': classification.confidence,
                'description': classification.description,
                'column_mappings': classification.column_mappings
            }
            
            table_analysis.append(table_info)
            
            if not silent:
                # Print detailed info
                print(f"\n📋 TABLE: {table_name}")
                print(f"   Shape: {df.shape}")
                print(f"   Smart Classification: {classification.category}")
                print(f"   Confidence: {classification.confidence:.1f}%")
                print(f"   Description: {classification.description}")
                print(f"   Columns: {list(df.columns)}")
                if classification.column_mappings:
                    print(f"   Column Mappings: {classification.column_mappings}")
                print("-" * 40)
    
    # Summary statistics
    if not silent:
        print("\n" + "=" * 80)
        print("📈 COMPREHENSIVE ANALYSIS SUMMARY")
        print("=" * 80)
        
        print(f"\n📊 EXTRACTION SUMMARY:")
        print(f"   Raw tables extracted by Tabula: {len(raw_tables)}")
        print(f"   Tables successfully identified: {len(identified_tables)}")
        print(f"   Tables missed during identification: {len(missed_tables)}")
        print(f"   Final processed dataframes: {len(final_dataframes)}")
        
        # Count by classification
        classification_counts = {}
        for table in table_analysis:
            category = table['classification']
            if category in classification_counts:
                classification_counts[category] += 1
            else:
                classification_counts[category] = 1
        
        print(f"\n📊 SMART CLASSIFICATION BREAKDOWN:")
        for category, count in sorted(classification_counts.items()):
            print(f"   {category}: {count} table(s)")
        
        # Show confidence distribution
        print(f"\n🎯 CONFIDENCE DISTRIBUTION:")
        high_conf = len([t for t in table_analysis if t['confidence'] > 80])
        medium_conf = len([t for t in table_analysis if 50 < t['confidence'] <= 80])
        low_conf = len([t for t in table_analysis if t['confidence'] <= 50])
        
        print(f"   High Confidence (>80%): {high_conf} table(s)")
        print(f"   Medium Confidence (50-80%): {medium_conf} table(s)")
        print(f"   Low Confidence (≤50%): {low_conf} table(s)")
        
        # Show all available table patterns
        print(f"\n📋 ALL AVAILABLE TABLE PATTERNS:")
        all_patterns = list(classifier.table_patterns.keys())
        for i, pattern in enumerate(all_patterns, 1):
            print(f"   {i:2d}. {pattern}")
    
    return {
        'raw_tables': raw_tables,
        'identified_tables': identified_tables,
        'missed_tables': missed_tables,
        'final_dataframes': final_dataframes,
        'table_analysis': table_analysis
    }

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = "Output/NLDC_PSP_URLS/2025-26/MAY/reports/14.05.25_NLDC_PSP_132.pdf"
        print(f"No PDF path provided, using default: {pdf_path}")
    
    analyze_pdf_tables(pdf_path) 