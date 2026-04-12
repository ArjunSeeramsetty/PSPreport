# /graph_builder/graph_model.py
# This file defines the schema of our knowledge graph: the types of nodes and relationships.
#
# REFINED TIMEBLOCK LOGIC:
# This version uses a lightweight model for time-series data to minimize node creation.
# 1. Only 96 canonical TimeBlock nodes are created once.
# 2. Daily data (frequency, demand) is stored as properties on a relationship
#    connecting a Report to the relevant canonical TimeBlock.
# This avoids creating hundreds of thousands of individual TimeBlock nodes.
#
# SUPERNODE PROBLEM SOLUTION:
# This implementation uses the MetricObservation pattern to solve the "supernode" problem.
# Instead of having a single Metric node connected to all reports (which creates visualization
# issues), each reported value becomes a unique MetricObservation node.
#
# Structure:
# (Report)-[:HAS_OBSERVATION]->(MetricObservation)-[:APPLIES_TO]->(Entity)
#                                          |
#                                          v
#                                     (Metric)
#
# Entity can be: State, Region, or Country
# This ensures that when querying for a specific entity, you only see the observations
# for that entity, not all observations from all entities.

import logging
import sqlite3
import os
from datetime import datetime
from neo4j import GraphDatabase
import re

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Canonical region mapping
REGION_ALIAS = {
    'NR': 'Northern Region',
    'N.R.': 'Northern Region',
    'NORTHERN REGION': 'Northern Region',
    'WR': 'Western Region',
    'W.R.': 'Western Region',
    'WESTERN REGION': 'Western Region',
    'SR': 'Southern Region',
    'S.R.': 'Southern Region',
    'SOUTHERN REGION': 'Southern Region',
    'ER': 'Eastern Region',
    'E.R.': 'Eastern Region',
    'EASTERN REGION': 'Eastern Region',
    'NER': 'North Eastern Region',
    'N.E.R.': 'North Eastern Region',
    'NORTH EASTERN REGION': 'North Eastern Region',
    'NORTH-EASTERN REGION': 'North Eastern Region',
    'INDIA': None,  # Do not create a Region node for India
    'ALL INDIA': None,
    'ALL-INDIA': None,
}

def canonical_region(name):
    if not name:
        return None
    key = str(name).strip().upper()
    canonical = REGION_ALIAS.get(key)
    if canonical is None and key in REGION_ALIAS:
        return None  # Explicitly mapped to None (e.g., 'INDIA')
    if canonical:
        return canonical
    # Try to match with regex for common patterns
    if key.replace(' ', '') in [k.replace(' ', '') for k in REGION_ALIAS]:
        for k, v in REGION_ALIAS.items():
            if key.replace(' ', '') == k.replace(' ', ''):
                return v
    # If not found, return the original name and print a warning
    if key not in REGION_ALIAS:
        print(f"[WARNING] Region name '{name}' is not canonicalized. Using as-is.")
    return name

class GraphModel:
    """
    Defines the Cypher queries to create nodes and relationships in the Neo4j graph.
    This centralized approach makes the graph schema easy to manage and update.
    """

    @staticmethod
    def create_constraints(tx):
        """
        Creates unique constraints on nodes to prevent duplicates and speed up lookups.
        This is a critical first step in ensuring data integrity.
        """
        logging.info("Creating graph constraints...")
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (y:Year) REQUIRE y.year IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Month) REQUIRE (m.year, m.month) IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Day) REQUIRE d.date IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Report) REQUIRE r.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (rg:Region) REQUIRE rg.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:State) REQUIRE s.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Metric) REQUIRE m.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (u:Unit) REQUIRE u.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (em:ExchangeMechanism) REQUIRE em.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (tb:TimeBlock) REQUIRE tb.time IS UNIQUE;",  # Constraint on the 96 canonical nodes
            "CREATE CONSTRAINT IF NOT EXISTS FOR (gs:GenerationSource) REQUIRE gs.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (pl:PowerLine) REQUIRE (pl.line_identifier, pl.date) IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (mo:MetricObservation) REQUIRE (mo.report_date, mo.metric_name, mo.entity, mo.time_block) IS UNIQUE;",
        ]
        for query in queries:
            tx.run(query)
        logging.info("Constraints created successfully.")

    @staticmethod
    def create_time_scaffolding(tx):
        """
        Creates all static time-related nodes and sequences.
        This is a one-time setup that creates the 96 canonical TimeBlock nodes.
        """
        logging.info("Creating full time scaffolding...")
        
        # Create 96 canonical TimeBlock nodes (one for each 15-min interval)
        for h in range(24):
            for m in [0, 15, 30, 45]:
                time_str = f'{h:02d}:{m:02d}'
                block_number = h * 4 + (m // 15) + 1
                tx.run("""
                    MERGE (tb:TimeBlock {time: $time_str})
                    SET tb.block_number = $block_number,
                        tb.hour = $hour,
                        tb.minute = $minute,
                        tb.display_name = $time_str,
                        tb.is_peak_hour = $hour IN [9, 10, 11, 18, 19, 20, 21],
                        tb.time_category = CASE
                            WHEN $hour >= 6 AND $hour < 12 THEN 'Morning'
                            WHEN $hour >= 12 AND $hour < 18 THEN 'Afternoon'
                            WHEN $hour >= 18 AND $hour < 22 THEN 'Evening'
                            ELSE 'Night'
                        END
                """, time_str=time_str, block_number=block_number, hour=h, minute=m)
        
        # Create the sequential NEXT relationships between canonical TimeBlocks
        sequence_query = """
        MATCH (tb:TimeBlock)
        WITH tb ORDER BY tb.time
        WITH collect(tb) as timeblocks
        UNWIND range(0, size(timeblocks) - 2) as i
        WITH timeblocks[i] as tb1, timeblocks[i+1] as tb2
        MERGE (tb1)-[:NEXT]->(tb2)
        """
        tx.run(sequence_query)
        logging.info("Time scaffolding created successfully.")

    @staticmethod
    def create_day_sequence(tx):
        """
        Connects all Day nodes sequentially with a NEXT_DAY relationship.
        This should be run once after the time tree is built.
        """
        logging.info("Creating sequential NEXT_DAY relationships...")
        sequence_query = """
        MATCH (d:Day)
        WITH d ORDER BY d.date
        WITH collect(d) as days
        UNWIND range(0, size(days) - 2) as i
        WITH days[i] as d1, days[i+1] as d2
        MERGE (d1)-[:NEXT_DAY]->(d2)
        """
        tx.run(sequence_query)
        logging.info("NEXT_DAY sequence created successfully.")

    @staticmethod
    def create_time_tree_nodes(tx, date_str):
        """
        Creates the time tree structure: Year -> Month -> Day
        This hierarchical structure makes temporal queries much more efficient.
        """
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            year, month, day = date_obj.year, date_obj.month, date_obj.day
            
            # Get month name
            month_names = [
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ]
            month_name = month_names[month - 1]
            
            query = """
            MERGE (y:Year {year: $year})
            SET y.display_name = toString($year)
            MERGE (m:Month {year: $year, month: $month})
            SET m.name = $month_name, m.display_name = $month_name
            MERGE (d:Day {date: date($date_str)})
            SET d.display_name = $date_str
            MERGE (y)-[:HAS_MONTH]->(m)
            MERGE (m)-[:HAS_DAY]->(d)
            """
            tx.run(query, year=year, month=month, month_name=month_name, date_str=date_str)
        except ValueError as e:
            logging.error(f"Invalid date format: {date_str}. Expected YYYY-MM-DD. Error: {e}")

    @staticmethod
    def create_report_node(tx, report_name, report_date, source_region):
        """
        Creates a Report node and links it to the time tree structure.
        """
        # First ensure the time tree exists
        GraphModel.create_time_tree_nodes(tx, report_date)
        
        # Create a standardized display name
        display_name = f"{source_region}_{report_date}"
        
        query = """
        MATCH (d:Day {date: date($report_date)})
        MERGE (r:Report {name: $report_name})
        SET r.source = $source_region, 
            r.date = date($report_date),
            r.display_name = $display_name
        MERGE (r)-[:FOR_DAY]->(d)
        """
        tx.run(query, report_name=report_name, report_date=report_date, source_region=source_region, display_name=display_name)

    @staticmethod
    def create_metric_observation(tx, report_name, metric_name, value, unit, entity_type, entity_name, confidence, time_block=None):
        actual_time_block = 'DAILY' if time_block is None else time_block
        query = f"""
        MATCH (r:Report {{name: $report_name}})
        // Create or merge Metric node
        MERGE (m:Metric {{name: $metric_name}})
        SET m.display_name = $metric_name
        // Create or merge Unit node
        MERGE (u:Unit {{name: $unit}})
        SET u.display_name = $unit
        // Create relationship between Metric and Unit
        MERGE (m)-[:HAS_UNIT]->(u)
        // Create or merge Entity node (State, Region, or Country)
        MERGE (e:{entity_type} {{name: $entity_name}})
        SET e.display_name = $entity_name
        // Create MetricObservation node
        MERGE (mo:MetricObservation {{
            entity: $entity_name,
            metric_name: $metric_name,
            report_date: r.date,
            time_block: $actual_time_block
        }})
        SET mo.value = $value,
            mo.confidence = $confidence,
            mo.unit = $unit,
            mo.reported_at = datetime(),
            mo.display_name = $metric_name + ' - ' + $entity_name
        // Create relationships
        MERGE (r)-[:HAS_OBSERVATION]->(mo)
        MERGE (mo)-[:IS_METRIC]->(m)
        MERGE (mo)-[:APPLIES_TO]->(e)
        """
        try:
            tx.run(query, report_name=report_name, metric_name=metric_name, value=value, unit=unit, entity_type=entity_type, entity_name=entity_name, confidence=confidence, actual_time_block=actual_time_block)
        except Exception as e:
            logging.error(f"[REL][ERROR] Cypher failed in create_metric_observation: {e}")

    @staticmethod
    def create_geographical_nodes(tx, state_name, region_name):
        region_name_canon = canonical_region(region_name)
        if not region_name_canon:
            return
        query = """
        MERGE (s:State {name: $state_name})
        SET s.type = 'State',
            s.display_name = $state_name
        MERGE (r:Region {name: $region_name})
        SET r.type = 'Region',
            r.display_name = $region_name
        MERGE (s)-[:IN_REGION]->(r)
        """
        try:
            tx.run(query, state_name=state_name, region_name=region_name_canon)
        except Exception as e:
            logging.error(f"[REL][ERROR] Cypher failed in create_geographical_nodes: {e}")

    @staticmethod
    def create_transnational_exchange(tx, report_name, country, mechanism, direction, value, unit, date_str):
        """
        Models the transnational exchange of power with time tree integration.
        Relationship is always between India (Country) and the foreign Country node.
        Now uses ExchangeObservation pattern to avoid the supernode problem.
        """
        # Ensure time tree exists
        GraphModel.create_time_tree_nodes(tx, date_str)
        query = """
        MATCH (r:Report {name: $report_name})
        MATCH (d:Day {date: date($date_str)})
        
        // Create or merge Country nodes
        MERGE (india:Country {name: 'India'})
        SET india.display_name = 'India'
        MERGE (c:Country {name: $country})
        SET c.type = 'Country',
            c.display_name = $country
        
        // Create or merge ExchangeMechanism node
        MERGE (em:ExchangeMechanism {name: $mechanism})
        SET em.display_name = $mechanism
        
        // Create or merge Unit node
        MERGE (u:Unit {name: $unit})
        SET u.display_name = $unit

        // Create a relationship representing the transaction (summary/compatibility)
        MERGE (india)-[rel:EXCHANGED_POWER_WITH]->(c)
        SET rel.direction = $direction,
            rel.value = $value,
            rel.mechanism = $mechanism,
            rel.unit = $unit,
            rel.date = $date_str,
            rel.reported_at = datetime(),
            rel.report = $report_name
        
        // Create ExchangeObservation node for this event
        CREATE (eo:ExchangeObservation {
            date: $date_str,
            direction: $direction,
            value: $value,
            unit: $unit,
            report: $report_name,
            reported_at: datetime()
        })
        MERGE (india)-[:HAS_EXCHANGE]->(eo)
        MERGE (eo)-[:USES_MECHANISM]->(em)
        MERGE (eo)-[:WITH]->(c)
        """
        tx.run(query, report_name=report_name, country=country, mechanism=mechanism, direction=direction, value=value, unit=unit, date_str=date_str)

    @staticmethod
    def create_timeblock_relationship(tx, report_name, block_time, data_properties):
        """
        Creates a relationship between a Report and a canonical TimeBlock,
        storing time-series data as properties on the relationship.
        This is the lightweight approach that avoids creating individual TimeBlock nodes.
        """
        # Robust conversion to HH:MM format with validation
        def to_hhmm(t):
            if not t or not isinstance(t, str):
                return None
            # Skip header rows or invalid data
            if t.upper() in ['TIME', 'BLOCKTIME', 'BLOCK_TIME', '']:
                return None
            try:
                parts = t.split(":")
                if len(parts) >= 2:
                    hour = int(parts[0])
                    minute = int(parts[1])
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        return f"{hour:02d}:{minute:02d}"
            except (ValueError, IndexError):
                pass
            return None
        
        canonical_time = to_hhmm(block_time)
        if not canonical_time:
            logging.warning(f"Skipping invalid block_time: {block_time}")
            return

        query = """
        MATCH (r:Report {name: $report_name})
        MATCH (tb:TimeBlock {time: $canonical_time})
        SET tb.display_name = $canonical_time
        MERGE (r)-[rel:HAS_DATA_FOR_BLOCK]->(tb)
        SET rel += $data_properties
        """
        tx.run(query, report_name=report_name, block_time=block_time, canonical_time=canonical_time, data_properties=data_properties)

    @staticmethod
    def create_temporal_aggregations(tx):
        """
        Creates aggregated nodes for common temporal queries (Quarters), skipping null quarters.
        """
        query = """
        // Create Quarter nodes, skip if quarter is null
        MATCH (m:Month)-[:HAS_MONTH]-(y:Year)
        WITH y, m.quarter as quarter, collect(m) as months
        WHERE quarter IS NOT NULL
        MERGE (q:Quarter {year: y.year, quarter: quarter})
        SET q.name = y.year + '-Q' + toString(quarter),
            q.display_name = y.year + '-Q' + toString(quarter)
        MERGE (q)-[:IN_YEAR]->(y)
        WITH q, months
        UNWIND months as month
        MERGE (month)-[:IN_QUARTER]->(q)
        """
        tx.run(query)
        logging.info("Created temporal aggregation nodes (Quarters)")

    @staticmethod
    def create_generation_source_relationship(tx, report_name, region_name, date_str, source_name, source_category, amount, unit):
        GraphModel.create_time_tree_nodes(tx, date_str)
        query = """
        MATCH (r:Report {name: $report_name})
        MERGE (region:Region {name: $region_name})
        SET region.display_name = $region_name
        MERGE (gs:GenerationSource {name: $source_name})
        SET gs.category = $source_category, gs.display_name = $source_name
        MERGE (u:Unit {name: $unit})
        SET u.display_name = $unit
        // Create GenerationObservation node
        CREATE (go:GenerationObservation {
            date: $date_str,
            amount: $amount,
            unit: $unit,
            report: $report_name,
            source: $source_name,
            region: $region_name,
            category: $source_category
        })
        MERGE (region)-[:HAS_GENERATION]->(go)
        MERGE (go)-[:OF_SOURCE]->(gs)
        MERGE (go)-[:IN_REPORT]->(r)
        """
        try:
            tx.run(query, report_name=report_name, region_name=region_name, date_str=date_str, source_name=source_name, source_category=source_category, amount=amount, unit=unit)
        except Exception as e:
            logging.error(f"[REL][ERROR] Cypher failed in create_generation_source_relationship: {e}")

    @staticmethod
    def create_powerline_relationship(tx, report_name, line_identifier, voltage, region1, region2, max_import, max_export, import_energy, export_energy, net_import_energy, date_str):
        GraphModel.create_time_tree_nodes(tx, date_str)
        query = """
        MATCH (r:Report {name: $report_name})
        // Create or merge Region nodes
        MERGE (reg1:Region {name: $region1})
        SET reg1.display_name = $region1
        MERGE (reg2:Region {name: $region2})
        SET reg2.display_name = $region2
        // Create a PowerLine node with all the properties
        MERGE (pl:PowerLine {line_identifier: $line_identifier, date: $date_str})
        SET pl.voltage = $voltage,
            pl.max_import = $max_import,
            pl.max_export = $max_export,
            pl.import_energy = $import_energy,
            pl.export_energy = $export_energy,
            pl.net_import_energy = $net_import_energy,
            pl.report = $report_name,
            pl.display_name = $line_identifier
        // Connect PowerLine to both regions
        MERGE (reg1)-[:CONNECTS_TO]->(pl)
        MERGE (pl)-[:CONNECTS_TO]->(reg2)
        // Connect Report to PowerLine
        MERGE (r)-[:REPORTS_POWERLINE {line_identifier: $line_identifier, date: $date_str}]->(pl)
        """
        try:
            tx.run(query, report_name=report_name, line_identifier=line_identifier, voltage=voltage, region1=region1, region2=region2, max_import=max_import, max_export=max_export, import_energy=import_energy, export_energy=export_energy, net_import_energy=net_import_energy, date_str=date_str)
        except Exception as e:
            logging.error(f"[REL][ERROR] Cypher failed in create_powerline_relationship: {e}")

    @staticmethod
    def create_international_powerline_relationship(tx, report_name, line_identifier, voltage, region_name, country_name, max_loading, min_loading, avg_loading, energy_exchanged, date_str):
        """
        Creates a PowerLine node and connects it to the Report node and the region and country.
        This avoids the relationship-to-relationship issue and provides better structure.
        """
        GraphModel.create_time_tree_nodes(tx, date_str)
        query = """
        MATCH (r:Report {name: $report_name})
        
        // Create or merge Region and Country nodes
        MERGE (reg:Region {name: $region_name})
        SET reg.display_name = $region_name
        MERGE (c:Country {name: $country_name})
        SET c.display_name = $country_name
        
        // Create a PowerLine node with all the properties
        MERGE (pl:PowerLine {line_identifier: $line_identifier, date: $date_str})
        SET pl.voltage = $voltage,
            pl.max_loading = $max_loading,
            pl.min_loading = $min_loading,
            pl.avg_loading = $avg_loading,
            pl.energy_exchanged = $energy_exchanged,
            pl.report = $report_name,
            pl.display_name = $line_identifier
            
        // Connect PowerLine to region and country
        MERGE (reg)-[:CONNECTS_TO]->(pl)
        MERGE (pl)-[:CONNECTS_TO]->(c)
        
        // Connect Report to PowerLine
        MERGE (r)-[:REPORTS_POWERLINE {line_identifier: $line_identifier, date: $date_str}]->(pl)
        """
        tx.run(query, report_name=report_name, line_identifier=line_identifier, voltage=voltage, region_name=region_name, country_name=country_name, max_loading=max_loading, min_loading=min_loading, avg_loading=avg_loading, energy_exchanged=energy_exchanged, date_str=date_str)

    @staticmethod
    def connect_regions_to_india(tx):
        """
        Connects all Region nodes (except 'India') to the Country node 'India' with an :IN_COUNTRY relationship.
        """
        query = """
        MERGE (c:Country {name: 'India'})
        SET c.display_name = 'India'
        WITH c
        MATCH (r:Region)
        WHERE r.name <> 'India'
        MERGE (r)-[:IN_COUNTRY]->(c)
        """
        tx.run(query)

    @staticmethod
    def cleanup_orphaned_nodes(tx):
        """
        Cleans up orphaned nodes in the graph to ensure data integrity.
        """
        # Clean orphaned MetricObservations
        result = tx.run("""
            MATCH (mo:MetricObservation)
            WHERE NOT (mo)-[:IS_METRIC]->() OR NOT (mo)-[:APPLIES_TO]->()
            DETACH DELETE mo
            RETURN count(mo) as deleted_count
        """)
        deleted_observations = result.single()["deleted_count"]
        if deleted_observations > 0:
            logging.info(f"Cleaned up {deleted_observations} orphaned MetricObservations")
        
        # Clean reports without any data connections
        result = tx.run("""
            MATCH (r:Report)
            WHERE NOT (r)-[:HAS_OBSERVATION]->() 
              AND NOT (r)-[:HAS_DATA_FOR_BLOCK]->()
              AND NOT (r)-[:HAS_GENERATION_SOURCE]->()
              AND NOT (r)-[:REPORTS_POWERLINE]->()
            DETACH DELETE r
            RETURN count(r) as deleted_count
        """)
        deleted_reports = result.single()["deleted_count"]
        if deleted_reports > 0:
            logging.info(f"Cleaned up {deleted_reports} orphaned Reports")
        
        # Clean orphaned TimeBlocks (should be none since we use canonical ones)
        result = tx.run("""
            MATCH (tb:TimeBlock)
            WHERE NOT (tb)<-[:HAS_DATA_FOR_BLOCK]-() AND NOT (tb)-[:NEXT]->()
            DETACH DELETE tb
            RETURN count(tb) as deleted_count
        """)
        deleted_timeblocks = result.single()["deleted_count"]
        if deleted_timeblocks > 0:
            logging.info(f"Cleaned up {deleted_timeblocks} orphaned TimeBlocks")

# /graph_builder/build_graph.py
# This script reads from the SQLite DB and uses the GraphModel to build the Neo4j graph.

# --- CONFIGURATION ---
NEO4J_CONFIG = {
    "uri": "neo4j://localhost:7687",
    "user": "neo4j",
    "password": "powerflow" # <-- IMPORTANT: Change this
}
DATABASE_NAME = 'power_data.db'

# Confidence scores for data reconciliation. NLDC is the highest authority.
SOURCE_CONFIDENCE = {
    "NLDC": 1.0,
    "SRLDC": 0.9,
    "WRLDC": 0.9,
    "NRLDC": 0.9,
    "ERLDC": 0.9,
    "NERLDC": 0.9,
    "UNKNOWN": 0.5
}

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
        if self._driver is not None:
            self._driver.close()
            logging.info("Neo4j connection closed.")

    def clear_database(self):
        """Deletes all nodes and relationships in the Neo4j database."""
        if self._driver is None:
            logging.error("Cannot clear database, Neo4j driver not available.")
            return
        with self._driver.session(database="neo4j") as session:
            session.run("MATCH (n) DETACH DELETE n")
            logging.info("Cleared all nodes and relationships from the Neo4j database.")

    def upload_data(self, graph_builder_instance):
        """Uploads all data by calling methods on the graph_builder instance."""
        if self._driver is None:
            logging.error("Cannot upload data, Neo4j driver not available.")
            return

        with self._driver.session(database="neo4j") as session:
            # Setup constraints first
            session.execute_write(GraphModel.create_constraints)

            # Connect all regions to India
            session.execute_write(GraphModel.connect_regions_to_india)

            # Process each type of data
            logging.info("Uploading regional summary data...")
            graph_builder_instance.process_regional_summary(session)

            logging.info("Uploading state generation data...")
            graph_builder_instance.process_state_generation(session)

            logging.info("Uploading transnational exchange data...")
            graph_builder_instance.process_transnational_exchange(session)

            logging.info("Uploading time block data...")
            graph_builder_instance.process_time_block_data(session)

            # Create temporal aggregations
            logging.info("Creating temporal aggregations...")
            session.execute_write(GraphModel.create_temporal_aggregations)

            # Upload generation sources
            logging.info("Uploading generation sources data...")
            graph_builder_instance.process_generation_sources(session)

            # Upload powerline data
            logging.info("Uploading powerline data...")
            graph_builder_instance.process_powerline_data(session)

            # Upload international transmission link flow data
            logging.info("Uploading international transmission link flow data...")
            graph_builder_instance.process_international_link_flow(session)

            # Create day sequence after all data is loaded
            session.execute_write(GraphModel.create_day_sequence)
            
        logging.info("Graph build process completed successfully!")
        logging.info("Time tree structure created with Year -> Month -> Day hierarchy")
        logging.info("You can now run complex temporal queries efficiently!")

class GraphBuilder:
    """
    Fetches data from SQLite and orchestrates the graph construction process.
    """
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row # Makes rows accessible by column name

    def get_latest_dates(self, n=5):
        """Returns a set of the latest n ActualDate strings from DimDates."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT ActualDate FROM DimDates ORDER BY ActualDate DESC LIMIT ?", (n,))
        return set(row[0] for row in cursor.fetchall())

    def get_date_range(self, start_date=None, end_date=None):
        """Returns a set of dates within the specified range."""
        cursor = self.conn.cursor()
        if start_date and end_date:
            cursor.execute("SELECT ActualDate FROM DimDates WHERE ActualDate BETWEEN ? AND ? ORDER BY ActualDate", (start_date, end_date))
        elif start_date:
            cursor.execute("SELECT ActualDate FROM DimDates WHERE ActualDate >= ? ORDER BY ActualDate", (start_date,))
        elif end_date:
            cursor.execute("SELECT ActualDate FROM DimDates WHERE ActualDate <= ? ORDER BY ActualDate", (end_date,))
        else:
            cursor.execute("SELECT ActualDate FROM DimDates ORDER BY ActualDate")
        return set(row[0] for row in cursor.fetchall())

    def _get_report_details(self, report_name):
        """Utility to extract date and source region from report name."""
        # Handles multiple formats
        base = os.path.basename(report_name)
        
        # Try new format: NLDC_PSP_YYYY-MM-DD
        if base.startswith('NLDC_PSP_'):
            date_part = base.replace('NLDC_PSP_', '').split('.')[0]
            try:
                # Accept both YYYY-MM-DD and DD-MM-YYYY
                if '-' in date_part:
                    # Try YYYY-MM-DD
                    report_date = datetime.strptime(date_part, '%Y-%m-%d').strftime('%Y-%m-%d')
                else:
                    # Fallback to DD.MM.YY
                    report_date = datetime.strptime(date_part, '%d.%m.%y').strftime('%Y-%m-%d')
                return report_date, 'NLDC'
            except Exception:
                pass
        
        # Try new format: PSP_Report_YYYY_MM_DD
        if base.startswith('PSP_Report_'):
            date_part = base.replace('PSP_Report_', '').split('.')[0]
            try:
                # Handle YYYY_MM_DD format
                if '_' in date_part:
                    # Convert YYYY_MM_DD to YYYY-MM-DD
                    date_str = date_part.replace('_', '-')
                    report_date = datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
                    return report_date, 'NLDC'
            except Exception:
                pass
        
        # Fallback to old logic: DD-MM-YY_Region
        parts = base.split('_')
        try:
            date_str = parts[0].replace('.', '-')
            report_date = datetime.strptime(date_str, '%d-%m-%y').strftime('%Y-%m-%d')
            source_region = parts[1] if len(parts) > 1 else "UNKNOWN"
            return report_date, source_region
        except (ValueError, IndexError):
            logging.warning(f"Could not parse date/source from report name: {report_name}")
            return None, "UNKNOWN"

    def process_regional_summary(self, session, date_filter=None):
        cursor = self.conn.cursor()
        if date_filter:
            placeholders = ','.join('?' for _ in date_filter)
            query = f"""
            SELECT frs.*, dr.RegionName, dd.ActualDate, drp.ReportName
            FROM FactAllIndiaDailySummary frs
            JOIN DimRegions dr ON frs.RegionID = dr.RegionID
            JOIN DimDates dd ON frs.DateID = dd.DateID
            JOIN DimReports drp ON frs.DateID = drp.DateID
            WHERE dd.ActualDate IN ({placeholders})
            """
            cursor.execute(query, list(date_filter))
        else:
            query = """
            SELECT frs.*, dr.RegionName, dd.ActualDate, drp.ReportName
            FROM FactAllIndiaDailySummary frs
            JOIN DimRegions dr ON frs.RegionID = dr.RegionID
            JOIN DimDates dd ON frs.DateID = dd.DateID
            JOIN DimReports drp ON frs.DateID = drp.DateID
            """
            cursor.execute(query)
        rows = cursor.fetchall()
        row_count = 0
        for row in rows:
            row_count += 1
            report_name = os.path.basename(row['ReportName'])
            report_date, source_region = self._get_report_details(report_name)
            if not report_date: continue
            confidence = SOURCE_CONFIDENCE.get(source_region, 0.5)
            session.execute_write(GraphModel.create_report_node, report_name, report_date, source_region)
            metrics = {}
            if 'EveningPeakDemandMet' in row.keys():
                metrics["Evening Peak Demand Met"] = (row["EveningPeakDemandMet"], "MW")
            if 'PeakShortage' in row.keys():
                metrics["Evening Peak Shortage"] = (row["PeakShortage"], "MW")
            if 'EnergyMet' in row.keys():
                metrics["Energy Met"] = (row["EnergyMet"], "MU")
            if 'EnergyShortage' in row.keys():
                metrics["Energy Shortage"] = (row["EnergyShortage"], "MU")
            if 'MaxDemandSCADA' in row.keys():
                metrics["Max Demand SCADA"] = (row["MaxDemandSCADA"], "MW")
            if 'TimeOfMaxDemandMet' in row.keys():
                metrics["Time Of Max Demand Met"] = (row["TimeOfMaxDemandMet"], "HH:MM:SS")
            if 'ScheduleDrawal' in row.keys():
                metrics["Schedule Drawal"] = (row["ScheduleDrawal"], "MU")
            if 'ActualDrawal' in row.keys():
                metrics["Actual Drawal"] = (row["ActualDrawal"], "MU")
            if 'OverUnderDrawal' in row.keys():
                metrics["Over/Under Drawal"] = (row["OverUnderDrawal"], "MU")
            if 'CentralSectorOutage' in row.keys():
                metrics["Central Sector Outage"] = (row["CentralSectorOutage"], "MW")
            if 'StateSectorOutage' in row.keys():
                metrics["State Sector Outage"] = (row["StateSectorOutage"], "MW")
            if 'TotalOutage' in row.keys():
                metrics["Total Outage"] = (row["TotalOutage"], "MW")
            if 'ShareRESInTotalGeneration' in row.keys():
                metrics["Share RES In Total Generation"] = (row["ShareRESInTotalGeneration"], "%")
            if 'ShareNonFossilInTotalGeneration' in row.keys():
                metrics["Share Non-Fossil In Total Generation"] = (row["ShareNonFossilInTotalGeneration"], "%")
            if 'FrequencyViolationIndex' in row.keys():
                metrics["Frequency Violation Index"] = (row["FrequencyViolationIndex"], "Index")
            if 'DurationFrequencyBelow49_7' in row.keys():
                metrics["Duration Frequency Below 49.7"] = (row["DurationFrequencyBelow49_7"], "Hours")
            if 'DurationFrequency_49_7_to_49_8' in row.keys():
                metrics["Duration Frequency 49.7-49.8"] = (row["DurationFrequency_49_7_to_49_8"], "Hours")
            if 'DurationFrequency_49_8_to_49_9' in row.keys():
                metrics["Duration Frequency 49.8-49.9"] = (row["DurationFrequency_49_8_to_49_9"], "Hours")
            if 'DurationFrequencyBelow49_9' in row.keys():
                metrics["Duration Frequency Below 49.9"] = (row["DurationFrequencyBelow49_9"], "Hours")
            if 'DurationFrequency_49_9_to_50_05' in row.keys():
                metrics["Duration Frequency 49.9-50.05"] = (row["DurationFrequency_49_9_to_50_05"], "Hours")
            if 'DurationFrequencyAbove50_05' in row.keys():
                metrics["Duration Frequency Above 50.05"] = (row["DurationFrequencyAbove50_05"], "Hours")
            if 'RegionDDF' in row.keys():
                metrics["Region DDF"] = (row["RegionDDF"], "Index")
            if 'StatesDDF' in row.keys():
                metrics["States DDF"] = (row["StatesDDF"], "Index")
            if 'SolarHRMaxDemand' in row.keys():
                metrics["Solar HR Max Demand"] = (row["SolarHRMaxDemand"], "MW")
            if 'SolarHRMaxDemandTime' in row.keys():
                metrics["Solar HR Max Demand Time"] = (row["SolarHRMaxDemandTime"], "HH:MM:SS")
            if 'SolarHRShortage' in row.keys():
                metrics["Solar HR Shortage"] = (row["SolarHRShortage"], "MW")
            if 'NonSolarHRMaxDemand' in row.keys():
                metrics["Non-Solar HR Max Demand"] = (row["NonSolarHRMaxDemand"], "MW")
            if 'NonSolarHRMaxDemandTime' in row.keys():
                metrics["Non-Solar HR Max Demand Time"] = (row["NonSolarHRMaxDemandTime"], "HH:MM:SS")
            if 'NonSolarHRShortage' in row.keys():
                metrics["Non-Solar HR Shortage"] = (row["NonSolarHRShortage"], "MW")

            region_canon = canonical_region(row['RegionName'])
            if region_canon is None:
                entity_type = 'Country'
                entity_name = 'India'
            else:
                entity_type = 'Region'
                entity_name = region_canon

            for metric_name, (value, unit) in metrics.items():
                if value is not None:
                    session.execute_write(
                        GraphModel.create_metric_observation,
                        report_name, metric_name, value, unit,
                        entity_type, entity_name, confidence
                    )
        logging.info(f"Processed {row_count} regional summary records.")

    def process_state_generation(self, session, date_filter=None):
        cursor = self.conn.cursor()
        if date_filter:
            placeholders = ','.join('?' for _ in date_filter)
            query = f"""
            SELECT fsg.*, ds.StateName, dr.RegionName, dd.ActualDate, drp.ReportName
            FROM FactStateDailyEnergy fsg
            JOIN DimStates ds ON fsg.StateID = ds.StateID
            JOIN DimRegions dr ON ds.RegionID = dr.RegionID
            JOIN DimDates dd ON fsg.DateID = dd.DateID
            JOIN DimReports drp ON fsg.DateID = drp.DateID
            WHERE dd.ActualDate IN ({placeholders})
            """
            cursor.execute(query, list(date_filter))
        else:
            query = """
            SELECT fsg.*, ds.StateName, dr.RegionName, dd.ActualDate, drp.ReportName
            FROM FactStateDailyEnergy fsg
            JOIN DimStates ds ON fsg.StateID = ds.StateID
            JOIN DimRegions dr ON ds.RegionID = dr.RegionID
            JOIN DimDates dd ON fsg.DateID = dd.DateID
            JOIN DimReports drp ON fsg.DateID = drp.DateID
            """
            cursor.execute(query)
        rows = cursor.fetchall()
        row_count = 0
        for row in rows:
            row_count += 1
            report_name = os.path.basename(row['ReportName'])
            report_date, source_region = self._get_report_details(report_name)
            if not report_date: continue
            confidence = SOURCE_CONFIDENCE.get(source_region, 0.5)
            session.execute_write(GraphModel.create_geographical_nodes, row['StateName'], row['RegionName'])
            session.execute_write(GraphModel.create_report_node, report_name, report_date, source_region)
            metrics = {}
            if 'MaximumDemand' in row.keys():
                metrics["Maximum Demand"] = (row["MaximumDemand"], "MW")
            if 'Shortage' in row.keys():
                metrics["Shortage"] = (row["Shortage"], "MW")
            if 'EnergyMet' in row.keys():
                metrics["Energy Met"] = (row["EnergyMet"], "MU")
            if 'DrawalSchedule' in row.keys():
                metrics["Drawal Schedule"] = (row["DrawalSchedule"], "MU")
            if 'OverUnderDrawal' in row.keys():
                metrics["Over/Under Drawal"] = (row["OverUnderDrawal"], "MU")
            if 'MaxOverDrawal' in row.keys():
                metrics["Max Over Drawal"] = (row["MaxOverDrawal"], "MW")
            if 'EnergyShortage' in row.keys():
                metrics["Energy Shortage"] = (row["EnergyShortage"], "MU")

            for metric_name, (value, unit) in metrics.items():
                if value is not None:
                    session.execute_write(
                        GraphModel.create_metric_observation,
                        report_name, metric_name, value, unit,
                        'State', row['StateName'], confidence
                    )
        logging.info(f"Processed {row_count} state generation records.")

    def process_transnational_exchange(self, session, date_filter=None):
        """Processes transnational exchange data for filtered dates only."""
        cursor = self.conn.cursor()
        query = """
        SELECT fted.DateID, d.ActualDate, fted.CountryID, c.CountryName, fted.MechanismID, em.MechanismName, fted.ExchangeDirection, fted.ExchangeValue
        FROM FactTransnationalExchangeDetail as fted
        JOIN DimDates as d ON fted.DateID = d.DateID
        JOIN DimCountries as c ON fted.CountryID = c.CountryID
        JOIN DimExchangeMechanisms as em ON fted.MechanismID = em.MechanismID
        """
        cursor.execute(query)
        processed_count = 0
        for row in cursor.fetchall():
            if date_filter and row['ActualDate'] not in date_filter:
                continue
            # Compose a synthetic report name for this date (or use a real one if available)
            report_name = f"Transnational_{row['ActualDate']}"
            # Use the date as report_date
            report_date = row['ActualDate']
            country = row['CountryName']
            mechanism = row['MechanismName']
            direction = row['ExchangeDirection']
            value = row['ExchangeValue']
            unit = "MU"  # As per schema
            
            session.execute_write(GraphModel.create_report_node, report_name, report_date, 'NLDC')
            session.execute_write(
                GraphModel.create_transnational_exchange,
                report_name, country, mechanism, direction, value, unit, report_date
            )
            processed_count += 1
        
        if processed_count > 0:
            logging.info(f"Processed {processed_count} transnational exchange records")

    def process_time_block_data(self, session, date_filter=None):
        """Processes time block data for filtered dates only using the lightweight relationship model."""
        cursor = self.conn.cursor()
        query = """
        SELECT ftb.DateID, d.ActualDate, ftb.BlockTime, ftb.BlockNumber, ftb.Frequency, ftb.DemandMet
        FROM FactTimeBlockPowerData as ftb
        JOIN DimDates as d ON ftb.DateID = d.DateID
        """
        cursor.execute(query)
        for row in cursor.fetchall():
            if date_filter and row['ActualDate'] not in date_filter:
                continue
            report_name = f"TimeBlock_{row['ActualDate']}"
            
            # Create the report node first
            session.execute_write(
                GraphModel.create_report_node,
                report_name, row['ActualDate'], 'NLDC'
            )
            
            # Create relationship between Report and canonical TimeBlock with data properties
            session.execute_write(
                GraphModel.create_timeblock_relationship,
                report_name, row['BlockTime'], {
                    "frequency": row['Frequency'],
                    "demand_met": row['DemandMet'],
                    "block_number": row['BlockNumber'],
                    "date": row['ActualDate']
                }
            )

    def process_generation_sources(self, session, date_filter=None):
        cursor = self.conn.cursor()
        # Daily generation breakdown
        if date_filter:
            placeholders = ','.join('?' for _ in date_filter)
            query = f'''
            SELECT d.ActualDate, dr.RegionName, drp.ReportName, gs.SourceName, gs.SourceCategory, f.GenerationAmount
            FROM FactDailyGenerationBreakdown f
            JOIN DimDates d ON f.DateID = d.DateID
            JOIN DimRegions dr ON f.RegionID = dr.RegionID
            JOIN DimGenerationSources gs ON f.GenerationSourceID = gs.GenerationSourceID
            JOIN DimReports drp ON f.DateID = drp.DateID
            WHERE d.ActualDate IN ({placeholders})
            '''
            cursor.execute(query, list(date_filter))
        else:
            query = '''
            SELECT d.ActualDate, dr.RegionName, drp.ReportName, gs.SourceName, gs.SourceCategory, f.GenerationAmount
            FROM FactDailyGenerationBreakdown f
            JOIN DimDates d ON f.DateID = d.DateID
            JOIN DimRegions dr ON f.RegionID = dr.RegionID
            JOIN DimGenerationSources gs ON f.GenerationSourceID = gs.GenerationSourceID
            JOIN DimReports drp ON f.DateID = drp.DateID
            '''
            cursor.execute(query)
        rows = cursor.fetchall()
        row_count = 0
        for row in rows:
            row_count += 1
            if 'RegionName' in row.keys():
                region_name = row['RegionName']
            elif 'region' in row.keys():
                region_name = row['region']
            elif 'region_name' in row.keys():
                region_name = row['region_name']
            else:
                continue
            region_canon = canonical_region(region_name)
            if region_canon:
                session.execute_write(
                    GraphModel.create_generation_source_relationship,
                    row['ReportName'], region_canon, row['ActualDate'],
                    row['SourceName'], row['SourceCategory'], row['GenerationAmount'], 'MU'
                )
        logging.info(f"Processed {row_count} generation source records (daily breakdown).")
        # Blockwise generation breakdown (modeled as MetricObservations with time_block property)
        if date_filter:
            placeholders = ','.join('?' for _ in date_filter)
            query2 = f'''
            SELECT d.ActualDate, ftbg.BlockTime, ftbg.BlockNumber, drp.ReportName, gs.SourceName, gs.SourceCategory, ftbg.GenerationOutput
            FROM FactTimeBlockGeneration ftbg
            JOIN DimDates d ON ftbg.DateID = d.DateID
            JOIN DimGenerationSources gs ON ftbg.GenerationSourceID = gs.GenerationSourceID
            JOIN DimReports drp ON ftbg.DateID = drp.DateID
            WHERE d.ActualDate IN ({placeholders})
            '''
            cursor.execute(query2, list(date_filter))
        else:
            query2 = '''
            SELECT d.ActualDate, ftbg.BlockTime, ftbg.BlockNumber, drp.ReportName, gs.SourceName, gs.SourceCategory, ftbg.GenerationOutput
            FROM FactTimeBlockGeneration ftbg
            JOIN DimDates d ON ftbg.DateID = d.DateID
            JOIN DimGenerationSources gs ON ftbg.GenerationSourceID = gs.GenerationSourceID
            JOIN DimReports drp ON ftbg.DateID = drp.DateID
            '''
            cursor.execute(query2)
        rows2 = cursor.fetchall()
        row_count2 = 0
        for row in rows2:
            row_count2 += 1
            report_name = row['ReportName']
            metric_name = f"Generation - {row['SourceName']}"
            session.execute_write(
                GraphModel.create_metric_observation,
                report_name, metric_name, row['GenerationOutput'], 'MW',
                'Country', 'India', 1.0, time_block=row['BlockTime']
            )
        logging.info(f"Processed {row_count2} generation source records (blockwise breakdown).")

    def process_powerline_data(self, session, date_filter=None):
        """Processes FactTransmissionLinkFlow for powerline data as relationships."""
        cursor = self.conn.cursor()
        query = '''
        SELECT d.ActualDate, drp.ReportName, tl.LineIdentifier, tl.VoltageLevel_kV, ftlf.Inter_Region, ftlf.MaxImport, ftlf.MaxExport, ftlf.ImportEnergy, ftlf.ExportEnergy, ftlf.NetImportEnergy
        FROM FactTransmissionLinkFlow ftlf
        JOIN DimDates d ON ftlf.DateID = d.DateID
        JOIN DimTransmissionLines tl ON ftlf.LineID = tl.LineID
        JOIN DimReports drp ON ftlf.DateID = drp.DateID
        '''
        cursor.execute(query)
        for row in cursor.fetchall():
            if date_filter and row['ActualDate'] not in date_filter:
                continue
            # Parse Inter_Region as 'Region1-Region2'
            if '-' in row['Inter_Region']:
                region1, region2 = [canonical_region(r.strip()) for r in row['Inter_Region'].split('-', 1)]
            else:
                region1 = region2 = canonical_region(row['Inter_Region'])
            if not region1 or not region2:
                continue  # Skip if either is None (e.g., 'India')
            session.execute_write(
                GraphModel.create_powerline_relationship,
                row['ReportName'], row['LineIdentifier'], row['VoltageLevel_kV'],
                region1, region2, row['MaxImport'], row['MaxExport'],
                row['ImportEnergy'], row['ExportEnergy'], row['NetImportEnergy'], row['ActualDate']
            )

    def process_international_link_flow(self, session, date_filter=None):
        """Processes FactInternationalTransmissionLinkFlow for international transmission link flow as relationships."""
        cursor = self.conn.cursor()
        query = '''
        SELECT d.ActualDate, drp.ReportName, tl.LineIdentifier, tl.VoltageLevel_kV, 
               c.CountryName, r.RegionName, fitlf.MaxLoading, fitlf.MinLoading, fitlf.AvgLoading, fitlf.EnergyExchanged
        FROM FactInternationalTransmissionLinkFlow fitlf
        JOIN DimDates d ON fitlf.DateID = d.DateID
        JOIN DimTransmissionLines tl ON fitlf.LineID = tl.LineID
        LEFT JOIN DimCountries c ON fitlf.CountryID = c.CountryID
        LEFT JOIN DimRegions r ON fitlf.RegionID = r.RegionID
        JOIN DimReports drp ON fitlf.DateID = drp.DateID
        '''
        cursor.execute(query)
        for row in cursor.fetchall():
            if date_filter and row['ActualDate'] not in date_filter:
                continue
            region_canon = canonical_region(row['RegionName'])
            if not region_canon:
                continue  # Skip if region is 'India' or None
            session.execute_write(
                GraphModel.create_international_powerline_relationship,
                row['ReportName'], row['LineIdentifier'], row['VoltageLevel_kV'],
                region_canon, row['CountryName'],
                row['MaxLoading'], row['MinLoading'], row['AvgLoading'], row['EnergyExchanged'], row['ActualDate']
            )

    def close_connection(self):
        self.conn.close()

# --- UTILITY FUNCTIONS FOR TIME TREE QUERIES ---
from tabulate import tabulate

class TimeTreeQueries:
    """
    Utility class containing common Cypher queries for the time tree structure.
    These queries demonstrate how to leverage the hierarchical time structure.
    Now generalized to accept parameters and return (query, params) tuple.
    """
    
    @staticmethod
    def get_data_for_month(year, month):
        """Query to get all data for a specific month."""
        query = """
        MATCH (m:Month {year: $year, month: $month})
        MATCH (d:Day)-[:HAS_DAY]-(m)
        MATCH (r:Report)-[:FOR_DAY]->(d)
        OPTIONAL MATCH (r)-[:HAS_OBSERVATION]->(mo:MetricObservation)-[:IS_METRIC]->(metric:Metric)
        RETURN d.date as date, r.name as report, metric.name as metric_name, 
               mo.value as value, mo.confidence as confidence, mo.entity as entity
        ORDER BY d.date
        """
        params = {"year": year, "month": month}
        return query, params
    
    @staticmethod
    def get_data_for_quarter(year, quarter):
        """Query to get all data for a specific quarter."""
        query = """
        MATCH (q:Quarter {year: $year, quarter: $quarter})
        MATCH (m:Month)-[:IN_QUARTER]->(q)
        MATCH (d:Day)-[:HAS_DAY]-(m)
        MATCH (r:Report)-[:FOR_DAY]->(d)
        OPTIONAL MATCH (r)-[:HAS_OBSERVATION]->(mo:MetricObservation)-[:IS_METRIC]->(metric:Metric)
        RETURN m.month as month, d.date as date, r.name as report, 
               metric.name as metric_name, mo.value as value, mo.entity as entity
        ORDER BY m.month, d.date
        """
        params = {"year": year, "quarter": quarter}
        return query, params
    
    @staticmethod
    def get_weekend_vs_weekday_analysis():
        """Query to compare weekend vs weekday power consumption."""
        query = """
        MATCH (d:Day)<-[:ON_DAY]-(r:Report)
        MATCH (r)-[:HAS_OBSERVATION]->(mo:MetricObservation)-[:IS_METRIC]->(m:Metric {name: 'Peak Demand Met'})
        WITH d.is_weekend as is_weekend, avg(mo.value) as avg_demand
        RETURN is_weekend, avg_demand
        ORDER BY is_weekend
        """
        return query, {}
    
    @staticmethod
    def get_monthly_trends(metric_name):
        """Query to get monthly trends for a specific metric."""
        query = """
        MATCH (m:Month)<-[:HAS_DAY]-(d:Day)<-[:FOR_DAY]-(r:Report)
        MATCH (r)-[:HAS_OBSERVATION]->(mo:MetricObservation)-[:IS_METRIC]->(metric:Metric {name: $metric_name})
        WITH m, avg(mo.value) as avg_value, count(mo.value) as data_points
        RETURN m.year as year, m.month as month, 
               avg_value, data_points
        ORDER BY m.year, m.month
        """
        params = {"metric_name": metric_name}
        return query, params
    
    @staticmethod
    def get_peak_hours_analysis():
        """Query to analyze peak hours using time block data."""
        query = """
        MATCH (tb:TimeBlock)<-[rel:HAS_DATA_FOR_BLOCK]-()
        WITH tb.hour as hour, tb.is_peak_hour as is_peak, 
             avg(rel.demand_met) as avg_demand, avg(rel.frequency) as avg_frequency
        RETURN hour, is_peak, avg_demand, avg_frequency
        ORDER BY hour
        """
        return query, {}
    
    @staticmethod
    def get_seasonal_patterns():
        """Query to identify seasonal patterns in power consumption."""
        query = """
        MATCH (m:Month)<-[:HAS_DAY]-(d:Day)<-[:FOR_DAY]-(r:Report)
        MATCH (r)-[:HAS_OBSERVATION]->(mo:MetricObservation)-[:IS_METRIC]->(metric:Metric {name: 'Energy Met'})
        WITH m.month as month,
             avg(mo.value) as avg_energy,
             CASE 
                WHEN m.month IN [12, 1, 2] THEN 'Winter'
                WHEN m.month IN [3, 4, 5] THEN 'Spring'
                WHEN m.month IN [6, 7, 8] THEN 'Summer'
                ELSE 'Autumn'
             END as season
        RETURN season, month, avg_energy
        ORDER BY month
        """
        return query, {}
    
    @staticmethod
    def get_entity_specific_observations(entity_name, entity_type="Region"):
        """
        Query to get observations for a specific entity (State, Region, or Country) only.
        This demonstrates how the MetricObservation pattern solves the supernode problem.
        """
        query = f"""
        MATCH (e:{entity_type} {{name: $entity_name}})
        MATCH (mo:MetricObservation)-[:APPLIES_TO]->(e)
        MATCH (mo)-[:IS_METRIC]->(metric:Metric)
        MATCH (report:Report)-[:HAS_OBSERVATION]->(mo)
        RETURN report.name as report, metric.name as metric, 
               mo.value as value, mo.confidence as confidence, mo.report_date as date
        ORDER BY mo.report_date DESC
        """
        params = {"entity_name": entity_name}
        return query, params
    
    @staticmethod
    def get_region_specific_observations(region_name):
        """
        Query to get observations for a specific region only.
        This demonstrates how the MetricObservation pattern solves the supernode problem.
        """
        query = """
                        MATCH (r:Region {name: $region_name})
        MATCH (mo:MetricObservation)-[:APPLIES_TO]->(r)
        MATCH (mo)-[:IS_METRIC]->(metric:Metric)
        MATCH (report:Report)-[:HAS_OBSERVATION]->(mo)
        RETURN report.name as report, metric.name as metric, 
               mo.value as value, mo.confidence as confidence, mo.report_date as date
        ORDER BY mo.report_date DESC
        """
        params = {"region_name": region_name}
        return query, params
    
    @staticmethod
    def get_metric_comparison_by_entity(metric_name):
        """
        Query to compare a specific metric across all entities (States, Regions, Countries).
        Shows how each entity has its own observations.
        """
        query = """
        MATCH (mo:MetricObservation)-[:IS_METRIC]->(metric:Metric {name: $metric_name})
        MATCH (mo)-[:APPLIES_TO]->(entity)
        WHERE entity:Region OR entity:Country OR entity:State
        WITH entity.name as entity_name, labels(entity)[0] as entity_type,
             avg(mo.value) as avg_value, count(mo.value) as observation_count
        RETURN entity_name, entity_type, avg_value, observation_count
        ORDER BY avg_value DESC
        """
        params = {"metric_name": metric_name}
        return query, params
    
    @staticmethod
    def get_metric_comparison_by_region(metric_name):
        """
        Query to compare a specific metric across all regions.
        Shows how each region has its own observations.
        """
        query = """
        MATCH (mo:MetricObservation)-[:IS_METRIC]->(metric:Metric {name: $metric_name})
        MATCH (mo)-[:APPLIES_TO]->(entity)
        WHERE entity:Region OR entity:Country
        WITH entity.name as entity_name, avg(mo.value) as avg_value, 
             count(mo.value) as observation_count
        RETURN entity_name, avg_value, observation_count
        ORDER BY avg_value DESC
        """
        params = {"metric_name": metric_name}
        return query, params
    
    @staticmethod
    def get_observations_by_entity_type(entity_type):
        """
        Query to get all observations for a specific entity type (State, Region, or Country).
        """
        query = f"""
        MATCH (mo:MetricObservation)-[:APPLIES_TO]->(entity:{entity_type})
        MATCH (mo)-[:IS_METRIC]->(metric:Metric)
        MATCH (report:Report)-[:HAS_OBSERVATION]->(mo)
        RETURN entity.name as entity_name, metric.name as metric, 
               mo.value as value, mo.confidence as confidence, mo.report_date as date
        ORDER BY entity.name, mo.report_date DESC
        """
        return query, {}
    
    @staticmethod
    def get_state_observations(state_name):
        """
        Query to get observations for a specific state only.
        """
        return TimeTreeQueries.get_entity_specific_observations(state_name, "State")
    
    @staticmethod
    def get_country_observations(country_name):
        """
        Query to get observations for a specific country only.
        """
        return TimeTreeQueries.get_entity_specific_observations(country_name, "Country")
    
    @staticmethod
    def get_entity_summary():
        """
        Query to get a summary of all entities and their observation counts.
        """
        query = """
        MATCH (mo:MetricObservation)-[:APPLIES_TO]->(entity)
        WITH labels(entity)[0] as entity_type, entity.name as entity_name, 
             count(mo) as observation_count
        RETURN entity_type, entity_name, observation_count
        ORDER BY entity_type, observation_count DESC
        """
        return query, {}
    
    @staticmethod
    def get_powerline_data_by_report(report_name):
        """
        Query to get all powerline data reported in a specific report.
        Demonstrates the benefit of connecting PowerLine nodes to Report nodes.
        """
        query = """
        MATCH (r:Report {name: $report_name})-[:REPORTS_POWERLINE]->(pl:PowerLine)
        RETURN pl.line_identifier as line, pl.voltage as voltage, 
               pl.max_import as max_import, pl.max_export as max_export,
               pl.import_energy as import_energy, pl.export_energy as export_energy,
               pl.net_import_energy as net_import_energy, pl.date as date
        ORDER BY pl.line_identifier
        """
        params = {"report_name": report_name}
        return query, params
    
    @staticmethod
    def get_powerline_flow_history(line_identifier):
        """
        Query to get the flow history of a specific powerline across multiple reports.
        Shows how connecting to Report nodes enables temporal analysis.
        """
        query = """
        MATCH (r:Report)-[:REPORTS_POWERLINE]->(pl:PowerLine {line_identifier: $line_identifier})
        RETURN r.name as report, r.date as report_date, pl.date as powerline_date,
               pl.net_import_energy as net_energy, pl.voltage as voltage
        ORDER BY pl.date
        """
        params = {"line_identifier": line_identifier}
        return query, params
    
    @staticmethod
    def get_report_data_summary(report_name):
        """
        Query to get a comprehensive summary of all data types in a specific report.
        Shows the value of consistent Report node connections.
        """
        query = """
        MATCH (r:Report {name: $report_name})
        
        // Get metric observations
        OPTIONAL MATCH (r)-[:HAS_OBSERVATION]->(mo:MetricObservation)
        WITH r, count(mo) as observation_count
        
        // Get powerline data
        OPTIONAL MATCH (r)-[:REPORTS_POWERLINE]->(pl:PowerLine)
        WITH r, observation_count, count(pl) as powerline_count
        
        // Get time block data
        OPTIONAL MATCH (r)-[:HAS_DATA_FOR_BLOCK]->(tb:TimeBlock)
        WITH r, observation_count, powerline_count, count(tb) as timeblock_count
        
        // Get generation sources
        OPTIONAL MATCH (r)-[:HAS_GENERATION_SOURCE]->(gs:GenerationSource)
        WITH r, observation_count, powerline_count, timeblock_count, count(gs) as generation_count
        
        RETURN r.name as report, r.date as date, r.source as source,
               observation_count, powerline_count, timeblock_count, generation_count
        """
        params = {"report_name": report_name}
        return query, params
    
    @staticmethod
    def get_sequential_timeblock_analysis():
        """
        Query to analyze sequential patterns in timeblock data using NEXT relationships.
        """
        query = """
        MATCH path = (tb1:TimeBlock)-[:NEXT*3]->(tb4:TimeBlock)
        WHERE tb1.time = '09:00'
        RETURN tb1.time as start_time, tb4.time as end_time,
               tb1.is_peak_hour as start_peak, tb4.is_peak_hour as end_peak,
               tb1.time_category as start_category, tb4.time_category as end_category
        LIMIT 5
        """
        return query, {}
    
    @staticmethod
    def get_consecutive_day_analysis():
        """
        Query to analyze patterns across consecutive days using NEXT_DAY relationships.
        """
        query = """
        MATCH path = (d1:Day)-[:NEXT_DAY]->(d2:Day)-[:NEXT_DAY]->(d3:Day)
        MATCH (d1)<-[:FOR_DAY]-(r1:Report)
        MATCH (d2)<-[:FOR_DAY]-(r2:Report)
        MATCH (d3)<-[:FOR_DAY]-(r3:Report)
        RETURN d1.date as day1, d2.date as day2, d3.date as day3,
               r1.name as report1, r2.name as report2, r3.name as report3
        ORDER BY d1.date
        LIMIT 10
        """
        return query, {}
    
    @staticmethod
    def get_timeblock_flow_analysis(start_time, end_time):
        """
        Query to analyze flow patterns across a sequence of timeblocks.
        """
        query = """
        MATCH path = (start:TimeBlock)-[:NEXT*]->(end:TimeBlock)
        WHERE start.time = $start_time AND end.time = $end_time
        MATCH (tb:TimeBlock)
        WHERE tb IN nodes(path)
        OPTIONAL MATCH (tb)<-[rel:HAS_DATA_FOR_BLOCK]-(r:Report)
        WITH tb, r, rel, path
        RETURN tb.time as time, tb.is_peak_hour as is_peak,
               tb.time_category as category, r.name as report, rel.frequency as frequency
        ORDER BY tb.time
        """
        params = {"start_time": start_time, "end_time": end_time}
        return query, params
    
    @staticmethod
    def get_peak_hour_transitions():
        """
        Query to find transitions between peak and non-peak hours.
        """
        query = """
        MATCH (tb1:TimeBlock)-[:NEXT]->(tb2:TimeBlock)
        WHERE tb1.is_peak_hour <> tb2.is_peak_hour
        RETURN tb1.time as from_time, tb2.time as to_time,
               tb1.is_peak_hour as from_peak, tb2.is_peak_hour as to_peak,
               tb1.time_category as from_category, tb2.time_category as to_category
        ORDER BY tb1.time
        """
        return query, {}
    
    @staticmethod
    def get_timeblock_data_by_report(report_name):
        """
        Query to get all timeblock data from a specific report.
        Shows how Reports are connected to canonical TimeBlocks via relationships.
        """
        query = """
        MATCH (r:Report {name: $report_name})-[rel:HAS_DATA_FOR_BLOCK]->(tb:TimeBlock)
        RETURN tb.time as time, rel.frequency as frequency, rel.demand_met as demand_met,
               tb.time_category as category, tb.is_peak_hour as is_peak, rel.date as date
        ORDER BY tb.time
        """
        params = {"report_name": report_name}
        return query, params
    
    @staticmethod
    def get_timeblock_data_by_day(date_str):
        """
        Query to get all timeblock data for a specific day.
        Shows how Reports are connected to canonical TimeBlocks via relationships.
        """
        query = """
        MATCH (r:Report)-[:FOR_DAY]->(d:Day {date: date($date_str)})
        MATCH (r)-[rel:HAS_DATA_FOR_BLOCK]->(tb:TimeBlock)
        WHERE rel.date = $date_str
        RETURN tb.time as time, rel.frequency as frequency, rel.demand_met as demand_met,
               tb.time_category as category, tb.is_peak_hour as is_peak
        ORDER BY tb.time
        """
        params = {"date_str": date_str}
        return query, params
    
    @staticmethod
    def get_canonical_timeblocks_count():
        """
        Query to show the count of canonical TimeBlock nodes.
        """
        query = """
        MATCH (tb:TimeBlock)
        RETURN count(tb) as canonical_timeblock_count
        """
        return query, {}
    
    @staticmethod
    def get_timeblock_relationships_by_canonical():
        """
        Query to show how many data relationships exist for each canonical TimeBlock.
        """
        query = """
        MATCH (tb:TimeBlock)<-[rel:HAS_DATA_FOR_BLOCK]-()
        WITH tb.time as time, count(rel) as relationship_count
        RETURN time, relationship_count
        ORDER BY time
        """
        return query, {}

def print_query_results(result):
    """Utility to print Neo4j query results in a tabular format using tabulate, showing only the first five records and unique values for each column."""
    records = [dict(record) for record in result]
    if records:
        # Print only the first five records
        print(tabulate(records[:5], headers="keys", tablefmt="grid"))
        # Print unique values for each column
        print("\nUnique values for each column:")
        for col in records[0].keys():
            unique_vals = set(r[col] for r in records if col in r)
            try:
                sorted_vals = sorted(unique_vals, key=lambda x: (str(type(x)), str(x)))
                print(f"- {col}: {sorted_vals}")
            except Exception:
                print(f"- {col}: {unique_vals}")
    else:
        print("No results found.")

# --- MAIN ENTRY POINT ---
def main():
    """Main function to build the graph for the latest 5 dates only."""
    logging.info("--- Starting Knowledge Graph Build Process with Time Tree (Latest 5 Dates Only) ---")
    
    if not os.path.exists(DATABASE_NAME):
        logging.error(f"Database file not found at {DATABASE_NAME}. Please run the ingestion pipeline first.")
        return

    uploader = Neo4jUploader(NEO4J_CONFIG['uri'], NEO4J_CONFIG['user'], NEO4J_CONFIG['password'])
    builder = GraphBuilder(DATABASE_NAME)

    try:
        # Clear the graph database before uploading new data
        uploader.clear_database()

        latest_dates = builder.get_latest_dates(5)
        logging.info(f"Processing only for these latest dates: {sorted(latest_dates)}")
        
        with uploader._driver.session(database="neo4j") as session:
            session.execute_write(GraphModel.create_constraints)
            
            # Create canonical TimeBlock nodes with sequence (one-time setup)
            session.execute_write(GraphModel.create_time_scaffolding)
            
            logging.info("Uploading regional summary data...")
            builder.process_regional_summary(session, date_filter=latest_dates)
            
            logging.info("Uploading state generation data...")
            builder.process_state_generation(session, date_filter=latest_dates)
            
            logging.info("Uploading transnational exchange data...")
            builder.process_transnational_exchange(session, date_filter=latest_dates)
            
            logging.info("Uploading time block data...")
            builder.process_time_block_data(session, date_filter=latest_dates)
            
            # Create temporal aggregations
            logging.info("Creating temporal aggregations...")
            session.execute_write(GraphModel.create_temporal_aggregations)
            
            # Upload generation sources
            logging.info("Uploading generation sources data...")
            builder.process_generation_sources(session, date_filter=latest_dates)
            
            # Upload powerline data
            logging.info("Uploading powerline data...")
            builder.process_powerline_data(session, date_filter=latest_dates)
            
            # Upload international transmission link flow data
            logging.info("Uploading international transmission link flow data...")
            builder.process_international_link_flow(session, date_filter=latest_dates)
            
            # Create day sequence after all data is loaded
            session.execute_write(GraphModel.create_day_sequence)
            
            # Apply final fixes and cleanup
            logging.info("Applying final graph fixes and cleanup...")
            session.execute_write(GraphModel.connect_regions_to_india)
            session.execute_write(GraphModel.cleanup_orphaned_nodes)
            
        logging.info("Graph build process completed successfully!")
        logging.info("Time tree structure created with Year -> Month -> Day hierarchy")
        logging.info("All relationships and data integrity checks completed!")
        logging.info("You can now run complex temporal queries efficiently!")
        
    except Exception as e:
        logging.error(f"An error occurred during the graph build process: {e}", exc_info=True)
    finally:
        builder.close_connection()
        uploader.close()

def build_full_graph():
    """Alternative main function to build the complete graph with all dates."""
    logging.info("--- Starting Full Knowledge Graph Build Process with Time Tree ---")
    
    if not os.path.exists(DATABASE_NAME):
        logging.error(f"Database file not found at {DATABASE_NAME}. Please run the ingestion pipeline first.")
        return

    uploader = Neo4jUploader(NEO4J_CONFIG['uri'], NEO4J_CONFIG['user'], NEO4J_CONFIG['password'])
    builder = GraphBuilder(DATABASE_NAME)

    try:
        # Clear the graph database before uploading new data
        uploader.clear_database()

        all_dates = builder.get_date_range()
        logging.info(f"Processing {len(all_dates)} dates in total")
        
        with uploader._driver.session(database="neo4j") as session:
            session.execute_write(GraphModel.create_constraints)
            
            # Create canonical TimeBlock nodes with sequence (one-time setup)
            session.execute_write(GraphModel.create_time_scaffolding)
            
            logging.info("Uploading regional summary data...")
            builder.process_regional_summary(session, date_filter=all_dates)
            
            logging.info("Uploading state generation data...")
            builder.process_state_generation(session, date_filter=all_dates)
            
            logging.info("Uploading transnational exchange data...")
            builder.process_transnational_exchange(session, date_filter=all_dates)
            
            logging.info("Uploading time block data...")
            builder.process_time_block_data(session, date_filter=all_dates)
            
            # Create temporal aggregations
            logging.info("Creating temporal aggregations...")
            session.execute_write(GraphModel.create_temporal_aggregations)
            
            # Create day sequence after all data is loaded
            session.execute_write(GraphModel.create_day_sequence)
            
            # Apply final fixes and cleanup
            logging.info("Applying final graph fixes and cleanup...")
            session.execute_write(GraphModel.connect_regions_to_india)
            session.execute_write(GraphModel.cleanup_orphaned_nodes)
            
        logging.info("Full graph build process completed successfully!")
        logging.info("All relationships and data integrity checks completed!")
        
    except Exception as e:
        logging.error(f"An error occurred during the graph build process: {e}", exc_info=True)
    finally:
        builder.close_connection()
        uploader.close()

def build_date_range_graph(start_date, end_date):
    """Build graph for a specific date range."""
    logging.info(f"--- Building Knowledge Graph for date range: {start_date} to {end_date} ---")
    
    if not os.path.exists(DATABASE_NAME):
        logging.error(f"Database file not found at {DATABASE_NAME}. Please run the ingestion pipeline first.")
        return

    uploader = Neo4jUploader(NEO4J_CONFIG['uri'], NEO4J_CONFIG['user'], NEO4J_CONFIG['password'])
    builder = GraphBuilder(DATABASE_NAME)

    try:
        # Clear the graph database before uploading new data
        uploader.clear_database()

        date_range = builder.get_date_range(start_date, end_date)
        logging.info(f"Processing {len(date_range)} dates in range")
        
        with uploader._driver.session(database="neo4j") as session:
            session.execute_write(GraphModel.create_constraints)
            
            # Create canonical TimeBlock nodes with sequence (one-time setup)
            session.execute_write(GraphModel.create_time_scaffolding)
            
            logging.info("Uploading regional summary data...")
            builder.process_regional_summary(session, date_filter=date_range)
            
            logging.info("Uploading state generation data...")
            builder.process_state_generation(session, date_filter=date_range)
            
            logging.info("Uploading transnational exchange data...")
            builder.process_transnational_exchange(session, date_filter=date_range)
            
            logging.info("Uploading time block data...")
            builder.process_time_block_data(session, date_filter=date_range)
            
            # Create temporal aggregations
            logging.info("Creating temporal aggregations...")
            session.execute_write(GraphModel.create_temporal_aggregations)
            
            # Create day sequence after all data is loaded
            session.execute_write(GraphModel.create_day_sequence)
            
            # Apply final fixes and cleanup
            logging.info("Applying final graph fixes and cleanup...")
            session.execute_write(GraphModel.connect_regions_to_india)
            session.execute_write(GraphModel.cleanup_orphaned_nodes)
            
        logging.info("Date range graph build process completed successfully!")
        logging.info("All relationships and data integrity checks completed!")
        
    except Exception as e:
        logging.error(f"An error occurred during the graph build process: {e}", exc_info=True)
    finally:
        builder.close_connection()
        uploader.close()

# --- Utility function to clean up unwanted nodes ---
def cleanup_unwanted_nodes(session):
    # Remove PowerLine, BlockData, and Region node for 'India'
    session.run("MATCH (n:PowerLine) DETACH DELETE n")
    session.run("MATCH (n:BlockData) DETACH DELETE n")
    session.run("MATCH (n:Region {name: 'India'}) DETACH DELETE n")
    print("[INFO] Cleaned up unwanted nodes: PowerLine, BlockData, and Region node for 'India'.")

# In main, after constraints and before data upload, call cleanup_unwanted_nodes(session)

UNWANTED_LABELS = ["PowerLine", "BlockData", "Block", "PeakDemand"]

def drop_constraints_and_indexes(session, label):
    # Drop constraints
    constraints = session.run(f"SHOW CONSTRAINTS WHERE labelsOrTypes = ['{label}']")
    for record in constraints:
        name = record["name"]
        print(f"Dropping constraint: {name}")
        session.run(f"DROP CONSTRAINT {name}")
    # Drop indexes
    indexes = session.run(f"SHOW INDEXES WHERE labelsOrTypes = ['{label}']")
    for record in indexes:
        name = record["name"]
        print(f"Dropping index: {name}")
        session.run(f"DROP INDEX {name}")

def cleanup_unwanted_labels_and_nodes(session):
    for label in UNWANTED_LABELS:
        # Check node count
        result = session.run(f"MATCH (n:{label}) RETURN count(n) AS count")
        count = result.single()["count"]
        print(f"Label :{label} node count: {count}")
        if count > 0:
            print(f"Deleting all :{label} nodes...")
            session.run(f"MATCH (n:{label}) DETACH DELETE n")
        # Drop constraints and indexes
        drop_constraints_and_indexes(session, label)
    print("[INFO] Unwanted labels and nodes cleanup complete.")

# In main, after constraints and before data upload, call cleanup_unwanted_labels_and_nodes(session)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "full":
            build_full_graph()
        elif sys.argv[1] == "range" and len(sys.argv) == 4:
            build_date_range_graph(sys.argv[2], sys.argv[3])
        else:
            print("Usage:")
            print("  python Powerflow_GRAPH_BUILDER.py          # Build latest 5 dates")
            print("  python Powerflow_GRAPH_BUILDER.py full     # Build all dates")
            print("  python Powerflow_GRAPH_BUILDER.py range YYYY-MM-DD YYYY-MM-DD  # Build date range")
    else:
        main()
