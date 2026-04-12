import os
import glob
import re
from datetime import datetime
from count_and_classify_tables import analyze_pdf_tables

# Directory containing PDFs
PDF_ROOT = 'Output/NLDC_PSP_URLS/'

# Regex to extract date from filename (e.g., 15.09.24_NLDC_PSP.pdf)
DATE_PATTERN = re.compile(r'(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP')

def extract_date_from_filename(filename):
    match = DATE_PATTERN.search(filename)
    if match:
        day, month, year = match.groups()
        # Assume year 20xx for 2-digit year
        year = int(year)
        year += 2000 if year < 50 else 1900
        try:
            return datetime(year, int(month), int(day))
        except Exception:
            return None
    return None

def find_all_pdfs(root):
    pdfs = glob.glob(os.path.join(root, '**', '*.pdf'), recursive=True)
    pdfs_with_dates = []
    for pdf in pdfs:
        date = extract_date_from_filename(os.path.basename(pdf))
        if date:
            pdfs_with_dates.append((pdf, date))
    # Sort from latest to oldest
    pdfs_with_dates.sort(key=lambda x: x[1], reverse=True)
    return [pdf for pdf, _ in pdfs_with_dates]

def main():
    pdfs = find_all_pdfs(PDF_ROOT)
    print(f"Found {len(pdfs)} PDF files to process.")
    print("Processing PDFs (showing only table counts)...")
    print("-" * 50)
    
    prev_table_count = None
    for idx, pdf_path in enumerate(pdfs):
        try:
            # Get just the filename for display
            filename = os.path.basename(pdf_path)
            
            # Run analysis but suppress detailed output
            result = analyze_pdf_tables(pdf_path, silent=True)
            identified_count = len(result['identified_tables'])
            missed_count = len(result['missed_tables'])
            
            # Show minimal output
            print(f"[{idx+1:3d}/{len(pdfs)}] {filename}: {identified_count} tables identified")
            
            # Check for issues and show detailed info only when problems occur
            if missed_count > 1:
                print(f"\n⚠️  ISSUE DETECTED: {filename}")
                print(f"   - Identified: {identified_count} tables")
                print(f"   - Missed: {missed_count} tables")
                print(f"   - This might indicate missing important tables like 15-minute blockwise data")
                print(f"   - Full path: {pdf_path}")
                input("Press Enter to continue to the next PDF...")
            elif prev_table_count is not None and identified_count != prev_table_count:
                print(f"\n⚠️  COUNT CHANGE: {filename}")
                print(f"   - Previous: {prev_table_count} tables")
                print(f"   - Current: {identified_count} tables")
                print(f"   - Full path: {pdf_path}")
                input("Press Enter to continue to the next PDF...")
            
            prev_table_count = identified_count
            
        except Exception as e:
            print(f"\n❌ EXCEPTION in {filename}:")
            print(f"   - Error: {str(e)}")
            print(f"   - Full path: {pdf_path}")
            input("Press Enter to continue to the next PDF...")
    
    print("\n" + "=" * 50)
    print("Batch processing completed!")

if __name__ == "__main__":
    main() 