#!/usr/bin/env python3
"""
Configuration file for PDF Orchestrator
Defines expected table counts and other processing parameters
"""

# Expected table counts for validation
# Set to 0 if a table type is optional
EXPECTED_TABLE_COUNTS = {
    'Regional Summary': 1,
    'States': 1,
    'International NET': 1,
    'Generation Breakdown': 1,
    'Frequency Profile': 1,
    'Block-wise': 1,
    'Import/Export Regions': 1,
    'Outage Data': 1,
    'RE Share': 1,
    'Solar/Non-Solar Hour': 1,
    'Inter Region': 1,
    'International Exchange': 1,
    'Cross Border Schedule': 1
}

# Database configuration
DATABASE_CONFIG = {
    'path': 'power_data.db',
    'backup_on_failure': True,
    'backup_dir': 'database_backups'
}

# Processing configuration
PROCESSING_CONFIG = {
    'base_dir': 'sample input',
    'recursive_search': True,
    'file_patterns': ['*.pdf'],
    'date_patterns': [
        r'(\d{2})\.(\d{2})\.(\d{2,4})',  # DD.MM.YY or DD.MM.YYYY
        r'(\d{4})-(\d{2})-(\d{2})',      # YYYY-MM-DD
        r'(\d{2})-(\d{2})-(\d{4})',      # DD-MM-YYYY
    ],
    'stop_on_failure': True,
    'commit_after_each_file': True
}

# Logging configuration
LOGGING_CONFIG = {
    'level': 'INFO',
    'file': 'orchestrator.log',
    'format': '%(asctime)s - %(levelname)s - %(message)s',
    'max_file_size': 10 * 1024 * 1024,  # 10MB
    'backup_count': 5
}

# Validation configuration
VALIDATION_CONFIG = {
    'strict_mode': True,  # Stop on any missing table
    'allow_extra_tables': True,  # Allow more tables than expected
    'warn_on_extra_tables': True,
    'required_tables': [
        'Regional Summary',
        'States',
        'Generation Breakdown'
    ]
} 