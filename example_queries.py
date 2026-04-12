#!/usr/bin/env python3
"""
Example queries demonstrating the MetricObservation pattern solution to the supernode problem.

This script shows how the new graph structure allows for clean, region-specific queries
without the visualization issues caused by supernodes.
"""

from neo4j import GraphDatabase
from Powerflow_GRAPH_BUILDER import TimeTreeQueries, print_query_results

# Neo4j connection configuration
NEO4J_CONFIG = {
    "uri": "neo4j://localhost:7687",
    "user": "neo4j",
    "password": "powerflow"  # Change this to your password
}

def run_example_queries():
    """Run example queries to demonstrate the MetricObservation pattern."""
    
    driver = GraphDatabase.driver(NEO4J_CONFIG['uri'], auth=(NEO4J_CONFIG['user'], NEO4J_CONFIG['password']))
    
    try:
        with driver.session(database="neo4j") as session:
            
            print("=" * 80)
            print("METRIC OBSERVATION PATTERN DEMONSTRATION")
            print("=" * 80)
            
            # Example 1: Get observations for Northern Region only
            print("\n1. NORTHERN REGION OBSERVATIONS ONLY")
            print("-" * 50)
            query, params = TimeTreeQueries.get_region_specific_observations("Northern Region")
            result = session.run(query, params)
            print_query_results(result)
            
            # Example 2: Get observations for India (Country) only
            print("\n2. INDIA (COUNTRY) OBSERVATIONS ONLY")
            print("-" * 50)
            query, params = TimeTreeQueries.get_country_observations("India")
            result = session.run(query, params)
            print_query_results(result)
            
            # Example 3: Compare Energy Met across all entities (States, Regions, Countries)
            print("\n3. ENERGY MET COMPARISON ACROSS ALL ENTITIES")
            print("-" * 50)
            query, params = TimeTreeQueries.get_metric_comparison_by_entity("Energy Met")
            result = session.run(query, params)
            print_query_results(result)
            
            # Example 4: Get monthly trends for Peak Demand Met
            print("\n4. MONTHLY TRENDS FOR PEAK DEMAND MET")
            print("-" * 50)
            query, params = TimeTreeQueries.get_monthly_trends("Peak Demand Met")
            result = session.run(query, params)
            print_query_results(result)
            
            # Example 5: Show the graph structure
            print("\n5. GRAPH STRUCTURE ANALYSIS")
            print("-" * 50)
            structure_query = """
            MATCH (r:Report)-[:HAS_OBSERVATION]->(mo:MetricObservation)-[:IS_METRIC]->(m:Metric)
            MATCH (mo)-[:APPLIES_TO]->(entity)
            WHERE entity:Region OR entity:Country OR entity:State
            RETURN r.name as report, m.name as metric, entity.name as entity, 
                   labels(entity)[0] as entity_type, mo.value as value, mo.confidence as confidence
            ORDER BY r.name, m.name
            LIMIT 10
            """
            result = session.run(structure_query)
            print_query_results(result)
            
            # Example 6: Entity summary
            print("\n6. ENTITY SUMMARY")
            print("-" * 50)
            query, params = TimeTreeQueries.get_entity_summary()
            result = session.run(query, params)
            print_query_results(result)
            
            # Example 7: Count observations by entity type
            print("\n7. OBSERVATION COUNTS BY ENTITY TYPE")
            print("-" * 50)
            count_query = """
            MATCH (mo:MetricObservation)-[:APPLIES_TO]->(entity)
            WITH labels(entity)[0] as entity_type, count(mo) as observation_count
            RETURN entity_type, observation_count
            ORDER BY observation_count DESC
            """
            result = session.run(count_query)
            print_query_results(result)
            
            # Example 8: Powerline data by report (demonstrates Report connection)
            print("\n8. POWERLINE DATA BY REPORT")
            print("-" * 50)
            # Get a sample report name first
            sample_report_query = """
            MATCH (r:Report)-[:REPORTS_POWERLINE]->(pl:PowerLine)
            RETURN r.name as report_name
            LIMIT 1
            """
            sample_result = session.run(sample_report_query)
            sample_record = sample_result.single()
            if sample_record:
                query, params = TimeTreeQueries.get_powerline_data_by_report(sample_record["report_name"])
                result = session.run(query, params)
                print_query_results(result)
            else:
                print("No powerline data found in any reports.")
            
            # Example 9: Report data summary
            print("\n9. REPORT DATA SUMMARY")
            print("-" * 50)
            # Get a sample report name
            sample_report_query = """
            MATCH (r:Report)
            RETURN r.name as report_name
            LIMIT 1
            """
            sample_result = session.run(sample_report_query)
            sample_record = sample_result.single()
            if sample_record:
                query, params = TimeTreeQueries.get_report_data_summary(sample_record["report_name"])
                result = session.run(query, params)
                print_query_results(result)
            else:
                print("No reports found.")
            
            # Example 10: Sequential TimeBlock analysis
            print("\n10. SEQUENTIAL TIMEBLOCK ANALYSIS")
            print("-" * 50)
            query, params = TimeTreeQueries.get_sequential_timeblock_analysis()
            result = session.run(query, params)
            print_query_results(result)
            
            # Example 11: Peak hour transitions
            print("\n11. PEAK HOUR TRANSITIONS")
            print("-" * 50)
            query, params = TimeTreeQueries.get_peak_hour_transitions()
            result = session.run(query, params)
            print_query_results(result)
            
            # Example 12: Consecutive day analysis
            print("\n12. CONSECUTIVE DAY ANALYSIS")
            print("-" * 50)
            query, params = TimeTreeQueries.get_consecutive_day_analysis()
            result = session.run(query, params)
            print_query_results(result)
            
            # Example 13: Canonical vs Data TimeBlocks
            print("\n13. CANONICAL VS DATA TIMEBLOCKS")
            print("-" * 50)
            query, params = TimeTreeQueries.get_canonical_vs_data_timeblocks()
            result = session.run(query, params)
            print_query_results(result)
            
            # Example 14: TimeBlock instances by canonical
            print("\n14. TIMEBLOCK INSTANCES BY CANONICAL")
            print("-" * 50)
            query, params = TimeTreeQueries.get_timeblock_instances_by_canonical()
            result = session.run(query, params)
            print_query_results(result)
            
            print("\n" + "=" * 80)
            print("SUPERNODE PROBLEM SOLVED!")
            print("=" * 80)
            print("✓ Each entity (State, Region, Country) has its own MetricObservation nodes")
            print("✓ No shared supernodes causing visualization clutter")
            print("✓ Clean, entity-specific queries")
            print("✓ Maintains data integrity and relationships")
            
    except Exception as e:
        print(f"Error running queries: {e}")
    finally:
        driver.close()

def demonstrate_supernode_solution():
    """Demonstrate the difference between old and new patterns."""
    
    print("\n" + "=" * 80)
    print("SUPERNODE PROBLEM EXPLANATION")
    print("=" * 80)
    
    print("\nOLD PATTERN (Supernode Problem):")
    print("(Report NR) -> (Metric: 'Energy Shortage') -> (Region: 'NR')")
    print("(Report WR) -> (Metric: 'Energy Shortage') -> (Region: 'WR')")
    print("(Report SR) -> (Metric: 'Energy Shortage') -> (Region: 'SR')")
    print("(Report India) -> (Metric: 'Energy Shortage') -> (Country: 'India')")
    print("(Report Maharashtra) -> (Metric: 'Energy Shortage') -> (State: 'Maharashtra')")
    print("❌ When querying any entity, you see ALL relationships to the shared Metric node")
    
    print("\nNEW PATTERN (MetricObservation Solution):")
    print("(Report NR) -> (MetricObservation NR) -> (Metric: 'Energy Shortage')")
    print("(Report WR) -> (MetricObservation WR) -> (Metric: 'Energy Shortage')")
    print("(Report SR) -> (MetricObservation SR) -> (Metric: 'Energy Shortage')")
    print("(Report India) -> (MetricObservation India) -> (Metric: 'Energy Shortage')")
    print("(Report Maharashtra) -> (MetricObservation Maharashtra) -> (Metric: 'Energy Shortage')")
    print("✓ Each entity (State, Region, Country) has its own MetricObservation node")
    print("✓ Querying any entity only shows observations for that entity")
    print("✓ No visualization clutter from other entities")

if __name__ == "__main__":
    demonstrate_supernode_solution()
    run_example_queries() 