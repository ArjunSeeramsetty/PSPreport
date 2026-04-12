#!/usr/bin/env python3
"""
Test script for enhanced modular database insertion
Tests improved state name processing and fuzzy column matching
"""

import os
import logging
from modular_psp_parser import PSPReportParser
from modular_db_insertion import EnhancedModularDBInserter

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_enhanced_insertion():
    """Test the enhanced insertion functionality"""
    
    # Test with a sample PDF that has state name issues
    pdf_path = "sample input/18.04.25_NLDC_PSP.pdf"
    
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        return False
    
    try:
        logger.info("=== Testing Enhanced Modular Database Insertion ===")
        
        # Parse PDF using modular parser
        logger.info("Step 1: Parsing PDF...")
        parser = PSPReportParser()
        results = parser.parse_pdf(pdf_path)
        
        if not results['success']:
            logger.error("Failed to parse PDF")
            return False
        
        logger.info(f"Successfully parsed PDF: {len(results['final_tables'])} tables extracted")
        
        # Show table types found
        table_types = []
        for table in results['final_tables']:
            table_name = table['Table Name'].iloc[0] if 'Table Name' in table.columns else "Unknown"
            table_types.append(table_name)
        
        logger.info(f"Table types found: {table_types}")
        
        # Test enhanced insertion
        logger.info("Step 2: Testing enhanced database insertion...")
        inserter = EnhancedModularDBInserter()
        
        if not inserter.connect():
            logger.error("Failed to connect to database")
            return False
        
        # Test state name normalization
        logger.info("Step 3: Testing state name normalization...")
        test_state_names = [
            "Punjab", "Haryana", "Rajasthan", "Delhi", "UP", "Uttarakhand", "HP",
            "J&K(UT) & Ladakh(UT)", "J&K(UT) &.", "J&K(UT)", "JAMMU & KASHMIR (UT)",
            "Railways_NR ISTS", "RailwaysNR ISTS", "Railways_NR",
            "Chhattisgarh", "Gujarat", "MP", "Maharashtra", "Goa",
            "Andhra Pradesh", "Telangana", "Karnataka", "Kerala", "Tamil Nadu",
            "Bihar", "DVC", "Jharkhand", "Odisha", "West Bengal", "Sikkim",
            "Arunachal Pradesh", "Arunachal", "Assam", "Manipur", "Meghalaya",
            "Mizoram", "Nagaland", "Tripura",
            # Invalid state names that should be filtered out
            "1907", "202", "123", "456", "789", "NR", "WR", "SR", "ER", "NER",
            "TOTAL", "ALL INDIA", "GRAND TOTAL", "", "None", None
        ]
        
        logger.info("Testing state name normalization:")
        for state_name in test_state_names:
            normalized = inserter._normalize_state_name(state_name)
            if normalized:
                logger.info(f"  '{state_name}' -> '{normalized}'")
            else:
                logger.info(f"  '{state_name}' -> SKIPPED")
        
        # Test fuzzy column matching
        logger.info("Step 4: Testing fuzzy column matching...")
        import pandas as pd
        
        # Test states table columns
        test_states_df = pd.DataFrame({
            'States': ['Punjab', 'Haryana'],
            'State': ['Punjab', 'Haryana'],  # Alternative column name
            'Maximum Demand (MW)': [1000, 800],
            'Max Demand (MW)': [1000, 800],  # Alternative column name
            'Energy Met (MU)': [500, 400],
            'Energy (MU)': [500, 400],  # Alternative column name
            'Date': ['4/18/2025', '4/18/2025']
        })
        
        logger.info("Original columns: " + str(test_states_df.columns.tolist()))
        matched_df = inserter._fuzzy_match_columns(test_states_df, 'states')
        logger.info("After fuzzy matching: " + str(matched_df.columns.tolist()))
        
        # Test regional summary columns
        test_regional_df = pd.DataFrame({
            'Region': ['Northern Region'],
            'Peak Demand Met (MW)': [5000],
            'Peak Shortage (MW)': [100],
            'Energy Met (MU)': [2500],
            'FVI': [0.5],  # Alternative for Frequency Violation Index
            'Date': ['4/18/2025']
        })
        
        logger.info("Original regional columns: " + str(test_regional_df.columns.tolist()))
        matched_regional_df = inserter._fuzzy_match_columns(test_regional_df, 'regional_summary')
        logger.info("After fuzzy matching: " + str(matched_regional_df.columns.tolist()))
        
        # Process actual parser results
        logger.info("Step 5: Processing actual parser results...")
        success = inserter.process_parser_results(results)
        
        if success:
            logger.info("✅ Enhanced database insertion completed successfully")
        else:
            logger.error("❌ Enhanced database insertion failed")
        
        inserter.close()
        return success
        
    except Exception as e:
        logger.error(f"Error in enhanced insertion test: {e}")
        return False

def test_specific_state_issues():
    """Test specific state name issues that were reported"""
    
    logger.info("=== Testing Specific State Name Issues ===")
    
    inserter = EnhancedModularDBInserter()
    
    # Test the specific invalid state names mentioned
    problematic_states = ["1907", "202", "123", "456", "789", "NR", "WR", "SR", "ER", "NER"]
    
    logger.info("Testing problematic state names:")
    for state_name in problematic_states:
        normalized = inserter._normalize_state_name(state_name)
        if normalized:
            logger.warning(f"  '{state_name}' -> '{normalized}' (should be skipped)")
        else:
            logger.info(f"  '{state_name}' -> SKIPPED (correctly filtered)")
    
    # Test valid state names that should be processed
    valid_states = ["Punjab", "Haryana", "Rajasthan", "Delhi", "UP", "Uttarakhand"]
    
    logger.info("Testing valid state names:")
    for state_name in valid_states:
        normalized = inserter._normalize_state_name(state_name)
        if normalized:
            logger.info(f"  '{state_name}' -> '{normalized}' (correctly processed)")
        else:
            logger.error(f"  '{state_name}' -> SKIPPED (should be processed)")

if __name__ == "__main__":
    # Test specific state issues first
    test_specific_state_issues()
    
    # Test full enhanced insertion
    test_enhanced_insertion() 