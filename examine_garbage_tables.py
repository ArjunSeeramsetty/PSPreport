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
    """Get expected number of raw tables based on date"""
    if date < datetime(2023, 7, 30):
        return 13  # Before cross-border schedules
    elif date < datetime(2024, 11, 4):
        return 16  # After cross-border schedules, before blockwise
    else:
        return 17  # After blockwise table

def examine_pdf_tables(pdf_path):
    """Examine tables in a PDF and identify garbage tables"""
    print(f"\n{'='*80}")
    print(f"EXAMINING: {pdf_path}")
    print(f"{'='*80}")
    
    # Get date and expected tables
    date = extract_date_from_path(pdf_path)
    expected_tables = get_expected_tables(date) if date else "Unknown"
    print(f"Date: {date.strftime('%Y-%m-%d') if date else 'Unknown'}")
    print(f"Expected tables: {expected_tables}")
    
    # Initialize parser and classifier
    parser = CustomPDFParser()
    classifier = SmartTableClassifier()
    
    # Parse PDF
    tables_data = parser.parse_pdf(pdf_path)
    
    if not tables_data:
        print("No tables found!")
        return
    
    print(f"\nTotal pages with tables: {len(tables_data)}")
    
    total_raw = 0
    total_identified = 0
    garbage_tables = []
    identified_tables = []
    
    for page_num, page_tables in tables_data.items():
        print(f"\n--- Page {page_num}: {len(page_tables)} tables ---")
        total_raw += len(page_tables)
        
        for table_idx, table_df in enumerate(page_tables):
            table_name = f"page_{page_num}_table_{table_idx}"
            
            # Classify table
            classification = classifier.classify_table(table_df)
            
            # Get confidence score
            if hasattr(classification, 'confidence'):
                confidence = classification.confidence
                table_type = classification.table_type if hasattr(classification, 'table_type') else 'Unknown'
            elif isinstance(classification, dict):
                confidence = classification.get('confidence', 0)
                table_type = classification.get('table_type', 'Unknown')
            else:
                confidence = 0
                table_type = 'Unknown'
            
            print(f"\n  Table {table_idx}: {table_df.shape[0]} rows, {table_df.shape[1]} cols")
            print(f"    Type: {table_type} (confidence: {confidence:.3f})")
            
            # Check if it's garbage
            is_garbage = False
            garbage_reason = ""
            
            # Check for empty tables
            if table_df.empty or (table_df.shape[0] == 0 and table_df.shape[1] == 0):
                is_garbage = True
                garbage_reason = "Empty table"
            
            # Check for tables with only NaN values
            elif table_df.isna().all().all():
                is_garbage = True
                garbage_reason = "All NaN values"
            
            # Check for Hindi text tables (first table on first page)
            elif page_num == 1 and table_idx == 0:
                if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                    first_cell = str(table_df.iloc[0, 0]) if not table_df.empty else ""
                    if any(hindi_char in first_cell for hindi_char in ['ा', 'ी', 'ु', 'ू', 'े', 'ै', 'ो', 'ौ', 'ं', 'ँ', '्']):
                        is_garbage = True
                        garbage_reason = "Hindi text table"
            
            # Check for very small tables with no meaningful data
            elif table_df.shape[0] <= 1 and table_df.shape[1] <= 2:
                if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                    content = ' '.join(str(cell) for cell in table_df.iloc[0].values)
                    if len(content.strip()) < 20:  # Very short content
                        is_garbage = True
                        garbage_reason = "Very small table with minimal content"
            
            # Show table content
            if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                print(f"    First row content: {str(table_df.iloc[0].values)[:200]}...")
                
                if table_df.shape[0] > 1:
                    print(f"    Second row content: {str(table_df.iloc[1].values)[:200]}...")
                
                # Show column headers
                headers = ' | '.join(str(col) for col in table_df.columns[:5])
                print(f"    Headers: {headers}")
            
            # Categorize table
            if is_garbage:
                garbage_tables.append(f"{table_name}: {garbage_reason}")
                print(f"    🗑️  GARBAGE: {garbage_reason}")
            elif confidence > 0.3:
                total_identified += 1
                identified_tables.append(f"{table_name}: {table_type}")
                print(f"    ✓ IDENTIFIED")
            else:
                print(f"    ✗ MISSED (low confidence)")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY FOR {pdf_path}")
    print(f"{'='*80}")
    print(f"Total raw tables: {total_raw}")
    print(f"Expected tables: {expected_tables}")
    print(f"Total identified: {total_identified}")
    print(f"Garbage tables: {len(garbage_tables)}")
    print(f"Success rate: {total_identified/(total_raw-len(garbage_tables))*100:.1f}% (excluding garbage)")
    
    if garbage_tables:
        print(f"\n🗑️  GARBAGE TABLES:")
        for garbage in garbage_tables:
            print(f"  - {garbage}")
    
    print(f"\n✓ IDENTIFIED TABLES:")
    for table in identified_tables:
        print(f"  - {table}")
    
    return {
        'total_raw': total_raw,
        'expected': expected_tables,
        'identified': total_identified,
        'garbage': len(garbage_tables),
        'garbage_tables': garbage_tables
    }

def main():
    # Define example PDFs for each scenario
    test_pdfs = [
        # Before cross-border schedules (expected: 13)
        "Output/NLDC_PSP_URLS/2023-24/JULY/reports/29.07.23_NLDC_PSP.pdf",
        
        # After cross-border, before blockwise (expected: 16) 
        "Output/NLDC_PSP_URLS/2024-25/OCTOBER/reports/22.10.24_NLDC_PSP.pdf",
        
        # After blockwise table (expected: 17)
        "Output/NLDC_PSP_URLS/2025-26/APRIL/reports/20.04.25_NLDC_PSP.pdf"
    ]
    
    results = []
    
    for pdf_path in test_pdfs:
        if Path(pdf_path).exists():
            result = examine_pdf_tables(pdf_path)
            results.append((pdf_path, result))
        else:
            print(f"\nPDF not found: {pdf_path}")
    
    # Summary across all PDFs
    print(f"\n{'='*80}")
    print(f"OVERALL SUMMARY")
    print(f"{'='*80}")
    
    for pdf_path, result in results:
        print(f"\n{pdf_path}:")
        print(f"  Raw: {result['total_raw']}, Expected: {result['expected']}, Identified: {result['identified']}, Garbage: {result['garbage']}")
        if result['garbage'] > 0:
            print(f"  Adjusted success rate: {result['identified']/(result['total_raw']-result['garbage'])*100:.1f}%")

if __name__ == "__main__":
    main() 
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
    """Get expected number of raw tables based on date"""
    if date < datetime(2023, 7, 30):
        return 13  # Before cross-border schedules
    elif date < datetime(2024, 11, 4):
        return 16  # After cross-border schedules, before blockwise
    else:
        return 17  # After blockwise table

def examine_pdf_tables(pdf_path):
    """Examine tables in a PDF and identify garbage tables"""
    print(f"\n{'='*80}")
    print(f"EXAMINING: {pdf_path}")
    print(f"{'='*80}")
    
    # Get date and expected tables
    date = extract_date_from_path(pdf_path)
    expected_tables = get_expected_tables(date) if date else "Unknown"
    print(f"Date: {date.strftime('%Y-%m-%d') if date else 'Unknown'}")
    print(f"Expected tables: {expected_tables}")
    
    # Initialize parser and classifier
    parser = CustomPDFParser()
    classifier = SmartTableClassifier()
    
    # Parse PDF
    tables_data = parser.parse_pdf(pdf_path)
    
    if not tables_data:
        print("No tables found!")
        return
    
    print(f"\nTotal pages with tables: {len(tables_data)}")
    
    total_raw = 0
    total_identified = 0
    garbage_tables = []
    identified_tables = []
    
    for page_num, page_tables in tables_data.items():
        print(f"\n--- Page {page_num}: {len(page_tables)} tables ---")
        total_raw += len(page_tables)
        
        for table_idx, table_df in enumerate(page_tables):
            table_name = f"page_{page_num}_table_{table_idx}"
            
            # Classify table
            classification = classifier.classify_table(table_df)
            
            # Get confidence score
            if hasattr(classification, 'confidence'):
                confidence = classification.confidence
                table_type = classification.table_type if hasattr(classification, 'table_type') else 'Unknown'
            elif isinstance(classification, dict):
                confidence = classification.get('confidence', 0)
                table_type = classification.get('table_type', 'Unknown')
            else:
                confidence = 0
                table_type = 'Unknown'
            
            print(f"\n  Table {table_idx}: {table_df.shape[0]} rows, {table_df.shape[1]} cols")
            print(f"    Type: {table_type} (confidence: {confidence:.3f})")
            
            # Check if it's garbage
            is_garbage = False
            garbage_reason = ""
            
            # Check for empty tables
            if table_df.empty or (table_df.shape[0] == 0 and table_df.shape[1] == 0):
                is_garbage = True
                garbage_reason = "Empty table"
            
            # Check for tables with only NaN values
            elif table_df.isna().all().all():
                is_garbage = True
                garbage_reason = "All NaN values"
            
            # Check for Hindi text tables (first table on first page)
            elif page_num == 1 and table_idx == 0:
                if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                    first_cell = str(table_df.iloc[0, 0]) if not table_df.empty else ""
                    if any(hindi_char in first_cell for hindi_char in ['ा', 'ी', 'ु', 'ू', 'े', 'ै', 'ो', 'ौ', 'ं', 'ँ', '्']):
                        is_garbage = True
                        garbage_reason = "Hindi text table"
            
            # Check for very small tables with no meaningful data
            elif table_df.shape[0] <= 1 and table_df.shape[1] <= 2:
                if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                    content = ' '.join(str(cell) for cell in table_df.iloc[0].values)
                    if len(content.strip()) < 20:  # Very short content
                        is_garbage = True
                        garbage_reason = "Very small table with minimal content"
            
            # Show table content
            if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                print(f"    First row content: {str(table_df.iloc[0].values)[:200]}...")
                
                if table_df.shape[0] > 1:
                    print(f"    Second row content: {str(table_df.iloc[1].values)[:200]}...")
                
                # Show column headers
                headers = ' | '.join(str(col) for col in table_df.columns[:5])
                print(f"    Headers: {headers}")
            
            # Categorize table
            if is_garbage:
                garbage_tables.append(f"{table_name}: {garbage_reason}")
                print(f"    🗑️  GARBAGE: {garbage_reason}")
            elif confidence > 0.3:
                total_identified += 1
                identified_tables.append(f"{table_name}: {table_type}")
                print(f"    ✓ IDENTIFIED")
            else:
                print(f"    ✗ MISSED (low confidence)")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY FOR {pdf_path}")
    print(f"{'='*80}")
    print(f"Total raw tables: {total_raw}")
    print(f"Expected tables: {expected_tables}")
    print(f"Total identified: {total_identified}")
    print(f"Garbage tables: {len(garbage_tables)}")
    print(f"Success rate: {total_identified/(total_raw-len(garbage_tables))*100:.1f}% (excluding garbage)")
    
    if garbage_tables:
        print(f"\n🗑️  GARBAGE TABLES:")
        for garbage in garbage_tables:
            print(f"  - {garbage}")
    
    print(f"\n✓ IDENTIFIED TABLES:")
    for table in identified_tables:
        print(f"  - {table}")
    
    return {
        'total_raw': total_raw,
        'expected': expected_tables,
        'identified': total_identified,
        'garbage': len(garbage_tables),
        'garbage_tables': garbage_tables
    }

def main():
    # Define example PDFs for each scenario
    test_pdfs = [
        # Before cross-border schedules (expected: 13)
        "Output/NLDC_PSP_URLS/2023-24/JULY/reports/29.07.23_NLDC_PSP.pdf",
        
        # After cross-border, before blockwise (expected: 16) 
        "Output/NLDC_PSP_URLS/2024-25/OCTOBER/reports/22.10.24_NLDC_PSP.pdf",
        
        # After blockwise table (expected: 17)
        "Output/NLDC_PSP_URLS/2025-26/APRIL/reports/20.04.25_NLDC_PSP.pdf"
    ]
    
    results = []
    
    for pdf_path in test_pdfs:
        if Path(pdf_path).exists():
            result = examine_pdf_tables(pdf_path)
            results.append((pdf_path, result))
        else:
            print(f"\nPDF not found: {pdf_path}")
    
    # Summary across all PDFs
    print(f"\n{'='*80}")
    print(f"OVERALL SUMMARY")
    print(f"{'='*80}")
    
    for pdf_path, result in results:
        print(f"\n{pdf_path}:")
        print(f"  Raw: {result['total_raw']}, Expected: {result['expected']}, Identified: {result['identified']}, Garbage: {result['garbage']}")
        if result['garbage'] > 0:
            print(f"  Adjusted success rate: {result['identified']/(result['total_raw']-result['garbage'])*100:.1f}%")

if __name__ == "__main__":
    main() 