#!/usr/bin/env python3
"""
Improved Modular PSP (Power Supply Position) Report Parser
Integrates better column mapping to handle actual PDF column names.
"""

import pandas as pd
import numpy as np
import logging
import re
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional, Union
from difflib import SequenceMatcher
from fuzzywuzzy import fuzz
import json
from dataclasses import dataclass
from PyPDF2 import PdfReader
import tabula

# Import the improved column mapping
from improved_column_mapping import ImprovedColumnMapper

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class TableClassification:
    """Represents a table classification result"""
    table_name: str
    confidence: float
    category: str
    description: str
    column_mappings: Dict[str, str]

@dataclass
class ProcessingResult:
    """Represents the result of processing a table"""
    table_name: str
    success: bool
    processed_df: Optional[pd.DataFrame]
    error_message: Optional[str]
    source_tables: List[str]

# ============================================================================
# TABLE IDENTIFICATION MODULE
# ============================================================================

class TableIdentifier:
    """
    Responsible for identifying and classifying tables from raw PDF extraction.
    Uses pattern matching, fuzzy logic, and content analysis.
    """
    
    def __init__(self):
        self.table_patterns = {
            'regional_summary': {
                'keywords': ['regional', 'summary', 'all india', 'power supply', 'demand met', 'peak demand', 'energy met'],
                'required_columns': ['demand', 'energy', 'peak', 'nr', 'wr', 'sr', 'er', 'ner'],
                'description': 'Regional power supply and demand summary'
            },
            'frequency_profile': {
                'keywords': ['frequency', 'fvi', '49.7', '50.05', 'frequency profile'],
                'required_columns': ['frequency', 'fvi', '49.7', '50.05'],
                'description': 'Frequency profile and violation index'
            },
            'state_energy': {
                'keywords': ['state', 'states', 'power supply position in states', 'maximum demand', 'energy met'],
                'required_columns': ['states', 'maximum demand', 'energy met', 'shortage'],
                'description': 'State-wise power supply and demand data'
            },
            'transnational_exchange': {
                'keywords': ['transnational', 'bhutan', 'nepal', 'bangladesh', 'godda', 'exchange', 'country', 'gna', 'bilateral', 'total', 'collective'],
                'required_columns': ['bhutan', 'nepal', 'bangladesh', 'exchange', 'country', 'gna'],
                'description': 'Transnational power exchange data'
            },
            'import_export_regions': {
                'keywords': ['import', 'export', 'regions', 'schedule', 'actual', 'od/ud', 'schedule(mu)', 'actual(mu)', 'o/d/u/d(mu)'],
                'required_columns': ['schedule', 'actual', 'import', 'export', 'nr', 'wr', 'sr', 'er', 'ner'],
                'description': 'Import/Export by regions data'
            },
            'outage_data': {
                'keywords': ['outage', 'central sector', 'state sector', 'generation outage', 'sector', 'total', '% share'],
                'required_columns': ['outage', 'sector', 'central sector', 'state sector', 'total'],
                'description': 'Generation outage information'
            },
            'generation_breakdown': {
                'keywords': ['sourcewise', 'generation', 'coal', 'hydro', 'nuclear', 'wind', 'solar', 'sourcewise generation', 'lignite', 'gas naptha diesel', 'all india', '% share'],
                'required_columns': ['coal', 'hydro', 'nuclear', 'generation', 'all india'],
                'description': 'Generation breakdown by source'
            },
            're_share': {
                'keywords': ['re', 'renewable', 'share', 'non-fossil', 'res', 'share of re', 'share of res in total generation', 'non-fossil fuel'],
                'required_columns': ['re', 'share', 'non-fossil', 'res'],
                'description': 'Renewable energy share data'
            },
            'demand_diversity_factor_ddf': {
                'keywords': ['diversity', 'ddf', 'demand diversity factor', 'all india demand diversity', 'based on regional max demands', 'based on state max demands'],
                'required_columns': ['diversity', 'ddf', 'factor', 'demands'],
                'description': 'Demand diversity factor data'
            },
            'solar_nonsolar_hour': {
                'keywords': ['solar', 'non-solar', 'peak demand', 'solar hour', 'non-solar hour', 'solar hr', 'non-solar hr', 'max demand met', 'shortage', 'time'],
                'required_columns': ['solar', 'non-solar', 'peak demand', 'time', 'shortage'],
                'description': 'Solar and non-solar hour peak demand data'
            },
            'transmission_flow': {
                'keywords': ['transmission', 'import', 'export', 'schedule', 'actual', 'line', 'import/export of er', 'with nr'],
                'required_columns': ['schedule', 'actual', 'import', 'export', 'line'],
                'description': 'Transmission and inter-regional exchange data'
            },
            'international_exchange': {
                'keywords': ['international', 'bhutan', 'nepal', 'bangladesh', 'exchange', 'international exchanges', 'state', 'region', 'line name', 'max (mw)', 'min (mw)', 'avg (mw)'],
                'required_columns': ['state', 'region', 'line name', 'max', 'min', 'avg'],
                'description': 'International power exchange data'
            },
            'cross_border_schedule_1': {
                'keywords': ['cross border', 'schedule', 'export', 'import', 'bilateral', 'total', 'collective'],
                'required_columns': ['country', 'gna', 'bilateral', 'total'],
                'description': 'Cross border schedule table 1'
            },
            'cross_border_schedule_2': {
                'keywords': ['cross border', 'schedule', 'export', 'import', 'bilateral', 'total', 'collective'],
                'required_columns': ['country', 'gna', 'bilateral', 'total'],
                'description': 'Cross border schedule table 2'
            },
            'cross_border_schedule_3': {
                'keywords': ['cross border', 'schedule', 'export', 'import', 'bilateral', 'total', 'collective'],
                'required_columns': ['country', 'gna', 'bilateral', 'total'],
                'description': 'Cross border schedule table 3'
            },
            'time_block': {
                'keywords': ['time block', 'block time', 'frequency', 'demand met', '15 min', 'instantaneous'],
                'required_columns': ['time', 'frequency', 'demand'],
                'description': 'Time block wise power data'
            }
        }
    
    def classify_table(self, df: pd.DataFrame, table_name: str = None) -> TableClassification:
        """Classify a table based on its content and structure"""
        if df.empty:
            return TableClassification(
                table_name=table_name or "unknown",
                confidence=0.0,
                category="unknown",
                description="Empty table",
                column_mappings={}
            )
        
        # Extract table text and columns
        table_text = self._extract_table_text(df, table_name)
        columns = [str(col).lower() for col in df.columns]
        
        # Find best matching pattern
        best_match = None
        best_score = 0.0
        
        for category, pattern in self.table_patterns.items():
            score = self._calculate_table_score(table_text, columns, pattern)
            if score > best_score:
                best_score = score
                best_match = category
        
        if best_match and best_score > 0.2:  # Lowered threshold
            return TableClassification(
                table_name=table_name or best_match,
                confidence=best_score,
                category=best_match,
                description=self.table_patterns[best_match]['description'],
                column_mappings=self._generate_column_mappings(df, best_match)
            )
        else:
            return TableClassification(
                table_name=table_name or "unknown",
                confidence=0.0,
                category="unknown",
                description="Unknown table type",
                column_mappings={}
            )
    
    def _extract_table_text(self, df: pd.DataFrame, table_name: str = None) -> str:
        """Extract text content from table for classification"""
        text_parts = []
        
        # Add column names
        text_parts.extend([str(col) for col in df.columns])
        
        # Add first few rows
        for idx, row in df.head(3).iterrows():
            text_parts.extend([str(val) for val in row.values])
        
        return " ".join(text_parts).lower()
    
    def _calculate_table_score(self, table_text: str, columns: List[str], pattern: Dict) -> float:
        """Calculate similarity score between table and pattern"""
        score = 0.0
        
        # Check keyword matches
        keyword_matches = 0
        for keyword in pattern['keywords']:
            if self._fuzzy_match(keyword, table_text):
                keyword_matches += 1
        
        keyword_score = keyword_matches / len(pattern['keywords']) if pattern['keywords'] else 0
        
        # Check required column matches
        column_matches = 0
        for required_col in pattern['required_columns']:
            for col in columns:
                if self._fuzzy_match(required_col, col):
                    column_matches += 1
                    break
        
        column_score = column_matches / len(pattern['required_columns']) if pattern['required_columns'] else 0
        
        # Combined score
        score = (keyword_score * 0.6) + (column_score * 0.4)
        
        return score
    
    def _fuzzy_match(self, target: str, source: str, threshold: float = 80) -> bool:
        """Check if target string matches source using fuzzy matching"""
        target_norm = self._normalize_text(target)
        source_norm = self._normalize_text(source)
        
        # Exact match
        if target_norm in source_norm or source_norm in target_norm:
            return True
        
        # Fuzzy match
        similarity = fuzz.ratio(target_norm, source_norm)
        return similarity >= threshold
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison"""
        return re.sub(r'[^\w\s]', '', text.lower()).strip()
    
    def _generate_column_mappings(self, df: pd.DataFrame, table_category: str) -> Dict[str, str]:
        """Generate column mappings for the table"""
        # This will be handled by the improved column mapper
        return {}

# ============================================================================
# IMPROVED TABLE PROCESSOR
# ============================================================================

class ImprovedTableProcessor:
    """
    Improved table processor that uses better column mapping.
    """
    
    def __init__(self, report_date: str):
        self.report_date = report_date
        self.mapper = ImprovedColumnMapper()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def process_table(self, table_df: pd.DataFrame, classification: TableClassification) -> ProcessingResult:
        """
        Process a table using improved column mapping.
        """
        try:
            category = classification.category
            
            # Apply improved column mapping
            mapped_df = self.mapper.map_columns(table_df, category)
            
            # Extract numeric data using category-specific logic
            extracted_df = self.mapper.extract_numeric_data(mapped_df, category)
            
            if extracted_df is not None and not extracted_df.empty:
                # Add common columns
                extracted_df['Date'] = self.report_date
                extracted_df['Table Name'] = classification.table_name
                
                return ProcessingResult(
                    table_name=classification.table_name,
                    success=True,
                    processed_df=extracted_df,
                    error_message=None,
                    source_tables=[classification.table_name]
                )
            else:
                return ProcessingResult(
                    table_name=classification.table_name,
                    success=False,
                    processed_df=None,
                    error_message="No data extracted after processing",
                    source_tables=[classification.table_name]
                )
            
        except Exception as e:
            self.logger.error(f"Error processing table {classification.table_name}: {e}")
            return ProcessingResult(
                table_name=classification.table_name,
                success=False,
                processed_df=None,
                error_message=str(e),
                source_tables=[classification.table_name]
            )
    
    def process_multiple_tables(self, tables_data: Dict[str, pd.DataFrame], 
                              classifications: Dict[str, TableClassification]) -> List[ProcessingResult]:
        """Process multiple tables"""
        results = []
        
        for table_key, table_df in tables_data.items():
            if table_key in classifications:
                classification = classifications[table_key]
                result = self.process_table(table_df, classification)
                results.append(result)
            else:
                self.logger.warning(f"No classification found for table {table_key}")
        
        return results

# ============================================================================
# PDF EXTRACTOR (unchanged)
# ============================================================================

class PDFExtractor:
    """Extract tables from PDF files"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def extract_tables_from_pdf(self, pdf_path: str) -> Tuple[Dict[str, pd.DataFrame], str]:
        """Extract tables from PDF and get report date"""
        try:
            # Get report date
            report_date = self._get_report_date_from_pdf(pdf_path)
            
            # Extract raw tables
            raw_tables = self._extract_raw_tables(pdf_path)
            
            # Clean and filter tables
            cleaned_tables = self._clean_and_filter_tables(raw_tables, pdf_path)
            
            return cleaned_tables, report_date
            
        except Exception as e:
            self.logger.error(f"Error extracting tables from PDF: {e}")
            return {}, "Unknown Date"
    
    def _get_report_date_from_pdf(self, pdf_path: str) -> str:
        """Extract report date from PDF filename"""
        filename = os.path.basename(pdf_path)
        match = re.search(r"(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", filename)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = 2000 + int(match.group(3))
            return f"{month:02d}/{day:02d}/{year}"
        return "Unknown Date"
    
    def _extract_raw_tables(self, pdf_path: str) -> Dict[str, pd.DataFrame]:
        """Extract raw tables from PDF using tabula"""
        raw_tables = {}
        
        try:
            reader = PdfReader(pdf_path)
            num_pages = len(reader.pages)
            
            for page_num in range(1, num_pages + 1):
                max_retries = 3
                for retry in range(max_retries):
                    try:
                        # Use different settings for different pages
                        if page_num == 5:  # Blockwise table page
                            tables_on_page = tabula.read_pdf(
                                pdf_path,
                                pages=page_num,
                                multiple_tables=True,
                                guess=False,
                                lattice=True,
                                stream=False,
                                silent=True,
                                java_options=["-Dfile.encoding=UTF8", "-Xmx2g"]
                            )
                        else:
                            tables_on_page = tabula.read_pdf(
                                pdf_path,
                                pages=page_num,
                                multiple_tables=True,
                                guess=True,
                                lattice=True,
                                stream=True,
                                silent=True
                            )
                        
                        # Process extracted tables
                        for table_idx, table_df in enumerate(tables_on_page):
                            if isinstance(table_df, pd.DataFrame) and not table_df.empty:
                                key = f"page_{page_num}_table_{table_idx}"
                                raw_tables[key] = table_df
                        
                        break  # Success, exit retry loop
                        
                    except Exception as e:
                        self.logger.error(f"Error processing page {page_num} (attempt {retry + 1}/{max_retries}): {e}")
                        if retry < max_retries - 1:
                            import time
                            time.sleep(1)
                        else:
                            self.logger.error(f"Failed to extract tables from page {page_num} after {max_retries} attempts")
            
            return raw_tables
            
        except Exception as e:
            self.logger.error(f"Error reading PDF: {e}")
            return {}
    
    def _clean_and_filter_tables(self, raw_tables: Dict[str, pd.DataFrame], pdf_path: str) -> Dict[str, pd.DataFrame]:
        """Clean and filter tables, removing garbage and merging split tables"""
        cleaned_tables = {}
        
        # Group tables by page
        tables_by_page = {}
        for key, df in raw_tables.items():
            page_num = int(key.split('_')[1])
            if page_num not in tables_by_page:
                tables_by_page[page_num] = []
            tables_by_page[page_num].append((key, df))
        
        # Process each page
        for page_num, page_tables in tables_by_page.items():
            page_cleaned_tables = []
            
            for table_idx, (key, df) in enumerate(page_tables):
                # Check if it's a garbage table
                is_garbage, reason = self._is_garbage_table(df, page_num, table_idx)
                if is_garbage:
                    self.logger.info(f"Skipping garbage table {key}: {reason}")
                    continue
                
                # Check if it's a blockwise table continuation
                if self._is_blockwise_continuation(df):
                    # Try to merge with previous table
                    if page_cleaned_tables and self._is_blockwise_table(page_cleaned_tables[-1][1]):
                        merged_df = pd.concat([page_cleaned_tables[-1][1], df], ignore_index=True)
                        page_cleaned_tables[-1] = (page_cleaned_tables[-1][0], merged_df)
                        self.logger.info(f"Merged blockwise continuation {key} with previous table")
                        continue
                
                # Check if it's a blockwise table
                if self._is_blockwise_table(df):
                    # Handle special case for December 1, 2024 PDF
                    if self._is_december_1_2024_exception(pdf_path, page_num):
                        split_tables = self._split_december_1_2024_table(df)
                        for split_idx, split_df in enumerate(split_tables):
                            split_key = f"{key}_split_{split_idx}"
                            page_cleaned_tables.append((split_key, split_df))
                        continue
                
                # Regular table
                page_cleaned_tables.append((key, df))
            
            # Add cleaned tables to result
            for key, df in page_cleaned_tables:
                cleaned_tables[key] = df
        
        return cleaned_tables
    
    def _is_garbage_table(self, df: pd.DataFrame, page_num: int, table_idx: int) -> Tuple[bool, str]:
        """Check if table is garbage (empty, Hindi text, etc.)"""
        if df.empty:
            return True, "Empty table"
        
        # Check for very small tables (likely garbage) - be less aggressive
        if df.shape[0] < 1 or df.shape[1] < 1:
            return True, "Too small table"
        
        # Check for Hindi text (common in garbage tables) - be more lenient
        first_row_text = " ".join(df.iloc[0].astype(str).fillna('').tolist())
        hindi_chars = re.findall(r'[\u0900-\u097F]', first_row_text)
        if len(hindi_chars) > 10:  # More than 10 Hindi characters (increased threshold)
            return True, "Hindi text table"
        
        # Check for tables that are mostly empty
        non_empty_cells = df.notna().sum().sum()
        total_cells = df.shape[0] * df.shape[1]
        if total_cells > 0 and non_empty_cells / total_cells < 0.1:  # Less than 10% non-empty
            return True, "Mostly empty table"
        
        return False, ""
    
    def _is_blockwise_table(self, df: pd.DataFrame) -> bool:
        """Check if table is a blockwise table"""
        if df.empty:
            return False
        
        # Check for blockwise table indicators
        first_row_text = " ".join(df.iloc[0].astype(str).fillna('').tolist()).lower()
        if "15 min" in first_row_text and "frequency" in first_row_text:
            return True
        
        if "time" in first_row_text and "demand met" in first_row_text:
            return True
        
        return False
    
    def _is_blockwise_continuation(self, df: pd.DataFrame) -> bool:
        """Check if table is a continuation of blockwise table"""
        if df.empty:
            return False
        
        # Check for continuation indicators (time values)
        first_col = df.iloc[:, 0].astype(str).fillna('')
        time_pattern = re.compile(r'\d{2}:\d{2}')
        time_matches = sum(1 for val in first_col if time_pattern.search(str(val)))
        
        return time_matches > 0
    
    def _is_december_1_2024_exception(self, pdf_path: str, page_num: int) -> bool:
        """Check if this is the December 1, 2024 PDF exception"""
        filename = os.path.basename(pdf_path)
        return "01.12.24_NLDC_PSP" in filename and page_num == 3
    
    def _split_december_1_2024_table(self, df: pd.DataFrame) -> List[pd.DataFrame]:
        """Split the merged table on page 3 of December 1, 2024 PDF"""
        split_tables = []
        
        # Find the row containing "INTERNATIONAL EXCHANGES"
        split_row = -1
        for idx, row in df.iterrows():
            row_text = " ".join(row.astype(str).fillna('').tolist())
            if "INTERNATIONAL EXCHANGES" in row_text:
                split_row = idx
                break
        
        if split_row > 0:
            # Split the table
            table1 = df.iloc[:split_row].copy()
            table2 = df.iloc[split_row:].copy()
            split_tables = [table1, table2]
        else:
            # If split point not found, return original table
            split_tables = [df]
        
        return split_tables

# ============================================================================
# IMPROVED MAIN ORCHESTRATOR
# ============================================================================

class ImprovedPSPReportParser:
    """
    Improved main orchestrator that coordinates table identification and processing.
    Uses better column mapping for improved data extraction.
    """
    
    def __init__(self):
        self.extractor = PDFExtractor()
        self.identifier = TableIdentifier()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def parse_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """
        Parse a PSP report PDF and return processed results.
        """
        try:
            # Step 1: Extract tables from PDF
            self.logger.info(f"Extracting tables from {pdf_path}")
            raw_tables, report_date = self.extractor.extract_tables_from_pdf(pdf_path)
            
            if not raw_tables:
                return {
                    'success': False,
                    'report_date': report_date,
                    'raw_tables': {},
                    'classifications': {},
                    'processed_results': [],
                    'final_tables': [],
                    'errors': ['No tables extracted from PDF']
                }
            
            # Step 2: Identify and classify tables
            self.logger.info("Classifying extracted tables")
            classifications = {}
            for table_key, table_df in raw_tables.items():
                classification = self.identifier.classify_table(table_df, table_key)
                if classification.confidence > 0.2:  # Lowered threshold
                    classifications[table_key] = classification
            
            # Step 3: Process tables with improved processor
            self.logger.info("Processing classified tables with improved mapping")
            processor = ImprovedTableProcessor(report_date)
            processing_results = processor.process_multiple_tables(raw_tables, classifications)
            
            # Step 4: Collect results
            final_tables = []
            errors = []
            
            for result in processing_results:
                if result.success and result.processed_df is not None and not result.processed_df.empty:
                    final_tables.append(result.processed_df)
                elif not result.success:
                    errors.append(f"{result.table_name}: {result.error_message}")
            
            return {
                'success': len(final_tables) > 0,
                'report_date': report_date,
                'raw_tables': raw_tables,
                'classifications': classifications,
                'processed_results': processing_results,
                'final_tables': final_tables,
                'errors': errors
            }
            
        except Exception as e:
            self.logger.error(f"Error parsing PDF {pdf_path}: {e}")
            return {
                'success': False,
                'report_date': "Unknown Date",
                'raw_tables': {},
                'classifications': {},
                'processed_results': [],
                'final_tables': [],
                'errors': [str(e)]
            }
    
    def save_results(self, results: Dict[str, Any], output_path: str = None) -> str:
        """
        Save processing results to CSV file.
        """
        if not results['success'] or not results['final_tables']:
            self.logger.warning("No tables to save")
            return ""
        
        # Generate output path if not provided
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"improved_processed_psp_report_{timestamp}.csv"
        
        # Combine all tables
        combined_df = pd.concat(results['final_tables'], ignore_index=True)
        
        # Save to CSV
        combined_df.to_csv(output_path, index=False)
        self.logger.info(f"Results saved to {output_path}")
        
        return output_path

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""
    if len(sys.argv) < 2:
        print("Usage: python improved_modular_psp_parser.py <pdf_path> [output_path]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    # Initialize improved parser
    parser = ImprovedPSPReportParser()
    
    # Parse PDF
    print(f"Parsing {pdf_path} with improved column mapping...")
    results = parser.parse_pdf(pdf_path)
    
    # Display results
    print(f"\n=== IMPROVED PARSING RESULTS ===")
    print(f"Success: {results['success']}")
    print(f"Report Date: {results['report_date']}")
    print(f"Raw Tables Extracted: {len(results['raw_tables'])}")
    print(f"Tables Classified: {len(results['classifications'])}")
    print(f"Tables Processed Successfully: {len(results['final_tables'])}")
    
    if results['errors']:
        print(f"\nErrors:")
        for error in results['errors']:
            print(f"  - {error}")
    
    # Save results if successful
    if results['success']:
        saved_path = parser.save_results(results, output_path)
        if saved_path:
            print(f"\nResults saved to: {saved_path}")
    
    return results

if __name__ == "__main__":
    main() 