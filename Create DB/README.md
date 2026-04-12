# PSP Report Database Creation

This folder contains all the necessary files to create the `power_data.db` SQLite database from PSP (Power Supply Position) PDF reports.

## 📁 Files Overview

### Core Database Files
- **`setup_database.py`** - Creates the SQLite database schema with all dimension and fact tables
- **`Data_Insertion.py`** - Handles all database insertion logic for fact and dimension tables
- **`SQL_power_data.sql`** - SQL schema definitions for reference

### PDF Processing Files
- **`modular_psp_parser.py`** - Main PDF parsing and table transformation logic
- **`extract_tables.py`** - Extracts tables from PDFs using tabula-py
- **`get_report_url.py`** - Downloads PDF reports from NLDC website
- **`pdf_pipeline_dag.py`** - Orchestrates the complete PDF processing workflow

### Utility Files
- **`process_psp_data.py`** - Additional data processing utilities
- **`requirements.txt`** - Python package dependencies
- **`chromedriver.exe`** - Required for web scraping PDF URLs
- **`Release-24.08.0-0/`** - Poppler utilities for PDF processing

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Setup Database Schema
```bash
python setup_database.py
```

### 3. Process PDF Reports
```bash
python pdf_pipeline_dag.py
```

## 📊 Database Schema

The database uses a **star schema** design with:

### Dimension Tables
- **DimDates** - Date dimension with year, month, day
- **DimRegions** - Power regions (NR, ER, WR, SR, NER)
- **DimStates** - Indian states and territories
- **DimCountries** - International countries (Bhutan, Nepal, Bangladesh)
- **DimGenerationSources** - Power generation sources (Nuclear, Thermal, Hydro, etc.)
- **DimTransmissionLines** - Transmission line information
- **DimExchangeMechanisms** - Exchange mechanism types
- **DimReports** - Report metadata

### Fact Tables
- **FactAllIndiaDailySummary** - Daily all-India power statistics
- **FactDailyGenerationBreakdown** - Generation breakdown by source
- **FactStateDailyEnergy** - State-wise energy data
- **FactCountryDailyExchange** - International power exchange
- **FactTransmissionLinkFlow** - Inter-region transmission data
- **FactInternationalTransmissionLinkFlow** - International transmission lines
- **FactTransnationalExchangeDetail** - Detailed transnational exchange
- **FactTimeBlockPowerData** - 15-minute block-wise power data
- **FactTimeBlockGeneration** - Block-wise generation breakdown

## 🔄 Processing Workflow

1. **PDF Download** → `get_report_url.py`
2. **Table Extraction** → `extract_tables.py`
3. **Table Parsing** → `modular_psp_parser.py`
4. **Database Setup** → `setup_database.py`
5. **Data Insertion** → `Data_Insertion.py`
6. **Pipeline Orchestration** → `pdf_pipeline_dag.py`

## 📋 Table Types Supported

The parser handles these table types from PSP reports:
- **Regional Summary** - All-India demand and generation data
- **States** - State-wise power supply position
- **Transnational Exchange** - International power exchange
- **Inter-Region Transmission** - Regional transmission flows
- **International Transmission** - International transmission lines
- **Cross Border Exchange** - Detailed border exchange data
- **Block-Wise Data** - 15-minute interval power data
- **Demand Diversity Factor** - DDF calculations

## ⚙️ Configuration

- **Database Path**: `power_data.db` (SQLite)
- **PDF Source**: NLDC website
- **Time Format**: HH:MM (24-hour format)
- **Block Intervals**: 15-minute blocks (96 blocks per day)

## 🐛 Troubleshooting

### Common Issues
1. **Missing Poppler**: Ensure `Release-24.08.0-0/` folder is present
2. **ChromeDriver**: Ensure `chromedriver.exe` is in the same directory
3. **Dependencies**: Run `pip install -r requirements.txt`
4. **Database Lock**: Close any open database connections

### Debug Files
- Check `batch_processing.log` for processing errors
- Use `debug_missing_fact_data.py` to identify missing dates
- Use `analyze_missing_dates_comprehensive.py` for detailed analysis

## 📈 Data Quality

The system includes robust error handling:
- **Missing Data**: Logs warnings and continues processing
- **Invalid Formats**: Attempts to clean and standardize data
- **Foreign Keys**: Ensures referential integrity
- **Data Validation**: Checks for realistic values

## 🔗 Dependencies

- **Python 3.8+**
- **pandas** - Data manipulation
- **sqlite3** - Database operations
- **tabula-py** - PDF table extraction
- **PyPDF2** - PDF text extraction
- **selenium** - Web scraping
- **requests** - HTTP requests

## 📝 Notes

- The database uses **INSERT OR REPLACE** to handle duplicate data
- Time blocks are **1-based indexed** (1-96 for 96 blocks)
- All dates are stored in **YYYY-MM-DD** format
- Energy values are in **MU** (Million Units)
- Power values are in **MW** (Megawatts) 