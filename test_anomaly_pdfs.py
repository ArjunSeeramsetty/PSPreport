import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import re

def extract_pdf_paths_from_anomaly_file(anomaly_file):
    """Extract unique PDF paths from the anomaly file"""
    pdf_paths = set()
    
    with open(anomaly_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for line in lines[1:]:  # Skip header
            parts = line.strip().split('\t')
            if len(parts) >= 1:
                pdf_path = parts[0]
                if pdf_path and not pdf_path.startswith('PDF_Path'):
                    pdf_paths.add(pdf_path)
    
    return sorted(list(pdf_paths))

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
    if date < datetime(2023, 7, 30):
        return 12  # Before cross-border schedules (3 tables not available)
    elif date < datetime(2024, 11, 4):
        return 15  # After cross-border schedules, before blockwise (excluding garbage)
    else:
        return 16  # After blockwise table (excluding garbage, with merged blockwise)

def analyze_pdf(pdf_path):
    """Run the analyze script for a single PDF"""
    try:
        result = subprocess.run([
            sys.executable, "count_and_identify_tables.py", pdf_path, "--silent"
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            # Parse the output to extract counts
            lines = result.stdout.strip().split('\n')
            page_counts = []
            expected_tables = "Unknown"
            total_cleaned = 0
            total_identified = 0
            blockwise_merged = False
            
            for line in lines:
                if "Page" in line and "tables extracted" in line:
                    # Extract page number and count
                    parts = line.split(':')
                    if len(parts) >= 2:
                        page_info = parts[0].strip()
                        count_info = parts[1].strip()
                        if "tables extracted" in count_info:
                            count = int(count_info.split()[0])
                            page_counts.append(f"{page_info}: {count}")
                elif "Expected tables:" in line:
                    expected_tables = line.split(':')[1].strip()
                elif "Total cleaned tables:" in line:
                    total_cleaned = int(line.split(':')[1].strip())
                elif "Total tables identified:" in line:
                    total_identified = int(line.split(':')[1].strip())
                elif "Merged split blockwise tables" in line:
                    blockwise_merged = True
            
            # Display results
            print(f"\n{pdf_path}")
            for page_count in page_counts:
                print(f"  {page_count}")
            print(f"  Expected tables: {expected_tables}")
            print(f"  Total cleaned tables: {total_cleaned}")
            print(f"  Total identified: {total_identified}")
            if blockwise_merged:
                print(f"  *** BLOCKWISE TABLES MERGED ***")
            
            # Check for anomalies
            if expected_tables != "Unknown":
                expected = int(expected_tables)
                if total_cleaned != expected:
                    print(f"  *** ANOMALY: Expected {expected}, got {total_cleaned} ***")
                    if total_cleaned - total_identified > 1:
                        print(f"  *** MISSING TABLES: {total_cleaned - total_identified} tables not identified ***")
            
            return total_cleaned, total_identified, expected_tables, blockwise_merged
            
        else:
            print(f"Error processing {pdf_path}: {result.stderr}")
            return 0, 0, "Unknown", False
            
    except subprocess.TimeoutExpired:
        print(f"Timeout processing {pdf_path}")
        return 0, 0, "Unknown", False
    except Exception as e:
        print(f"Exception processing {pdf_path}: {e}")
        return 0, 0, "Unknown", False

def main():
    # Get PDF paths from anomaly file
    anomaly_file = "anomaly_pdfs.txt"
    if not os.path.exists(anomaly_file):
        print(f"Anomaly file {anomaly_file} not found!")
        return
    
    pdf_files = extract_pdf_paths_from_anomaly_file(anomaly_file)
    print(f"Found {len(pdf_files)} unique anomaly PDF files to test")
    
    # Create results file
    results_file = "anomaly_test_results.txt"
    with open(results_file, 'w', encoding='utf-8') as f:
        f.write("PDF_Path\tOriginal_Issue\tCleaned_Tables\tIdentified_Tables\tExpected_Tables\tBlockwise_Merged\tStatus\n")
    
    total_processed = 0
    total_fixed = 0
    total_still_anomalous = 0
    total_merged = 0
    
    for pdf_file in pdf_files:
        print(f"\n{'='*80}")
        print(f"Testing: {pdf_file}")
        
        cleaned_count, identified_count, expected_count, blockwise_merged = analyze_pdf(pdf_file)
        total_processed += 1
        
        if blockwise_merged:
            total_merged += 1
        
        # Determine status
        status = "UNKNOWN"
        if expected_count != "Unknown":
            expected = int(expected_count)
            if cleaned_count == expected and cleaned_count - identified_count <= 1:
                status = "FIXED"
                total_fixed += 1
            else:
                status = "STILL_ANOMALOUS"
                total_still_anomalous += 1
        
        # Save results
        with open(results_file, 'a', encoding='utf-8') as f:
            f.write(f"{pdf_file}\tANOMALY\t{cleaned_count}\t{identified_count}\t{expected_count}\t{blockwise_merged}\t{status}\n")
        
        print(f"Status: {status}")
        
        if total_processed % 5 == 0:
            print(f"\n--- Processed {total_processed} files ---")
    
    print(f"\n{'='*80}")
    print(f"=== ANOMALY TEST RESULTS ===")
    print(f"Total anomaly PDFs tested: {total_processed}")
    print(f"Fixed by enhanced logic: {total_fixed}")
    print(f"Still anomalous: {total_still_anomalous}")
    print(f"Blockwise tables merged: {total_merged}")
    print(f"Success rate: {total_fixed/total_processed*100:.1f}%")
    print(f"Results saved to: {results_file}")

if __name__ == "__main__":
    main() 