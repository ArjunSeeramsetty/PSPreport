import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import re

def get_pdf_files():
    """Get all PDF files from latest to oldest"""
    pdf_dir = Path("Output/NLDC_PSP_URLS")
    pdf_files = []
    
    for year_dir in sorted(pdf_dir.glob("*"), reverse=True):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.glob("*"), reverse=True):
            if not month_dir.is_dir():
                continue
            reports_dir = month_dir / "reports"
            if reports_dir.exists():
                for pdf_file in sorted(reports_dir.glob("*.pdf"), reverse=True):
                    pdf_files.append(str(pdf_file))
    
    return pdf_files

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
            
            # Display results
            print(f"\n{pdf_path}")
            for page_count in page_counts:
                print(f"  {page_count}")
            print(f"  Expected tables: {expected_tables}")
            print(f"  Total cleaned tables: {total_cleaned}")
            print(f"  Total identified: {total_identified}")
            
            # Check for anomalies
            if expected_tables != "Unknown":
                expected = int(expected_tables)
                if total_cleaned != expected:
                    print(f"  *** ANOMALY: Expected {expected}, got {total_cleaned} ***")
                    if total_cleaned - total_identified > 1:
                        print(f"  *** MISSING TABLES: {total_cleaned - total_identified} tables not identified ***")
            
            return total_cleaned, total_identified, expected_tables
            
        else:
            print(f"Error processing {pdf_path}: {result.stderr}")
            return 0, 0, "Unknown"
            
    except subprocess.TimeoutExpired:
        print(f"Timeout processing {pdf_path}")
        return 0, 0, "Unknown"
    except Exception as e:
        print(f"Exception processing {pdf_path}: {e}")
        return 0, 0, "Unknown"

def save_to_file(pdf_path, reason, cleaned_count, identified_count, expected_count, output_file):
    """Save PDF path to file with reason and counts"""
    with open(output_file, 'a', encoding='utf-8') as f:
        f.write(f"{pdf_path}\t{reason}\t{cleaned_count}\t{identified_count}\t{expected_count}\n")

def main():
    pdf_files = get_pdf_files()
    print(f"Found {len(pdf_files)} PDF files to analyze")
    
    # Create output file with header
    output_file = "anomaly_pdfs_corrected.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("PDF_Path\tReason\tCleaned_Tables\tIdentified_Tables\tExpected_Tables\n")
    
    total_processed = 0
    total_cleaned_all = 0
    total_identified_all = 0
    previous_identified_count = None
    
    for pdf_file in pdf_files:
        cleaned_count, identified_count, expected_count = analyze_pdf(pdf_file)
        total_processed += 1
        total_cleaned_all += cleaned_count
        total_identified_all += identified_count
        
        # Check for anomalies and save to file
        if expected_count != "Unknown":
            expected = int(expected_count)
            if cleaned_count != expected:
                save_to_file(pdf_file, "COUNT_MISMATCH", cleaned_count, identified_count, expected_count, output_file)
                print(f"  *** SAVED: Count mismatch (expected {expected}, got {cleaned_count}) ***")
        
        if cleaned_count - identified_count > 1:
            save_to_file(pdf_file, "MISSING_TABLES", cleaned_count, identified_count, expected_count, output_file)
            print(f"  *** SAVED: {cleaned_count - identified_count} tables missed ***")
        
        if previous_identified_count is not None and identified_count != previous_identified_count:
            save_to_file(pdf_file, "COUNT_CHANGE", cleaned_count, identified_count, expected_count, output_file)
            print(f"  *** SAVED: Table count changed from {previous_identified_count} to {identified_count} ***")
        
        previous_identified_count = identified_count
        
        if total_processed % 10 == 0:
            print(f"\n--- Processed {total_processed} files ---")
    
    print(f"\n=== FINAL SUMMARY ===")
    print(f"Total PDFs processed: {total_processed}")
    print(f"Total cleaned tables: {total_cleaned_all}")
    print(f"Total identified tables: {total_identified_all}")
    print(f"Overall success rate: {total_identified_all/total_cleaned_all*100:.1f}%")
    print(f"Corrected anomaly PDFs saved to: {output_file}")

if __name__ == "__main__":
    main() 