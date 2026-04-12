# neo4j_uploader.py
# -----------------
# This script defines a dedicated tool for uploading structured pandas DataFrames
# to a Neo4j graph database. It's designed to be imported and used by the
# main agentic orchestrator.

import logging
from neo4j import GraphDatabase
import re

class Neo4jUploader:
    """Manages the connection to Neo4j and data uploading."""
    def __init__(self, uri, user, password):
        try:
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            logging.info("Successfully connected to Neo4j.")
        except Exception as e:
            logging.error(f"Failed to create Neo4j driver: {e}")
            self._driver = None

    def close(self):
        if self._driver: self._driver.close(); logging.info("Neo4j connection closed.")

    def _execute_query(self, query, parameters=None):
        if not self._driver: return
        with self._driver.session() as session:
            try: session.run(query, parameters)
            except Exception as e: logging.error(f"Query failed for query:\n{query}\nParams: {parameters}\nError: {e}")

    def setup_constraints(self):
        logging.info("Setting up database constraints...")
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Report) REQUIRE r.report_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Region) REQUIRE r.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:State) REQUIRE s.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (gs:GenerationSource) REQUIRE gs.type IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (pl:PowerLine) REQUIRE pl.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:PeakDemand) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (b:BlockData) REQUIRE b.id IS UNIQUE",
        ]
        for query in queries: self._execute_query(query)
        logging.info("Constraints are set.")

    def upload_dataframes(self, dataframes: list, report_info: dict):
        """
        Uploads a list of processed pandas DataFrames to Neo4j.
        Each DataFrame is identified by its 'Table Name' column.
        """
        if not dataframes:
            logging.error("No DataFrames provided to upload.")
            return

        report_date = report_info.get('date', 'Unknown Date')
        report_id = report_info.get('id', f"report_{report_date.replace('-', '')}")

        self._execute_query("MERGE (r:Report {report_id: $id}) SET r.date = $date", {'id': report_id, 'date': report_date})
        for region in ['NR', 'WR', 'SR', 'ER', 'NER']: self._execute_query("MERGE (r:Region {name: $name})", {'name': region})

        # Route each dataframe to its specific upload handler
        for df in dataframes:
            table_name = df['Table Name'].iloc[0] if 'Table Name' in df.columns and not df.empty else 'Unknown'
            logging.info(f"Uploading data for table: {table_name}")

            if table_name == 'States':
                self._upload_state_data(df, report_id)
            elif table_name == 'Regional Summary':
                self._upload_regional_summary_data(df, report_id)
            elif table_name == 'Inter-Region':
                self._upload_inter_regional_exchanges(df, report_id)
            elif table_name == 'International':
                self._upload_international_exchanges(df, report_id)
            elif table_name == 'Exchange':
                 self._upload_cross_border_schedule(df, report_id)
            elif table_name == 'Block-wise':
                 self._upload_blockwise_data(df, report_id)
            else:
                logging.warning(f"No uploader found for table name: {table_name}")


        logging.info("Data upload to Neo4j complete.")

    def _upload_state_data(self, df, report_id):
        records = df.to_dict('records')
        for state in records:
            if isinstance(state, dict) and state.get('States') and state.get('Region'):
                self._execute_query(
                    """
                    MERGE (s:State {name: $state_name})
                    MERGE (r:Region {name: $region_name})
                    MERGE (r)-[:HAS_STATE]->(s)
                    WITH s
                    MATCH (report:Report {report_id: $report_id})
                    MERGE (s)-[rel:HAS_METRICS_ON]->(report)
                    SET rel += {
                        date: $date,
                        max_demand_met_mw: toFloat($max_demand),
                        energy_met_mu: toFloat($energy_met),
                        energy_shortage_mu: toFloat($energy_shortage)
                    }
                    """,
                    {
                        'state_name': state.get('States'), 
                        'region_name': state.get('Region'), 
                        'date': state.get('Date'), 
                        'report_id': report_id,
                        'max_demand': state.get('Maximum Demand (MW)'), 
                        'energy_met': state.get('Energy Met (MU)'), 
                        'energy_shortage': state.get('Energy Shortage (MU)')
                    }
                )
    
    def _upload_regional_summary_data(self, df, report_id):
        records = df.to_dict('records')
        for record in records:
            region_name = record.get('Table Name') # In the transformed summary, region is 'Table Name'
            if not region_name or region_name == 'India': continue

            # Example for one metric. This can be expanded for all metrics.
            if 'G_Main_Coal' in record:
                self._execute_query("MERGE (gs:GenerationSource {type: 'Coal'})", {})
                self._execute_query(
                    """
                    MATCH (r:Region {name: $region_name})
                    MATCH (gs:GenerationSource {type: 'Coal'})
                    MATCH (report:Report {report_id: $report_id})
                    MERGE (r)-[rel:GENERATED_FROM {date: $date}]->(gs)
                    SET rel.gross_generation_mu = toFloat($gen_mu)
                    """,
                    {'region_name': region_name, 'date': record.get('Date'), 'report_id': report_id, 'gen_mu': record.get('G_Main_Coal')}
                )
    
    def _upload_inter_regional_exchanges(self, df, report_id):
        records = df.to_dict('records')
        for ex in records:
            source_match = re.search(r'\(With (\w+)\)', str(ex.get('Import', '')))
            if source_match:
                source_region = source_match.group(1)
                target_region = ex.get('Import').split(' ')[-1].replace(')', '') # Heuristic
                
                if ex.get('Line Details') and source_region and target_region:
                    self._execute_query(
                        """
                        MERGE (source:Region {name: $source_region})
                        MERGE (target:Region {name: $target_region})
                        MERGE (pl:PowerLine {name: $line_details})
                        SET pl.voltage = $voltage
                        
                        MATCH (report:Report {report_id: $report_id})
                        MERGE (source)-[rel:EXCHANGED_POWER_VIA {date: $date}]->(target)
                        SET rel.power_line_name = $line_details,
                            rel.net_mu = toFloat($net_mu)
                        MERGE (rel)-[:PART_OF_REPORT]->(report)
                        """,
                        {
                            'source_region': source_region, 'target_region': target_region,
                            'line_details': ex.get('Line Details'), 'voltage': ex.get('Voltage Level'),
                            'net_mu': ex.get('NET Import (MU)'), 'date': ex.get('Date'), 'report_id': report_id
                        }
                    )

    def _upload_international_exchanges(self, df, report_id):
        records = df.to_dict('records')
        self._execute_query("MERGE (i:Country {name: 'India'})")
        for ex in records:
            country_name = ex.get('State') # In this table, the country is in the 'State' column
            if country_name in ['BHUTAN', 'NEPAL', 'BANGLADESH']:
                 self._execute_query(
                    """
                    MERGE (c:Country {name: $country})
                    WITH c
                    MATCH (i:Country {name: 'India'})
                    MATCH (rp:Report {report_id: $report_id})
                    MERGE (c)-[rel:EXCHANGED_WITH_ON_DATE {date: $date}]->(i)
                    SET rel.energy_exchange_mu = toFloat($energy_exchange)
                    """,
                    {'country': country_name, 'date': ex.get('Date'), 'report_id': report_id, 'energy_exchange': ex.get('Energy Exchange (MU)')}
                )

    def _upload_cross_border_schedule(self, df, report_id):
        records = df.to_dict('records')
        for item in records:
            if item.get('Country') and item.get('Type'):
                self._execute_query(
                    """
                    MERGE (c:Country {name: $country})
                    WITH c
                    MATCH (r:Report {report_id: $report_id})
                    MERGE (c)-[rel:HAS_TRADE_SCHEDULE {date: $date, type: $type}]->(r)
                    SET rel.total_mu = toFloat($total)
                    """,
                    {'country': item.get('Country'), 'type': item.get('Type'), 'date': item.get('Date'), 
                     'report_id': report_id, 'total': item.get('Total')}
                )

    def _upload_blockwise_data(self, df, report_id):
        records = df.to_dict('records')
        for block in records:
            time = block.get('TIME')
            if time:
                self._execute_query(
                    """
                    MATCH (r:Report {report_id: $report_id})
                    MERGE (b:BlockData {id: $id})
                    SET b.time = $time,
                        b.frequency_hz = toFloat($freq)
                    MERGE (r)-[:HAS_BLOCK_DATA]->(b)
                    """,
                    {'id': f"{report_id}_{time}", 'report_id': report_id, 'time': time, 'freq': block.get('FREQUENCY (Hz)')}
                )

