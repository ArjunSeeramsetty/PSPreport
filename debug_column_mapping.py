#!/usr/bin/env python3
"""
Debug column mapping issues by examining actual vs expected column names.
"""

import pandas as pd
import numpy as np
import logging
import re
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional
import tabula
from PyPDF2 import PdfReader
import json

# Import the modular parser components
from modular_psp_parser import PDFExtractor, TableIdentifier, TableProcessor, PSPReportParser

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ColumnMappingDebugger:
    """Debug column mapping issues"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.extractor = PDFExtractor()
        self.identifier = TableIdentifier()
    
    def debug_column_mapping(self, pdf_path: str) -> Dict[str, Any]:
        """Debug column mapping for a PDF"""
        results = {
            'pdf_path': pdf_path,
            'table_analysis': {},
            'column_mapping_issues': [],
            'recommendations': []
        }
        
        try:
            # Extract raw tables
            self.logger.info("Extracting raw tables...")
            raw_tables, report_date = self.extractor.extract_tables_from_pdf(pdf_path)
            
            # Classify tables
            self.logger.info("Classifying tables...")
            classifications = {}
            for table_key, table_df in raw_tables.items():
                classification = self.identifier.classify_table(table_df, table_key)
                classifications[table_key] = classification
            
            # Analyze each table
            for table_key, table_df in raw_tables.items():
                classification = classifications[table_key]
                
                table_analysis = {
                    'category': classification.category,
                    'confidence': classification.confidence,
                    'actual_columns': list(table_df.columns),
                    'expected_columns': self._get_expected_columns(classification.category),
                    'column_mappings': classification.column_mappings,
                    'sample_data': table_df.head(3).to_dict('records'),
                    'issues': []
                }
                
                # Check for column mapping issues
                issues = self._check_column_mapping_issues(table_analysis)
                table_analysis['issues'] = issues
                results['column_mapping_issues'].extend(issues)
                
                results['table_analysis'][table_key] = table_analysis
            
            # Generate recommendations
            results['recommendations'] = self._generate_column_mapping_recommendations(results)
            
        except Exception as e:
            self.logger.error(f"Error during column mapping debug: {e}")
            results['column_mapping_issues'].append(f"Debug failed: {e}")
        
        return results
    
    def _get_expected_columns(self, category: str) -> List[str]:
        """Get expected columns for a table category"""
        expected_columns = {
            'regional_summary': [
                'Region', 'Peak Demand Met (MW)', 'Energy Met (MU)', 'Energy Shortage (MU)',
                'Max Demand SCADA (MW)', 'Peak Shortage (MW)', 'Time of Max Demand Met',
                'Schedule Drawal (MU)', 'Actual Drawal (MU)', 'Over/Under Drawal (MU)'
            ],
            'state_energy': [
                'Region', 'States', 'Maximum Demand (MW)', 'Shortage (MW)', 'Energy Met (MU)',
                'Drawal Schedule (MU)', 'OD(+)/UD(-) (MU)', 'Max OD (MW)', 'Energy Shortage (MU)'
            ],
            'transnational_exchange': [
                'Country', 'Exchange (MU)', 'Import (+ve)', 'Export (-ve)'
            ],
            'frequency_profile': [
                'Frequency (Hz)', 'FVI', 'Duration Frequency Below 49.7 (s)',
                'Duration Frequency 49.7-49.8 (s)', 'Duration Frequency 49.8-49.9 (s)',
                'Duration Frequency Below 49.9 (s)', 'Duration Frequency 49.9-50.05 (s)',
                'Duration Frequency Above 50.05 (s)'
            ],
            'import_export_regions': [
                'Region', 'Schedule (MU)', 'Actual (MU)', 'Import (MU)', 'Export (MU)'
            ],
            'outage_data': [
                'Sector', 'Central Sector', 'State Sector', 'Total Outage (MW)', 'Share (%)'
            ],
            'generation_breakdown': [
                'Source', 'Generation (MW)', 'Share (%)'
            ],
            're_share': [
                'RE Share', 'Non-Fossil Share'
            ],
            'solar_nonsolar_hour': [
                'Solar HR Max Demand (MW)', 'Solar HR Shortage (MW)',
                'Non-Solar HR Max Demand (MW)', 'Non-Solar HR Shortage (MW)'
            ],
            'transmission_flow': [
                'From Region', 'To Region', 'Schedule (MU)', 'Actual (MU)', 'OD/UD (MU)'
            ],
            'cross_border_schedule_1': [
                'Country', 'GNA', 'Bilateral', 'Total'
            ],
            'time_block': [
                'TIME', 'FREQUENCY (Hz)', 'DEMAND MET (MW)', 'NUCLEAR (MW)', 'WIND (MW)',
                'SOLAR (MW)', 'HYDRO (MW)', 'GAS (MW)', 'THERMAL (MW)', 'OTHERS* (MW)',
                'NET DEMAND MET (MW)', 'TOTAL GENERATION (MW)', 'NET TRANSNATIONAL EXCHANGE (MW) (+ve) Import, (-ve) Export'
            ]
        }
        
        return expected_columns.get(category, [])
    
    def _check_column_mapping_issues(self, table_analysis: Dict[str, Any]) -> List[str]:
        """Check for column mapping issues"""
        issues = []
        
        actual_columns = table_analysis['actual_columns']
        expected_columns = table_analysis['expected_columns']
        category = table_analysis['category']
        
        # Check for missing expected columns
        missing_columns = []
        for expected_col in expected_columns:
            if expected_col not in actual_columns:
                missing_columns.append(expected_col)
        
        if missing_columns:
            issues.append(f"Missing expected columns: {missing_columns}")
        
        # Check for exact matches
        exact_matches = []
        for expected_col in expected_columns:
            if expected_col in actual_columns:
                exact_matches.append(expected_col)
        
        if len(exact_matches) == 0:
            issues.append("No exact column matches found")
        elif len(exact_matches) < len(expected_columns) * 0.5:
            issues.append(f"Only {len(exact_matches)}/{len(expected_columns)} expected columns found exactly")
        
        # Check for potential fuzzy matches
        potential_matches = []
        for expected_col in expected_columns:
            if expected_col not in actual_columns:
                # Look for similar columns
                for actual_col in actual_columns:
                    similarity = self._calculate_similarity(expected_col.lower(), actual_col.lower())
                    if similarity > 0.7:  # 70% similarity threshold
                        potential_matches.append((expected_col, actual_col, similarity))
        
        if potential_matches:
            issues.append(f"Potential fuzzy matches: {potential_matches}")
        
        return issues
    
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity between two strings"""
        from difflib import SequenceMatcher
        return SequenceMatcher(None, str1, str2).ratio()
    
    def _generate_column_mapping_recommendations(self, results: Dict[str, Any]) -> List[str]:
        """Generate recommendations for fixing column mapping"""
        recommendations = []
        
        # Analyze common issues
        missing_columns_count = 0
        no_exact_matches_count = 0
        
        for table_key, table_analysis in results['table_analysis'].items():
            for issue in table_analysis['issues']:
                if "Missing expected columns" in issue:
                    missing_columns_count += 1
                if "No exact column matches found" in issue:
                    no_exact_matches_count += 1
        
        if missing_columns_count > 0:
            recommendations.append(f"{missing_columns_count} tables have missing expected columns")
        
        if no_exact_matches_count > 0:
            recommendations.append(f"{no_exact_matches_count} tables have no exact column matches")
        
        # Generate specific recommendations for each table
        for table_key, table_analysis in results['table_analysis'].items():
            category = table_analysis['category']
            actual_columns = table_analysis['actual_columns']
            
            if len(table_analysis['issues']) > 0:
                recommendations.append(f"Table {table_key} ({category}): Review column mapping logic")
                recommendations.append(f"  Actual columns: {actual_columns}")
        
        return recommendations
    
    def save_debug_report(self, results: Dict[str, Any], output_path: str = None) -> str:
        """Save detailed debug report"""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_name = Path(results['pdf_path']).stem
            output_path = f"column_mapping_debug_{pdf_name}_{timestamp}.json"
        
        # Convert numpy types to native Python types for JSON serialization
        def convert_numpy(obj):
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, pd.DataFrame):
                return obj.to_dict('records')
            return obj
        
        # Recursively convert numpy types
        def clean_for_json(obj):
            if isinstance(obj, dict):
                return {k: clean_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_for_json(v) for v in obj]
            else:
                return convert_numpy(obj)
        
        clean_results = clean_for_json(results)
        
        with open(output_path, 'w') as f:
            json.dump(clean_results, f, indent=2, default=str)
        
        self.logger.info(f"Debug report saved to {output_path}")
        return output_path

def main():
    """Main execution function"""
    if len(sys.argv) < 2:
        print("Usage: python debug_column_mapping.py <pdf_path> [output_path]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    # Initialize debugger
    debugger = ColumnMappingDebugger()
    
    # Run debug
    print(f"Debugging column mapping for {pdf_path}...")
    results = debugger.debug_column_mapping(pdf_path)
    
    # Display summary
    print(f"\n=== COLUMN MAPPING DEBUG SUMMARY ===")
    print(f"PDF Path: {results['pdf_path']}")
    print(f"Tables Analyzed: {len(results['table_analysis'])}")
    print(f"Column Mapping Issues: {len(results['column_mapping_issues'])}")
    
    # Show table analysis
    print(f"\n=== TABLE ANALYSIS ===")
    for table_key, table_analysis in results['table_analysis'].items():
        print(f"\n{table_key} ({table_analysis['category']}, confidence: {table_analysis['confidence']:.2f})")
        print(f"  Actual columns: {table_analysis['actual_columns']}")
        print(f"  Expected columns: {table_analysis['expected_columns']}")
        
        if table_analysis['issues']:
            print(f"  Issues:")
            for issue in table_analysis['issues']:
                print(f"    - {issue}")
        else:
            print(f"  No issues found")
    
    if results['column_mapping_issues']:
        print(f"\n=== COLUMN MAPPING ISSUES ===")
        for issue in results['column_mapping_issues']:
            print(f"  - {issue}")
    
    if results['recommendations']:
        print(f"\n=== RECOMMENDATIONS ===")
        for rec in results['recommendations']:
            print(f"  - {rec}")
    
    # Save detailed report
    if output_path:
        saved_path = debugger.save_debug_report(results, output_path)
        print(f"\nDetailed report saved to: {saved_path}")
    
    return results

if __name__ == "__main__":
    main() 