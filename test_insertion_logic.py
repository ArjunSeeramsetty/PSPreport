#!/usr/bin/env python3
"""
Test script to verify the insertion logic is receiving correct data.
"""

import pandas as pd
import sqlite3
from modular_db_insertion import EnhancedModularDBInserter

def test_insertion_logic():
    """Test the insertion logic with sample transformed data"""
    
    # Create sample transformed DataFrame (matching what we saw in debug)
    sample_data = {
        'Region': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
        'Peak Demand Met (MW)': [58663.0, 63359.0, 43038.0, 21187.0, 2628.0, 188875.0],
        'Energy Met (MU)': [1249.0, 1492.0, 1080.0, 429.0, 49.0, 4298.0],
        'Max Demand SCADA (MW)': [67817.0, 75025.0, 53695.0, 21992.0, 2794.0, 217258.0],
        'Date': ['12/17/2024'] * 6,
        'Table Name': ['page_2_table_0'] * 6
    }
    
    df = pd.DataFrame(sample_data)
    print("Sample transformed DataFrame:")
    print(df)
    print(f"Shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    
    # Test the clean_numeric_value function
    inserter = EnhancedModularDBInserter('power_data.db')
    
    print(f"\nTesting clean_numeric_value function:")
    test_values = [58663.0, 63359.0, 1249.0, 1492.0, 67817.0, 75025.0]
    for value in test_values:
        cleaned = inserter._clean_numeric_value(value)
        print(f"  {value} -> {cleaned}")
    
    # Test the insertion logic directly
    print(f"\nTesting insertion logic...")
    try:
        success = inserter.insert_regional_summary(df)
        print(f"Insertion result: {success}")
        
        # Check what was actually inserted
        conn = sqlite3.connect('power_data.db')
        cursor = conn.cursor()
        
        # Get the date ID for 2024-12-17
        cursor.execute("SELECT DateID FROM DimDates WHERE ActualDate = '2024-12-17'")
        date_result = cursor.fetchone()
        
        if date_result:
            date_id = date_result[0]
            print(f"Found DateID: {date_id}")
            
            # Query the inserted data
            query = """
            SELECT 
                r.RegionName,
                f.PeakDemandMet,
                f.EnergyMet,
                f.MaxDemandSCADA
            FROM FactAllIndiaDailySummary f
            JOIN DimRegions r ON f.RegionID = r.RegionID
            WHERE f.DateID = ?
            ORDER BY r.RegionName
            """
            
            cursor.execute(query, (date_id,))
            results = cursor.fetchall()
            
            print(f"\nInserted data:")
            for row in results:
                print(f"  {row}")
        else:
            print("Date 2024-12-17 not found in DimDates")
        
        conn.close()
        
    except Exception as e:
        print(f"Error during insertion: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_insertion_logic() 
"""
Test script to verify the insertion logic is receiving correct data.
"""

import pandas as pd
import sqlite3
from modular_db_insertion import EnhancedModularDBInserter

def test_insertion_logic():
    """Test the insertion logic with sample transformed data"""
    
    # Create sample transformed DataFrame (matching what we saw in debug)
    sample_data = {
        'Region': ['NR', 'WR', 'SR', 'ER', 'NER', 'TOTAL'],
        'Peak Demand Met (MW)': [58663.0, 63359.0, 43038.0, 21187.0, 2628.0, 188875.0],
        'Energy Met (MU)': [1249.0, 1492.0, 1080.0, 429.0, 49.0, 4298.0],
        'Max Demand SCADA (MW)': [67817.0, 75025.0, 53695.0, 21992.0, 2794.0, 217258.0],
        'Date': ['12/17/2024'] * 6,
        'Table Name': ['page_2_table_0'] * 6
    }
    
    df = pd.DataFrame(sample_data)
    print("Sample transformed DataFrame:")
    print(df)
    print(f"Shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    
    # Test the clean_numeric_value function
    inserter = EnhancedModularDBInserter('power_data.db')
    
    print(f"\nTesting clean_numeric_value function:")
    test_values = [58663.0, 63359.0, 1249.0, 1492.0, 67817.0, 75025.0]
    for value in test_values:
        cleaned = inserter._clean_numeric_value(value)
        print(f"  {value} -> {cleaned}")
    
    # Test the insertion logic directly
    print(f"\nTesting insertion logic...")
    try:
        success = inserter.insert_regional_summary(df)
        print(f"Insertion result: {success}")
        
        # Check what was actually inserted
        conn = sqlite3.connect('power_data.db')
        cursor = conn.cursor()
        
        # Get the date ID for 2024-12-17
        cursor.execute("SELECT DateID FROM DimDates WHERE ActualDate = '2024-12-17'")
        date_result = cursor.fetchone()
        
        if date_result:
            date_id = date_result[0]
            print(f"Found DateID: {date_id}")
            
            # Query the inserted data
            query = """
            SELECT 
                r.RegionName,
                f.PeakDemandMet,
                f.EnergyMet,
                f.MaxDemandSCADA
            FROM FactAllIndiaDailySummary f
            JOIN DimRegions r ON f.RegionID = r.RegionID
            WHERE f.DateID = ?
            ORDER BY r.RegionName
            """
            
            cursor.execute(query, (date_id,))
            results = cursor.fetchall()
            
            print(f"\nInserted data:")
            for row in results:
                print(f"  {row}")
        else:
            print("Date 2024-12-17 not found in DimDates")
        
        conn.close()
        
    except Exception as e:
        print(f"Error during insertion: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_insertion_logic() 