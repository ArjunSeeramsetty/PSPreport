import sys
import pandas as pd
from pathlib import Path
from custom_pdf_parser import CustomPDFParser
from smart_table_classifier import SmartTableClassifier

def analyze_anomaly_pdf(pdf_path):
    """Analyze a specific anomaly PDF in detail"""
    print(f"=== Analyzing Anomaly PDF: {pdf_path} ===")
    
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
    identified_tables = []
    missed_tables = []
    
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
            
            print(f"  Table {table_idx}: {table_df.shape[0]} rows, {table_df.shape[1]} cols")
            print(f"    Type: {table_type} (confidence: {confidence:.3f})")
            
            if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                # Show first row content
                first_row = ' '.join(str(cell) for cell in table_df.iloc[0].values[:3])
                print(f"    First row: {first_row[:100]}...")
                
                # Show column headers if available
                if table_df.shape[0] > 1:
                    headers = ' | '.join(str(col) for col in table_df.columns[:5])
                    print(f"    Headers: {headers}")
            
            if confidence > 0.3:
                total_identified += 1
                identified_tables.append(f"{table_name}: {table_type}")
                print(f"    ✓ IDENTIFIED")
            else:
                missed_tables.append(f"{table_name}: {table_type} (conf: {confidence:.3f})")
                print(f"    ✗ MISSED")
    
    print(f"\n=== SUMMARY ===")
    print(f"Total raw tables: {total_raw}")
    print(f"Total identified: {total_identified}")
    print(f"Success rate: {total_identified/total_raw*100:.1f}%")
    
    print(f"\n=== IDENTIFIED TABLES ===")
    for table in identified_tables:
        print(f"  ✓ {table}")
    
    print(f"\n=== MISSED TABLES ===")
    for table in missed_tables:
        print(f"  ✗ {table}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_anomaly_pdf.py <pdf_path>")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    analyze_anomaly_pdf(pdf_path)

if __name__ == "__main__":
    main() 
import pandas as pd
from pathlib import Path
from custom_pdf_parser import CustomPDFParser
from smart_table_classifier import SmartTableClassifier

def analyze_anomaly_pdf(pdf_path):
    """Analyze a specific anomaly PDF in detail"""
    print(f"=== Analyzing Anomaly PDF: {pdf_path} ===")
    
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
    identified_tables = []
    missed_tables = []
    
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
            
            print(f"  Table {table_idx}: {table_df.shape[0]} rows, {table_df.shape[1]} cols")
            print(f"    Type: {table_type} (confidence: {confidence:.3f})")
            
            if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                # Show first row content
                first_row = ' '.join(str(cell) for cell in table_df.iloc[0].values[:3])
                print(f"    First row: {first_row[:100]}...")
                
                # Show column headers if available
                if table_df.shape[0] > 1:
                    headers = ' | '.join(str(col) for col in table_df.columns[:5])
                    print(f"    Headers: {headers}")
            
            if confidence > 0.3:
                total_identified += 1
                identified_tables.append(f"{table_name}: {table_type}")
                print(f"    ✓ IDENTIFIED")
            else:
                missed_tables.append(f"{table_name}: {table_type} (conf: {confidence:.3f})")
                print(f"    ✗ MISSED")
    
    print(f"\n=== SUMMARY ===")
    print(f"Total raw tables: {total_raw}")
    print(f"Total identified: {total_identified}")
    print(f"Success rate: {total_identified/total_raw*100:.1f}%")
    
    print(f"\n=== IDENTIFIED TABLES ===")
    for table in identified_tables:
        print(f"  ✓ {table}")
    
    print(f"\n=== MISSED TABLES ===")
    for table in missed_tables:
        print(f"  ✗ {table}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_anomaly_pdf.py <pdf_path>")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    analyze_anomaly_pdf(pdf_path)

if __name__ == "__main__":
    main() 