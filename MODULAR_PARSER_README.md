# Modular PSP Report Parser

A comprehensive, modular Python parser for Power Supply Position (PSP) report PDFs. This parser combines table identification and processing logic into a single, well-organized file with clear separation of concerns.

## Features

- **Modular Design**: Clear separation between table identification, processing, and PDF extraction
- **Smart Table Classification**: Uses fuzzy matching and pattern recognition to identify table types
- **Robust PDF Processing**: Handles various PDF formats and edge cases
- **Garbage Table Filtering**: Automatically removes empty or irrelevant tables
- **Split Table Merging**: Merges tables that were split across pages
- **Exception Handling**: Special handling for known problematic PDFs
- **Comprehensive Logging**: Detailed logging for debugging and monitoring

## Architecture

The parser is organized into four main modules:

### 1. Table Identifier (`TableIdentifier`)
- **Purpose**: Identifies and classifies tables from raw PDF extraction
- **Features**:
  - Pattern-based table recognition
  - Fuzzy string matching for robust identification
  - Confidence scoring for classification quality
  - Column mapping generation

### 2. Table Processor (`TableProcessor`)
- **Purpose**: Transforms identified tables into standardized formats
- **Features**:
  - Data cleaning and normalization
  - Column name standardization
  - Numeric data processing
  - Common column addition (Date, Table Name)

### 3. PDF Extractor (`PDFExtractor`)
- **Purpose**: Extracts raw tables from PDF files
- **Features**:
  - Multi-page PDF processing
  - Retry logic for failed extractions
  - Garbage table filtering
  - Split table detection and merging
  - Special exception handling

### 4. Main Orchestrator (`PSPReportParser`)
- **Purpose**: Coordinates all modules and provides unified interface
- **Features**:
  - End-to-end PDF processing
  - Result aggregation and error handling
  - CSV output generation
  - Comprehensive result reporting

## Data Structures

### TableClassification
```python
@dataclass
class TableClassification:
    table_name: str
    confidence: float
    category: str
    description: str
    column_mappings: Dict[str, str]
```

### ProcessingResult
```python
@dataclass
class ProcessingResult:
    table_name: str
    success: bool
    processed_df: Optional[pd.DataFrame]
    error_message: Optional[str]
    source_tables: List[str]
```

## Usage

### Basic Usage

```python
from modular_psp_parser import PSPReportParser

# Initialize parser
parser = PSPReportParser()

# Parse a PDF
results = parser.parse_pdf("path/to/your/report.pdf")

# Check results
if results['success']:
    print(f"Successfully processed {len(results['final_tables'])} tables")
    
    # Save to CSV
    output_path = parser.save_results(results, "output.csv")
    print(f"Results saved to: {output_path}")
else:
    print("Processing failed:")
    for error in results['errors']:
        print(f"  - {error}")
```

### Command Line Usage

```bash
# Parse single PDF
python modular_psp_parser.py "path/to/report.pdf"

# Parse PDF with custom output path
python modular_psp_parser.py "path/to/report.pdf" "output.csv"
```

### Testing

```bash
# Test single PDF
python test_modular_parser.py "path/to/report.pdf"

# Test all PDFs in directory
python test_modular_parser.py "path/to/pdf/directory"
```

## Table Types Supported

The parser recognizes and processes the following table types:

1. **Regional Summary** - Power supply and demand summary by region
2. **Frequency Profile** - Frequency violation index and duration data
3. **State Energy** - State-wise power supply and demand data
4. **Transnational Exchange** - International power exchange data
5. **Import/Export Regions** - Regional import/export data
6. **Outage Data** - Generation outage information
7. **Generation Breakdown** - Generation by source type
8. **RE Share** - Renewable energy share data
9. **Demand Diversity Factor** - DDF calculations
10. **Solar/Non-Solar Hour** - Peak demand by time period
11. **Transmission Flow** - Inter-regional transmission data
12. **International Exchange** - International exchange details
13. **Cross Border Schedules** - Cross-border power schedules
14. **Time Block** - 15-minute blockwise data

## Expected Table Counts

The parser uses date-aware expected table counts:

- **Before May 1, 2023**: 11 tables
- **May 1, 2023 - July 29, 2023**: 12 tables (added Solar/Non-Solar Hour table)
- **July 30, 2023 - November 3, 2024**: 15 tables (added cross-border schedules)
- **After November 4, 2024**: 16 tables (added blockwise table)

## Special Handling

### Garbage Table Filtering
- Removes empty tables
- Filters out Hindi text tables
- Excludes very small tables (< 2x2)

### Split Table Merging
- Automatically detects and merges blockwise tables split across pages
- Handles table continuations based on time patterns

### Exception Handling
- **December 1, 2024 PDF**: Special handling for merged tables on page 3
- **Missing Blockwise Tables**: Graceful handling when blockwise table is missing

## Output Format

The parser generates standardized CSV output with the following common columns:
- `Date`: Report date
- `Table Name`: Type of table
- Additional columns specific to each table type

## Dependencies

```python
pandas>=1.3.0
PyPDF2>=3.0.0
tabula-py>=2.0.0
fuzzywuzzy>=0.18.0
python-Levenshtein>=0.12.0
```

## Installation

1. Install dependencies:
```bash
pip install pandas PyPDF2 tabula-py fuzzywuzzy python-Levenshtein
```

2. Ensure Java is installed (required for tabula-py):
```bash
# On Windows
# Download and install Java from https://java.com/

# On Linux/Mac
sudo apt-get install default-jre  # Ubuntu/Debian
brew install java                 # macOS
```

## Error Handling

The parser includes comprehensive error handling:

- **PDF Reading Errors**: Retry logic with different extraction settings
- **Table Classification Errors**: Graceful fallback for unidentified tables
- **Processing Errors**: Detailed error messages for debugging
- **Missing Tables**: Continues processing even when some tables are missing

## Logging

The parser uses Python's logging module with configurable levels:

```python
import logging

# Set logging level
logging.basicConfig(level=logging.INFO)  # or DEBUG, WARNING, ERROR

# Parse with logging
parser = PSPReportParser()
results = parser.parse_pdf("report.pdf")
```

## Performance Considerations

- **Memory Usage**: Large PDFs may require increased Java heap size
- **Processing Time**: Complex tables (like blockwise) may take longer to process
- **Retry Logic**: Failed extractions are retried with different settings

## Troubleshooting

### Common Issues

1. **Java Not Found**: Ensure Java is installed and in PATH
2. **Memory Errors**: Increase Java heap size in tabula settings
3. **Table Not Recognized**: Check table patterns in `TableIdentifier`
4. **Processing Errors**: Review error messages in results['errors']

### Debug Mode

Enable debug logging for detailed information:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

parser = PSPReportParser()
results = parser.parse_pdf("report.pdf")
```

## Contributing

To extend the parser:

1. **Add New Table Types**: Update patterns in `TableIdentifier`
2. **Add Processing Logic**: Implement new methods in `TableProcessor`
3. **Handle New Exceptions**: Add special cases in `PDFExtractor`
4. **Update Documentation**: Keep this README current

## License

This project is part of the PSP Report analysis system. 