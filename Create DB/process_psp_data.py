import pdfplumber
import pandas as pd
import os
from datetime import datetime

def extract_tables_from_pdf(pdf_path):
    """
    Extract all tables from the PDF file
    """
    print(f"Reading PDF file: {pdf_path}")
    all_tables = []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"Number of pages in PDF: {len(pdf.pages)}")
            
            for page_num, page in enumerate(pdf.pages, 1):
                print(f"Processing page {page_num}")
                tables = page.extract_tables()
                
                if tables:
                    for table in tables:
                        # Clean the table data
                        cleaned_table = []
                        for row in table:
                            # Remove None values and clean strings
                            cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
                            cleaned_table.append(cleaned_row)
                        
                        all_tables.append(cleaned_table)
    
    except Exception as e:
        print(f"Error reading PDF: {str(e)}")
        raise
    
    return all_tables

def process_tables(tables):
    """
    Process and organize the extracted tables
    """
    processed_data = {}
    current_section = None
    
    for table in tables:
        if not table or len(table) < 2:  # Skip empty tables or tables with less than 2 rows
            continue
            
        # Check if first row contains section header
        first_row = table[0]
        if len(first_row) > 0 and first_row[0]:
            # This might be a section header
            header = first_row[0].strip()
            if any(section in header for section in ['India', 'International', 'NR', 'WR', 'SR', 'ER', 'NER', 'States', 'Inter-Region', 'Exchange', 'Block-wise']):
                current_section = header
                # Remove the header row from the table
                table = table[1:]
        
        if current_section:
            if current_section not in processed_data:
                processed_data[current_section] = []
            processed_data[current_section].extend(table)
    
    return processed_data

def save_to_csv(data, output_path):
    """
    Save processed data to CSV file
    """
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        for section, table_data in data.items():
            # Write section header
            f.write(f"{section}\n")
            
            if table_data:
                # Write the table data
                for row in table_data:
                    f.write(','.join(row) + '\n')
                
                # Add spacing between sections
                f.write('\n\n')

def main():
    # Input and output paths
    input_pdf = 'sample input/19.04.25_NLDC_PSP.pdf'
    output_csv = 'sample output/Processed_PSP.csv'
    
    print(f"Starting processing...")
    print(f"Input file: {input_pdf}")
    print(f"Output file: {output_csv}")
    
    # Create output directory if it doesn't exist
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    
    # Extract tables from PDF
    tables = extract_tables_from_pdf(input_pdf)
    
    # Process the tables
    processed_data = process_tables(tables)
    
    # Save to CSV
    save_to_csv(processed_data, output_csv)
    
    print(f"Data processing complete. Output saved to {output_csv}")

if __name__ == "__main__":
    main()