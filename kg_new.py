# /graph_builder/graph_model.py
# This file defines the schema of our knowledge graph: the types of nodes and relationships.

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
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Day) REQUIRE (d.year, d.month, d.day) IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (dt:Date) REQUIRE dt.date IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Report) REQUIRE r.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (rg:Region) REQUIRE rg.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:State) REQUIRE s.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Metric) REQUIRE m.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (u:Unit) REQUIRE u.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (em:ExchangeMechanism) REQUIRE em.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (tb:TimeBlock) REQUIRE tb.time IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (gs:GenerationSource) REQUIRE gs.name IS UNIQUE;",
        ]
        for query in queries:
            tx.run(query)
        logging.info("Constraints created successfully.")

    @staticmethod
    def create_timeblock_nodes(tx):
        # Only 96 canonical TimeBlock nodes (one for each 15-min interval)
        for h in range(24):
            for m in [0, 15, 30, 45]:
                time_str = f'{h:02d}:{m:02d}'
                tx.run("MERGE (tb:TimeBlock {time: $time_str})", time_str=time_str)

    @staticmethod
    def create_time_tree_nodes(tx, date_str):
        """
        Creates the time tree structure: Year -> Month -> Day -> Date
        This hierarchical structure makes temporal queries much more efficient.
        """
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            year, month, day = date_obj.year, date_obj.month, date_obj.day
            query = """
            MERGE (y:Year {year: $year})
            MERGE (m:Month {year: $year, month: $month})
            MERGE (d:Day {year: $year, month: $month, day: $day})
            MERGE (dt:Date {date: $date_str})
            MERGE (m)-[:IN_YEAR]->(y)
            MERGE (d)-[:IN_MONTH]->(m)
            MERGE (dt)-[:ON_DAY]->(d)
            """
            tx.run(query, year=year, month=month, day=day, date_str=date_str)
        except ValueError as e:
            logging.error(f"Invalid date format: {date_str}. Expected YYYY-MM-DD. Error: {e}")

    @staticmethod
    def create_report_node(tx, report_name, report_date, source_region):
        """
        Creates a Report node and links it to the time tree structure.
        """
        # First ensure the time tree exists
        GraphModel.create_time_tree_nodes(tx, report_date)
        
        query = """
        MATCH (dt:Date {date: $report_date})
        MERGE (r:Report {name: $report_name})
        SET r.source = $source_region, r.date = $report_date
        MERGE (r)-[:ON_DATE]->(dt)
        """
        tx.run(query, report_name=report_name, report_date=report_date, source_region=source_region)

    @staticmethod
    def create_metric_relationship(tx, report_name, metric_name, value, unit, entity_type, entity_name, confidence):
        """
        Creates a relationship from a Report to a Metric for a specific entity (Region or State).
        This is the core of our model for handling conflicting values. Each report states its own value
        for a metric, and we capture this with a relationship property, along with a confidence score.
        """
        query = f"""
        MATCH (r:Report {{name: $report_name}})
        MERGE (m:Metric {{name: $metric_name}})
        MERGE (u:Unit {{name: $unit}})
        MERGE (m)-[:HAS_UNIT]->(u)
        MERGE (e:{entity_type} {{name: $entity_name}})
        MERGE (r)-[rel:REPORTS_METRIC {{for_entity: $entity_name, metric: $metric_name}}]->(m)
        SET rel.value = $value, rel.confidence = $confidence, rel.unit = $unit, rel.reported_at = datetime()
        MERGE (m)-[:APPLIES_TO]->(e)
        """
        tx.run(query, report_name=report_name, metric_name=metric_name, value=value, unit=unit, entity_name=entity_name, confidence=confidence)

    @staticmethod
    def create_geographical_nodes(tx, state_name, region_name):
        region_name_canon = canonical_region(region_name)
        if not region_name_canon:
            return  # Do not create a Region node for 'India' or None
        query = """
        MERGE (s:State {name: $state_name})
        SET s.type = 'State'
        MERGE (r:Region {name: $region_name})
        SET r.type = 'Region'
        MERGE (s)-[:IN_REGION]->(r)
        """
        tx.run(query, state_name=state_name, region_name=region_name_canon)

    @staticmethod
    def create_transnational_exchange(tx, report_name, country, mechanism, direction, value, unit, date_str):
        """
        Models the transnational exchange of power with time tree integration.
        Relationship is always between India (Country) and the foreign Country node.
        """
        # Ensure time tree exists
        GraphModel.create_time_tree_nodes(tx, date_str)
        query = """
        MATCH (r:Report {name: $report_name})
        MATCH (dt:Date {date: $date_str})-[:ON_DAY]->(d:Day)
        MERGE (india:Country {name: 'India'})
        MERGE (c:Country {name: $country})
        SET c.type = 'Country'
        MERGE (em:ExchangeMechanism {name: $mechanism})
        MERGE (u:Unit {name: $unit})

        // Create a relationship representing the transaction
        MERGE (india)-[rel:EXCHANGED_POWER_WITH]->(c)
        SET rel.direction = $direction,
            rel.value = $value,
            rel.mechanism = $mechanism,
            rel.unit = $unit,
            rel.date = $date_str,
            rel.reported_at = datetime(),
            rel.report = $report_name
        """
        tx.run(query, report_name=report_name, country=country, mechanism=mechanism, direction=direction, value=value, unit=unit, date_str=date_str)

    @staticmethod
    def create_time_block_data(tx, report_name, block_time, block_number, frequency, demand_met, date_str):
        """
        Creates nodes for 15-minute time block data and links them to the time tree.
        """
        # Ensure time tree exists
        GraphModel.create_time_tree_nodes(tx, date_str)
        
        query = """
        MATCH (r:Report {name: $report_name})
        MATCH (dt:Date {date: $date_str})-[:ON_DAY]->(d:Day)-[:IN_MONTH]->(m:Month)
        
        // Create TimeBlock with enhanced properties
        CREATE (tb:TimeBlock {
            datetime: datetime($date_str + 'T' + $block_time),
            date: $date_str,
            time: $block_time,
            block_number: $block_number,
            frequency: $frequency,
            demand_met: $demand_met,
            hour: toInteger(split($block_time, ':')[0]),
            minute: toInteger(split($block_time, ':')[1])
        })
        
        // Categorize time blocks
        SET tb.time_category = CASE
            WHEN tb.hour >= 6 AND tb.hour < 12 THEN 'Morning'
            WHEN tb.hour >= 12 AND tb.hour < 18 THEN 'Afternoon'
            WHEN tb.hour >= 18 AND tb.hour < 22 THEN 'Evening'
            ELSE 'Night'
        END,
        tb.is_peak_hour = tb.hour IN [9, 10, 11, 18, 19, 20, 21]
        
        // Link to report and time tree
        MERGE (r)-[:HAS_TIME_BLOCK]->(tb)
        MERGE (tb)-[:ON_DAY]->(d)
        MERGE (tb)-[:IN_MONTH]->(m)
        """
        tx.run(query, report_name=report_name, block_time=block_time, block_number=block_number, frequency=frequency, demand_met=demand_met, date_str=date_str)

    @staticmethod
    def create_temporal_aggregations(tx):
        """
        Creates aggregated nodes for common temporal queries (Quarters), skipping null quarters.
        """
        query = """
        // Create Quarter nodes, skip if quarter is null
        MATCH (m:Month)-[:IN_YEAR]->(y:Year)
        WITH y, m.quarter as quarter, collect(m) as months
        WHERE quarter IS NOT NULL
        MERGE (q:Quarter {year: y.year, quarter: quarter})
        SET q.name = y.year + '-Q' + toString(quarter)
        MERGE (q)-[:IN_YEAR]->(y)
        WITH q, months
        UNWIND months as month
        MERGE (month)-[:IN_QUARTER]->(q)
        """
        tx.run(query)
        logging.info("Created temporal aggregation nodes (Quarters)")

    @staticmethod
    def create_generation_source_relationship(tx, report_name, region_name, date_str, source_name, source_category, amount, unit):
        """
        Creates GenerationSource node and relationship to Region and Report for daily generation breakdown.
        """
        # Ensure time tree exists
        GraphModel.create_time_tree_nodes(tx, date_str)
        query = """
        MATCH (r:Report {name: $report_name})
        MERGE (region:Region {name: $region_name})
        MERGE (gs:GenerationSource {name: $source_name})
        SET gs.category = $source_category
        MERGE (region)-[rel:GENERATED_FROM]->(gs)
        SET rel.amount = $amount, rel.unit = $unit, rel.date = $date_str
        MERGE (r)-[:HAS_GENERATION_SOURCE {region: $region_name, source: $source_name, date: $date_str}]->(gs)
        """
        tx.run(query, report_name=report_name, region_name=region_name, date_str=date_str, source_name=source_name, source_category=source_category, amount=amount, unit=unit)

    @staticmethod
    def create_timeblock_generation_source(tx, report_name, block_time, block_number, date_str, source_name, source_category, amount, unit):
        """
        Creates GenerationSource node and relationship to TimeBlock for blockwise generation breakdown.
        """
        # Ensure time tree exists
        GraphModel.create_time_tree_nodes(tx, date_str)
        query = """
        MATCH (r:Report {name: $report_name})
        MATCH (tb:TimeBlock {date: $date_str, time: $block_time, block_number: $block_number})
        MERGE (gs:GenerationSource {name: $source_name})
        SET gs.category = $source_category
        MERGE (tb)-[rel:GENERATED_FROM]->(gs)
        SET rel.amount = $amount, rel.unit = $unit
        MERGE (r)-[:HAS_GENERATION_SOURCE {block_time: $block_time, source: $source_name, date: $date_str}]->(gs)
        """
        tx.run(query, report_name=report_name, block_time=block_time, block_number=block_number, date_str=date_str, source_name=source_name, source_category=source_category, amount=amount, unit=unit)

    @staticmethod
    def create_powerline_relationship(tx, report_name, line_identifier, voltage, region1, region2, max_import, max_export, import_energy, export_energy, net_import_energy, date_str):
        """
        Creates a POWERLINE relationship (with properties) between two Region nodes for domestic transmission.
        """
        GraphModel.create_time_tree_nodes(tx, date_str)
        query = """
        MERGE (reg1:Region {name: $region1})
        MERGE (reg2:Region {name: $region2})
        MERGE (reg1)-[pl:POWERLINE {line_identifier: $line_identifier, date: $date_str}]->(reg2)
        SET pl.voltage = $voltage,
            pl.max_import = $max_import,
            pl.max_export = $max_export,
            pl.import_energy = $import_energy,
            pl.export_energy = $export_energy,
            pl.net_import_energy = $net_import_energy,
            pl.report = $report_name
        """
        tx.run(query, report_name=report_name, line_identifier=line_identifier, voltage=voltage, region1=region1, region2=region2, max_import=max_import, max_export=max_export, import_energy=import_energy, export_energy=export_energy, net_import_energy=net_import_energy, date_str=date_str)

    @staticmethod
    def create_international_powerline_relationship(tx, report_name, line_identifier, voltage, region_name, country_name, max_loading, min_loading, avg_loading, energy_exchanged, date_str):
        """
        Creates a POWERLINE relationship (with properties) between a Region and a Country node for international transmission.
        """
        GraphModel.create_time_tree_nodes(tx, date_str)
        query = """
        MERGE (reg:Region {name: $region_name})
        MERGE (c:Country {name: $country_name})
        MERGE (reg)-[pl:POWERLINE {line_identifier: $line_identifier, date: $date_str}]->(c)
        SET pl.voltage = $voltage,
            pl.max_loading = $max_loading,
            pl.min_loading = $min_loading,
            pl.avg_loading = $avg_loading,
            pl.energy_exchanged = $energy_exchanged,
            pl.report = $report_name
        """
        tx.run(query, report_name=report_name, line_identifier=line_identifier, voltage=voltage, region_name=region_name, country_name=country_name, max_loading=max_loading, min_loading=min_loading, avg_loading=avg_loading, energy_exchanged=energy_exchanged, date_str=date_str)

    @staticmethod
    def connect_regions_to_india(tx):
        """
        Connects all Region nodes (except 'India') to the Country node 'India' with an :IN_COUNTRY relationship.
        """
        query = """
        MERGE (c:Country {name: 'India'})
        WITH c
        MATCH (r:Region)
        WHERE r.name <> 'India'
        MERGE (r)-[:IN_COUNTRY]->(c)
        """
        tx.run(query)

    @staticmethod
    def create_timeblock_relationship(tx, report_name, block_time, value_dict):
        query = """
        MATCH (r:Report {name: $report_name})
        MATCH (tb:TimeBlock {time: $block_time})
        MERGE (r)-[rel:HAS_DATA_FOR_BLOCK {block_time: $block_time}]->(tb)
        SET rel += $value_dict
        """
        tx.run(query, report_name=report_name, block_time=block_time, value_dict=value_dict)

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

            # Create timeblock nodes
            session.execute_write(GraphModel.create_timeblock_nodes)

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
        # Handles both old and new formats
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
        # Fallback to old logic
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
        """Processes FactAllIndiaDailySummary data for filtered dates only."""
        cursor = self.conn.cursor()
        query = """
        SELECT frs.*, dr.RegionName, dd.ActualDate, drp.ReportName
        FROM FactAllIndiaDailySummary frs
        JOIN DimRegions dr ON frs.RegionID = dr.RegionID
        JOIN DimDates dd ON frs.DateID = dd.DateID
        JOIN DimReports drp ON frs.DateID = drp.DateID
        """
        cursor.execute(query)
        for row in cursor.fetchall():
            if date_filter and row['ActualDate'] not in date_filter:
                continue
            report_name = os.path.basename(row['ReportName'])
            report_date, source_region = self._get_report_details(report_name)
            if not report_date: continue

            confidence = SOURCE_CONFIDENCE.get(source_region, 0.5)

            session.execute_write(GraphModel.create_report_node, report_name, report_date, source_region)

            # Use only columns that exist in the result set
            metrics = {}
            if 'PeakDemandMet' in row.keys():
                metrics["Peak Demand Met"] = (row["PeakDemandMet"], "MW")
            if 'PeakShortage' in row.keys():
                metrics["Peak Shortage"] = (row["PeakShortage"], "MW")
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

            # Attach metrics for 'India' to Country node, others to Region node
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
                        GraphModel.create_metric_relationship,
                        report_name, metric_name, value, unit,
                        entity_type, entity_name, confidence
                    )

    def process_state_generation(self, session, date_filter=None):
        """Processes FactStateDailyEnergy data for filtered dates only."""
        cursor = self.conn.cursor()
        query = """
        SELECT fsg.*, ds.StateName, dr.RegionName, dd.ActualDate, drp.ReportName
        FROM FactStateDailyEnergy fsg
        JOIN DimStates ds ON fsg.StateID = ds.StateID
        JOIN DimRegions dr ON ds.RegionID = dr.RegionID
        JOIN DimDates dd ON fsg.DateID = dd.DateID
        JOIN DimReports drp ON fsg.DateID = drp.DateID
        """
        cursor.execute(query)
        for row in cursor.fetchall():
            if date_filter and row['ActualDate'] not in date_filter:
                continue
            report_name = os.path.basename(row['ReportName'])
            report_date, source_region = self._get_report_details(report_name)
            if not report_date: continue

            confidence = SOURCE_CONFIDENCE.get(source_region, 0.5)

            # Ensure geo nodes exist
            session.execute_write(GraphModel.create_geographical_nodes, row['StateName'], row['RegionName'])
            session.execute_write(GraphModel.create_report_node, report_name, report_date, source_region)

            # Only add state-level metrics that exist in FactStateDailyEnergy
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
                    GraphModel.create_metric_relationship,
                    report_name, metric_name, value, unit,
                    'State', row['StateName'], confidence
                    )

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
            logging.info(f"Transnational exchange: {report_name}, {country}, {mechanism}, {direction}, {value} {unit}")

    def process_time_block_data(self, session, date_filter=None):
        """Processes time block data for filtered dates only, using canonical TimeBlock nodes and relationship properties. No region info is used; data is national-level."""
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
            value_dict = {
                'block_number': row['BlockNumber'],
                'frequency': row['Frequency'],
                'demand_met': row['DemandMet'],
                'date': row['ActualDate'],
                'for_entity': 'India'  # Explicitly mark as national-level
            }
            session.execute_write(
                GraphModel.create_timeblock_relationship,
                report_name, row['BlockTime'], value_dict
            )

    def process_generation_sources(self, session, date_filter=None):
        """Processes FactDailyGenerationBreakdown and FactTimeBlockGeneration for generation sources."""
        cursor = self.conn.cursor()
        # Daily generation breakdown
        query = '''
        SELECT d.ActualDate, dr.RegionName, drp.ReportName, gs.SourceName, gs.SourceCategory, f.GenerationAmount
        FROM FactDailyGenerationBreakdown f
        JOIN DimDates d ON f.DateID = d.DateID
        JOIN DimRegions dr ON f.RegionID = dr.RegionID
        JOIN DimGenerationSources gs ON f.GenerationSourceID = gs.GenerationSourceID
        JOIN DimReports drp ON f.DateID = drp.DateID
        '''
        cursor.execute(query)
        for row in cursor.fetchall():
            if date_filter and row['ActualDate'] not in date_filter:
                continue
            if 'RegionName' in row.keys():
                region_name = row['RegionName']
            elif 'region' in row.keys():
                region_name = row['region']
            elif 'region_name' in row.keys():
                region_name = row['region_name']
            else:
                print(f"[WARNING] No region name found in row: {dict(row)}. Skipping.")
                continue
            region_canon = canonical_region(region_name)
            if region_canon:
                session.execute_write(
                    GraphModel.create_generation_source_relationship,
                    row['ReportName'], region_canon, row['ActualDate'],
                    row['SourceName'], row['SourceCategory'], row['GenerationAmount'], 'MU'
                )
        # Blockwise generation breakdown (no region, always link to India)
        query2 = '''
        SELECT d.ActualDate, ftbg.BlockTime, ftbg.BlockNumber, drp.ReportName, gs.SourceName, gs.SourceCategory, ftbg.GenerationOutput
        FROM FactTimeBlockGeneration ftbg
        JOIN DimDates d ON ftbg.DateID = d.DateID
        JOIN DimGenerationSources gs ON ftbg.GenerationSourceID = gs.GenerationSourceID
        JOIN DimReports drp ON ftbg.DateID = drp.DateID
        '''
        cursor.execute(query2)
        for row in cursor.fetchall():
            if date_filter and row['ActualDate'] not in date_filter:
                continue
            report_name = row['ReportName']
            session.execute_write(
                GraphModel.create_timeblock_generation_source,
                report_name, row['BlockTime'], row['BlockNumber'], row['ActualDate'],
                'India', row['SourceCategory'], row['GenerationOutput'], 'MW'
            )

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
        MATCH (d:Day)-[:IN_MONTH]->(m)
        MATCH (r:Report)-[:ON_DAY]->(d)
        OPTIONAL MATCH (r)-[rel:REPORTS_METRIC]->(metric:Metric)
        RETURN d.name as date, r.name as report, metric.name as metric_name, 
               rel.value as value, metric.category as category
        ORDER BY d.name
        """
        params = {"year": year, "month": month}
        return query, params
    
    @staticmethod
    def get_data_for_quarter(year, quarter):
        """Query to get all data for a specific quarter."""
        query = """
        MATCH (q:Quarter {year: $year, quarter: $quarter})
        MATCH (m:Month)-[:IN_QUARTER]->(q)
        MATCH (d:Day)-[:IN_MONTH]->(m)
        MATCH (r:Report)-[:ON_DAY]->(d)
        OPTIONAL MATCH (r)-[rel:REPORTS_METRIC]->(metric:Metric)
        RETURN m.name as month, d.name as date, r.name as report, 
               metric.name as metric_name, rel.value as value
        ORDER BY m.name, d.name
        """
        params = {"year": year, "quarter": quarter}
        return query, params
    
    @staticmethod
    def get_weekend_vs_weekday_analysis():
        """Query to compare weekend vs weekday power consumption."""
        query = """
        MATCH (d:Day)<-[:ON_DAY]-(r:Report)
        MATCH (r)-[rel:REPORTS_METRIC]->(m:Metric {name: 'Peak Demand Met'})
        WITH d.is_weekend as is_weekend, avg(rel.value) as avg_demand
        RETURN is_weekend, avg_demand
        ORDER BY is_weekend
        """
        return query, {}
    
    @staticmethod
    def get_monthly_trends(metric_name):
        """Query to get monthly trends for a specific metric."""
        query = """
        MATCH (m:Month)<-[:IN_MONTH]-(d:Day)<-[:ON_DAY]-(r:Report)
        MATCH (r)-[rel:REPORTS_METRIC]->(metric:Metric {name: $metric_name})
        WITH m, avg(rel.value) as avg_value, count(rel.value) as data_points
        RETURN m.year as year, m.month as month, m.name as month_name, 
               avg_value, data_points
        ORDER BY m.year, m.month
        """
        params = {"metric_name": metric_name}
        return query, params
    
    @staticmethod
    def get_peak_hours_analysis():
        """Query to analyze peak hours using time block data."""
        query = """
        MATCH (tb:TimeBlock)
        WITH tb.hour as hour, tb.is_peak_hour as is_peak, 
             avg(tb.demand_met) as avg_demand, avg(tb.frequency) as avg_frequency
        RETURN hour, is_peak, avg_demand, avg_frequency
        ORDER BY hour
        """
        return query, {}
    
    @staticmethod
    def get_seasonal_patterns():
        """Query to identify seasonal patterns in power consumption."""
        query = """
        MATCH (m:Month)<-[:IN_MONTH]-(d:Day)<-[:ON_DAY]-(r:Report)
        MATCH (r)-[rel:REPORTS_METRIC]->(metric:Metric {name: 'Energy Met'})
        WITH m.month as month, m.month_name as month_name,
             avg(rel.value) as avg_energy,
             CASE 
                WHEN m.month IN [12, 1, 2] THEN 'Winter'
                WHEN m.month IN [3, 4, 5] THEN 'Spring'
                WHEN m.month IN [6, 7, 8] THEN 'Summer'
                ELSE 'Autumn'
             END as season
        RETURN season, month_name, avg_energy
        ORDER BY month
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
            
            # Create timeblock nodes
            session.execute_write(GraphModel.create_timeblock_nodes)
            
        logging.info("Graph build process completed successfully!")
        logging.info("Time tree structure created with Year -> Month -> Day -> Date hierarchy")
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
            
        logging.info("Full graph build process completed successfully!")
        
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
            
        logging.info("Date range graph build process completed successfully!")
        
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
