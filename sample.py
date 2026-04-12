# deterministic_graph_builder.py
# --------------------------------
# This script creates a Neo4j graph from the PDF report using a direct,
# deterministic process without any LLM or agentic framework.

# --- SETUP ---
# 1. Make sure `PDFparser_Gemini.py` is in the same directory.
# 2. Update the `NEO4J_CONFIG` and `PDF_PATH` variables below.
# 3. Ensure your Neo4j database is running.
# 4. Install Required Python Libraries:
#    - pip install neo4j pandas tabula-py PyPDF2

import logging
import os
from PDFparser_Gemini import PDFParser
from neo4j import GraphDatabase
import pandas as pd
import re
import glob
from datetime import datetime

# --- CONFIGURATION ---
NEO4J_CONFIG = {
    "uri": "neo4j://localhost:7687",
    "user": "neo4j",
    "password": "powerflow"
}
PDF_PATH = "sample input/19.04.25_NLDC_PSP.pdf"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Neo4jUploader:
    """Manages the connection to Neo4j and data uploading."""
    def __init__(self, uri, user, password):
        try:
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            logging.info("Successfully connected to Neo4j.")
        except Exception as e:
            logging.error(f"Failed to create Neo4j driver: {e}")
            self._driver = None
        self.region_set = {'NR', 'WR', 'SR', 'ER', 'NER'}

    def close(self):
        if self._driver: self._driver.close(); logging.info("Neo4j connection closed.")

    def _execute_query(self, query, parameters=None):
        if not self._driver: return
        with self._driver.session() as session:
            try: session.run(query, parameters)
            except Exception as e: logging.error(f"Query failed for query:\n{query}\nParams: {parameters}\nError: {e}")

    def _sanitize_property_name(self, name: str) -> str:
        """Sanitizes a string to be a valid Cypher property name."""
        return re.sub(r'[^a-zA-Z0-9_]', '_', name)

    def setup_constraints(self):
        logging.info("Setting up database constraints...")
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Report) REQUIRE r.report_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Region) REQUIRE r.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:State) REQUIRE s.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (gs:GenerationSource) REQUIRE gs.type IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (pl:PowerLine) REQUIRE pl.name IS UNIQUE",
        ]
        for query in queries: self._execute_query(query)
        logging.info("Constraints are set.")

    def upload_dataframes(self, dataframes: list, report_info: dict):
        if not dataframes:
            logging.error("No DataFrames provided to upload.")
            return
        
        report_date = report_info.get('date', 'Unknown Date')
        report_id = report_info.get('id', f"report_{report_date.replace('-', '')}")

        self._execute_query("MERGE (r:Report {report_id: $id}) SET r.date = $date", {'id': report_id, 'date': report_date})
        for region in self.region_set:
            self._execute_query("""
                MERGE (r:Region {name: $name})
                WITH r
                MATCH (report:Report {report_id: $report_id})
                MERGE (r)-[:IN_REPORT]->(report)
            """, {'name': region, 'report_id': report_id})
        self._execute_query("""
            MERGE (c:Country {name: 'India'})
            WITH c
            MATCH (report:Report {report_id: $report_id})
            MERGE (c)-[:IN_REPORT]->(report)
            WITH c
            MATCH (r:Region)
            MERGE (c)-[:HAS_REGION]->(r)
        """, {'report_id': report_id})

        # Track countries found in data
        countries_in_data = set()
        for df in dataframes:
            table_name = df['Table Name'].iloc[0] if 'Table Name' in df.columns and not df.empty else 'Unknown'
            if table_name == 'International' or table_name == 'International NET' or table_name == 'Exchange':
                # Collect country names from these tables
                for col in df.columns:
                    if col.lower() in ['state', 'country']:
                        countries_in_data.update(df[col].dropna().map(str.title))
                for col in df.columns:
                    if any(x in col.lower() for x in ['bhutan', 'nepal', 'bangladesh', 'myanmar', 'godda']):
                        countries_in_data.add(col.split()[0].title())
            # No need to process other tables for country names
        # Remove India if present
        countries_in_data.discard('India')
        # Create/link only those country nodes
        for country in countries_in_data:
            self._execute_query("""
                MERGE (c:Country {name: $name})
                WITH c
                MATCH (report:Report {report_id: $report_id})
                MERGE (c)-[:IN_REPORT]->(report)
            """, {'name': country, 'report_id': report_id})

        for df in dataframes:
            table_name = df['Table Name'].iloc[0] if 'Table Name' in df.columns and not df.empty else 'Unknown'
            if table_name in self.region_set or table_name == 'India':
                self._upload_regional_summary_data(df, report_id)
            elif table_name == 'States':
                self._upload_state_data(df, report_id)
            elif table_name == 'Inter-Region':
                self._upload_inter_regional_exchanges(df, report_id)
            elif table_name == 'International':
                self._upload_international_powerlines(df, report_id)
            elif table_name == 'International NET':
                self._upload_international_net_exchanges(df, report_id)
            elif table_name == 'Exchange':
                self._upload_cross_border_schedule(df, report_id)
            elif table_name == 'Block-wise':
                self._upload_blockwise_data(df, report_id)
            else:
                logging.warning(f"No specific uploader found for table name: '{table_name}'. Skipping.")

        logging.info("Data upload to Neo4j complete.")

    def _upload_state_data(self, df, report_id):
        records = df.to_dict('records')
        for state in records:
            state_name = state.get('States')
            if isinstance(state, dict) and state_name and state.get('Region'):
                if str(state_name).strip().lower() in ['other', 'others']:
                    continue
                node_props = {self._sanitize_property_name(k): v for k, v in state.items() if k not in ['States', 'Region', 'Date', 'Table Name'] and pd.notna(v)}
                node_props['name'] = state_name
                set_clause = ", ".join([f"s.`{k}` = toFloat(${k})" for k in node_props if k != 'name'])
                params = node_props.copy()
                params['report_id'] = report_id
                self._execute_query(
                    f"""
                    MERGE (s:State {{name: $name}})
                    SET {set_clause}
                    WITH s
                    MATCH (report:Report {{report_id: $report_id}})
                    MERGE (s)-[:IN_REPORT]->(report)
                    """,
                    params
                )

    def _upload_regional_summary_data(self, df, report_id):
        records = df.to_dict('records')
        gen_source_map = {
            'G_Main_Coal': 'Coal',
            'G_Main_Gas__Naptha___Diesel': 'Gas/Naptha/Diesel',
            'G_Main_Hydro': 'Hydro',
            'G_Main_Lignite': 'Lignite',
            'G_Main_Nuclear': 'Nuclear',
            'G_Main_RES__Wind__Solar__Biomass___Others_': 'Renewables',
            'A_Solar_Gen__MU__': 'Solar',
            'A_Wind_Gen__MU_': 'Wind',
            'G_Main_Total': 'Total'
        }
        for record in records:
            node_name = record.get('Table Name')
            if not node_name or str(node_name).strip().lower() in ['other', 'others']:
                continue
            node_label = "Region" if node_name in self.region_set else "Country"
            metrics = {k: v for k, v in record.items() if k not in ['Table Name', 'Date'] and pd.notna(v)}
            node_props = {self._sanitize_property_name(k): v for k, v in metrics.items()}
            node_props['name'] = node_name
            set_clause = ", ".join([f"n.`{k}` = toFloat(${k})" for k in node_props if k != 'name'])
            params = node_props.copy()
            params['node_name'] = node_name
            params['report_id'] = report_id
            self._execute_query(
                f"""
                MERGE (n:{node_label} {{name: $node_name}})
                SET {set_clause}
                WITH n
                MATCH (report:Report {{report_id: $report_id}})
                MERGE (n)-[:IN_REPORT]->(report)
                """,
                params
            )
            # Generation sources as before
            for metric, value in metrics.items():
                sanitized_metric = self._sanitize_property_name(metric)
                if sanitized_metric in gen_source_map:
                    source_type = gen_source_map[sanitized_metric]
                    self._execute_query("MERGE (gs:GenerationSource {type: $type})", {'type': source_type})
                    self._execute_query(f"""
                        MATCH (n:{node_label} {{name: $node_name}})
                        MATCH (gs:GenerationSource {{type: $source_type}})
                        MERGE (n)-[rel:GENERATED_FROM]->(gs)
                        SET rel.gross_generation_mu = toFloat($value)
                        """, {'node_name': node_name, 'source_type': source_type, 'value': value})

    def _upload_inter_regional_exchanges(self, df, report_id):
        records = df.to_dict('records')
        logging.info(f"Processing {len(records)} potential inter-regional exchange rows...")
        for ex in records:
            import_info = ex.get('Import', '')
            line_details = ex.get('Line Details')

            # Skip summary/aggregate rows
            if not line_details or str(line_details).strip().lower() == "total":
                continue

            # Parse source and target from Import column (e.g., "ER-NR")
            match = re.match(r'([A-Z]{2,3})-([A-Z]{2,3})', str(import_info).strip())
            if match:
                source_region, target_region = match.groups()
                if source_region in self.region_set and target_region in self.region_set:
                    logging.info(f"Creating PowerLine: {line_details} between {source_region} and {target_region}")
                    # Add all numeric properties to PowerLine node
                    pl_props = {self._sanitize_property_name(k): v for k, v in ex.items() if k not in ['Import', 'Region', 'Date', 'Table Name'] and pd.notna(v)}
                    pl_props['name'] = line_details
                    set_clause = ", ".join([f"pl.`{k}` = toFloat(${k})" for k in pl_props if k != 'name'])
                    params = pl_props.copy()
                    params['source_region'] = source_region
                    params['target_region'] = target_region
                    params['report_id'] = report_id
                    self._execute_query(
                        f"""
                        MERGE (source:Region {{name: $source_region}})
                        MERGE (target:Region {{name: $target_region}})
                        MERGE (pl:PowerLine {{name: $name}})
                        SET {set_clause}
                        WITH source, target, pl
                        MATCH (report:Report {{report_id: $report_id}})
                        MERGE (pl)-[:IN_REPORT]->(report)
                        MERGE (source)-[:USES_POWERLINE]->(pl)
                        MERGE (pl)-[:CONNECTS]->(target)
                        """,
                        params
                    )
                else:
                    logging.warning(f"Skipping PowerLine {line_details} due to invalid region codes: {import_info}")
            else:
                logging.warning(f"Skipping row with Import='{import_info}' (could not parse regions)")

    def _upload_international_powerlines(self, df, report_id):
        records = df.to_dict('records')
        for ex in records:
            region = ex.get('Region', '')
            if isinstance(region, str) and 'Isolated from Indian Grid' in region:
                region = 'ER'
            country = ex.get('State', '').title()  # Convert to title case for case-insensitive matching
            line_details = ex.get('Line Name', '')
            if not region or not country or not line_details or str(line_details).strip().lower() == 'total':
                continue
            # Add all numeric properties to PowerLine node
            pl_props = {self._sanitize_property_name(k): v for k, v in ex.items() if k not in ['Region', 'State', 'Date', 'Table Name'] and pd.notna(v)}
            pl_props['name'] = line_details
            set_clause = ", ".join([f"pl.`{k}` = toFloat(${k})" for k in pl_props if k != 'name'])
            params = pl_props.copy()
            params['region'] = region
            params['country'] = country
            params['report_id'] = report_id
            self._execute_query(
                f"""
                MERGE (reg:Region {{name: $region}})
                MERGE (c:Country {{name: $country}})
                MERGE (pl:PowerLine {{name: $name}})
                SET {set_clause}
                WITH reg, c, pl
                MATCH (report:Report {{report_id: $report_id}})
                MERGE (pl)-[:IN_REPORT]->(report)
                MERGE (reg)-[:USES_POWERLINE]->(pl)
                MERGE (pl)-[:CONNECTS]->(c)
                """,
                params
            )

    def _upload_international_net_exchanges(self, df, report_id):
        records = df.to_dict('records')
        for ex in records:
            # Extract all numerical properties for the relationship
            rel_props = {self._sanitize_property_name(k): v for k, v in ex.items() if k not in ['Date', 'Table Name'] and pd.notna(v)}
            if not rel_props:
                continue
            # Create relationships for each country
            countries = ['Bhutan', 'Nepal', 'Bangladesh', 'Godda (Bangladesh)']
            for country in countries:
                # Find properties specific to this country
                country_props = {}
                for prop, value in rel_props.items():
                    if country.lower() in prop.lower():
                        country_props[prop] = value
                if country_props:
                    set_clause = ", ".join([f"rel.`{k}` = toFloat(${k})" for k in country_props])
                    params = country_props.copy()
                    params['country'] = country
                    params['report_id'] = report_id
                    self._execute_query(
                        f"""
                        MERGE (c:Country {{name: $country}})
                        WITH c
                        MATCH (i:Country {{name: 'India'}})
                        MATCH (report:Report {{report_id: $report_id}})
                        MERGE (c)-[rel:HAS_TRADE_SCHEDULE]->(i)
                        SET {set_clause}
                        WITH c
                        MERGE (c)-[:IN_REPORT]->(report)
                        """,
                        params
                    )

    def _upload_cross_border_schedule(self, df, report_id):
        records = df.to_dict('records')
        for item in records:
            if item.get('Country') and item.get('Type'):
                self._execute_query(
                    """
                    MERGE (c:Country {name: $country})
                    WITH c
                    MATCH (i:Country {name: 'India'})
                    MATCH (report:Report {report_id: $report_id})
                    MERGE (c)-[rel:HAS_TRADE_SCHEDULE {date: $date, type: $type}]->(i)
                    SET rel.total_mu = toFloat($total)
                    WITH c
                    MERGE (c)-[:IN_REPORT]->(report)
                    """,
                    {'country': item.get('Country'), 'type': item.get('Type'), 'date': item.get('Date'), 
                     'report_id': report_id, 'total': item.get('Total')}
                )

    def _upload_blockwise_data(self, df, report_id):
        records = df.to_dict('records')
        logging.info(f"Uploading {len(records)} block-wise records.")
        for block in records:
            time = block.get('TIME')
            if time:
                params = {'id': f"{report_id}_{time}", 'report_id': report_id}
                set_clauses = []
                for key, value in block.items():
                    if key in ['Table Name', 'Date'] or pd.isna(value): continue
                    prop_name = self._sanitize_property_name(key)
                    params[prop_name] = value
                    set_clauses.append(f"b.`{prop_name}` = toFloat(${prop_name})")
                if set_clauses:
                    set_query_part = "SET " + ", ".join(set_clauses)
                    query = f"""
                        MATCH (report:Report {{report_id: $report_id}})
                        MERGE (b:BlockData {{id: $id}})
                        {set_query_part}
                        MERGE (b)-[:IN_REPORT]->(report)
                    """
                    self._execute_query(query, params)

def run_deterministic_workflow(pdf_path: str, clear_db: bool = False):
    """
    Orchestrates the deterministic workflow to process a PDF and build the graph.
    """
    logging.info("--- DETERMINISTIC WORKFLOW STARTED ---")

    logging.info(">>> Step 1: Parsing and Transforming PDF...")
    parser = PDFParser()
    processed_dataframes = parser.process_pdf(pdf_path)
    
    if not processed_dataframes:
        logging.error("Parsing and transformation failed. Halting workflow.")
        return

    logging.info(f">>> Step 1 Successful. Processed {len(processed_dataframes)} tables.")
    
    logging.info(">>> Step 2: Uploading to Neo4j...")
    uploader = Neo4jUploader(NEO4J_CONFIG['uri'], NEO4J_CONFIG['user'], NEO4J_CONFIG['password'])
    
        if uploader._driver:
        try:
            if clear_db:
            logging.info("Clearing existing database...")
            uploader._execute_query("MATCH (n) DETACH DELETE n")
            uploader.setup_constraints()
            report_date = parser._get_report_date_from_pdf(pdf_path)
            report_id = f"NLDC_PSP_{report_date.replace('/', '')}" if report_date != "Unknown Date" else "NLDC_PSP_UnknownDate"
            report_info = {'id': report_id, 'date': report_date}
            uploader.upload_dataframes(processed_dataframes, report_info)
        finally:
            uploader.close()
    else:
        logging.error("Could not connect to Neo4j. Upload step failed.")

    logging.info("--- DETERMINISTIC WORKFLOW FINISHED ---")

def extract_fy_start_year(fy_name):
    try:
        return int(fy_name.split('-')[0])
    except Exception:
        return 0

FY_MONTHS = [
    "MARCH", "FEBRUARY", "JANUARY", "DECEMBER", "NOVEMBER", "OCTOBER",
    "SEPTEMBER", "AUGUST", "JULY", "JUNE", "MAY", "APRIL"
]

def process_all_pdfs_data_insertion_style(pdf_base_dir):
    all_pdf_paths = []
    for fy in sorted(os.listdir(pdf_base_dir), key=extract_fy_start_year, reverse=True):
        fy_path = os.path.join(pdf_base_dir, fy)
        if not os.path.isdir(fy_path):
            continue
        for month in FY_MONTHS:
            month_path = os.path.join(fy_path, month)
            if not os.path.isdir(month_path):
                continue
            reports_dir = os.path.join(month_path, "reports")
            if not os.path.isdir(reports_dir):
                continue
            pdfs = [f for f in os.listdir(reports_dir) if f.lower().endswith('.pdf')]
            def extract_date_from_filename(filename):
                try:
                    date_part = filename.split('_')[0]
                    return datetime.strptime(date_part, "%d.%m.%y")
                except Exception:
                    return datetime.min
            pdfs_sorted = sorted(pdfs, key=extract_date_from_filename, reverse=True)
            for pdf_file in pdfs_sorted:
                pdf_path = os.path.join(reports_dir, pdf_file)
                all_pdf_paths.append(pdf_path)
    for i, pdf_path in enumerate(all_pdf_paths):
        logging.info(f"Processing PDF: {pdf_path}")
        run_deterministic_workflow(pdf_path, clear_db=(i == 0))

if __name__ == "__main__":
    pdf_base_dir = r"C:\Users\arjun\Desktop\PSPreport\Output\NLDC_PSP_URLS"
    process_all_pdfs_data_insertion_style(pdf_base_dir)
