import tabula
import pandas as pd
import os
from pathlib import Path
import numpy as np
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
import json
import re

class TableTransformer:
    def __init__(self):
        # Initialize the LLM model
        self.tokenizer = AutoTokenizer.from_pretrained("gpt2")
        self.model = AutoModelForCausalLM.from_pretrained("gpt2")
        
        # Define table type prompts
        self.table_prompts = {
            'States': """Analyze this table and transform it to match the States.csv format:
            - Date, Region, States, Maximum Demand (MW), Shortage (MW), Energy Met (MU), Drawal Schedule (MU), OD(+)/UD(-) (MU), Max OD (MW), Energy Shortage (MU)
            - Ensure numeric columns are properly formatted
            - Forward fill Date and Region columns
            - Remove empty rows""",
            
            'International NET': """Transform this table to match International NET.csv format:
            - Date, Region, Import/Export, Value
            - Ensure proper date formatting
            - Clean up any special characters""",
            
            'Inter Region': """Transform this table to match Inter Region.csv format:
            - Date, From Region, To Region, Value
            - Ensure proper region names
            - Clean up any special characters""",
            
            'International': """Transform this table to match International.csv format:
            - Date, Country, Import/Export, Value
            - Ensure proper country names
            - Clean up any special characters""",
            
            'Exchange': """Transform this table to match Exchange.csv format:
            - Date, Region, Import/Export, Value
            - Ensure proper region names
            - Clean up any special characters""",
            
            'Blockwise': """Transform this table to match Blockwise.csv format:
            - Date, Time Block, Value
            - Ensure proper time block formatting
            - Clean up any special characters""",
            
            # Add prompts for regional tables
            'India': """Transform this table to match India.csv format:
            - Date, Value
            - Ensure proper date formatting
            - Clean up any special characters
            - Ensure numeric values are properly formatted""",
            
            'NR': """Transform this table to match NR.csv format:
            - Date, Value
            - Ensure proper date formatting
            - Clean up any special characters
            - Ensure numeric values are properly formatted""",
            
            'WR': """Transform this table to match WR.csv format:
            - Date, Value
            - Ensure proper date formatting
            - Clean up any special characters
            - Ensure numeric values are properly formatted""",
            
            'SR': """Transform this table to match SR.csv format:
            - Date, Value
            - Ensure proper date formatting
            - Clean up any special characters
            - Ensure numeric values are properly formatted""",
            
            'ER': """Transform this table to match ER.csv format:
            - Date, Value
            - Ensure proper date formatting
            - Clean up any special characters
            - Ensure numeric values are properly formatted""",
            
            'NER': """Transform this table to match NER.csv format:
            - Date, Value
            - Ensure proper date formatting
            - Clean up any special characters
            - Ensure numeric values are properly formatted"""
        }
        
        # Define valid table types
        self.valid_table_types = list(self.table_prompts.keys())
    
    def clean_table_type(self, table_type):
        """Clean and validate table type"""
        # Remove any non-alphanumeric characters
        cleaned_type = re.sub(r'[^a-zA-Z0-9]', '', table_type)
        
        # Check if the cleaned type is in our valid types
        for valid_type in self.valid_table_types:
            if cleaned_type.lower() == valid_type.lower():
                return valid_type
        
        # If no match found, return None
        return None
    
    def analyze_table_structure(self, table):
        """Use LLM to analyze table structure and determine its type"""
        # Convert table to string representation (limit to first 100 rows)
        table_str = table.head(100).to_string()
        
        # Create prompt for structure analysis
        prompt = f"""Analyze this table structure and determine its type:
        {table_str}
        
        Possible types:
        - States (contains state-wise data with demand, shortage, etc.)
        - International NET (contains international import/export data)
        - Inter Region (contains inter-region exchange data)
        - International (contains country-wise data)
        - Exchange (contains region-wise exchange data)
        - Blockwise (contains time block-wise data)
        - India (contains India-wide data)
        - NR (contains Northern Region data)
        - WR (contains Western Region data)
        - SR (contains Southern Region data)
        - ER (contains Eastern Region data)
        - NER (contains North Eastern Region data)
        
        Return only the type name."""
        
        # Get model prediction with increased max_length
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        outputs = self.model.generate(**inputs, max_new_tokens=50)
        prediction = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Clean and validate the prediction
        cleaned_type = self.clean_table_type(prediction)
        if cleaned_type:
            return cleaned_type
        
        # If cleaning fails, try to extract the type from the prediction
        for valid_type in self.valid_table_types:
            if valid_type.lower() in prediction.lower():
                return valid_type
        
        # If all else fails, return a default type
        return 'Other'
    
    def transform_table(self, table, table_type):
        """Transform table to desired format without using LLM for large tables"""
        # For large tables, use direct transformation
        if len(table) > 100:
            return self.transform_table_direct(table, table_type)
        
        # For smaller tables, use LLM
        try:
            # Convert table to JSON for better structure handling
            table_json = table.to_json(orient='records')
            
            # Get the appropriate prompt for this table type
            prompt = self.table_prompts.get(table_type, "Transform this table to a clean format:")
            
            # Create full prompt with table data
            full_prompt = f"{prompt}\n\nTable data in JSON format:\n{table_json}\n\nTransform the table and return the result in JSON format."
            
            # Get model prediction with increased max_length
            inputs = self.tokenizer(full_prompt, return_tensors="pt", truncation=True, max_length=512)
            outputs = self.model.generate(**inputs, max_new_tokens=1000)
            transformed_json = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            # Convert JSON back to DataFrame
            try:
                transformed_data = json.loads(transformed_json)
                return pd.DataFrame(transformed_data)
            except:
                # If JSON parsing fails, use direct transformation
                return self.transform_table_direct(table, table_type)
        except:
            # If LLM transformation fails, use direct transformation
            return self.transform_table_direct(table, table_type)
    
    def transform_table_direct(self, table, table_type):
        """Transform table directly without using LLM"""
        # Remove completely empty rows and columns
        table = table.dropna(how='all').dropna(axis=1, how='all')
        
        # Convert all values to string first
        table = table.astype(str)
        
        # Remove any special characters and extra spaces
        for col in table.columns:
            table[col] = table[col].str.strip().str.replace('\r', ' ').str.replace('\n', ' ')
        
        # Handle different table types
        if table_type == 'States':
            expected_columns = [
                'Date', 'Region', 'States', 'Maximum Demand (MW)', 
                'Shortage (MW)', 'Energy Met (MU)', 'Drawal Schedule (MU)',
                'OD(+)/UD(-) (MU)', 'Max OD (MW)', 'Energy Shortage (MU)'
            ]
            # Ensure we have the right number of columns
            if len(table.columns) < len(expected_columns):
                # Add missing columns
                for i in range(len(table.columns), len(expected_columns)):
                    table[f'Column_{i+1}'] = np.nan
            elif len(table.columns) > len(expected_columns):
                # Keep only the first len(expected_columns) columns
                table = table.iloc[:, :len(expected_columns)]
            
            # Set the column names
            table.columns = expected_columns
            
            # Convert numeric columns
            numeric_cols = ['Maximum Demand (MW)', 'Shortage (MW)', 'Energy Met (MU)', 
                           'Drawal Schedule (MU)', 'OD(+)/UD(-) (MU)', 'Max OD (MW)', 
                           'Energy Shortage (MU)']
            for col in numeric_cols:
                if col in table.columns:
                    table[col] = pd.to_numeric(table[col], errors='coerce')
            
            # Forward fill Date and Region
            table['Date'] = table['Date'].fillna(method='ffill')
            table['Region'] = table['Region'].fillna(method='ffill')
            
        elif table_type == 'International NET':
            expected_columns = ['Date', 'Region', 'Import/Export', 'Value']
            # Ensure we have the right number of columns
            if len(table.columns) < len(expected_columns):
                # Add missing columns
                for i in range(len(table.columns), len(expected_columns)):
                    table[f'Column_{i+1}'] = np.nan
            elif len(table.columns) > len(expected_columns):
                # Keep only the first len(expected_columns) columns
                table = table.iloc[:, :len(expected_columns)]
            table.columns = expected_columns
            
        elif table_type == 'Inter Region':
            expected_columns = ['Date', 'From Region', 'To Region', 'Value']
            # Ensure we have the right number of columns
            if len(table.columns) < len(expected_columns):
                # Add missing columns
                for i in range(len(table.columns), len(expected_columns)):
                    table[f'Column_{i+1}'] = np.nan
            elif len(table.columns) > len(expected_columns):
                # Keep only the first len(expected_columns) columns
                table = table.iloc[:, :len(expected_columns)]
            table.columns = expected_columns
            
        elif table_type == 'International':
            expected_columns = ['Date', 'Country', 'Import/Export', 'Value']
            # Ensure we have the right number of columns
            if len(table.columns) < len(expected_columns):
                # Add missing columns
                for i in range(len(table.columns), len(expected_columns)):
                    table[f'Column_{i+1}'] = np.nan
            elif len(table.columns) > len(expected_columns):
                # Keep only the first len(expected_columns) columns
                table = table.iloc[:, :len(expected_columns)]
            table.columns = expected_columns
            
        elif table_type == 'Exchange':
            expected_columns = ['Date', 'Region', 'Import/Export', 'Value']
            # Ensure we have the right number of columns
            if len(table.columns) < len(expected_columns):
                # Add missing columns
                for i in range(len(table.columns), len(expected_columns)):
                    table[f'Column_{i+1}'] = np.nan
            elif len(table.columns) > len(expected_columns):
                # Keep only the first len(expected_columns) columns
                table = table.iloc[:, :len(expected_columns)]
            table.columns = expected_columns
            
        elif table_type == 'Blockwise':
            expected_columns = ['Date', 'Time Block', 'Value']
            # Ensure we have the right number of columns
            if len(table.columns) < len(expected_columns):
                # Add missing columns
                for i in range(len(table.columns), len(expected_columns)):
                    table[f'Column_{i+1}'] = np.nan
            elif len(table.columns) > len(expected_columns):
                # Keep only the first len(expected_columns) columns
                table = table.iloc[:, :len(expected_columns)]
            table.columns = expected_columns
            
        # For regional tables (India, NR, WR, SR, ER, NER)
        elif table_type in ['India', 'NR', 'WR', 'SR', 'ER', 'NER']:
            expected_columns = ['Date', 'Value']
            # Ensure we have the right number of columns
            if len(table.columns) < len(expected_columns):
                # Add missing columns
                for i in range(len(table.columns), len(expected_columns)):
                    table[f'Column_{i+1}'] = np.nan
            elif len(table.columns) > len(expected_columns):
                # Keep only the first len(expected_columns) columns
                table = table.iloc[:, :len(expected_columns)]
            table.columns = expected_columns
        
        # Remove any rows where all values are empty
        table = table[~table.apply(lambda x: x.str.strip().eq('').all(), axis=1)]
        
        # Reset index
        table = table.reset_index(drop=True)
        
        return table
    
    def extract_regional_data(self, table):
        """Extract regional data from table 2 which contains all regional information"""
        # Define regional types
        regional_types = ['India', 'NR', 'WR', 'SR', 'ER', 'NER']
        
        # Dictionary to store regional data
        regional_data = {}
        
        # Convert table to string for analysis (limit to first 100 rows)
        table_str = table.head(100).to_string()
        
        # Create prompt for regional data extraction
        prompt = f"""Extract regional data from this table:
        {table_str}
        
        Extract data for each region:
        - India
        - NR (Northern Region)
        - WR (Western Region)
        - SR (Southern Region)
        - ER (Eastern Region)
        - NER (North Eastern Region)
        
        Return the data in JSON format with keys for each region."""
        
        # Get model prediction with increased max_length
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        outputs = self.model.generate(**inputs, max_new_tokens=1000)
        extracted_json = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Parse the extracted data
        try:
            extracted_data = json.loads(extracted_json)
            for region in regional_types:
                if region in extracted_data:
                    regional_data[region] = pd.DataFrame(extracted_data[region])
        except:
            # If parsing fails, try to extract data manually
            for region in regional_types:
                # Look for region-specific data in the table
                region_data = table[table.apply(lambda x: x.astype(str).str.contains(region, case=False).any(), axis=1)]
                if not region_data.empty:
                    regional_data[region] = region_data
        
        return regional_data

def extract_tables_from_pdf(pdf_path, output_dir):
    """
    Extract tables from a PDF file and save them as CSV files.
    
    Args:
        pdf_path (str): Path to the PDF file
        output_dir (str): Directory to save the extracted tables
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize table transformer
    transformer = TableTransformer()
    
    # Extract tables from the PDF
    print(f"Extracting tables from {pdf_path}...")
    tables = tabula.read_pdf(
        pdf_path,
        pages='all',
        multiple_tables=True,
        guess=True,
        lattice=True,
        stream=True
    )
    
    # Table mapping for primary tables
    table_mapping = {
        4: 'States',
        5: 'International NET',
        12: 'Inter Region',
        13: 'International',
        14: 'Exchange',
        15: 'Exchange',
        16: 'Exchange',
        17: 'Blockwise'
    }
    
    # Process each table
    for i, table in enumerate(tables):
        if not table.empty:
            table_number = i + 1
            
            # Special handling for table 2 (contains all regional data)
            if table_number == 2:
                # Extract regional data from table 2
                regional_data = transformer.extract_regional_data(table)
                
                # Save each regional table
                for region, data in regional_data.items():
                    output_file = os.path.join(output_dir, f"{region}.csv")
                    data.to_csv(output_file, index=False)
                    print(f"Saved {region} table to {output_file}")
                
                continue
            
            # Determine table type from mapping
            if table_number in table_mapping:
                table_type = table_mapping[table_number]
            else:
                # Use LLM to determine table type for unmapped tables
                table_type = transformer.analyze_table_structure(table)
            
            # Skip if table type is not valid
            if table_type not in transformer.valid_table_types:
                print(f"Skipping table {table_number} - invalid type: {table_type}")
                continue
            
            # Transform the table using LLM
            transformed_table = transformer.transform_table(table, table_type)
            
            # Save the transformed table
            output_file = os.path.join(output_dir, f"{table_type}.csv")
            transformed_table.to_csv(output_file, index=False)
            print(f"Saved {table_type} table to {output_file}")

def main():
    # Define input and output directories
    input_dir = "sample input"
    output_dir = "sample output"
    
    # Process all PDF files in the input directory
    for file in os.listdir(input_dir):
        if file.lower().endswith('.pdf'):
            pdf_path = os.path.join(input_dir, file)
            extract_tables_from_pdf(pdf_path, output_dir)

if __name__ == "__main__":
    main()