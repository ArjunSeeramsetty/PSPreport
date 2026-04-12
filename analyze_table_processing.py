#!/usr/bin/env python3
"""
Analyze table processing step by step to identify why data is being converted to zeros.
This script will examine the raw extracted tables and the processing logic.
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

class TableProcessingAnalyzer:
    """Analyzer to examine table processing step by step"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.extractor = PDFExtractor()
        self.identifier = TableIdentifier()
    
    def analyze_pdf_processing(self, pdf_path: str) -> Dict[str, Any]:
        """Comprehensive analysis of PDF processing"""
        results = {
            'pdf_path': pdf_path,
            'raw_extraction': {},
            'table_classifications': {},
            'processing_results': {},
            'issues_found': [],
            'recommendations': []
        }
        
        try:
            # Step 1: Extract raw tables
            self.logger.info("Step 1: Extracting raw tables...")
            raw_tables, report_date = self.extractor.extract_tables_from_pdf(pdf_path)
            results['raw_extraction'] = {
                'report_date': report_date,
                'num_tables': len(raw_tables),
                'tables': {}
            }
            
            # Analyze each raw table
            for table_key, table_df in raw_tables.items():
                table_analysis = self._analyze_raw_table(table_df, table_key)
                results['raw_extraction']['tables'][table_key] = table_analysis
            
            # Step 2: Classify tables
            self.logger.info("Step 2: Classifying tables...")
            classifications = {}
            for table_key, table_df in raw_tables.items():
                classification = self.identifier.classify_table(table_df, table_key)
                classifications[table_key] = classification
                
                # Analyze classification result
                classification_analysis = {
                    'table_name': classification.table_name,
                    'confidence': classification.confidence,
                    'category': classification.category,
                    'description': classification.description,
                    'column_mappings': classification.column_mappings
                }
                results['table_classifications'][table_key] = classification_analysis
            
            # Step 3: Process tables
            self.logger.info("Step 3: Processing tables...")
            processor = TableProcessor(report_date)
            processing_results = processor.process_multiple_tables(raw_tables, classifications)
            
            # Analyze processing results
            for result in processing_results:
                processing_analysis = {
                    'table_name': result.table_name,
                    'success': result.success,
                    'error_message': result.error_message,
                    'source_tables': result.source_tables,
                    'processed_data_analysis': {}
                }
                
                if result.success and result.processed_df is not None:
                    processed_analysis = self._analyze_processed_table(result.processed_df, result.table_name)
                    processing_analysis['processed_data_analysis'] = processed_analysis
                
                results['processing_results'][result.table_name] = processing_analysis
            
            # Step 4: Identify issues
            results['issues_found'] = self._identify_processing_issues(results)
            
            # Step 5: Generate recommendations
            results['recommendations'] = self._generate_processing_recommendations(results)
            
        except Exception as e:
            self.logger.error(f"Error during analysis: {e}")
            results['issues_found'].append(f"Analysis failed: {e}")
        
        return results
    
    def _analyze_raw_table(self, df: pd.DataFrame, table_key: str) -> Dict[str, Any]:
        """Analyze a raw extracted table"""
        analysis = {
            'shape': df.shape,
            'columns': list(df.columns),
            'data_types': df.dtypes.to_dict(),
            'non_null_counts': df.notna().sum().to_dict(),
            'sample_data': df.head(5).to_dict('records'),
            'data_density': df.notna().sum().sum() / (df.shape[0] * df.shape[1]) if df.shape[0] * df.shape[1] > 0 else 0,
            'numeric_columns': [],
            'text_columns': [],
            'empty_columns': [],
            'potential_data_columns': []
        }
        
        # Analyze each column
        for col in df.columns:
            col_data = df[col]
            
            # Check if column is numeric
            try:
                numeric_data = pd.to_numeric(col_data, errors='coerce')
                non_null_numeric = numeric_data.dropna()
                if len(non_null_numeric) > 0:
                    analysis['numeric_columns'].append({
                        'column': col,
                        'non_null_count': len(non_null_numeric),
                        'min_value': float(non_null_numeric.min()),
                        'max_value': float(non_null_numeric.max()),
                        'mean_value': float(non_null_numeric.mean()),
                        'sample_values': non_null_numeric.head(3).tolist()
                    })
                    analysis['potential_data_columns'].append(col)
            except:
                pass
            
            # Check if column is text
            text_data = col_data.astype(str)
            non_empty_text = text_data[text_data != 'nan'].dropna()
            if len(non_empty_text) > 0:
                analysis['text_columns'].append({
                    'column': col,
                    'non_empty_count': len(non_empty_text),
                    'sample_values': non_empty_text.head(3).tolist()
                })
            
            # Check if column is empty
            if col_data.isna().all() or (col_data.astype(str) == '').all():
                analysis['empty_columns'].append(col)
        
        return analysis
    
    def _analyze_processed_table(self, df: pd.DataFrame, table_name: str) -> Dict[str, Any]:
        """Analyze a processed table"""
        analysis = {
            'shape': df.shape,
            'columns': list(df.columns),
            'data_types': df.dtypes.to_dict(),
            'non_null_counts': df.notna().sum().to_dict(),
            'sample_data': df.head(5).to_dict('records'),
            'data_density': df.notna().sum().sum() / (df.shape[0] * df.shape[1]) if df.shape[0] * df.shape[1] > 0 else 0,
            'zero_counts': {},
            'non_zero_counts': {},
            'potential_issues': []
        }
        
        # Analyze numeric columns for zeros vs non-zeros
        for col in df.columns:
            try:
                numeric_data = pd.to_numeric(df[col], errors='coerce')
                non_null_data = numeric_data.dropna()
                
                if len(non_null_data) > 0:
                    zero_count = (non_null_data == 0).sum()
                    non_zero_count = (non_null_data != 0).sum()
                    
                    analysis['zero_counts'][col] = int(zero_count)
                    analysis['non_zero_counts'][col] = int(non_zero_count)
                    
                    # Check if all values are zero
                    if non_zero_count == 0 and zero_count > 0:
                        analysis['potential_issues'].append(f"Column '{col}' has all zero values")
                    
                    # Check if most values are zero
                    if zero_count > 0 and non_zero_count > 0:
                        zero_ratio = zero_count / (zero_count + non_zero_count)
                        if zero_ratio > 0.8:
                            analysis['potential_issues'].append(f"Column '{col}' has {zero_ratio:.1%} zero values")
            except:
                pass
        
        return analysis
    
    def _identify_processing_issues(self, results: Dict[str, Any]) -> List[str]:
        """Identify issues in the processing pipeline"""
        issues = []
        
        # Check raw extraction
        raw_extraction = results['raw_extraction']
        if raw_extraction['num_tables'] == 0:
            issues.append("No tables extracted from PDF")
        
        # Check classifications
        classifications = results['table_classifications']
        low_confidence_count = sum(1 for c in classifications.values() if c['confidence'] < 0.5)
        if low_confidence_count > 0:
            issues.append(f"{low_confidence_count} tables have low classification confidence (< 0.5)")
        
        # Check processing results
        processing_results = results['processing_results']
        failed_count = sum(1 for p in processing_results.values() if not p['success'])
        if failed_count > 0:
            issues.append(f"{failed_count} tables failed processing")
        
        # Check for all-zero data
        all_zero_tables = []
        for table_name, processing_analysis in processing_results.items():
            if processing_analysis['success']:
                processed_analysis = processing_analysis.get('processed_data_analysis', {})
                if processed_analysis.get('non_zero_counts'):
                    total_non_zero = sum(processed_analysis['non_zero_counts'].values())
                    if total_non_zero == 0:
                        all_zero_tables.append(table_name)
        
        if all_zero_tables:
            issues.append(f"Tables with all zero data: {', '.join(all_zero_tables)}")
        
        return issues
    
    def _generate_processing_recommendations(self, results: Dict[str, Any]) -> List[str]:
        """Generate recommendations for improving processing"""
        recommendations = []
        
        # Check raw extraction quality
        raw_extraction = results['raw_extraction']
        for table_key, table_analysis in raw_extraction['tables'].items():
            if table_analysis['data_density'] < 0.1:
                recommendations.append(f"Table {table_key} has very low data density ({table_analysis['data_density']:.1%})")
            
            if len(table_analysis['numeric_columns']) == 0:
                recommendations.append(f"Table {table_key} has no numeric columns - may need different extraction settings")
        
        # Check classification issues
        classifications = results['table_classifications']
        for table_key, classification in classifications.items():
            if classification['confidence'] < 0.3:
                recommendations.append(f"Table {table_key} has very low classification confidence ({classification['confidence']:.2f})")
        
        # Check processing issues
        processing_results = results['processing_results']
        for table_name, processing_analysis in processing_results.items():
            if not processing_analysis['success']:
                recommendations.append(f"Fix processing for table '{table_name}': {processing_analysis['error_message']}")
            
            if processing_analysis['success']:
                processed_analysis = processing_analysis.get('processed_data_analysis', {})
                if processed_analysis.get('potential_issues'):
                    for issue in processed_analysis['potential_issues']:
                        recommendations.append(f"Table '{table_name}': {issue}")
        
        return recommendations
    
    def save_analysis_report(self, results: Dict[str, Any], output_path: str = None) -> str:
        """Save detailed analysis report"""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_name = Path(results['pdf_path']).stem
            output_path = f"processing_analysis_{pdf_name}_{timestamp}.json"
        
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
        
        self.logger.info(f"Analysis report saved to {output_path}")
        return output_path

def main():
    """Main execution function"""
    if len(sys.argv) < 2:
        print("Usage: python analyze_table_processing.py <pdf_path> [output_path]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    # Initialize analyzer
    analyzer = TableProcessingAnalyzer()
    
    # Run analysis
    print(f"Analyzing table processing for {pdf_path}...")
    results = analyzer.analyze_pdf_processing(pdf_path)
    
    # Display summary
    print(f"\n=== PROCESSING ANALYSIS SUMMARY ===")
    print(f"PDF Path: {results['pdf_path']}")
    print(f"Raw Tables Extracted: {results['raw_extraction']['num_tables']}")
    print(f"Tables Classified: {len(results['table_classifications'])}")
    print(f"Tables Processed: {len(results['processing_results'])}")
    
    # Show raw extraction summary
    print(f"\n=== RAW EXTRACTION SUMMARY ===")
    for table_key, table_analysis in results['raw_extraction']['tables'].items():
        print(f"{table_key}: {table_analysis['shape']}, density: {table_analysis['data_density']:.1%}, "
              f"numeric cols: {len(table_analysis['numeric_columns'])}")
    
    # Show classification summary
    print(f"\n=== CLASSIFICATION SUMMARY ===")
    for table_key, classification in results['table_classifications'].items():
        print(f"{table_key}: {classification['category']} (confidence: {classification['confidence']:.2f})")
    
    # Show processing summary
    print(f"\n=== PROCESSING SUMMARY ===")
    for table_name, processing_analysis in results['processing_results'].items():
        success = processing_analysis['success']
        if success:
            processed_analysis = processing_analysis.get('processed_data_analysis', {})
            non_zero_count = sum(processed_analysis.get('non_zero_counts', {}).values())
            print(f"{table_name}: SUCCESS, non-zero values: {non_zero_count}")
        else:
            print(f"{table_name}: FAILED - {processing_analysis['error_message']}")
    
    if results['issues_found']:
        print(f"\n=== ISSUES FOUND ===")
        for issue in results['issues_found']:
            print(f"  - {issue}")
    
    if results['recommendations']:
        print(f"\n=== RECOMMENDATIONS ===")
        for rec in results['recommendations']:
            print(f"  - {rec}")
    
    # Save detailed report
    if output_path:
        saved_path = analyzer.save_analysis_report(results, output_path)
        print(f"\nDetailed report saved to: {saved_path}")
    
    return results

if __name__ == "__main__":
    main() 