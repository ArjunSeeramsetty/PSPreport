import os
import sqlite3
import pandas as pd
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATABASE_NAME = 'power_data.db'
PDF_BASE_DIR = r'C:\Users\arjun\Desktop\PSPreport\Output\NLDC_PSP_URLS'

def extract_fy_start_year(fy_folder):
    """Extract the start year from FY folder name (e.g., 'FY 2024-25' -> 2024)"""
    try:
        return int(fy_folder.split()[1].split('-')[0])
    except (IndexError, ValueError):
        return 0

def get_all_pdf_paths():
    """Get all PDF paths from the directory structure, sorted from oldest to latest"""
    all_pdf_paths = []
    
    if not os.path.exists(PDF_BASE_DIR):
        logger.error(f"PDF base directory '{PDF_BASE_DIR}' does not exist")
        return all_pdf_paths
    
    # Define the order of months in a FY
    fy_months = ['APRIL', 'MAY', 'JUNE', 'JULY', 'AUGUST', 'SEPTEMBER', 
                 'OCTOBER', 'NOVEMBER', 'DECEMBER', 'JANUARY', 'FEBRUARY', 'MARCH']
    
    # Sort FYs from oldest to latest by year
    for fy in sorted(os.listdir(PDF_BASE_DIR), key=extract_fy_start_year):
        fy_path = os.path.join(PDF_BASE_DIR, fy)
        if not os.path.isdir(fy_path):
            continue
        
        # Iterate months in FY order (oldest to latest)
        for month in reversed(fy_months):
            month_path = os.path.join(fy_path, month)
            if not os.path.isdir(month_path):
                continue
            
            reports_dir = os.path.join(month_path, "reports")
            if not os.path.isdir(reports_dir):
                continue
            
            pdfs = [f for f in os.listdir(reports_dir) if f.endswith('.pdf')]
            pdfs_sorted = sorted(pdfs)  # Sort by name (oldest to latest)
            
            for pdf in pdfs_sorted:
                pdf_path = os.path.join(reports_dir, pdf)
                all_pdf_paths.append(pdf_path)
    
    return all_pdf_paths

def extract_date_from_pdf_path(pdf_path):
    """Extract date from PDF filename (e.g., '18.04.25_NLDC_PSP.pdf' -> '04/18/2025')"""
    try:
        filename = os.path.basename(pdf_path)
        # Extract date part (e.g., '18.04.25')
        date_part = filename.split('_')[0]
        day, month, year = date_part.split('.')
        # Convert 2-digit year to 4-digit
        year = '20' + year if len(year) == 2 else year
        return f"{int(month):02d}/{int(day):02d}/{year}"
    except Exception as e:
        logger.error(f"Error extracting date from {pdf_path}: {e}")
        return None

def convert_db_date_format(db_date_str):
    """Convert database date from YYYY-MM-DD to MM/DD/YYYY format"""
    try:
        if pd.isna(db_date_str) or db_date_str is None:
            return None
        # Parse the database date (YYYY-MM-DD)
        date_obj = datetime.strptime(str(db_date_str), '%Y-%m-%d')
        # Convert to MM/DD/YYYY format
        return date_obj.strftime('%m/%d/%Y')
    except Exception as e:
        logger.error(f"Error converting date format {db_date_str}: {e}")
        return None

def get_database_dates():
    """Get all dates from DimDates table"""
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        query = "SELECT DateID, ActualDate FROM DimDates ORDER BY ActualDate"
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    except Exception as e:
        logger.error(f"Error reading from database: {e}")
        return pd.DataFrame()

def show_missing_dates():
    """Display only the missing dates in database"""
    logger.info("=== MISSING DATES ANALYSIS ===")
    
    # Get all PDF paths
    all_pdf_paths = get_all_pdf_paths()
    logger.info(f"Total PDF files found: {len(all_pdf_paths)}")
    
    if not all_pdf_paths:
        logger.error("No PDF files found.")
        return
    
    # Extract dates from PDF paths
    pdf_dates = []
    for pdf_path in all_pdf_paths:
        date_str = extract_date_from_pdf_path(pdf_path)
        if date_str:
            pdf_dates.append({
                'pdf_path': pdf_path,
                'date_str': date_str,
                'report_name': os.path.basename(pdf_path)
            })
    
    # Get database dates
    db_dates_df = get_database_dates()
    logger.info(f"Total dates in DimDates: {len(db_dates_df)}")
    
    # Convert database dates to MM/DD/YYYY format for comparison
    db_dates_df['Date_MMDDYYYY'] = db_dates_df['ActualDate'].apply(convert_db_date_format)
    
    # Create a set of dates from PDFs for easy comparison
    pdf_date_set = {item['date_str'] for item in pdf_dates}
    db_date_set = set(db_dates_df['Date_MMDDYYYY'].dropna().tolist())
    
    # Find missing dates
    missing_dates = pdf_date_set - db_date_set
    
    logger.info(f"\n=== MISSING DATES: {len(missing_dates)} ===")
    
    if missing_dates:
        logger.warning("The following dates from PDF files are missing in the DimDates table:")
        logger.warning("Format: Date (MM/DD/YYYY) - PDF Filename")
        logger.warning("-" * 60)
        
        # Sort missing dates chronologically
        missing_dates_sorted = sorted(missing_dates, key=lambda x: datetime.strptime(x, '%m/%d/%Y'))
        
        for date in missing_dates_sorted:
            # Find corresponding PDF
            pdf_info = next((item for item in pdf_dates if item['date_str'] == date), None)
            if pdf_info:
                logger.warning(f"{date} - {pdf_info['report_name']}")
        
        logger.warning("-" * 60)
        logger.warning(f"Total missing dates: {len(missing_dates)}")
        
        # Summary by year
        logger.info("\n=== MISSING DATES BY YEAR ===")
        missing_by_year = {}
        for date in missing_dates_sorted:
            year = date.split('/')[-1]
            if year not in missing_by_year:
                missing_by_year[year] = 0
            missing_by_year[year] += 1
        
        for year in sorted(missing_by_year.keys()):
            logger.info(f"{year}: {missing_by_year[year]} missing dates")
            
    else:
        logger.info("✓ No missing dates found! All PDF dates are present in DimDates table.")

if __name__ == "__main__":
    show_missing_dates() 