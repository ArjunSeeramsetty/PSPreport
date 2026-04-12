import sqlite3

conn = sqlite3.connect('power_data.db')
cursor = conn.cursor()

print("=== Generation Sources ===")
cursor.execute("SELECT * FROM DimGenerationSources WHERE SourceName IN ('Coal', 'Hydro', 'Nuclear', 'Gas, Naptha & Diesel', 'Lignite', 'RE', 'Total')")
for row in cursor.fetchall():
    print(row)

print("\n=== Regions ===")
cursor.execute("SELECT * FROM DimRegions WHERE RegionName IN ('Northern Region', 'Western Region', 'Southern Region', 'Eastern Region', 'North Eastern Region')")
for row in cursor.fetchall():
    print(row)

print("\n=== FactDailyGenerationBreakdown (last 5 rows) ===")
cursor.execute("SELECT * FROM FactDailyGenerationBreakdown ORDER BY DateID DESC LIMIT 5")
for row in cursor.fetchall():
    print(row)

print("\n=== FactAllIndiaDailySummary (last 5 rows) ===")
cursor.execute("SELECT * FROM FactAllIndiaDailySummary ORDER BY DateID DESC LIMIT 5")
for row in cursor.fetchall():
    print(row)

# Debug: Check what columns are actually in the Regional Summary dataframe
print("\n=== Debug: Regional Summary DataFrame Columns ===")
try:
    from custom_pdf_parser import PDFParser
    from Data_Insertion import DataLoader
    
    pdf_path = "Output/NLDC_PSP_URLS/2023-24/JULY/reports/23.07.23_NLDC_PSP.pdf"
    parser = PDFParser()
    dataframes_list = parser.process_pdf(pdf_path)
    
    for i, df in enumerate(dataframes_list):
        if df is not None and not df.empty and 'Table Name' in df.columns:
            table_name = df['Table Name'].iloc[0]
            if table_name == 'Regional Summary':
                print(f"Regional Summary DataFrame Columns: {df.columns.tolist()}")
                print(f"First row: {df.iloc[0].to_dict()}")
                break
except Exception as e:
    print(f"Error debugging: {e}")

conn.close() 