import pandas as pd
import logging
import re
import os
from PyPDF2 import PdfReader
import tabula
from PDFparser_Gemini import PSPTransformer

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CustomPDFParser:
    """
    Custom PDF parser that can handle PDFs with missing first pages.
    Dynamically detects the page structure and adjusts table mapping accordingly.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def _get_report_date_from_pdf(self, pdf_path: str) -> str:
        """Extracts the report date from the PDF content or filename."""
        try:
            reader = PdfReader(pdf_path)
            first_page_text = reader.pages[0].extract_text()
            
            # Try to find the date in the first page text
            match = re.search(r"Sub: Daily PSP Report for the date\s*(\d{1,2})\s*\.(\d{2})\.(\d{4})", first_page_text)
            if match:
                day = int(match.group(1))
                month = int(match.group(2))
                year = int(match.group(3))
                return f"{month}/{day}/{year}"
            
            # Fallback: Extract date from PDF filename
            filename = os.path.basename(pdf_path)
            filename_match = re.search(r"(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", filename)
            if filename_match:
                day = int(filename_match.group(1))
                month = int(filename_match.group(2))
                year = 2000 + int(filename_match.group(3))
                return f"{month}/{day}/{year}"
            
            self.logger.warning("Could not find report date in PDF or filename.")
            return "Unknown Date"
        except Exception as e:
            self.logger.error(f"Error extracting report date: {e}")
            return "Unknown Date"
    
    def _detect_page_structure(self, pdf_path: str) -> dict:
        """
        Detects the page structure by analyzing the content of each page.
        Returns a mapping of what each page contains.
        """
        try:
            reader = PdfReader(pdf_path)
            num_pages = len(reader.pages)
            self.logger.info(f"PDF has {num_pages} pages")
            
            page_structure = {}
            
            for page_num in range(num_pages):
                page_text = reader.pages[page_num].extract_text()
                
                # Analyze page content to determine what it contains
                if "Power Supply Position at All India and Regional level" in page_text:
                    page_structure[page_num + 1] = "main_tables"  # Page 2 content
                elif "Intra-national Exchange" in page_text and "International Exchange" in page_text:
                    page_structure[page_num + 1] = "exchange_tables"  # Page 3 content
                elif "Export From India" in page_text and "Import by India" in page_text:
                    page_structure[page_num + 1] = "import_export_tables"  # Page 4 content
                elif "15 Min (INSTANTANEOUS) ALL INDIA GRID FREQUENCY" in page_text:
                    page_structure[page_num + 1] = "block_wise_table"  # Page 5 content
                else:
                    page_structure[page_num + 1] = "unknown"
                
                self.logger.info(f"Page {page_num + 1}: {page_structure[page_num + 1]}")
            
            return page_structure
            
        except Exception as e:
            self.logger.error(f"Error detecting page structure: {e}")
            return {}
    
    def _extract_raw_tables(self, pdf_path: str) -> tuple[dict, str]:
        """Extracts raw tables from the PDF using dynamic page mapping."""
        try:
            reader = PdfReader(pdf_path)
            num_pages = len(reader.pages)
        except Exception as e:
            self.logger.error(f"Error reading PDF for page count: {e}")
            return {}, "Unknown Date"

        processed_tables = {}
        report_date = self._get_report_date_from_pdf(pdf_path)
        
        # Detect page structure
        page_structure = self._detect_page_structure(pdf_path)
        
        for page_num in range(1, num_pages + 1):
            max_retries = 3
            for retry in range(max_retries):
                try:
                    # For page 5 (blockwise data), use more conservative settings
                    if page_num == 5:
                        tables_on_page = tabula.read_pdf(
                            pdf_path,
                            pages=page_num,
                            multiple_tables=True,
                            guess=False,  # More conservative
                            lattice=True,
                            stream=False,  # Try lattice first for structured tables
                            silent=True,
                            java_options=["-Dfile.encoding=UTF8", "-Xmx2g"]  # More memory for large tables
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
                    
                    self.logger.info(f"Page {page_num} ({page_structure.get(page_num, 'unknown')}): {len(tables_on_page)} tables extracted")
                    
                    for table_idx, table_df in enumerate(tables_on_page):
                        if isinstance(table_df, pd.DataFrame):
                            key = f"page_{page_num}_table_{table_idx}"
                            processed_tables[key] = table_df
                            
                            # Log table info for debugging
                            if not table_df.empty:
                                self.logger.info(f"  {key}: {table_df.shape[0]} rows, {table_df.shape[1]} cols")
                                # Show first few characters of first row for identification
                                first_row_str = " ".join(table_df.iloc[0].astype(str).fillna('').str.strip().tolist())
                                self.logger.info(f"    First row preview: {first_row_str[:100]}...")
                    
                    # If we get here, extraction was successful
                    break
                    
                except Exception as e:
                    self.logger.error(f"Error processing page {page_num} (attempt {retry + 1}/{max_retries}): {e}")
                    
                    if retry < max_retries - 1:
                        # Try different extraction settings for retry
                        try:
                            if page_num == 5:
                                # For page 5, try with different settings
                                self.logger.info(f"Retrying page {page_num} with alternative settings...")
                                tables_on_page = tabula.read_pdf(
                                    pdf_path,
                                    pages=page_num,
                                    multiple_tables=True,
                                    guess=True,
                                    lattice=False,  # Try stream mode
                                    stream=True,
                                    silent=True,
                                    java_options=["-Dfile.encoding=UTF8", "-Xmx4g"]  # Even more memory
                                )
                                
                                self.logger.info(f"Page {page_num} retry successful: {len(tables_on_page)} tables extracted")
                                
                                for table_idx, table_df in enumerate(tables_on_page):
                                    if isinstance(table_df, pd.DataFrame):
                                        key = f"page_{page_num}_table_{table_idx}"
                                        processed_tables[key] = table_df
                                        
                                        if not table_df.empty:
                                            self.logger.info(f"  {key}: {table_df.shape[0]} rows, {table_df.shape[1]} cols")
                                            first_row_str = " ".join(table_df.iloc[0].astype(str).fillna('').str.strip().tolist())
                                            self.logger.info(f"    First row preview: {first_row_str[:100]}...")
                                
                                break  # Success on retry
                            else:
                                # For other pages, just wait and retry
                                import time
                                time.sleep(1)
                        except Exception as retry_e:
                            self.logger.error(f"Retry failed for page {page_num}: {retry_e}")
                            continue
                    else:
                        # Final attempt failed
                        self.logger.error(f"Failed to extract tables from page {page_num} after {max_retries} attempts")
                        # Add a placeholder to indicate the page was processed but failed
                        processed_tables[f"page_{page_num}_failed"] = pd.DataFrame()
        
        return processed_tables, report_date
    
    def _identify_tables_dynamic(self, raw_tables_dict: dict, page_structure: dict) -> dict:
        """
        Dynamically identifies tables based on page structure and content analysis.
        """
        identified_tables = {}
        
        # Define table patterns with more specific keywords and scoring weights
        table_patterns = {
            'A. Power Supply Position at All India and Regional level': {
                'patterns': ['Power Supply Position at All India', 'Regional level', 'All India', 'Regional', 'Peak Demand Met', 'Evening Peak'],
                'weight': 2,
                'validation': lambda df, content: 'Peak Demand Met' in content or 'Evening Peak' in content
            },
            'B. Frequency Profile (%)': {
                'patterns': ['Frequency Profile', 'FVI', 'Frequency (<49.7)', 'Frequency (49.7 - 49.8)', '< 49.7', '49.7 - 49.8'],
                'weight': 3,
                'validation': lambda df, content: (
                    'All India' in content and 
                    any(char.isdigit() for char in content) and
                    df.shape[1] >= 7 and  # Should have multiple frequency columns
                    any('0.' in str(val) for val in df.iloc[0] if pd.notna(val))  # Should have decimal values like FVI
                )
            },
            'C. Power Supply Position in States': {
                'patterns': ['Power Supply Position in States', 'States', 'Punjab', 'Haryana', 'Rajasthan', 'Delhi', 'UP'],
                'weight': 2,
                'validation': lambda df, content: any(state in content for state in ['Punjab', 'Haryana', 'Rajasthan', 'Delhi', 'UP', 'Bihar', 'West Bengal'])
            },
            'D. Transnational Exchanges (MU) - Import(+ve)/Export(-ve)': {
                'patterns': ['Transnational Exchanges', 'Bhutan', 'Nepal', 'Bangladesh', 'Godda'],
                'weight': 3,
                'validation': lambda df, content: any(country in content for country in ['Bhutan', 'Nepal', 'Bangladesh'])
            },
            'E. Import/Export by Regions (in MU) - Import(+ve)/Export(-ve); OD(+)/UD(-)': {
                'patterns': ['Import/Export by Regions', 'OD', 'UD', 'Schedule(MU)', 'Actual (MU)'],
                'weight': 3,
                'validation': lambda df, content: 'Schedule(MU)' in content or 'Actual (MU)' in content
            },
            'F. Generation Outage(MW)': {
                'patterns': ['Generation Outage', 'Outage', 'Central Sector', 'State Sector'],
                'weight': 2,
                'validation': lambda df, content: 'Central Sector' in content or 'State Sector' in content
            },
            'G. Sourcewise generation (Gross) (MU)': {
                'patterns': ['Sourcewise generation', 'Gross', 'Coal', 'Gas', 'Nuclear', 'Hydro'],
                'weight': 2,
                'validation': lambda df, content: any(source in content for source in ['Coal', 'Gas', 'Nuclear', 'Hydro', 'Wind', 'Solar'])
            },
            'G. Share of RE and Non-fossil': {
                'patterns': ['Share of RE', 'Non-fossil', 'fossil fuel', 'Hydro,Nuclear and RES'],
                'weight': 3,
                'validation': lambda df, content: 'fossil fuel' in content or 'Non-fossil' in content
            },
            'H. All India Demand Diversity Factor': {
                'patterns': ['Demand Diversity Factor', 'DDF', 'Based on State Max Demands'],
                'weight': 3,
                'validation': lambda df, content: 'Based on State Max Demands' in content
            },
            'I. All India Peak Demand and shortage at Solar and Non-Solar Hour': {
                'patterns': ['Peak Demand', 'Solar hr', 'Non-Solar hr', 'Max Demand', 'Shortage'],
                'weight': 3,
                'validation': lambda df, content: 'Solar hr' in content or 'Non-Solar hr' in content
            },
            'Intra-national Exchange': {
                'patterns': ['Intra-national Exchange', 'Inter-region', 'Import/Export of ER', 'Import/Export of WR', 'Import/Export of ER (With NR)', 'HVDC'],
                'weight': 3,
                'validation': lambda df, content: (
                    'Import/Export of ER' in content or 
                    'Import/Export of WR' in content or
                    'HVDC' in content or
                    (df.shape[0] > 50 and 'Import/Export' in content)  # Large table with import/export content
                )
            },
            'International Exchange': {
                'patterns': ['International Exchange', 'International', 'State Region Line Name', 'NEPAL', 'BANGLADESH'],
                'weight': 3,
                'validation': lambda df, content: (
                    'State Region Line Name' in content or 
                    'NEPAL' in content or 
                    'BANGLADESH' in content or
                    (df.shape[0] < 10 and 'Exchange' in content)  # Small table with exchange content
                )
            },
            'Export From India (in MU)': {
                'patterns': ['Export From India'],
                'weight': 3,
                'validation': lambda df, content: 'Export From India' in content
            },
            'Import by India(in MU)': {
                'patterns': ['Import by India'],
                'weight': 3,
                'validation': lambda df, content: 'Import by India' in content
            },
            'Net from India(in MU)': {
                'patterns': ['Net from India'],
                'weight': 3,
                'validation': lambda df, content: 'Net from India' in content
            },
            'Cross-border Schedule 1': {
                'patterns': ['TOTAL COLLECTIVE', 'BILATERAL', 'IDAM', 'RTM', 'IEX', 'PXIL', 'HPX'],
                'weight': 3,
                'validation': lambda df, content: (
                    'TOTAL COLLECTIVE' in content and 
                    'BILATERAL' in content and
                    df.shape[0] >= 8 and df.shape[1] >= 8
                )
            },
            'Cross-border Schedule 2': {
                'patterns': ['TOTAL COLLECTIVE', 'BILATERAL', 'IDAM', 'RTM', 'IEX', 'PXIL', 'HPX'],
                'weight': 3,
                'validation': lambda df, content: (
                    'TOTAL COLLECTIVE' in content and 
                    'BILATERAL' in content and
                    df.shape[0] >= 8 and df.shape[1] >= 8
                )
            },
            'Cross-border Schedule 3': {
                'patterns': ['TOTAL COLLECTIVE', 'BILATERAL', 'IDAM', 'RTM', 'IEX', 'PXIL', 'HPX'],
                'weight': 3,
                'validation': lambda df, content: (
                    'TOTAL COLLECTIVE' in content and 
                    'BILATERAL' in content and
                    df.shape[0] >= 8 and df.shape[1] >= 8
                )
            },
            '15 Min (INSTANTANEOUS) ALL INDIA GRID FREQUENCY, GENERATION & DEMAND MET (SCADA DATA)': {
                'patterns': ['15 Min', 'INSTANTANEOUS', 'SCADA DATA', 'TIME', 'FREQUENCY HZ', 'ALL INDIA GRID FREQUENCY', 'THERMAL', 'HYDRO', 'NUCLEAR', 'RES'],
                'weight': 3,
                'validation': lambda df, content: (
                    # More flexible validation - just check for time-related content and large table structure
                    ('TIME' in content or 'FREQUENCY' in content or 'THERMAL' in content or 'HYDRO' in content) and
                    df.shape[0] >= 90 and  # Should have around 96 time blocks (24 hours * 4 blocks per hour), but allow some flexibility
                    df.shape[1] >= 3  # Should have at least TIME, FREQUENCY, and one other column
                )
            }
        }
        
        for tabula_key, df in raw_tables_dict.items():
            if df.empty:
                continue
                
            # Convert table content to string for pattern matching
            table_content = " ".join(df.astype(str).fillna('').values.flatten())
            
            # Find the best matching table pattern
            best_match = None
            best_score = 0
            
            for table_name, config in table_patterns.items():
                patterns = config['patterns']
                weight = config['weight']
                validation = config.get('validation', lambda df, content: True)
                
                # Count matching patterns
                matches = sum(1 for pattern in patterns if pattern.lower() in table_content.lower())
                score = matches * weight
                
                # Apply validation function
                if validation(df, table_content):
                    score += 2  # Bonus for passing validation
                else:
                    score = 0  # Zero score if validation fails
                    self.logger.debug(f"Table {tabula_key} failed validation for {table_name}")
                
                # Additional scoring based on table structure
                if table_name == 'D. Transnational Exchanges (MU) - Import(+ve)/Export(-ve)':
                    # This table should have 2 rows and 5 columns
                    if df.shape[0] == 2 and df.shape[1] == 5:
                        score += 5  # Bonus for correct structure
                elif table_name == 'B. Frequency Profile (%)':
                    # This table should have frequency-related content
                    if 'All India' in table_content and any(freq in table_content for freq in ['49.7', '49.8', '49.9', '50.05']):
                        score += 3
                elif table_name == 'C. Power Supply Position in States':
                    # This table should have state names
                    state_names = ['Punjab', 'Haryana', 'Rajasthan', 'Delhi', 'UP', 'Bihar', 'West Bengal']
                    if any(state in table_content for state in state_names):
                        score += 2
                elif table_name == 'Intra-national Exchange':
                    # This table should be large and contain HVDC lines
                    if df.shape[0] > 50 and 'HVDC' in table_content:
                        score += 5  # Bonus for correct structure
                    elif 'Import/Export of ER (With NR)' in table_content:
                        score += 3  # Bonus for specific content
                elif table_name == 'International Exchange':
                    # This table should be small and contain international exchange data
                    if df.shape[0] < 10 and ('NEPAL' in table_content or 'BANGLADESH' in table_content):
                        score += 3  # Bonus for correct structure
                elif table_name == '15 Min (INSTANTANEOUS) ALL INDIA GRID FREQUENCY, GENERATION & DEMAND MET (SCADA DATA)':
                    # This table should be large and contain time-based data
                    if df.shape[0] >= 90 and df.shape[1] >= 10:
                        score += 10  # High bonus for correct structure (large table with many columns)
                    if 'TIME' in table_content and 'FREQUENCY' in table_content:
                        score += 5  # Bonus for time and frequency content
                    if any(source in table_content for source in ['THERMAL', 'HYDRO', 'NUCLEAR', 'RES']):
                        score += 3  # Bonus for generation sources
                
                if score > best_score:
                    best_score = score
                    best_match = table_name
            
            if best_match and best_score >= 2:  # Minimum score threshold
                # Special handling for cross-border schedule tables
                if best_match.startswith('Cross-border Schedule'):
                    # For cross-border schedules, we want to keep all of them
                    # Find the next available number
                    schedule_number = 1
                    while f'Cross-border Schedule {schedule_number}' in identified_tables:
                        schedule_number += 1
                    
                    actual_table_name = f'Cross-border Schedule {schedule_number}'
                    identified_tables[actual_table_name] = df
                    self.logger.info(f"Identified {tabula_key} as {actual_table_name} (score: {best_score})")
                else:
                    # Check if this table is already identified (avoid duplicates)
                    if best_match in identified_tables:
                        # Keep the one with higher score or better structure
                        existing_df = identified_tables[best_match]
                        existing_content = " ".join(existing_df.astype(str).fillna('').values.flatten())
                        
                        # Recalculate score for existing table
                        existing_config = table_patterns[best_match]
                        existing_matches = sum(1 for pattern in existing_config['patterns'] if pattern.lower() in existing_content.lower())
                        existing_score = existing_matches * existing_config['weight']
                        
                        if best_score > existing_score:
                            identified_tables[best_match] = df
                            self.logger.info(f"Replaced {best_match} with {tabula_key} (score: {best_score} vs {existing_score})")
                        else:
                            self.logger.info(f"Kept existing {best_match} over {tabula_key} (score: {existing_score} vs {best_score})")
                    else:
                        identified_tables[best_match] = df
                        self.logger.info(f"Identified {tabula_key} as {best_match} (score: {best_score})")
            else:
                self.logger.warning(f"Could not identify table {tabula_key} (best score: {best_score})")
                # Show what the best match was for debugging
                if best_match:
                    self.logger.debug(f"Best match was {best_match} with score {best_score}")
                    # Show a preview of the table content
                    preview = " ".join(df.iloc[0].astype(str).fillna('').tolist())[:100]
                    self.logger.debug(f"Table preview: {preview}...")
        
        return identified_tables
    
    def parse_pdf(self, pdf_path: str) -> dict:
        """
        Parse PDF and return raw tables organized by page number.
        This method is used for table counting and classification.
        """
        try:
            # Extract raw tables
            raw_tables, report_date = self._extract_raw_tables(pdf_path)
            
            # Organize tables by page number
            tables_by_page = {}
            
            for table_key, table_df in raw_tables.items():
                # Extract page number from key like "page_1_table_0"
                if table_key.startswith("page_") and "_table_" in table_key:
                    parts = table_key.split("_")
                    if len(parts) >= 3:
                        page_num = int(parts[1])
                        if page_num not in tables_by_page:
                            tables_by_page[page_num] = []
                        tables_by_page[page_num].append(table_df)
            
            # Filter out garbage tables and merge split blockwise tables
            cleaned_tables_by_page = self._clean_and_merge_tables(tables_by_page, pdf_path)
            
            return cleaned_tables_by_page
            
        except Exception as e:
            self.logger.error(f"Error parsing PDF {pdf_path}: {e}")
            return {}

    def _is_garbage_table(self, table_df: pd.DataFrame, page_num: int, table_idx: int) -> tuple[bool, str]:
        """
        Check if a table is garbage and return reason if it is.
        """
        # Check for empty tables
        if table_df.empty or (table_df.shape[0] == 0 and table_df.shape[1] == 0):
            return True, "Empty table"
        
        # Check for tables with only NaN values
        if table_df.isna().all().all():
            return True, "All NaN values"
        
        # Check for Hindi text tables (first table on first page)
        if page_num == 1 and table_idx == 0:
            if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                first_cell = str(table_df.iloc[0, 0]) if not table_df.empty else ""
                hindi_chars = ['ा', 'ी', 'ु', 'ू', 'े', 'ै', 'ो', 'ौ', 'ं', 'ँ', '्', 'क', 'ख', 'ग', 'घ', 'ङ', 'च', 'छ', 'ज', 'झ', 'ञ', 'ट', 'ठ', 'ड', 'ढ', 'ण', 'त', 'थ', 'द', 'ध', 'न', 'प', 'फ', 'ब', 'भ', 'म', 'य', 'र', 'ल', 'व', 'श', 'ष', 'स', 'ह', '०', '१', '२', '३', '४', '५', '६', '७', '८', '९']
                if any(hindi_char in first_cell for hindi_char in hindi_chars):
                    return True, "Hindi text table"
        
        # Check for very small tables with no meaningful data
        if table_df.shape[0] <= 1 and table_df.shape[1] <= 2:
            if table_df.shape[0] > 0 and table_df.shape[1] > 0:
                content = ' '.join(str(cell) for cell in table_df.iloc[0].values)
                if len(content.strip()) < 20:  # Very short content
                    return True, "Very small table with minimal content"
        
        return False, ""

    def _is_blockwise_table(self, table_df: pd.DataFrame) -> bool:
        """
        Check if a table is a blockwise table (15-minute frequency data).
        """
        if table_df.empty or table_df.shape[0] < 2 or table_df.shape[1] < 3:
            return False
        
        # Check for specific blockwise table indicators in first row
        first_row = ' '.join(str(cell) for cell in table_df.iloc[0].values).lower()
        if any(keyword in first_row for keyword in ['15 min', 'instantaneous', 'grid frequency']):
            return True
        
        # Check column headers for specific blockwise table structure
        headers = ' '.join(str(col) for col in table_df.columns).lower()
        if any(keyword in headers for keyword in ['15 min', 'instantaneous', 'grid frequency']):
            return True
        
        # More specific check for blockwise table structure
        # Blockwise tables should have specific characteristics:
        # 1. Many columns (typically 10+)
        # 2. First column contains time values in HH:MM format
        # 3. Should have frequency, generation, demand columns
        if table_df.shape[1] >= 10 and table_df.shape[0] > 1:
            # Check if first column contains time values (like "00:00", "00:15", etc.)
            first_col_values = [str(val).strip() for val in table_df.iloc[:, 0].values if pd.notna(val)]
            time_patterns = [val for val in first_col_values if ':' in val and len(val) <= 5 and val.count(':') == 1]
            
            # Must have multiple time patterns to be considered blockwise
            if len(time_patterns) >= 4:  # At least 4 time entries
                # Additional check: should have frequency-related content
                all_text = ' '.join(str(cell) for cell in table_df.values.flatten() if pd.notna(cell)).lower()
                if any(keyword in all_text for keyword in ['frequency', 'generation', 'demand', 'scada']):
                    return True
        
        return False

    def _is_blockwise_continuation(self, table_df: pd.DataFrame) -> bool:
        """
        Check if a table is a continuation of a blockwise table (no headers, just data rows).
        """
        if table_df.empty or table_df.shape[0] < 1 or table_df.shape[1] < 3:
            return False
        
        # Check if it has the same number of columns as a typical blockwise table
        if table_df.shape[1] >= 10:
            # Check if first column contains time values (like "00:00", "00:15", etc.)
            first_col_values = [str(val).strip() for val in table_df.iloc[:, 0].values if pd.notna(val)]
            time_patterns = [val for val in first_col_values if ':' in val and len(val) <= 5]
            if len(time_patterns) > 0:
                return True
        
        return False

    def _split_merged_tables_by_columns(self, table_df: pd.DataFrame) -> list:
        """
        Split a merged table into separate tables based on column count changes.
        This helps when Tabula merges two tables with different column counts.
        """
        if table_df.empty or table_df.shape[0] < 2:
            return [table_df]
        
        tables = []
        current_table_start = 0
        current_columns = table_df.shape[1]
        
        for row_idx in range(1, table_df.shape[0]):
            # Count non-null columns in this row
            non_null_cols = table_df.iloc[row_idx].notna().sum()
            
            # Only split if there's a significant column count change (more than 2 columns difference)
            # and the change represents at least 30% of the original column count
            column_diff = abs(non_null_cols - current_columns)
            if column_diff > 2 and column_diff >= current_columns * 0.3:
                # Extract the current table
                if row_idx > current_table_start:
                    current_table = table_df.iloc[current_table_start:row_idx].copy()
                    if not current_table.empty and current_table.shape[0] > 1:
                        tables.append(current_table)
                
                # Start new table
                current_table_start = row_idx
                current_columns = non_null_cols
        
        # Add the last table
        if current_table_start < table_df.shape[0]:
            last_table = table_df.iloc[current_table_start:].copy()
            if not last_table.empty and last_table.shape[0] > 1:
                tables.append(last_table)
        
        # If no splits were made, return original table
        if len(tables) == 0:
            return [table_df]
        
        # Only return splits if we have exactly 2 tables (the expected case)
        # If we have more than 2, the splitting was too aggressive, so return original
        if len(tables) == 2:
            return tables
        else:
            return [table_df]

    def _clean_and_merge_tables(self, tables_by_page: dict, pdf_path: str) -> dict:
        """
        Clean garbage tables and merge split blockwise tables.
        Expects only 1 blockwise table per PDF, merges any splits found on consecutive pages.
        """
        cleaned_tables = {}
        blockwise_tables = []
        
        # First pass: filter out garbage tables and collect blockwise tables
        for page_num, page_tables in tables_by_page.items():
            cleaned_page_tables = []
            
            for table_idx, table_df in enumerate(page_tables):
                is_garbage, reason = self._is_garbage_table(table_df, page_num, table_idx)
                
                if is_garbage:
                    self.logger.info(f"Removing garbage table page_{page_num}_table_{table_idx}: {reason}")
                    continue

                # Exception for 17.12.24_NLDC_PSP.pdf page 3
                if (
                    os.path.basename(pdf_path) == "17.12.24_NLDC_PSP.pdf"
                    and page_num == 3
                    and table_idx == 0
                    and table_df.shape[0] > 2
                ):
                    # Find the row containing "INTERNATIONAL EXCHANGES"
                    split_row = None
                    for row_idx in range(table_df.shape[0]):
                        row_text = ' '.join(str(cell) for cell in table_df.iloc[row_idx].values if pd.notna(cell)).upper()
                        if "INTERNATIONAL EXCHANGES" in row_text:
                            split_row = row_idx
                            break
                    
                    if split_row is not None:
                        # Split at this row
                        t1 = table_df.iloc[:split_row].copy()
                        t2 = table_df.iloc[split_row:].copy()
                        self.logger.info(f"Exception: Split merged table on page 3 at row {split_row} (found 'INTERNATIONAL EXCHANGES')")
                        cleaned_page_tables.append(t1)
                        cleaned_page_tables.append(t2)
                    else:
                        cleaned_page_tables.append(table_df)
                    continue

                # Check if it's a blockwise table (on any page)
                if self._is_blockwise_table(table_df) or self._is_blockwise_continuation(table_df):
                    blockwise_tables.append((page_num, table_idx, table_df))
                    self.logger.info(f"Found blockwise table on page {page_num}, table {table_idx}")
                else:
                    # Try to split merged tables based on column count changes
                    split_tables = self._split_merged_tables_by_columns(table_df)
                    if len(split_tables) > 1:
                        self.logger.info(f"Split merged table page_{page_num}_table_{table_idx} into {len(split_tables)} tables")
                        for split_idx, split_table in enumerate(split_tables):
                            cleaned_page_tables.append(split_table)
                    else:
                        cleaned_page_tables.append(table_df)
            
            if cleaned_page_tables:
                cleaned_tables[page_num] = cleaned_page_tables
        
        # Second pass: handle blockwise tables - expect only 1 final table
        if len(blockwise_tables) > 0:
            if len(blockwise_tables) == 1:
                # Single blockwise table, add it to cleaned tables
                page_num, table_idx, table_df = blockwise_tables[0]
                if page_num not in cleaned_tables:
                    cleaned_tables[page_num] = []
                cleaned_tables[page_num].append(table_df)
                self.logger.info(f"Single blockwise table on page {page_num} with {table_df.shape[0]} rows")
                
            else:
                # Multiple blockwise tables found - merge them
                self.logger.info(f"Found {len(blockwise_tables)} split blockwise tables, merging into 1 table")
                
                # Sort by page number and table index
                blockwise_tables.sort(key=lambda x: (x[0], x[1]))
                
                # Check if tables are on consecutive pages
                pages = [page_num for page_num, _, _ in blockwise_tables]
                pages.sort()
                consecutive = True
                for i in range(1, len(pages)):
                    if pages[i] != pages[i-1] + 1:
                        consecutive = False
                        break
                
                if consecutive:
                    # Merge all blockwise tables
                    merged_blockwise = pd.concat([table_df for _, _, table_df in blockwise_tables], ignore_index=True)
                    
                    # Add merged table to the first page where blockwise table was found
                    first_page = min(pages)
                    if first_page not in cleaned_tables:
                        cleaned_tables[first_page] = []
                    cleaned_tables[first_page].append(merged_blockwise)
                    
                    self.logger.info(f"Merged split blockwise tables from pages {pages}")
                    self.logger.info(f"Merged blockwise table has {merged_blockwise.shape[0]} rows, {merged_blockwise.shape[1]} cols")
                    
                    # Check if we have 96 blocks (4 blocks per hour * 24 hours)
                    if merged_blockwise.shape[0] >= 96:
                        self.logger.info(f"Blockwise table has {merged_blockwise.shape[0]} rows (should be 96)")
                    else:
                        self.logger.warning(f"Blockwise table has {merged_blockwise.shape[0]} rows (expected 96)")
                else:
                    # Tables not on consecutive pages, treat as separate tables
                    self.logger.warning(f"Blockwise tables found on non-consecutive pages {pages}, treating as separate tables")
                    for page_num, table_idx, table_df in blockwise_tables:
                        if page_num not in cleaned_tables:
                            cleaned_tables[page_num] = []
                        cleaned_tables[page_num].append(table_df)
        
        return cleaned_tables
    
    def process_pdf(self, pdf_path: str) -> list[pd.DataFrame]:
        """Main method to process a PDF with dynamic table identification."""
        self.logger.info(f"--- Starting Custom PDF Parsing for: {pdf_path} ---")
        
        try:
            # Extract raw tables
            raw_tables, report_date = self._extract_raw_tables(pdf_path)
            if not raw_tables or report_date == "Unknown Date":
                self.logger.error("Failed to extract raw tables or report date from PDF.")
                return []
            
            # Detect page structure
            page_structure = self._detect_page_structure(pdf_path)
            
            # Identify tables dynamically
            identified_tables = self._identify_tables_dynamic(raw_tables, page_structure)
            
            self.logger.info(f"Identified {len(identified_tables)} tables: {list(identified_tables.keys())}")
            
            # Process tables using the existing transformer
            transformer = PSPTransformer(report_date)
            final_dataframes = []

            # Display each identified table for visual inspection
            for table_name, df in identified_tables.items():
                print(f"\n=== Table: {table_name} ===")
                print(f"Shape: {df.shape}")
                print(df.head(min(5, len(df))))

            # Process each identified table
            if 'C. Power Supply Position in States' in identified_tables:
                try:
                    df = transformer.transform_states(identified_tables['C. Power Supply Position in States'])
                    final_dataframes.append(df)
                    self.logger.info("Successfully processed States table")
                except Exception as e:
                    self.logger.error(f"Error processing states table: {e}")
            
            # Process Regional Summary (Table A) if available
            if 'A. Power Supply Position at All India and Regional level' in identified_tables:
                try:
                    # Use the proper transformer method that processes all the data
                    df_a = identified_tables['A. Power Supply Position at All India and Regional level']
                    df_b = identified_tables.get('B. Frequency Profile (%)', pd.DataFrame())
                    df_e = identified_tables.get('E. Import/Export by Regions (in MU) - Import(+ve)/Export(-ve); OD(+)/UD(-)', pd.DataFrame())
                    df_f = identified_tables.get('F. Generation Outage(MW)', pd.DataFrame())
                    df_g_main = identified_tables.get('G. Sourcewise generation (Gross) (MU)', pd.DataFrame())
                    df_g_share = identified_tables.get('G. Share of RE and Non-fossil', pd.DataFrame())
                    df_h = identified_tables.get('H. All India Demand Diversity Factor', pd.DataFrame())
                    df_i = identified_tables.get('I. All India Peak Demand and shortage at Solar and Non-Solar Hour', pd.DataFrame())
                    
                    df = transformer.transform_regional_summary(df_a, df_b, df_e, df_f, df_g_main, df_g_share, df_h, df_i)
                    final_dataframes.append(df)
                    self.logger.info("Successfully processed Regional Summary table")
                except Exception as e:
                    self.logger.error(f"Error processing regional summary table: {e}")
            
            # Process Generation tables
            if 'G. Sourcewise generation (Gross) (MU)' in identified_tables:
                try:
                    df_g = identified_tables['G. Sourcewise generation (Gross) (MU)']
                    if not df_g.empty:
                        generation_data = []
                        for _, row in df_g.iterrows():
                            source = row.iloc[0] if len(row) > 0 else 'Unknown'
                            for col in df_g.columns[1:]:
                                if col not in ['Unnamed: 0', 'All India', '% Share']:
                                    value = row[col] if pd.notna(row[col]) else None
                                    generation_data.append({
                                        'Date': transformer.report_date,
                                        'Table Name': 'Generation Breakdown',
                                        'Generation Source': source,
                                        'Region': col,
                                        'Generation (MU)': value
                                    })
                        
                        if generation_data:
                            df = pd.DataFrame(generation_data)
                            final_dataframes.append(df)
                            self.logger.info("Successfully processed Generation Breakdown table")
                except Exception as e:
                    self.logger.error(f"Error processing generation breakdown table: {e}")
            
            # Process RE Share table
            if 'G. Share of RE and Non-fossil' in identified_tables:
                try:
                    df_re = identified_tables['G. Share of RE and Non-fossil']
                    if not df_re.empty:
                        re_data = []
                        for _, row in df_re.iterrows():
                            metric = row.iloc[0] if len(row) > 0 else 'Unknown'
                            for col in df_re.columns[1:]:
                                if col not in ['Unnamed: 0']:
                                    value = row[col] if pd.notna(row[col]) else None
                                    re_data.append({
                                        'Date': transformer.report_date,
                                        'Table Name': 'RE Share',
                                        'Metric': metric,
                                        'Region': col,
                                        'Value (%)': value
                                    })
                        
                        if re_data:
                            df = pd.DataFrame(re_data)
                            final_dataframes.append(df)
                            self.logger.info("Successfully processed RE Share table")
                except Exception as e:
                    self.logger.error(f"Error processing RE share table: {e}")
            
            if 'D. Transnational Exchanges (MU) - Import(+ve)/Export(-ve)' in identified_tables:
                try:
                    df = transformer.transform_international_net(identified_tables['D. Transnational Exchanges (MU) - Import(+ve)/Export(-ve)'])
                    final_dataframes.append(df)
                    self.logger.info("Successfully processed International Net table")
                except Exception as e:
                    self.logger.error(f"Error processing international net table: {e}")
            
            if 'Intra-national Exchange' in identified_tables:
                try:
                    df = transformer.transform_inter_region(identified_tables['Intra-national Exchange'])
                    final_dataframes.append(df)
                    self.logger.info("Successfully processed Inter-region table")
                except Exception as e:
                    self.logger.error(f"Error processing inter-region table: {e}")
            
            if 'International Exchange' in identified_tables:
                try:
                    df = transformer.transform_international_exchange(identified_tables['International Exchange'])
                    final_dataframes.append(df)
                    self.logger.info("Successfully processed International Exchange table")
                except Exception as e:
                    self.logger.error(f"Error processing international exchange table: {e}")
            
            if 'Export From India (in MU)' in identified_tables and \
               'Import by India(in MU)' in identified_tables and \
               'Net from India(in MU)' in identified_tables:
                try:
                    df = transformer.transform_exchange(identified_tables['Export From India (in MU)'],
                                                        identified_tables['Import by India(in MU)'],
                                                        identified_tables['Net from India(in MU)'])
                    final_dataframes.append(df)
                    self.logger.info("Successfully processed Exchange tables")
                except Exception as e:
                    self.logger.error(f"Error processing exchange tables: {e}")
            
            if '15 Min (INSTANTANEOUS) ALL INDIA GRID FREQUENCY, GENERATION & DEMAND MET (SCADA DATA)' in identified_tables:
                try:
                    df = transformer.transform_block_wise(identified_tables['15 Min (INSTANTANEOUS) ALL INDIA GRID FREQUENCY, GENERATION & DEMAND MET (SCADA DATA)'])
                    final_dataframes.append(df)
                    self.logger.info("Successfully processed Block-wise table")
                except Exception as e:
                    self.logger.error(f"Error processing block-wise table: {e}")
            
            # Process Cross-border Schedule tables
            for i in range(1, 4):
                schedule_key = f'Cross-border Schedule {i}'
                if schedule_key in identified_tables:
                    try:
                        df_schedule = identified_tables[schedule_key]
                        if not df_schedule.empty:
                            schedule_data = []
                            for _, row in df_schedule.iterrows():
                                for col in df_schedule.columns:
                                    if col not in ['Unnamed: 0'] and pd.notna(row[col]):
                                        value = row[col]
                                        schedule_data.append({
                                            'Date': transformer.report_date,
                                            'Table Name': f'Cross-border Schedule {i}',
                                            'Row': row.iloc[0] if len(row) > 0 else 'Unknown',
                                            'Column': col,
                                            'Value': value
                                        })
                            
                            if schedule_data:
                                df = pd.DataFrame(schedule_data)
                                final_dataframes.append(df)
                                self.logger.info(f"Successfully processed {schedule_key} table")
                    except Exception as e:
                        self.logger.error(f"Error processing {schedule_key} table: {e}")
            
            if final_dataframes:
                self.logger.info(f"--- Custom PDF Parsing Completed Successfully: {len(final_dataframes)} dataframes extracted ---")
            else:
                self.logger.warning("--- Custom PDF Parsing completed but no data extracted ---")
            
            return final_dataframes
            
        except Exception as e:
            self.logger.error(f"--- Custom PDF Parsing Failed: {e} ---", exc_info=True)
            return []

# Test the custom parser
if __name__ == "__main__":
    parser = CustomPDFParser()
    result = parser.process_pdf("Output/NLDC_PSP_URLS/2023-24/JULY/reports/23.07.23_NLDC_PSP.pdf")
    print(f"Extracted {len(result)} dataframes") 