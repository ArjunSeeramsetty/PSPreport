#!/usr/bin/env python3
"""
Debug script to examine the regional summary transformation process.
"""

import pandas as pd
import logging
from improved_modular_psp_parser import ImprovedPSPReportParser

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def debug_regional_summary_transformation(pdf_path: str):
    """Debug the regional summary transformation process"""
    
    print(f"Debugging regional summary transformation for {pdf_path}")
    
    # Parse PDF
    parser = ImprovedPSPReportParser()
    results = parser.parse_pdf(pdf_path)
    
    if not results['success']:
        print(f"❌ PDF parsing failed: {results['errors']}")
        return
    
    # Print the top-level keys to debug the structure
    print(f"Top-level keys in parser results: {list(results.keys())}")
    print(f"Type of processed_results: {type(results.get('processed_results'))}, length: {len(results.get('processed_results', [])) if results.get('processed_results') is not None else 'N/A'}")
    print(f"Type of final_tables: {type(results.get('final_tables'))}, length: {len(results.get('final_tables', [])) if results.get('final_tables') is not None else 'N/A'}")
    
    # Print the first ProcessingResult object to understand its structure
    if results.get('processed_results'):
        first_result = results['processed_results'][0]
        print(f"\nFirst ProcessingResult type: {type(first_result)}")
        print(f"First ProcessingResult attributes: {dir(first_result)}")
        if hasattr(first_result, '__dict__'):
            print(f"First ProcessingResult dict: {first_result.__dict__}")
    
    # Print the first final_tables element to understand its structure
    if results.get('final_tables'):
        first_final = results['final_tables'][0]
        print(f"\nFirst final_tables type: {type(first_final)}")
        if hasattr(first_final, '__dict__'):
            print(f"First final_tables dict: {first_final.__dict__}")
        elif isinstance(first_final, dict):
            print(f"First final_tables keys: {list(first_final.keys())}")
    
    # Print classifications structure
    if results.get('classifications'):
        print(f"\nClassifications type: {type(results['classifications'])}")
        if isinstance(results['classifications'], dict):
            print(f"Classifications keys: {list(results['classifications'].keys())}")
            # Print first few classifications
            for i, (key, value) in enumerate(list(results['classifications'].items())[:3]):
                print(f"  {key}: {value}")
    
    # Find regional summary tables
    regional_tables = []
    
    # Find regional summary tables by matching classifications with processed_results
    for table_name, classification in results['classifications'].items():
        if classification.category == 'regional_summary':
            # Find the corresponding ProcessingResult
            for proc_result in results['processed_results']:
                if proc_result.table_name == table_name:
                    regional_tables.append({
                        'table_name': table_name,
                        'classification': classification,
                        'processing_result': proc_result
                    })
                    break
    
    print(f"Found {len(regional_tables)} regional summary tables")
    
    # Debug each regional summary table
    for i, table_info in enumerate(regional_tables):
        print(f"\n{'='*60}")
        print(f"Regional Summary Table {i+1}: {table_info['table_name']}")
        print(f"{'='*60}")
        
        proc_result = table_info['processing_result']
        df = proc_result.processed_df
        
        print(f"Original shape: {df.shape}")
        print(f"Original columns: {df.columns.tolist()}")
        print(f"First few rows:")
        print(df.head())
        
        # Check if this is a long-format table
        if 'Metric' in df.columns and 'Value' in df.columns:
            print(f"\n🔍 This is a long-format table (Region, Metric, Value)")
            print(f"Unique metrics: {df['Metric'].unique()}")
            print(f"Sample metrics:")
            for metric in df['Metric'].unique()[:5]:
                print(f"  - '{metric}'")
            
            # Simulate the transformation
            print(f"\n🔄 Simulating transformation...")
            
            # Create metric mapping (simplified version)
            metric_mapping = {
                'Demand Met during Evening Peak hrs(MW)': 'Peak Demand Met (MW)',
                'Demand Met during Evening Peak hrs(MW) (at': 'Peak Demand Met (MW)',
                'Schedule(MU)': 'Schedule Drawal (MU)',
                'Central Sector': 'Central Sector (MW)',
                'Coal': 'Coal Generation (MW)',
                'Hydro': 'Hydro Generation (MW)',
                'Nuclear': 'Nuclear Generation (MW)',
                'Gas': 'Gas Generation (MW)',
                'Energy Met (MU)': 'Energy Met (MU)',
                'Energy Shortage (MU)': 'Energy Shortage (MU)',
                'Peak Shortage (MW)': 'Peak Shortage (MW)',
                'Maximum Demand Met During the Day (MW)': 'Max Demand SCADA (MW)',
                'Maximum Demand Met During the Day (MW)\r(From NLDC SCADA)': 'Max Demand SCADA (MW)',
                'Actual(MU)': 'Actual Drawal (MU)',
                'O/D/U/D(MU)': 'Over/Under Drawal (MU)',
                'State Sector': 'State Sector (MW)',
                'Total Generation (MW)': 'Total Generation (MW)',
                'Lignite': 'Lignite Generation (MW)',
                'Gas, Naptha & Diesel': 'Gas Generation (MW)',
                'RES (Wind, Solar, Biomass & Others)': 'RES Generation (MW)',
                'Solar Gen (MU)*': 'Solar Generation (MU)',
                'Wind Gen (MU)': 'Wind Generation (MU)'
            }
            
            # Transform the data
            transformed_data = {}
            
            for _, row in df.iterrows():
                region = row['Region']
                metric = row['Metric']
                value = row['Value']
                
                # Find matching database column
                db_column = None
                for metric_key, db_col in metric_mapping.items():
                    if metric_key in metric:
                        db_column = db_col
                        break
                
                if db_column:
                    if region not in transformed_data:
                        transformed_data[region] = {'Region': region}
                    transformed_data[region][db_column] = value
                    print(f"  Mapped '{metric}' -> '{db_column}' = {value}")
                else:
                    print(f"  ❌ No mapping found for metric: '{metric}'")
            
            # Convert to DataFrame
            if transformed_data:
                transformed_df = pd.DataFrame(list(transformed_data.values()))
                print(f"\n✅ Transformed DataFrame:")
                print(f"Shape: {transformed_df.shape}")
                print(f"Columns: {transformed_df.columns.tolist()}")
                print(transformed_df)
                
                # Check for non-zero values
                numeric_cols = [col for col in transformed_df.columns if col != 'Region']
                for col in numeric_cols:
                    if col in transformed_df.columns:
                        non_zero = (transformed_df[col] != 0).sum()
                        print(f"  {col}: {non_zero}/{len(transformed_df)} non-zero values")
            else:
                print("❌ No data transformed")
        else:
            print("This is not a long-format table")

if __name__ == "__main__":
    debug_regional_summary_transformation("Output/NLDC_PSP_URLS/2024-25/DECEMBER/reports/17.12.24_NLDC_PSP.pdf") 