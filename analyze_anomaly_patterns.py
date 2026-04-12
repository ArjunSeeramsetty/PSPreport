import pandas as pd
from datetime import datetime
from pathlib import Path
import re

def extract_date_from_path(pdf_path):
    """Extract date from PDF path"""
    # Extract date from filename like "20.04.25_NLDC_PSP.pdf"
    filename = Path(pdf_path).name
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", filename)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = 2000 + int(match.group(3))
        return datetime(year, month, day)
    return None

def get_expected_tables(date):
    """Get expected number of raw tables based on date"""
    if date < datetime(2023, 7, 30):
        return 13  # Before cross-border schedules
    elif date < datetime(2024, 11, 4):
        return 16  # After cross-border schedules, before blockwise
    else:
        return 17  # After blockwise table

def analyze_anomaly_patterns():
    """Analyze anomaly patterns based on both cutoff dates"""
    
    # Read anomaly file
    df = pd.read_csv("anomaly_pdfs.txt", sep='\t')
    
    # Extract dates
    df['date'] = df['PDF_Path'].apply(extract_date_from_path)
    
    # Filter out rows where date couldn't be extracted
    df = df[df['date'].notna()].copy()
    
    # Define cutoff dates
    cross_border_date = datetime(2023, 7, 30)
    blockwise_date = datetime(2024, 11, 4)
    
    # Categorize periods
    def categorize_period(date):
        if date < cross_border_date:
            return 'Before_CrossBorder'
        elif date < blockwise_date:
            return 'After_CrossBorder_Before_Blockwise'
        else:
            return 'After_Blockwise'
    
    df['period'] = df['date'].apply(categorize_period)
    df['expected_raw'] = df['date'].apply(get_expected_tables)
    df['anomaly_type'] = df.apply(lambda row: 
        'Extra_Tables' if row['Raw_Tables'] > row['expected_raw'] else 'Missing_Tables', axis=1)
    
    print("=== ANOMALY ANALYSIS ===")
    print(f"Total anomalies: {len(df)}")
    print(f"Cross-border schedules introduced: {cross_border_date.strftime('%Y-%m-%d')}")
    print(f"Blockwise table introduced: {blockwise_date.strftime('%Y-%m-%d')}")
    
    print(f"\n=== BY PERIOD ===")
    period_stats = df.groupby('period').agg({
        'Raw_Tables': ['count', 'mean', 'min', 'max'],
        'Identified_Tables': ['mean', 'min', 'max'],
        'expected_raw': 'first'
    }).round(2)
    print(period_stats)
    
    print(f"\n=== BY ANOMALY TYPE ===")
    anomaly_stats = df.groupby(['period', 'anomaly_type']).size().unstack(fill_value=0)
    print(anomaly_stats)
    
    print(f"\n=== DETAILED BREAKDOWN ===")
    
    # Before cross-border schedules
    before_cross = df[df['period'] == 'Before_CrossBorder']
    print(f"\nBefore {cross_border_date.strftime('%Y-%m-%d')} (Expected: 13 raw tables):")
    print(f"  Total PDFs: {len(before_cross)}")
    if len(before_cross) > 0:
        print(f"  Raw tables range: {before_cross['Raw_Tables'].min()}-{before_cross['Raw_Tables'].max()}")
        print(f"  Most common raw count: {before_cross['Raw_Tables'].mode().iloc[0] if len(before_cross['Raw_Tables'].mode()) > 0 else 'N/A'}")
        
        extra_before = before_cross[before_cross['Raw_Tables'] > 13]
        if len(extra_before) > 0:
            print(f"  PDFs with >13 tables: {len(extra_before)}")
            for _, row in extra_before.head(3).iterrows():
                print(f"    {row['PDF_Path']}: {row['Raw_Tables']} raw, {row['Identified_Tables']} identified")
    
    # After cross-border, before blockwise
    after_cross = df[df['period'] == 'After_CrossBorder_Before_Blockwise']
    print(f"\n{cross_border_date.strftime('%Y-%m-%d')} to {blockwise_date.strftime('%Y-%m-%d')} (Expected: 16 raw tables):")
    print(f"  Total PDFs: {len(after_cross)}")
    if len(after_cross) > 0:
        print(f"  Raw tables range: {after_cross['Raw_Tables'].min()}-{after_cross['Raw_Tables'].max()}")
        print(f"  Most common raw count: {after_cross['Raw_Tables'].mode().iloc[0] if len(after_cross['Raw_Tables'].mode()) > 0 else 'N/A'}")
        
        extra_after_cross = after_cross[after_cross['Raw_Tables'] > 16]
        if len(extra_after_cross) > 0:
            print(f"  PDFs with >16 tables: {len(extra_after_cross)}")
            for _, row in extra_after_cross.head(3).iterrows():
                print(f"    {row['PDF_Path']}: {row['Raw_Tables']} raw, {row['Identified_Tables']} identified")
    
    # After blockwise table
    after_blockwise = df[df['period'] == 'After_Blockwise']
    print(f"\nAfter {blockwise_date.strftime('%Y-%m-%d')} (Expected: 17 raw tables):")
    print(f"  Total PDFs: {len(after_blockwise)}")
    if len(after_blockwise) > 0:
        print(f"  Raw tables range: {after_blockwise['Raw_Tables'].min()}-{after_blockwise['Raw_Tables'].max()}")
        print(f"  Most common raw count: {after_blockwise['Raw_Tables'].mode().iloc[0] if len(after_blockwise['Raw_Tables'].mode()) > 0 else 'N/A'}")
        
        extra_after_blockwise = after_blockwise[after_blockwise['Raw_Tables'] > 17]
        if len(extra_after_blockwise) > 0:
            print(f"  PDFs with >17 tables: {len(extra_after_blockwise)}")
            for _, row in extra_after_blockwise.head(3).iterrows():
                print(f"    {row['PDF_Path']}: {row['Raw_Tables']} raw, {row['Identified_Tables']} identified")
    
    # Summary of issues
    print(f"\n=== SUMMARY OF ISSUES ===")
    print("1. Before cross-border schedules: Some PDFs have extra tables beyond the expected 13")
    print("2. After cross-border schedules: Some PDFs have extra tables beyond the expected 16")
    print("3. After blockwise table: Blockwise table is split across pages, creating extra raw tables")
    
    # Save categorized anomalies
    output_file = "categorized_anomalies_v2.txt"
    df.to_csv(output_file, sep='\t', index=False)
    print(f"\nCategorized anomalies saved to: {output_file}")
    
    return df

if __name__ == "__main__":
    analyze_anomaly_patterns() 
from datetime import datetime
from pathlib import Path
import re

def extract_date_from_path(pdf_path):
    """Extract date from PDF path"""
    # Extract date from filename like "20.04.25_NLDC_PSP.pdf"
    filename = Path(pdf_path).name
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", filename)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = 2000 + int(match.group(3))
        return datetime(year, month, day)
    return None

def get_expected_tables(date):
    """Get expected number of raw tables based on date"""
    if date < datetime(2023, 7, 30):
        return 13  # Before cross-border schedules
    elif date < datetime(2024, 11, 4):
        return 16  # After cross-border schedules, before blockwise
    else:
        return 17  # After blockwise table

def analyze_anomaly_patterns():
    """Analyze anomaly patterns based on both cutoff dates"""
    
    # Read anomaly file
    df = pd.read_csv("anomaly_pdfs.txt", sep='\t')
    
    # Extract dates
    df['date'] = df['PDF_Path'].apply(extract_date_from_path)
    
    # Filter out rows where date couldn't be extracted
    df = df[df['date'].notna()].copy()
    
    # Define cutoff dates
    cross_border_date = datetime(2023, 7, 30)
    blockwise_date = datetime(2024, 11, 4)
    
    # Categorize periods
    def categorize_period(date):
        if date < cross_border_date:
            return 'Before_CrossBorder'
        elif date < blockwise_date:
            return 'After_CrossBorder_Before_Blockwise'
        else:
            return 'After_Blockwise'
    
    df['period'] = df['date'].apply(categorize_period)
    df['expected_raw'] = df['date'].apply(get_expected_tables)
    df['anomaly_type'] = df.apply(lambda row: 
        'Extra_Tables' if row['Raw_Tables'] > row['expected_raw'] else 'Missing_Tables', axis=1)
    
    print("=== ANOMALY ANALYSIS ===")
    print(f"Total anomalies: {len(df)}")
    print(f"Cross-border schedules introduced: {cross_border_date.strftime('%Y-%m-%d')}")
    print(f"Blockwise table introduced: {blockwise_date.strftime('%Y-%m-%d')}")
    
    print(f"\n=== BY PERIOD ===")
    period_stats = df.groupby('period').agg({
        'Raw_Tables': ['count', 'mean', 'min', 'max'],
        'Identified_Tables': ['mean', 'min', 'max'],
        'expected_raw': 'first'
    }).round(2)
    print(period_stats)
    
    print(f"\n=== BY ANOMALY TYPE ===")
    anomaly_stats = df.groupby(['period', 'anomaly_type']).size().unstack(fill_value=0)
    print(anomaly_stats)
    
    print(f"\n=== DETAILED BREAKDOWN ===")
    
    # Before cross-border schedules
    before_cross = df[df['period'] == 'Before_CrossBorder']
    print(f"\nBefore {cross_border_date.strftime('%Y-%m-%d')} (Expected: 13 raw tables):")
    print(f"  Total PDFs: {len(before_cross)}")
    if len(before_cross) > 0:
        print(f"  Raw tables range: {before_cross['Raw_Tables'].min()}-{before_cross['Raw_Tables'].max()}")
        print(f"  Most common raw count: {before_cross['Raw_Tables'].mode().iloc[0] if len(before_cross['Raw_Tables'].mode()) > 0 else 'N/A'}")
        
        extra_before = before_cross[before_cross['Raw_Tables'] > 13]
        if len(extra_before) > 0:
            print(f"  PDFs with >13 tables: {len(extra_before)}")
            for _, row in extra_before.head(3).iterrows():
                print(f"    {row['PDF_Path']}: {row['Raw_Tables']} raw, {row['Identified_Tables']} identified")
    
    # After cross-border, before blockwise
    after_cross = df[df['period'] == 'After_CrossBorder_Before_Blockwise']
    print(f"\n{cross_border_date.strftime('%Y-%m-%d')} to {blockwise_date.strftime('%Y-%m-%d')} (Expected: 16 raw tables):")
    print(f"  Total PDFs: {len(after_cross)}")
    if len(after_cross) > 0:
        print(f"  Raw tables range: {after_cross['Raw_Tables'].min()}-{after_cross['Raw_Tables'].max()}")
        print(f"  Most common raw count: {after_cross['Raw_Tables'].mode().iloc[0] if len(after_cross['Raw_Tables'].mode()) > 0 else 'N/A'}")
        
        extra_after_cross = after_cross[after_cross['Raw_Tables'] > 16]
        if len(extra_after_cross) > 0:
            print(f"  PDFs with >16 tables: {len(extra_after_cross)}")
            for _, row in extra_after_cross.head(3).iterrows():
                print(f"    {row['PDF_Path']}: {row['Raw_Tables']} raw, {row['Identified_Tables']} identified")
    
    # After blockwise table
    after_blockwise = df[df['period'] == 'After_Blockwise']
    print(f"\nAfter {blockwise_date.strftime('%Y-%m-%d')} (Expected: 17 raw tables):")
    print(f"  Total PDFs: {len(after_blockwise)}")
    if len(after_blockwise) > 0:
        print(f"  Raw tables range: {after_blockwise['Raw_Tables'].min()}-{after_blockwise['Raw_Tables'].max()}")
        print(f"  Most common raw count: {after_blockwise['Raw_Tables'].mode().iloc[0] if len(after_blockwise['Raw_Tables'].mode()) > 0 else 'N/A'}")
        
        extra_after_blockwise = after_blockwise[after_blockwise['Raw_Tables'] > 17]
        if len(extra_after_blockwise) > 0:
            print(f"  PDFs with >17 tables: {len(extra_after_blockwise)}")
            for _, row in extra_after_blockwise.head(3).iterrows():
                print(f"    {row['PDF_Path']}: {row['Raw_Tables']} raw, {row['Identified_Tables']} identified")
    
    # Summary of issues
    print(f"\n=== SUMMARY OF ISSUES ===")
    print("1. Before cross-border schedules: Some PDFs have extra tables beyond the expected 13")
    print("2. After cross-border schedules: Some PDFs have extra tables beyond the expected 16")
    print("3. After blockwise table: Blockwise table is split across pages, creating extra raw tables")
    
    # Save categorized anomalies
    output_file = "categorized_anomalies_v2.txt"
    df.to_csv(output_file, sep='\t', index=False)
    print(f"\nCategorized anomalies saved to: {output_file}")
    
    return df

if __name__ == "__main__":
    analyze_anomaly_patterns() 