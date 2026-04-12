#!/usr/bin/env python3
"""
Comprehensive test script for the Powerflow Knowledge Graph
Tests data integrity, relationships, and query functionality
"""

import logging
import sys
from datetime import datetime, timedelta
from neo4j import GraphDatabase
from tabulate import tabulate

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Neo4j configuration
NEO4J_CONFIG = {
    "uri": "neo4j://localhost:7687",
    "user": "neo4j",
    "password": "powerflow"
}

class GraphTester:
    """Comprehensive test suite for the Powerflow Knowledge Graph"""
    
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.test_results = []
        
    def close(self):
        self.driver.close()
        
    def run_test(self, test_name, test_func):
        """Run a test and record results"""
        try:
            logger.info(f"Running test: {test_name}")
            result = test_func()
            self.test_results.append({
                'test': test_name,
                'status': 'PASS',
                'result': result
            })
            logger.info(f"✓ {test_name} - PASSED")
            return result
        except Exception as e:
            logger.error(f"✗ {test_name} - FAILED: {str(e)}")
            self.test_results.append({
                'test': test_name,
                'status': 'FAIL',
                'error': str(e)
            })
            return None
    
    def test_connection(self):
        """Test Neo4j connection"""
        with self.driver.session() as session:
            result = session.run("RETURN 1 as test")
            return result.single()["test"] == 1
    
    def test_node_counts(self):
        """Test basic node counts"""
        with self.driver.session() as session:
            counts = {}
            node_types = ['Report', 'State', 'Region', 'Country', 'Metric', 'MetricObservation', 
                         'TimeBlock', 'Day', 'Month', 'Year', 'Unit', 'GenerationSource']
            
            for node_type in node_types:
                result = session.run(f"MATCH (n:{node_type}) RETURN count(n) as count")
                counts[node_type] = result.single()["count"]
            
            return counts
    
    def test_relationship_counts(self):
        """Test relationship counts"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) as relationship_type, count(r) as count
                ORDER BY count DESC
            """)
            return [dict(record) for record in result]
    
    def test_time_tree_integrity(self):
        """Test time tree structure integrity"""
        with self.driver.session() as session:
            # Check if time tree exists
            result = session.run("""
                MATCH (y:Year)-[:HAS_MONTH]->(m:Month)-[:HAS_DAY]->(d:Day)
                RETURN count(y) as years, count(m) as months, count(d) as days
            """)
            time_tree = result.single()
            
            # Check canonical TimeBlocks
            result = session.run("MATCH (tb:TimeBlock) RETURN count(tb) as timeblock_count")
            timeblock_count = result.single()["timeblock_count"]
            
            return {
                'years': time_tree["years"],
                'months': time_tree["months"], 
                'days': time_tree["days"],
                'timeblocks': timeblock_count
            }
    
    def test_metric_observations(self):
        """Test MetricObservation pattern"""
        with self.driver.session() as session:
            # Check if MetricObservations are properly connected
            result = session.run("""
                MATCH (mo:MetricObservation)
                OPTIONAL MATCH (mo)-[:IS_METRIC]->(m:Metric)
                OPTIONAL MATCH (mo)-[:APPLIES_TO]->(e)
                OPTIONAL MATCH (mo)<-[:HAS_OBSERVATION]-(r:Report)
                RETURN count(mo) as total_observations,
                       count(m) as connected_metrics,
                       count(e) as connected_entities,
                       count(r) as connected_reports
            """)
            return dict(result.single())
    
    def test_geographical_hierarchy(self):
        """Test geographical hierarchy (States -> Regions -> Country)"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (s:State)-[:IN_REGION]->(r:Region)-[:IN_COUNTRY]->(c:Country)
                WHERE c.name = 'India'
                RETURN count(s) as states_in_india,
                       count(DISTINCT r) as regions_in_india
            """)
            return dict(result.single())
    
    def test_report_data_integrity(self):
        """Test report data integrity"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (r:Report)
                OPTIONAL MATCH (r)-[:HAS_OBSERVATION]->(mo:MetricObservation)
                OPTIONAL MATCH (r)-[:HAS_DATA_FOR_BLOCK]->(tb:TimeBlock)
                OPTIONAL MATCH (r)-[:REPORTS_POWERLINE]->(pl:PowerLine)
                RETURN count(r) as total_reports,
                       count(mo) as total_observations,
                       count(tb) as total_timeblocks,
                       count(pl) as total_powerlines
            """)
            return dict(result.single())
    
    def test_latest_data(self):
        """Test latest data availability"""
        with self.driver.session() as session:
            # Get latest 5 dates
            result = session.run("""
                MATCH (d:Day)<-[:FOR_DAY]-(r:Report)
                RETURN d.date as date, count(r) as report_count
                ORDER BY d.date DESC
                LIMIT 5
            """)
            return [dict(record) for record in result]
    
    def test_region_data(self):
        """Test region-specific data"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (r:Region)
                OPTIONAL MATCH (r)<-[:APPLIES_TO]-(mo:MetricObservation)
                OPTIONAL MATCH (r)<-[:IN_REGION]-(s:State)
                RETURN r.name as region_name,
                       count(mo) as observations,
                       count(s) as states
                ORDER BY observations DESC
            """)
            return [dict(record) for record in result]
    
    def test_state_data(self):
        """Test state-specific data"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (s:State)
                OPTIONAL MATCH (s)<-[:APPLIES_TO]-(mo:MetricObservation)
                RETURN s.name as state_name,
                       count(mo) as observations
                ORDER BY observations DESC
                LIMIT 10
            """)
            return [dict(record) for record in result]
    
    def test_timeblock_data(self):
        """Test timeblock data integrity"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (tb:TimeBlock)<-[rel:HAS_DATA_FOR_BLOCK]-()
                RETURN tb.time as time,
                       tb.is_peak_hour as is_peak,
                       count(rel) as data_points,
                       avg(rel.frequency) as avg_frequency,
                       avg(rel.demand_met) as avg_demand
                ORDER BY tb.time
                LIMIT 10
            """)
            return [dict(record) for record in result]
    
    def test_metric_distribution(self):
        """Test metric distribution across entities"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (mo:MetricObservation)-[:IS_METRIC]->(m:Metric)
                RETURN m.name as metric_name,
                       count(mo) as observation_count,
                       avg(mo.value) as avg_value,
                       min(mo.value) as min_value,
                       max(mo.value) as max_value
                ORDER BY observation_count DESC
                LIMIT 10
            """)
            return [dict(record) for record in result]
    
    def test_orphaned_nodes(self):
        """Test for orphaned nodes"""
        with self.driver.session() as session:
            # Check for orphaned MetricObservations
            result = session.run("""
                MATCH (mo:MetricObservation)
                WHERE NOT (mo)-[:IS_METRIC]->() OR NOT (mo)-[:APPLIES_TO]->()
                RETURN count(mo) as orphaned_observations
            """)
            orphaned_obs = result.single()["orphaned_observations"]
            
            # Check for orphaned Reports
            result = session.run("""
                MATCH (r:Report)
                WHERE NOT (r)-[:HAS_OBSERVATION]->() 
                  AND NOT (r)-[:HAS_DATA_FOR_BLOCK]->()
                  AND NOT (r)-[:REPORTS_POWERLINE]->()
                RETURN count(r) as orphaned_reports
            """)
            orphaned_reports = result.single()["orphaned_reports"]
            
            return {
                'orphaned_observations': orphaned_obs,
                'orphaned_reports': orphaned_reports
            }
    
    def test_performance_queries(self):
        """Test performance of common queries"""
        with self.driver.session() as session:
            # Test regional summary query
            start_time = datetime.now()
            result = session.run("""
                MATCH (r:Region)<-[:APPLIES_TO]-(mo:MetricObservation)-[:IS_METRIC]->(m:Metric {name: 'Energy Met'})
                RETURN r.name as region, avg(mo.value) as avg_energy
                ORDER BY avg_energy DESC
            """)
            regional_data = [dict(record) for record in result]
            regional_time = (datetime.now() - start_time).total_seconds()
            
            # Test time-based query
            start_time = datetime.now()
            result = session.run("""
                MATCH (d:Day)<-[:FOR_DAY]-(r:Report)-[:HAS_OBSERVATION]->(mo:MetricObservation)
                WHERE d.date >= date('2025-01-01')
                RETURN d.date as date, count(mo) as observations
                ORDER BY d.date DESC
                LIMIT 10
            """)
            time_data = [dict(record) for record in result]
            time_query_time = (datetime.now() - start_time).total_seconds()
            
            return {
                'regional_query_time': regional_time,
                'time_query_time': time_query_time,
                'regional_data_count': len(regional_data),
                'time_data_count': len(time_data)
            }
    
    def run_all_tests(self):
        """Run all tests and generate report"""
        logger.info("=== Starting Powerflow Graph Test Suite ===")
        
        # Basic connectivity and structure tests
        self.run_test("Neo4j Connection", self.test_connection)
        self.run_test("Node Counts", self.test_node_counts)
        self.run_test("Relationship Counts", self.test_relationship_counts)
        self.run_test("Time Tree Integrity", self.test_time_tree_integrity)
        
        # Data integrity tests
        self.run_test("Metric Observations Pattern", self.test_metric_observations)
        self.run_test("Geographical Hierarchy", self.test_geographical_hierarchy)
        self.run_test("Report Data Integrity", self.test_report_data_integrity)
        self.run_test("Orphaned Nodes Check", self.test_orphaned_nodes)
        
        # Data availability tests
        self.run_test("Latest Data Availability", self.test_latest_data)
        self.run_test("Region Data", self.test_region_data)
        self.run_test("State Data", self.test_state_data)
        self.run_test("Timeblock Data", self.test_timeblock_data)
        self.run_test("Metric Distribution", self.test_metric_distribution)
        
        # Performance tests
        self.run_test("Query Performance", self.test_performance_queries)
        
        # Generate report
        self.generate_report()
    
    def generate_report(self):
        """Generate comprehensive test report"""
        logger.info("\n=== TEST REPORT ===")
        
        passed = sum(1 for result in self.test_results if result['status'] == 'PASS')
        failed = sum(1 for result in self.test_results if result['status'] == 'FAIL')
        total = len(self.test_results)
        
        print(f"\nOverall Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
        
        if failed > 0:
            print(f"\n❌ FAILED TESTS:")
            for result in self.test_results:
                if result['status'] == 'FAIL':
                    print(f"  - {result['test']}: {result['error']}")
        
        print(f"\n✅ PASSED TESTS:")
        for result in self.test_results:
            if result['status'] == 'PASS':
                print(f"  - {result['test']}")
                if 'result' in result and result['result']:
                    if isinstance(result['result'], dict):
                        for key, value in result['result'].items():
                            print(f"    {key}: {value}")
                    elif isinstance(result['result'], list) and len(result['result']) > 0:
                        print(f"    Count: {len(result['result'])}")
                        if isinstance(result['result'][0], dict):
                            print(f"    Sample: {list(result['result'][0].keys())}")
        
        # Detailed results table
        print(f"\n📊 DETAILED RESULTS:")
        table_data = []
        for result in self.test_results:
            status_icon = "✅" if result['status'] == 'PASS' else "❌"
            table_data.append([
                status_icon,
                result['test'],
                result['status'],
                result.get('error', 'N/A')
            ])
        
        print(tabulate(table_data, headers=['Status', 'Test', 'Result', 'Error'], tablefmt='grid'))

def main():
    """Main test execution"""
    try:
        tester = GraphTester(NEO4J_CONFIG['uri'], NEO4J_CONFIG['user'], NEO4J_CONFIG['password'])
        tester.run_all_tests()
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        sys.exit(1)
    finally:
        tester.close()

if __name__ == "__main__":
    main() 