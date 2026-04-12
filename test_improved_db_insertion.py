#!/usr/bin/env python3
"""
Test script for improved database insertion using the enhanced parser.
"""

import pandas as pd
import numpy as np
import logging
import sys
import sqlite3
from pathlib import Path
from datetime import datetime
from improved_modular_psp_parser import ImprovedPSPReportParser
from modular_db_insertion import EnhancedModularDBInserter

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_improved_db_insertion(pdf_path: str, db_path: str = 'power_data.db'):
    """Test the improved parser with database insertion"""
    
    print(f"Testing improved parser with database insertion for {pdf_path}")
    
    # Step 1: Parse PDF with improved parser
    print("\n1. Parsing PDF with improved parser...")
    parser = ImprovedPSPReportParser()
    results = parser.parse_pdf(pdf_path)
    
    if not results['success']:
        print(f"❌ PDF parsing failed: {results['errors']}")
        return False
    
    print(f"✅ PDF parsed successfully")
    print(f"   - Report Date: {results['report_date']}")
    print(f"   - Tables extracted: {len(results['raw_tables'])}")
    print(f"   - Tables processed: {len(results['final_tables'])}")
    
    # Step 2: Initialize database inserter
    print("\n2. Initializing database inserter...")
    try:
        inserter = EnhancedModularDBInserter(db_path)
        if not inserter.connect():
            print(f"❌ Database connection failed")
            return False
        print(f"✅ Database connection established")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
    
    # Step 3: Process each table for database insertion
    print("\n3. Processing tables for database insertion...")
    
    total_inserted = 0
    total_skipped = 0
    insertion_results = []
    
    for table_df in results['final_tables']:
        if table_df.empty:
            continue
            
        table_name = table_df['Table Name'].iloc[0] if 'Table Name' in table_df.columns else "Unknown"
        print(f"\n   Processing table: {table_name}")
        print(f"   Shape: {table_df.shape}")
        
        # Determine table type based on content
        table_type = determine_table_type(table_df)
        print(f"   Detected type: {table_type}")
        
        # Insert into database
        try:
            if table_type == 'regional_summary':
                success = inserter.insert_regional_summary(table_df)
            elif table_type == 'state_energy':
                success = inserter.insert_states_data(table_df)
            elif table_type == 'frequency_profile':
                success = inserter.insert_frequency_profile(table_df)
            elif table_type == 'transnational_exchange':
                success = inserter.insert_international_net(table_df)
            elif table_type == 'import_export_regions':
                success = inserter.insert_import_export_regions(table_df)
            elif table_type == 'outage_data':
                success = inserter.insert_outage_data(table_df)
            elif table_type == 'generation_breakdown':
                success = inserter.insert_generation_breakdown(table_df)
            elif table_type == 're_share':
                success = inserter.insert_re_share(table_df)
            elif table_type == 'solar_nonsolar_hour':
                success = inserter.insert_solar_non_solar_hour(table_df)
            elif table_type == 'transmission_flow':
                success = inserter.insert_inter_region(table_df)
            elif table_type == 'cross_border_schedule':
                success = inserter.insert_cross_border_schedule(table_df)
            elif table_type == 'time_block':
                success = inserter.insert_block_wise(table_df)
            else:
                print(f"   ⚠️  Unknown table type, skipping")
                success = False
            
            if success:
                inserted = len(table_df)
                skipped = 0
                print(f"   ✅ Inserted: {inserted} records")
            else:
                inserted = 0
                skipped = len(table_df)
                print(f"   ❌ Failed to insert, skipped: {skipped} records")
            
            total_inserted += inserted
            total_skipped += skipped
            
            insertion_results.append({
                'table_name': table_name,
                'table_type': table_type,
                'inserted': inserted,
                'skipped': skipped,
                'total': len(table_df)
            })
            
        except Exception as e:
            print(f"   ❌ Insertion failed: {e}")
            insertion_results.append({
                'table_name': table_name,
                'table_type': table_type,
                'inserted': 0,
                'skipped': len(table_df),
                'total': len(table_df),
                'error': str(e)
            })
    
    # Step 4: Summary
    print(f"\n=== INSERTION SUMMARY ===")
    print(f"Total records inserted: {total_inserted}")
    print(f"Total records skipped: {total_skipped}")
    print(f"Success rate: {total_inserted/(total_inserted + total_skipped)*100:.1f}%" if (total_inserted + total_skipped) > 0 else "0%")
    
    print(f"\n=== DETAILED RESULTS ===")
    for result in insertion_results:
        status = "✅" if result['inserted'] > 0 else "❌"
        error_msg = f" (Error: {result['error']})" if 'error' in result else ""
        print(f"{status} {result['table_name']} ({result['table_type']}): {result['inserted']}/{result['total']} inserted{error_msg}")
    
    # Step 5: Verify data in database
    print(f"\n4. Verifying data in database...")
    verify_database_data(inserter.conn, results['report_date'])
    
    # Close database connection
    inserter.close()
    
    return total_inserted > 0

def determine_table_type(df: pd.DataFrame) -> str:
    """Determine the table type based on DataFrame content"""
    
    # Check for specific columns or data patterns
    columns = df.columns.tolist()
    
    # Regional summary - has Region and Metric columns
    if 'Region' in columns and 'Metric' in columns:
        return 'regional_summary'
    
    # State energy - has States column
    if 'States' in columns:
        return 'state_energy'
    
    # Frequency profile - has FVI column
    if 'FVI' in columns:
        return 'frequency_profile'
    
    # Transnational exchange - has Country column
    if 'Country' in columns:
        return 'transnational_exchange'
    
    # Import/Export regions - has Region and Metric (but not States)
    if 'Region' in columns and 'Metric' in columns and 'States' not in columns:
        return 'import_export_regions'
    
    # Outage data - has specific metrics
    if any('Sector' in col for col in columns):
        return 'outage_data'
    
    # Generation breakdown - has generation sources
    if any(source in str(columns) for source in ['Coal', 'Hydro', 'Nuclear', 'Wind', 'Solar']):
        return 'generation_breakdown'
    
    # RE Share - has renewable energy metrics
    if any('RES' in col or 'Non-fossil' in col for col in columns):
        return 're_share'
    
    # Solar/Non-Solar hour - has period information
    if 'Period' in columns:
        return 'solar_nonsolar_hour'
    
    # Transmission flow - has line details
    if 'Line Details' in columns:
        return 'transmission_flow'
    
    # Cross border schedule - has GNA, Bilateral, Total
    if all(col in columns for col in ['GNA', 'Bilateral', 'Total']):
        return 'cross_border_schedule'
    
    # Time block - has TIME column
    if 'TIME' in columns:
        return 'time_block'
    
    return 'unknown'

def verify_database_data(conn: sqlite3.Connection, report_date: str):
    """Verify that data was inserted into the database"""
    
    try:
        cursor = conn.cursor()
        
        # Check each fact table for data from this report date
        fact_tables = [
            'FactAllIndiaDailySummary',
            'FactStateDailyEnergy', 
            'FactTransmissionLinkFlow',
            'FactTimeBlockPowerData',
            'FactTimeBlockGeneration',
            'FactDailyGenerationBreakdown',
            'FactCountryDailyExchange',
            'FactInternationalTransmissionLinkFlow',
            'FactTransnationalExchangeDetail'
        ]
        
        print(f"   Checking data for date: {report_date}")
        
        for table in fact_tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE Date = ?", (report_date,))
                count = cursor.fetchone()[0]
                if count > 0:
                    print(f"   ✅ {table}: {count} records")
                else:
                    print(f"   ❌ {table}: 0 records")
            except Exception as e:
                print(f"   ⚠️  {table}: Error checking - {e}")
        
        # Show some sample data
        print(f"\n   Sample data from FactAllIndiaDailySummary:")
        cursor.execute("SELECT * FROM FactAllIndiaDailySummary WHERE Date = ? LIMIT 3", (report_date,))
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(f"   {row}")
        else:
            print(f"   No data found")
            
    except Exception as e:
        print(f"   ❌ Error verifying database data: {e}")

def main():
    """Main execution function"""
    if len(sys.argv) < 2:
        print("Usage: python test_improved_db_insertion.py <pdf_path> [db_path]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else 'power_data.db'
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    if not Path(db_path).exists():
        print(f"Database file not found: {db_path}")
        print("Please run setup_database.py first to create the database")
        sys.exit(1)
    
    # Run test
    success = test_improved_db_insertion(pdf_path, db_path)
    
    if success:
        print(f"\n✅ Test completed successfully!")
    else:
        print(f"\n❌ Test failed!")
        sys.exit(1)

if __name__ == "__main__":
    main() 