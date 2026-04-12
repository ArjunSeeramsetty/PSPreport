#!/usr/bin/env python3
"""
Diagnostic script to analyze PDF extraction process and identify why tables are empty.
This script will examine each step of the extraction process to find the root cause.
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

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PDFExtractionDiagnostic:
    """Diagnostic tool to analyze PDF extraction issues"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def diagnose_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """Comprehensive diagnosis of PDF extraction process"""
        results = {
            'pdf_path': pdf_path,
            'pdf_info': {},
            'raw_extraction': {},
            'table_analysis': {},
            'issues_found': [],
            'recommendations': []
        }
        
        try:
            # Step 1: Analyze PDF structure
            results['pdf_info'] = self._analyze_pdf_structure(pdf_path)
            
            # Step 2: Test raw extraction with different settings
            results['raw_extraction'] = self._test_raw_extraction(pdf_path)
            
            # Step 3: Analyze extracted tables
            results['table_analysis'] = self._analyze_extracted_tables(results['raw_extraction'])
            
            # Step 4: Identify issues
            results['issues_found'] = self._identify_issues(results)
            
            # Step 5: Generate recommendations
            results['recommendations'] = self._generate_recommendations(results)
            
        except Exception as e:
            self.logger.error(f"Error during diagnosis: {e}")
            results['issues_found'].append(f"Diagnosis failed: {e}")
        
        return results
    
    def _analyze_pdf_structure(self, pdf_path: str) -> Dict[str, Any]:
        """Analyze PDF structure and properties"""
        info = {}
        
        try:
            reader = PdfReader(pdf_path)
            info['num_pages'] = len(reader.pages)
            info['file_size_mb'] = os.path.getsize(pdf_path) / (1024 * 1024)
            
            # Analyze each page
            page_info = []
            for i, page in enumerate(reader.pages):
                page_data = {
                    'page_num': i + 1,
                    'width': float(page.mediabox.width),
                    'height': float(page.mediabox.height),
                    'rotation': page.rotation,
                    'has_text': len(page.extract_text()) > 0,
                    'text_length': len(page.extract_text()),
                    'sample_text': page.extract_text()[:200] + "..." if len(page.extract_text()) > 200 else page.extract_text()
                }
                page_info.append(page_data)
            
            info['pages'] = page_info
            
        except Exception as e:
            self.logger.error(f"Error analyzing PDF structure: {e}")
            info['error'] = str(e)
        
        return info
    
    def _test_raw_extraction(self, pdf_path: str) -> Dict[str, Any]:
        """Test raw extraction with different tabula settings"""
        extraction_results = {}
        
        # Test different extraction settings
        settings_to_test = [
            {
                'name': 'default',
                'settings': {
                    'multiple_tables': True,
                    'guess': True,
                    'lattice': True,
                    'stream': True,
                    'silent': True
                }
            },
            {
                'name': 'lattice_only',
                'settings': {
                    'multiple_tables': True,
                    'guess': False,
                    'lattice': True,
                    'stream': False,
                    'silent': True
                }
            },
            {
                'name': 'stream_only',
                'settings': {
                    'multiple_tables': True,
                    'guess': False,
                    'lattice': False,
                    'stream': True,
                    'silent': True
                }
            },
            {
                'name': 'aggressive',
                'settings': {
                    'multiple_tables': True,
                    'guess': True,
                    'lattice': True,
                    'stream': True,
                    'silent': True,
                    'java_options': ["-Dfile.encoding=UTF8", "-Xmx2g"]
                }
            }
        ]
        
        for setting in settings_to_test:
            try:
                self.logger.info(f"Testing extraction with {setting['name']} settings...")
                
                # Extract from all pages
                all_tables = []
                reader = PdfReader(pdf_path)
                
                for page_num in range(1, len(reader.pages) + 1):
                    try:
                        tables = tabula.read_pdf(
                            pdf_path,
                            pages=page_num,
                            **setting['settings']
                        )
                        
                        for table_idx, table in enumerate(tables):
                            if isinstance(table, pd.DataFrame) and not table.empty:
                                table_info = {
                                    'page': page_num,
                                    'table_index': table_idx,
                                    'shape': table.shape,
                                    'columns': list(table.columns),
                                    'sample_data': table.head(3).to_dict('records'),
                                    'non_null_count': table.notna().sum().sum(),
                                    'total_cells': table.shape[0] * table.shape[1],
                                    'data_density': table.notna().sum().sum() / (table.shape[0] * table.shape[1]) if table.shape[0] * table.shape[1] > 0 else 0
                                }
                                all_tables.append(table_info)
                    
                    except Exception as e:
                        self.logger.warning(f"Error extracting from page {page_num} with {setting['name']}: {e}")
                
                extraction_results[setting['name']] = {
                    'tables_found': len(all_tables),
                    'tables': all_tables
                }
                
            except Exception as e:
                self.logger.error(f"Error with {setting['name']} extraction: {e}")
                extraction_results[setting['name']] = {
                    'error': str(e),
                    'tables_found': 0,
                    'tables': []
                }
        
        return extraction_results
    
    def _analyze_extracted_tables(self, raw_extraction: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the quality and content of extracted tables"""
        analysis = {}
        
        for setting_name, extraction_data in raw_extraction.items():
            if 'error' in extraction_data:
                analysis[setting_name] = {'error': extraction_data['error']}
                continue
            
            tables = extraction_data.get('tables', [])
            analysis[setting_name] = {
                'total_tables': len(tables),
                'tables_with_data': 0,
                'tables_without_data': 0,
                'avg_data_density': 0,
                'table_details': []
            }
            
            if tables:
                data_densities = []
                for table in tables:
                    density = table.get('data_density', 0)
                    data_densities.append(density)
                    
                    has_data = density > 0.1  # More than 10% non-null cells
                    if has_data:
                        analysis[setting_name]['tables_with_data'] += 1
                    else:
                        analysis[setting_name]['tables_without_data'] += 1
                    
                    # Analyze table content
                    table_detail = {
                        'page': table['page'],
                        'shape': table['shape'],
                        'data_density': density,
                        'has_data': has_data,
                        'columns': table['columns'],
                        'sample_data': table['sample_data']
                    }
                    analysis[setting_name]['table_details'].append(table_detail)
                
                analysis[setting_name]['avg_data_density'] = np.mean(data_densities)
        
        return analysis
    
    def _identify_issues(self, results: Dict[str, Any]) -> List[str]:
        """Identify specific issues in the extraction process"""
        issues = []
        
        # Check PDF structure issues
        pdf_info = results['pdf_info']
        if 'error' in pdf_info:
            issues.append(f"PDF structure analysis failed: {pdf_info['error']}")
        
        # Check extraction issues
        extraction_results = results['raw_extraction']
        for setting_name, extraction_data in extraction_results.items():
            if 'error' in extraction_data:
                issues.append(f"Extraction failed with {setting_name} settings: {extraction_data['error']}")
            elif extraction_data.get('tables_found', 0) == 0:
                issues.append(f"No tables found with {setting_name} settings")
        
        # Check table quality issues
        table_analysis = results['table_analysis']
        for setting_name, analysis in table_analysis.items():
            if 'error' in analysis:
                continue
            
            if analysis.get('tables_with_data', 0) == 0:
                issues.append(f"No tables with meaningful data found with {setting_name} settings")
            
            if analysis.get('avg_data_density', 0) < 0.1:
                issues.append(f"Very low data density ({analysis['avg_data_density']:.2%}) with {setting_name} settings")
        
        return issues
    
    def _generate_recommendations(self, results: Dict[str, Any]) -> List[str]:
        """Generate recommendations for improving extraction"""
        recommendations = []
        
        # Analyze which settings work best
        table_analysis = results['table_analysis']
        best_setting = None
        best_score = 0
        
        for setting_name, analysis in table_analysis.items():
            if 'error' in analysis:
                continue
            
            score = analysis.get('tables_with_data', 0) * analysis.get('avg_data_density', 0)
            if score > best_score:
                best_score = score
                best_setting = setting_name
        
        if best_setting:
            recommendations.append(f"Use {best_setting} extraction settings (found {table_analysis[best_setting]['tables_with_data']} tables with data)")
        
        # Check if we need different settings for different pages
        extraction_results = results['raw_extraction']
        if 'default' in extraction_results and 'lattice_only' in extraction_results:
            default_tables = extraction_results['default'].get('tables_found', 0)
            lattice_tables = extraction_results['lattice_only'].get('tables_found', 0)
            
            if abs(default_tables - lattice_tables) > 2:
                recommendations.append("Consider using different extraction settings for different pages (some pages may need lattice=True, others stream=True)")
        
        # Check for PDF-specific issues
        pdf_info = results['pdf_info']
        if pdf_info.get('file_size_mb', 0) > 10:
            recommendations.append("Large PDF file - consider increasing Java memory allocation")
        
        return recommendations
    
    def save_diagnosis_report(self, results: Dict[str, Any], output_path: str = None) -> str:
        """Save detailed diagnosis report"""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_name = Path(results['pdf_path']).stem
            output_path = f"diagnosis_report_{pdf_name}_{timestamp}.json"
        
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
        
        self.logger.info(f"Diagnosis report saved to {output_path}")
        return output_path

def main():
    """Main execution function"""
    if len(sys.argv) < 2:
        print("Usage: python diagnose_pdf_extraction.py <pdf_path> [output_path]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not Path(pdf_path).exists():
        print(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    
    # Initialize diagnostic tool
    diagnostic = PDFExtractionDiagnostic()
    
    # Run diagnosis
    print(f"Diagnosing PDF extraction for {pdf_path}...")
    results = diagnostic.diagnose_pdf(pdf_path)
    
    # Display summary
    print(f"\n=== DIAGNOSIS SUMMARY ===")
    print(f"PDF Path: {results['pdf_path']}")
    print(f"PDF Pages: {results['pdf_info'].get('num_pages', 'Unknown')}")
    print(f"File Size: {results['pdf_info'].get('file_size_mb', 0):.2f} MB")
    
    print(f"\n=== EXTRACTION RESULTS ===")
    for setting_name, extraction_data in results['raw_extraction'].items():
        if 'error' in extraction_data:
            print(f"{setting_name}: ERROR - {extraction_data['error']}")
        else:
            print(f"{setting_name}: {extraction_data.get('tables_found', 0)} tables found")
    
    print(f"\n=== TABLE ANALYSIS ===")
    for setting_name, analysis in results['table_analysis'].items():
        if 'error' in analysis:
            print(f"{setting_name}: ERROR - {analysis['error']}")
        else:
            print(f"{setting_name}: {analysis.get('tables_with_data', 0)} tables with data, "
                  f"avg density: {analysis.get('avg_data_density', 0):.2%}")
    
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
        saved_path = diagnostic.save_diagnosis_report(results, output_path)
        print(f"\nDetailed report saved to: {saved_path}")
    
    return results

if __name__ == "__main__":
    main() 