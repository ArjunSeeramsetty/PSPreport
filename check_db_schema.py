#!/usr/bin/env python3
"""
Check the actual database schema to understand the table structure.
"""

import sqlite3
import pandas as pd

def check_database_schema(db_path: str = 'power_data.db'):
    """Check the database schema"""
    
    print("Checking database schema...")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        print(f"📋 Tables in database:")
        for table in tables:
            print(f"  - {table[0]}")
        
        print(f"\n🔍 Checking DimDates table structure:")
        cursor.execute("PRAGMA table_info(DimDates)")
        dim_dates_columns = cursor.fetchall()
        for col in dim_dates_columns:
            print(f"  {col[1]} ({col[2]})")
        
        print(f"\n🔍 Checking FactAllIndiaDailySummary table structure:")
        cursor.execute("PRAGMA table_info(FactAllIndiaDailySummary)")
        fact_columns = cursor.fetchall()
        for col in fact_columns:
            print(f"  {col[1]} ({col[2]})")
        
        print(f"\n📊 Sample data from DimDates:")
        cursor.execute("SELECT * FROM DimDates LIMIT 5")
        dates_data = cursor.fetchall()
        for row in dates_data:
            print(f"  {row}")
        
        print(f"\n📊 Sample data from FactAllIndiaDailySummary:")
        cursor.execute("SELECT * FROM FactAllIndiaDailySummary LIMIT 3")
        fact_data = cursor.fetchall()
        for row in fact_data:
            print(f"  {row}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error checking schema: {e}")

if __name__ == "__main__":
    check_database_schema() 