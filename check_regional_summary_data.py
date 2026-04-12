#!/usr/bin/env python3
"""
Check the actual data values in FactAllIndiaDailySummary table.
"""

import sqlite3
import pandas as pd
from datetime import datetime

def check_regional_summary_data(db_path: str = 'power_data.db'):
    """Check the actual data values in FactAllIndiaDailySummary"""
    
    print("Checking Regional Summary data in database...")
    
    try:
        conn = sqlite3.connect(db_path)
        
        # Get the date ID for 2024-12-17
        cursor = conn.cursor()
        cursor.execute("SELECT DateID FROM DimDates WHERE ActualDate = '2024-12-17'")
        date_result = cursor.fetchone()
        
        if not date_result:
            print("❌ Date 2024-12-17 not found in DimDates")
            return
        
        date_id = date_result[0]
        print(f"✅ Found DateID: {date_id} for 2024-12-17")
        
        # Query the FactAllIndiaDailySummary table
        query = """
        SELECT 
            r.RegionName,
            f.PeakDemandMet,
            f.EnergyMet,
            f.ScheduleDrawal,
            f.ActualDrawal,
            f.OverUnderDrawal,
            f.MaxDemandSCADA,
            f.ShareRESInTotalGeneration,
            f.SolarHRMaxDemand,
            f.NonSolarHRMaxDemand
        FROM FactAllIndiaDailySummary f
        JOIN DimRegions r ON f.RegionID = r.RegionID
        WHERE f.DateID = ?
        ORDER BY r.RegionName
        """
        
        df = pd.read_sql_query(query, conn, params=(date_id,))
        
        print(f"\n📊 Regional Summary Data for 2024-12-17:")
        print(f"Total records: {len(df)}")
        print("\n" + "="*80)
        
        if len(df) > 0:
            print(df.to_string(index=False))
            
            # Check for non-zero values
            numeric_columns = ['PeakDemandMet', 'EnergyMet', 'ScheduleDrawal', 'ActualDrawal', 
                             'OverUnderDrawal', 'MaxDemandSCADA', 'ShareRESInTotalGeneration',
                             'SolarHRMaxDemand', 'NonSolarHRMaxDemand']
            
            print(f"\n🔍 Non-zero value analysis:")
            for col in numeric_columns:
                if col in df.columns:
                    non_zero_count = (df[col] != 0).sum()
                    total_count = len(df)
                    print(f"  {col}: {non_zero_count}/{total_count} non-zero values")
                    
                    if non_zero_count > 0:
                        sample_values = df[df[col] != 0][col].head(3).tolist()
                        print(f"    Sample values: {sample_values}")
        else:
            print("❌ No data found for this date")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")

if __name__ == "__main__":
    check_regional_summary_data() 