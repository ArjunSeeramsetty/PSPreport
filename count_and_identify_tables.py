import sys
import pandas as pd
from pathlib import Path
from custom_pdf_parser import CustomPDFParser
from smart_table_classifier import SmartTableClassifier
from datetime import datetime
import re

def extract_date_from_path(pdf_path):
    """Extract date from PDF path"""
    filename = Path(pdf_path).name
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", filename)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = 2000 + int(match.group(3))
        return datetime(year, month, day)
    return None

def get_expected_tables(date):
    """Get expected number of tables based on date"""
    if date < datetime(2023, 5, 1):
        return 11  # Before Solar/Non-Solar Hour table
    elif date < datetime(2023, 7, 30):
        return 12  # After Solar/Non-Solar Hour table, before cross-border schedules
    elif date < datetime(2024, 11, 4):
        return 15  # After cross-border schedules, before blockwise (excluding garbage)
    else:
        return 16  # After blockwise table (excluding garbage, with merged blockwise)
        # Note: Some PDFs after Nov 2024 may be missing the blockwise table due to data quality issues

def analyze_pdf_tables(pdf_path, silent=False):
    """Analyze tables in a PDF and return classification results"""
    try:
        # Initialize parser and classifier
        parser = CustomPDFParser()
        classifier = SmartTableClassifier()
        
        # Get date and expected tables
        date = extract_date_from_path(pdf_path)
        expected_tables = get_expected_tables(date) if date else "Unknown"
        
        # Parse PDF (this now includes garbage filtering and blockwise merging)
        tables_data = parser.parse_pdf(pdf_path)
        
        if not tables_data:
            if not silent:
                print(f"No tables found in {pdf_path}")
            return {}
        
        # Classify tables
        classification_results = {}
        total_cleaned = 0
        total_identified = 0
        
        for page_num, page_tables in tables_data.items():
            if not silent:
                print(f"Page {page_num}: {len(page_tables)} tables extracted")
            
            page_cleaned_count = len(page_tables)
            total_cleaned += page_cleaned_count
            page_identified = 0
            
            for table_idx, table_df in enumerate(page_tables):
                table_name = f"page_{page_num}_table_{table_idx}"
                
                # Classify table
                classification = classifier.classify_table(table_df)
                
                # Access confidence as attribute
                if hasattr(classification, 'confidence') and classification.confidence > 0.3:
                    page_identified += 1
                    total_identified += 1
                    classification_results[table_name] = classification
                elif isinstance(classification, dict) and classification.get('confidence', 0) > 0.3:
                    page_identified += 1
                    total_identified += 1
                    classification_results[table_name] = classification
                
                if not silent:
                    print(f"  {table_name}: {table_df.shape[0]} rows, {table_df.shape[1]} cols")
                    if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                        first_row = ' '.join(str(cell) for cell in table_df.iloc[0].values[:3])
                        print(f"    First row preview: {first_row[:100]}...")
        
        # Display summary
        if not silent:
            print(f"\nExpected tables: {expected_tables}")
            print(f"Total cleaned tables: {total_cleaned}")
            print(f"Total tables identified: {total_identified}")
            print(f"Success rate: {total_identified/total_cleaned*100:.1f}%")
        else:
            # Silent mode - just print the counts for batch processing
            for page_num, page_tables in tables_data.items():
                print(f"Page {page_num}: {len(page_tables)} tables extracted")
            print(f"Expected tables: {expected_tables}")
            print(f"Total cleaned tables: {total_cleaned}")
            print(f"Total tables identified: {total_identified}")
        
        return classification_results
        
    except Exception as e:
        if not silent:
            print(f"Error analyzing {pdf_path}: {e}")
        else:
            print(f"Error: {e}")
        return {}

def main():
    if len(sys.argv) < 2:
        print("Usage: python count_and_identify_tables.py <pdf_path> [--silent]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    silent = "--silent" in sys.argv
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    analyze_pdf_tables(pdf_path, silent=silent)

if __name__ == "__main__":
    main() 