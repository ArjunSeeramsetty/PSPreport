#!/usr/bin/env python3
"""
Utility script for managing and validating generation source canonical mappings.
This script helps maintain consistency in the generation source mapping system.
"""

import re
import logging
from typing import Dict, List, Tuple, Set
from collections import defaultdict

# Import the mappings from Data_Insertion.py
from Data_Insertion import (
    GEN_SOURCE_CANONICAL, 
    GENERATION_SOURCE_CATEGORIES, 
    GENERATION_COLUMN_PATTERNS,
    normalize_column_name,
    GenerationSourceMatcher
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class GenerationSourceValidator:
    """Validates and analyzes generation source canonical mappings."""
    
    def __init__(self):
        self.matcher = GenerationSourceMatcher(logger)
        self.issues = []
        self.warnings = []
    
    def validate_all_mappings(self) -> bool:
        """Comprehensive validation of all generation source mappings."""
        logger.info("=== Starting Comprehensive Generation Source Validation ===")
        
        # Clear previous issues
        self.issues = []
        self.warnings = []
        
        # Run all validation checks
        checks = [
            self._validate_canonical_mapping_consistency,
            self._validate_category_consistency,
            self._validate_pattern_consistency,
            self._validate_normalization_consistency,
            self._validate_no_duplicates,
            self._validate_coverage
        ]
        
        all_passed = True
        for check in checks:
            if not check():
                all_passed = False
        
        # Report results
        if self.issues:
            logger.error("=== VALIDATION ISSUES FOUND ===")
            for issue in self.issues:
                logger.error(f"❌ {issue}")
        
        if self.warnings:
            logger.warning("=== VALIDATION WARNINGS ===")
            for warning in self.warnings:
                logger.warning(f"⚠️  {warning}")
        
        if all_passed:
            logger.info("✅ All validation checks passed!")
        else:
            logger.error("❌ Some validation checks failed!")
        
        return all_passed
    
    def _validate_canonical_mapping_consistency(self) -> bool:
        """Validate that canonical mappings are consistent."""
        logger.info("Checking canonical mapping consistency...")
        
        # Check that all normalized keys map to valid canonical names
        canonical_names = {mapping[0] for mapping in GEN_SOURCE_CANONICAL.values()}
        categories = {mapping[1] for mapping in GEN_SOURCE_CANONICAL.values()}
        
        # Check for empty or invalid canonical names
        for normalized_key, (canonical_name, category) in GEN_SOURCE_CANONICAL.items():
            if not canonical_name or canonical_name.strip() == "":
                self.issues.append(f"Empty canonical name for key: {normalized_key}")
            if not category or category.strip() == "":
                self.issues.append(f"Empty category for key: {normalized_key}")
        
        return len(self.issues) == 0
    
    def _validate_category_consistency(self) -> bool:
        """Validate that categories are consistent across mappings."""
        logger.info("Checking category consistency...")
        
        # Check that all canonical names in categories exist in mappings
        canonical_names_in_mappings = {mapping[0] for mapping in GEN_SOURCE_CANONICAL.values()}
        
        for category, names in GENERATION_SOURCE_CATEGORIES.items():
            for name in names:
                if name not in canonical_names_in_mappings:
                    self.issues.append(f"Canonical name '{name}' in category '{category}' not found in GEN_SOURCE_CANONICAL")
        
        # Check that all mapped categories are defined
        mapped_categories = {mapping[1] for mapping in GEN_SOURCE_CANONICAL.values()}
        defined_categories = set(GENERATION_SOURCE_CATEGORIES.keys())
        
        for category in mapped_categories:
            if category not in defined_categories:
                self.issues.append(f"Category '{category}' used in mappings but not defined in GENERATION_SOURCE_CATEGORIES")
        
        return len(self.issues) == 0
    
    def _validate_pattern_consistency(self) -> bool:
        """Validate that patterns are consistent with canonical mappings."""
        logger.info("Checking pattern consistency...")
        
        # Check that all patterns in GENERATION_COLUMN_PATTERNS have corresponding canonical mappings
        all_patterns = set()
        for patterns in GENERATION_COLUMN_PATTERNS.values():
            all_patterns.update(patterns)
        
        # Normalize patterns and check against canonical mappings
        for pattern in all_patterns:
            normalized_pattern = normalize_column_name(pattern)
            if normalized_pattern not in GEN_SOURCE_CANONICAL:
                self.warnings.append(f"Pattern '{pattern}' (normalized: '{normalized_pattern}') not found in canonical mappings")
        
        return True
    
    def _validate_normalization_consistency(self) -> bool:
        """Validate that normalization is consistent."""
        logger.info("Checking normalization consistency...")
        
        # Test normalization on sample inputs
        test_cases = [
            ("G_Main_Coal", "GMAINCOAL"),
            ("A_Solar Gen (MU)*", "ASOLARGEN(MU)"),
            ("Wind Gen (MU)", "WINDGEN(MU)"),
            ("RES (Wind, Solar, Biomass & Others)", "RES(WINDSOLARBIOMASSOTHERS)"),
            ("Gas, Naptha & Diesel", "GASNAPTHADIESEL")
        ]
        
        for input_name, expected_output in test_cases:
            actual_output = normalize_column_name(input_name)
            if actual_output != expected_output:
                self.issues.append(f"Normalization inconsistency: '{input_name}' -> '{actual_output}' (expected: '{expected_output}')")
        
        return len(self.issues) == 0
    
    def _validate_no_duplicates(self) -> bool:
        """Validate that there are no duplicate mappings."""
        logger.info("Checking for duplicates...")
        
        # Check for duplicate normalized keys
        normalized_keys = list(GEN_SOURCE_CANONICAL.keys())
        duplicates = [key for key in set(normalized_keys) if normalized_keys.count(key) > 1]
        
        if duplicates:
            self.issues.append(f"Duplicate normalized keys found: {duplicates}")
        
        # Check for duplicate canonical names with different categories
        canonical_to_categories = defaultdict(set)
        for normalized_key, (canonical_name, category) in GEN_SOURCE_CANONICAL.items():
            canonical_to_categories[canonical_name].add(category)
        
        for canonical_name, categories in canonical_to_categories.items():
            if len(categories) > 1:
                self.issues.append(f"Canonical name '{canonical_name}' has multiple categories: {categories}")
        
        return len(self.issues) == 0
    
    def _validate_coverage(self) -> bool:
        """Validate that we have good coverage of common generation source variations."""
        logger.info("Checking coverage...")
        
        # Common variations that should be covered
        common_variations = [
            "Coal", "coal", "COAL", "G_Main_Coal", "GMainCoal",
            "Solar", "solar", "SOLAR", "A_Solar Gen (MU)*", "Solar Gen (MU)",
            "Wind", "wind", "WIND", "A_Wind Gen (MU)", "Wind Gen (MU)",
            "Hydro", "hydro", "HYDRO", "A_Hydro Gen (MU)", "Hydro Gen (MU)",
            "Nuclear", "nuclear", "NUCLEAR", "G_Main_Nuclear",
            "Gas, Naptha & Diesel", "Gas Naptha Diesel", "GASNAPTHADIESEL",
            "RES", "re", "Renewable", "RES (Wind, Solar, Biomass & Others)",
            "Total", "total", "TOTAL", "F_Total"
        ]
        
        missing_variations = []
        for variation in common_variations:
            normalized = normalize_column_name(variation)
            if normalized not in GEN_SOURCE_CANONICAL:
                missing_variations.append(variation)
        
        if missing_variations:
            self.warnings.append(f"Common variations not covered: {missing_variations}")
        
        return True
    
    def generate_mapping_report(self) -> str:
        """Generate a comprehensive report of the current mappings."""
        logger.info("Generating mapping report...")
        
        report = []
        report.append("=== GENERATION SOURCE CANONICAL MAPPING REPORT ===\n")
        
        # Summary statistics
        total_mappings = len(GEN_SOURCE_CANONICAL)
        categories = {mapping[1] for mapping in GEN_SOURCE_CANONICAL.values()}
        canonical_names = {mapping[0] for mapping in GEN_SOURCE_CANONICAL.values()}
        
        report.append(f"Total mappings: {total_mappings}")
        report.append(f"Categories: {len(categories)} ({', '.join(sorted(categories))})")
        report.append(f"Canonical names: {len(canonical_names)} ({', '.join(sorted(canonical_names))})")
        report.append("")
        
        # Mappings by category
        report.append("=== MAPPINGS BY CATEGORY ===")
        by_category = defaultdict(list)
        for normalized_key, (canonical_name, category) in GEN_SOURCE_CANONICAL.items():
            by_category[category].append((normalized_key, canonical_name))
        
        for category in sorted(by_category.keys()):
            report.append(f"\n{category}:")
            for normalized_key, canonical_name in sorted(by_category[category]):
                report.append(f"  {normalized_key} -> {canonical_name}")
        
        # Pattern coverage
        report.append("\n=== PATTERN COVERAGE ===")
        for pattern_type, patterns in GENERATION_COLUMN_PATTERNS.items():
            report.append(f"\n{pattern_type.upper()}:")
            for pattern in sorted(patterns):
                normalized = normalize_column_name(pattern)
                canonical = GEN_SOURCE_CANONICAL.get(normalized, ("NOT FOUND", "NOT FOUND"))
                report.append(f"  {pattern} -> {normalized} -> {canonical[0]} ({canonical[1]})")
        
        return "\n".join(report)
    
    def suggest_missing_mappings(self, test_columns: List[str]) -> List[Tuple[str, str, str]]:
        """
        Suggest missing mappings based on test columns.
        
        Args:
            test_columns: List of column names to test
            
        Returns:
            List of (original_column, normalized_column, suggested_canonical) tuples
        """
        logger.info(f"Analyzing {len(test_columns)} test columns for missing mappings...")
        
        suggestions = []
        for col in test_columns:
            normalized = normalize_column_name(col)
            if normalized not in GEN_SOURCE_CANONICAL:
                # Try to suggest a canonical name based on the column name
                suggested_canonical = self._suggest_canonical_name(col)
                if suggested_canonical:
                    suggestions.append((col, normalized, suggested_canonical))
        
        if suggestions:
            logger.info(f"Found {len(suggestions)} potential missing mappings:")
            for original, normalized, suggested in suggestions:
                logger.info(f"  '{original}' -> '{normalized}' -> '{suggested}'")
        else:
            logger.info("No missing mappings found!")
        
        return suggestions
    
    def _suggest_canonical_name(self, column_name: str) -> str:
        """Suggest a canonical name based on column name patterns."""
        column_lower = column_name.lower()
        
        # Simple pattern matching
        if 'coal' in column_lower:
            return 'Coal'
        elif 'solar' in column_lower:
            return 'Solar'
        elif 'wind' in column_lower:
            return 'Wind'
        elif 'hydro' in column_lower:
            return 'Hydro'
        elif 'nuclear' in column_lower:
            return 'Nuclear'
        elif 'gas' in column_lower or 'naptha' in column_lower or 'diesel' in column_lower:
            return 'Gas, Naptha & Diesel'
        elif 'lignite' in column_lower:
            return 'Lignite'
        elif 'biomass' in column_lower:
            return 'Biomass'
        elif 'others' in column_lower:
            return 'Others'
        elif 're' in column_lower or 'renewable' in column_lower:
            return 'RE'
        elif 'total' in column_lower:
            return 'Total'
        
        return None

def main():
    """Main function to run validation and generate reports."""
    validator = GenerationSourceValidator()
    
    # Run comprehensive validation
    validation_passed = validator.validate_all_mappings()
    
    # Generate mapping report
    report = validator.generate_mapping_report()
    print(report)
    
    # Test with some sample columns
    test_columns = [
        "G_Main_Coal",
        "A_Solar Gen (MU)*",
        "A_Wind Gen (MU)",
        "A_Hydro Gen (MU)",
        "G_Main_Nuclear",
        "G_Main_Gas, Naptha & Diesel",
        "G_Main_RES (Wind, Solar, Biomass & Others)",
        "F_Total",
        "Unknown_Column",
        "New_Solar_Generation"
    ]
    
    suggestions = validator.suggest_missing_mappings(test_columns)
    
    if not validation_passed:
        logger.error("Validation failed! Please fix the issues above.")
        return 1
    
    logger.info("Validation completed successfully!")
    return 0

if __name__ == "__main__":
    exit(main()) 