#!/usr/bin/env python3
"""
PDF Processing Orchestrator
Processes PDFs in chronological order with error handling and database commit points.
Stops and commits database when expected table counts don't match or insertion fails.
"""

import os
import logging
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import glob
import re
import shutil

from modular_psp_parser import PSPReportParser
from modular_db_insertion import ModularDBInserter
from orchestrator_config import (
    EXPECTED_TABLE_COUNTS, 
    DATABASE_CONFIG, 
    PROCESSING_CONFIG, 
    LOGGING_CONFIG, 
    VALIDATION_CONFIG
)

# Set up logging
logging.basicConfig(
    level=getattr(logging, LOGGING_CONFIG['level']),
    format=LOGGING_CONFIG['format'],
    handlers=[
        logging.FileHandler(LOGGING_CONFIG['file']),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PDFOrchestrator:
    """Orchestrates PDF processing in chronological order with error handling"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_CONFIG['path']
        self.parser = PSPReportParser()
        self.inserter = ModularDBInserter(self.db_path)
        self.processed_files = []
        self.failed_files = []
        self.expected_table_counts = EXPECTED_TABLE_COUNTS.copy()
        
    def backup_database(self) -> bool:
        """Create a backup of the database before processing"""
        try:
            if not os.path.exists(self.db_path):
                logger.warning("Database file does not exist, skipping backup")
                return True
            
            # Create backup directory if it doesn't exist
            backup_dir = DATABASE_CONFIG['backup_dir']
            os.makedirs(backup_dir, exist_ok=True)
            
            # Create backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"power_data_backup_{timestamp}.db"
            backup_path = os.path.join(backup_dir, backup_filename)
            
            # Copy database file
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"Database backed up to: {backup_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to backup database: {e}")
            return False
        
    def connect_database(self) -> bool:
        """Connect to database"""
        return self.inserter.connect()
    
    def extract_date_from_filename(self, filename: str) -> Optional[date]:
        """Extract date from PDF filename"""
        try:
            # Remove file extension
            name = os.path.splitext(filename)[0]
            
            # Try different date patterns from config
            for pattern in PROCESSING_CONFIG['date_patterns']:
                match = re.search(pattern, name)
                if match:
                    groups = match.groups()
                    if len(groups[2]) == 2:  # YY format
                        year = 2000 + int(groups[2])
                    else:  # YYYY format
                        year = int(groups[2])
                    
                    month = int(groups[1])
                    day = int(groups[0])
                    
                    return date(year, month, day)
            
            logger.warning(f"Could not extract date from filename: {filename}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting date from {filename}: {e}")
            return None
    
    def find_pdf_files(self, base_dir: str = None) -> List[Tuple[date, str]]:
        """Find all PDF files and sort them by date"""
        base_dir = base_dir or PROCESSING_CONFIG['base_dir']
        pdf_files = []
        
        # Search for PDF files
        if PROCESSING_CONFIG['recursive_search']:
            search_pattern = os.path.join(base_dir, "**/*.pdf")
        else:
            search_pattern = os.path.join(base_dir, "*.pdf")
        
        for pdf_path in glob.glob(search_pattern, recursive=PROCESSING_CONFIG['recursive_search']):
            filename = os.path.basename(pdf_path)
            file_date = self.extract_date_from_filename(filename)
            
            if file_date:
                pdf_files.append((file_date, pdf_path))
            else:
                logger.warning(f"Skipping file with unparseable date: {filename}")
        
        # Sort by date (oldest first)
        pdf_files.sort(key=lambda x: x[0])
        
        logger.info(f"Found {len(pdf_files)} PDF files to process")
        for file_date, file_path in pdf_files:
            logger.info(f"  {file_date}: {os.path.basename(file_path)}")
        
        return pdf_files
    
    def validate_table_count(self, results: Dict, pdf_path: str) -> bool:
        """Validate that expected number of tables were extracted"""
        if not results['success']:
            logger.error(f"Parser failed for {pdf_path}")
            return False
        
        extracted_tables = results['final_tables']
        table_counts = {}
        
        # Count tables by type
        for table in extracted_tables:
            table_name = table['Table Name'].iloc[0] if 'Table Name' in table.columns else "Unknown"
            table_counts[table_name] = table_counts.get(table_name, 0) + 1
        
        # Check against expected counts
        missing_tables = []
        extra_tables = []
        
        for expected_table, expected_count in self.expected_table_counts.items():
            if expected_count == 0:  # Skip optional tables
                continue
                
            actual_count = table_counts.get(expected_table, 0)
            if actual_count < expected_count:
                missing_tables.append(f"{expected_table} (expected {expected_count}, got {actual_count})")
            elif actual_count > expected_count and VALIDATION_CONFIG['warn_on_extra_tables']:
                extra_tables.append(f"{expected_table} (expected {expected_count}, got {actual_count})")
        
        # Check required tables
        if VALIDATION_CONFIG['strict_mode']:
            for required_table in VALIDATION_CONFIG['required_tables']:
                if table_counts.get(required_table, 0) == 0:
                    missing_tables.append(f"{required_table} (required but missing)")
        
        # Log validation results
        logger.info(f"Table validation for {os.path.basename(pdf_path)}:")
        logger.info(f"  Extracted {len(extracted_tables)} total tables")
        logger.info(f"  Table counts: {table_counts}")
        
        if missing_tables:
            logger.error(f"  Missing tables: {missing_tables}")
        if extra_tables:
            logger.warning(f"  Extra tables: {extra_tables}")
        
        # Return True if no missing tables (extra tables are OK if allowed)
        return len(missing_tables) == 0
    
    def process_single_pdf(self, pdf_path: str, file_date: date) -> bool:
        """Process a single PDF file"""
        logger.info(f"Processing {os.path.basename(pdf_path)} (Date: {file_date})")
        
        try:
            # Parse PDF
            logger.info(f"Parsing PDF: {pdf_path}")
            results = self.parser.parse_pdf(pdf_path)
            
            # Validate table count
            if not self.validate_table_count(results, pdf_path):
                logger.error(f"Table validation failed for {pdf_path}")
                return False
            
            # Insert into database
            logger.info(f"Inserting data into database for {pdf_path}")
            success = self.inserter.process_parser_results(results)
            
            if not success:
                logger.error(f"Database insertion failed for {pdf_path}")
                return False
            
            logger.info(f"Successfully processed {pdf_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing {pdf_path}: {e}")
            return False
    
    def commit_database(self):
        """Commit current database state"""
        try:
            if self.inserter.conn:
                self.inserter.conn.commit()
                logger.info("Database committed successfully")
        except Exception as e:
            logger.error(f"Error committing database: {e}")
    
    def rollback_database(self):
        """Rollback current database state"""
        try:
            if self.inserter.conn:
                self.inserter.conn.rollback()
                logger.info("Database rolled back")
        except Exception as e:
            logger.error(f"Error rolling back database: {e}")
    
    def process_pdfs_chronologically(self, base_dir: str = None) -> Dict:
        """Process all PDFs in chronological order with error handling"""
        logger.info("Starting chronological PDF processing")
        
        # Create database backup if configured
        if DATABASE_CONFIG['backup_on_failure']:
            self.backup_database()
        
        # Find and sort PDF files
        pdf_files = self.find_pdf_files(base_dir)
        
        if not pdf_files:
            logger.error("No PDF files found to process")
            return {
                'success': False,
                'processed_count': 0,
                'failed_count': 0,
                'last_successful_date': None,
                'processed_files': [],
                'failed_files': []
            }
        
        # Connect to database
        if not self.connect_database():
            logger.error("Failed to connect to database")
            return {
                'success': False,
                'processed_count': 0,
                'failed_count': 0,
                'last_successful_date': None,
                'processed_files': [],
                'failed_files': []
            }
        
        processed_count = 0
        failed_count = 0
        last_successful_date = None
        
        try:
            for file_date, pdf_path in pdf_files:
                logger.info(f"\n{'='*60}")
                logger.info(f"Processing file {processed_count + failed_count + 1}/{len(pdf_files)}")
                logger.info(f"Date: {file_date}, File: {os.path.basename(pdf_path)}")
                logger.info(f"{'='*60}")
                
                # Process the PDF
                success = self.process_single_pdf(pdf_path, file_date)
                
                if success:
                    # Commit after each successful processing if configured
                    if PROCESSING_CONFIG['commit_after_each_file']:
                        self.commit_database()
                    processed_count += 1
                    last_successful_date = file_date
                    self.processed_files.append({
                        'date': file_date,
                        'path': pdf_path,
                        'filename': os.path.basename(pdf_path)
                    })
                    logger.info(f"✓ Successfully processed {os.path.basename(pdf_path)}")
                else:
                    # Rollback and stop processing if configured
                    if PROCESSING_CONFIG['stop_on_failure']:
                        self.rollback_database()
                        failed_count += 1
                        self.failed_files.append({
                            'date': file_date,
                            'path': pdf_path,
                            'filename': os.path.basename(pdf_path),
                            'error': 'Processing failed'
                        })
                        logger.error(f"✗ Failed to process {os.path.basename(pdf_path)}")
                        logger.error("Stopping processing due to failure")
                        break
                    else:
                        # Continue processing even on failure
                        failed_count += 1
                        self.failed_files.append({
                            'date': file_date,
                            'path': pdf_path,
                            'filename': os.path.basename(pdf_path),
                            'error': 'Processing failed'
                        })
                        logger.error(f"✗ Failed to process {os.path.basename(pdf_path)} but continuing...")
        
        except KeyboardInterrupt:
            logger.info("Processing interrupted by user")
            self.commit_database()
        except Exception as e:
            logger.error(f"Unexpected error during processing: {e}")
            self.rollback_database()
        finally:
            # Close database connection
            self.inserter.close()
        
        # Generate summary
        summary = {
            'success': failed_count == 0,
            'processed_count': processed_count,
            'failed_count': failed_count,
            'total_files': len(pdf_files),
            'last_successful_date': last_successful_date,
            'processed_files': self.processed_files,
            'failed_files': self.failed_files
        }
        
        self._log_summary(summary)
        return summary
    
    def _log_summary(self, summary: Dict):
        """Log processing summary"""
        logger.info(f"\n{'='*60}")
        logger.info("PROCESSING SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Total files found: {summary['total_files']}")
        logger.info(f"Successfully processed: {summary['processed_count']}")
        logger.info(f"Failed: {summary['failed_count']}")
        logger.info(f"Success rate: {summary['processed_count']/summary['total_files']*100:.1f}%")
        
        if summary['last_successful_date']:
            logger.info(f"Last successful date: {summary['last_successful_date']}")
        
        if summary['processed_files']:
            logger.info(f"\nSuccessfully processed files:")
            for file_info in summary['processed_files']:
                logger.info(f"  ✓ {file_info['date']}: {file_info['filename']}")
        
        if summary['failed_files']:
            logger.info(f"\nFailed files:")
            for file_info in summary['failed_files']:
                logger.info(f"  ✗ {file_info['date']}: {file_info['filename']}")
        
        logger.info(f"{'='*60}")

def main():
    """Main execution function"""
    logger.info("Starting PDF Orchestrator")
    
    # Create orchestrator
    orchestrator = PDFOrchestrator()
    
    # Process PDFs
    summary = orchestrator.process_pdfs_chronologically()
    
    if summary['success']:
        logger.info("All PDFs processed successfully!")
    else:
        logger.warning(f"Processing stopped with {summary['failed_count']} failures")
        logger.info(f"Data committed up to: {summary['last_successful_date']}")

if __name__ == "__main__":
    main() 