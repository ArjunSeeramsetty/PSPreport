#!/usr/bin/env python3
"""
Batch processing script to run Data_Insertion logic on all PDFs located at the base path.
Processes PDFs from all years, months, and dates in chronological order.
Saves failed run details to a text file and continues processing.
"""

import os
import glob
import logging
import pandas as pd
import traceback
from datetime import datetime
from pathlib import Path
from Data_Insertion import process_pdf_and_insert_data

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('batch_processing.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_all_pdf_paths(base_path):
    """
    Get all PDF paths from the base directory, sorted chronologically.
    
    Args:
        base_path: Base path to search for PDFs
        
    Returns:
        List of PDF file paths sorted by date
    """
    pdf_paths = []
    
    # Walk through all subdirectories
    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file.endswith('.pdf') and 'NLDC_PSP' in file:
                full_path = os.path.join(root, file)
                pdf_paths.append(full_path)
    
    # Sort PDFs by date (extract date from filename)
    def extract_date_from_filename(filepath):
        filename = os.path.basename(filepath)
        # Extract date from filename like "01.04.25_NLDC_PSP.pdf"
        try:
            date_part = filename.split('_')[0]  # "01.04.25"
            day, month, year = date_part.split('.')
            # Convert to datetime for sorting
            return datetime(2000 + int(year), int(month), int(day))
        except:
            # If date extraction fails, use file modification time
            return datetime.fromtimestamp(os.path.getmtime(filepath))
    
    pdf_paths.sort(key=extract_date_from_filename)
    
    return pdf_paths

def save_failed_run_details(failed_details, output_file):
    """
    Save failed run details to a text file.
    
    Args:
        failed_details: List of dictionaries containing failure information
        output_file: Path to the output text file
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("BATCH PROCESSING FAILED RUN DETAILS\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total failed PDFs: {len(failed_details)}\n\n")
            
            for i, detail in enumerate(failed_details, 1):
                f.write(f"FAILED PDF #{i}\n")
                f.write("-" * 30 + "\n")
                f.write(f"File: {detail['file_path']}\n")
                f.write(f"Filename: {detail['filename']}\n")
                f.write(f"Error: {detail['error']}\n")
                f.write(f"Timestamp: {detail['timestamp']}\n")
                f.write(f"Processing Time: {detail['processing_time']:.2f} seconds\n")
                f.write(f"Traceback:\n{detail['traceback']}\n")
                f.write("\n" + "=" * 50 + "\n\n")
        
        logger.info(f"Failed run details saved to: {output_file}")
        
    except Exception as e:
        logger.error(f"Error saving failed run details: {e}")

def process_pdfs_batch(base_path, start_date=None, end_date=None, max_pdfs=None):
    """
    Process all PDFs in the base path with optional filtering.
    Saves failed run details to a text file and continues processing.
    
    Args:
        base_path: Base path containing PDFs
        start_date: Optional start date filter (datetime object)
        end_date: Optional end date filter (datetime object)
        max_pdfs: Optional maximum number of PDFs to process
        
    Returns:
        Dictionary with processing statistics
    """
    logger.info(f"Starting batch processing from base path: {base_path}")
    
    # Get all PDF paths
    all_pdf_paths = get_all_pdf_paths(base_path)
    logger.info(f"Found {len(all_pdf_paths)} PDF files")
    
    # Filter by date if specified
    if start_date or end_date:
        filtered_paths = []
        for pdf_path in all_pdf_paths:
            filename = os.path.basename(pdf_path)
            try:
                date_part = filename.split('_')[0]
                day, month, year = date_part.split('.')
                pdf_date = datetime(2000 + int(year), int(month), int(day))
                
                if start_date and pdf_date < start_date:
                    continue
                if end_date and pdf_date > end_date:
                    continue
                    
                filtered_paths.append(pdf_path)
            except:
                # If date extraction fails, include the file
                filtered_paths.append(pdf_path)
        
        all_pdf_paths = filtered_paths
        logger.info(f"After date filtering: {len(all_pdf_paths)} PDF files")
    
    # Limit number of PDFs if specified
    if max_pdfs:
        all_pdf_paths = all_pdf_paths[:max_pdfs]
        logger.info(f"Limited to {len(all_pdf_paths)} PDF files")
    
    # Processing statistics
    stats = {
        'total_pdfs': len(all_pdf_paths),
        'successful': 0,
        'failed': 0,
        'errors': [],
        'processed_files': [],
        'failed_files': [],
        'failed_details': []  # Detailed failure information
    }
    
    # Process each PDF
    for i, pdf_path in enumerate(all_pdf_paths, 1):
        start_time = datetime.now()
        filename = os.path.basename(pdf_path)
        
        try:
            logger.info(f"Processing PDF {i}/{len(all_pdf_paths)}: {filename}")
            
            # Process the PDF using the insertion logic
            success = process_pdf_and_insert_data(pdf_path)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            if success:
                stats['successful'] += 1
                stats['processed_files'].append(pdf_path)
                logger.info(f"✅ Successfully processed: {filename} (took {processing_time:.2f}s)")
            else:
                stats['failed'] += 1
                stats['failed_files'].append(pdf_path)
                error_msg = f"PDF processing returned False"
                stats['errors'].append(f"{filename}: {error_msg}")
                
                # Save detailed failure information
                failed_detail = {
                    'file_path': pdf_path,
                    'filename': filename,
                    'error': error_msg,
                    'timestamp': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'processing_time': processing_time,
                    'traceback': 'No exception - process_pdf_and_insert_data returned False'
                }
                stats['failed_details'].append(failed_detail)
                
                logger.error(f"❌ Failed to process: {filename} (took {processing_time:.2f}s)")
                
        except Exception as e:
            processing_time = (datetime.now() - start_time).total_seconds()
            stats['failed'] += 1
            stats['failed_files'].append(pdf_path)
            error_msg = f"Exception: {str(e)}"
            stats['errors'].append(f"{filename}: {error_msg}")
            
            # Save detailed failure information
            failed_detail = {
                'file_path': pdf_path,
                'filename': filename,
                'error': error_msg,
                'timestamp': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                'processing_time': processing_time,
                'traceback': traceback.format_exc()
            }
            stats['failed_details'].append(failed_detail)
            
            logger.error(f"❌ Error processing {filename}: {str(e)} (took {processing_time:.2f}s)")
            logger.error(f"Traceback: {traceback.format_exc()}")
            continue  # Continue with next PDF
    
    # Save failed run details to text file
    if stats['failed_details']:
        failed_details_file = f"failed_pdfs.txt"
        save_failed_run_details(stats['failed_details'], failed_details_file)
        stats['failed_details_file'] = failed_details_file
    
    # Log final statistics
    logger.info("\n" + "="*60)
    logger.info("BATCH PROCESSING COMPLETED")
    logger.info("="*60)
    logger.info(f"Total PDFs: {stats['total_pdfs']}")
    logger.info(f"Successful: {stats['successful']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Success Rate: {(stats['successful']/stats['total_pdfs']*100):.1f}%")
    
    if stats['failed_files']:
        logger.info(f"\nFailed files ({len(stats['failed_files'])}):")
        for failed_file in stats['failed_files']:
            logger.info(f"  - {os.path.basename(failed_file)}")
    
    if stats['failed_details_file']:
        logger.info(f"\nDetailed failure information saved to: {stats['failed_details_file']}")
    
    return stats

def main():
    """Main function to run batch processing"""
    base_path = r"C:\Users\arjun\Desktop\PSPreport\Output\NLDC_PSP_URLS"
    
    # Check if base path exists
    if not os.path.exists(base_path):
        logger.error(f"Base path does not exist: {base_path}")
        return
    
    # Optional: Set date range for processing
    start_date = datetime(2023, 4, 1)  # Start from April 1, 2023
    end_date = datetime(2025, 7, 10)   # End at July 10, 2025
    
    # Optional: Limit number of PDFs for testing
    # max_pdfs = 10  # Process only first 10 PDFs
    
    # Process all PDFs
    stats = process_pdfs_batch(
        base_path=base_path,
        start_date=start_date,  # Uncomment to filter by start date
        end_date=end_date,      # Uncomment to filter by end date
        # max_pdfs=max_pdfs       # Uncomment to limit number of PDFs
    )
    
    # Save statistics to JSON file
    stats_file = f"batch_processing_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    import json
    with open(stats_file, 'w') as f:
        # Convert datetime objects to strings for JSON serialization
        json_stats = {
            'total_pdfs': stats['total_pdfs'],
            'successful': stats['successful'],
            'failed': stats['failed'],
            'success_rate': f"{(stats['successful']/stats['total_pdfs']*100):.1f}%",
            'processed_files': [os.path.basename(f) for f in stats['processed_files']],
            'failed_files': [os.path.basename(f) for f in stats['failed_files']],
            'errors': stats['errors'],
            'failed_details_file': stats.get('failed_details_file', None)
        }
        json.dump(json_stats, f, indent=2)
    
    logger.info(f"Statistics saved to: {stats_file}")
    logger.info("Batch processing completed!")

if __name__ == "__main__":
    main() 