# pdf_pipeline_dag.py

from __future__ import annotations

import pendulum # Used by Airflow for time management
import logging
import os
import requests
import time
from datetime import timedelta

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context # For explicit XCom if needed, though @task handles it

# Import the get_report_url function
from get_report_url import get_report_url

# --- Configuration ---
# USER ACTION: Update these configurations
PDF_BASE_URL = "http://example.com/reports/report_{date_placeholder}.pdf"  # Your actual PDF base URL
PDF_URL_DATE_FORMAT = "%Y%m%d"  # Format of the date in the PDF URL (e.g., YYYYMMDD)

# Ensure these paths are accessible by Airflow workers
AIRFLOW_DATA_DIR = os.getenv("AIRFLOW_HOME", ".") + "/data" # Example: store data in a subdir of AIRFLOW_HOME
DOWNLOAD_DIR = os.path.join(AIRFLOW_DATA_DIR, "daily_psp_downloads")
DB_NAME = "power_data.db" # Name of your SQLite DB
DATABASE_PATH = os.path.join(AIRFLOW_DATA_DIR, DB_NAME) # Absolute or fixed path for the DB

# Create directories if they don't exist (Airflow might run this parsing DAG file often)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(AIRFLOW_DATA_DIR, exist_ok=True)

# Import your custom processing functions
# Ensure these scripts are in your PYTHONPATH or Airflow's dags/plugins folder
try:
    from PDFparser_Gemini import main_pdf_processing_logic
    from Data_Insertion import automate_data_insertion_from_list
except ImportError as e:
    logging.error(f"Could not import custom modules: {e}. Ensure they are in PYTHONPATH.")
    # This will cause DAG import error if modules are not found
    raise

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False, # Set to True and configure email if desired
    "email_on_retry": False,
    "retries": 1, # Number of retries on failure
    "retry_delay": timedelta(minutes=5),
}

@dag(
    dag_id="daily_pdf_to_sqlite_pipeline",
    default_args=default_args,
    description="Daily pipeline to get report URL, download PDF, parse it, and load data into SQLite DB.",
    schedule=timedelta(days=1), # Or "@daily", or a cron expression e.g., "0 7 * * *" for 7 AM daily
    start_date=pendulum.datetime(2025, 6, 1, tz="UTC"), # Adjust start date
    catchup=False, # Set to True if you want to backfill for past missed schedules
    tags=["data_pipeline", "pdf", "sqlite"],
)
def pdf_to_sqlite_dag():
    """
    ### PDF to SQLite Pipeline DAG
    This DAG:
    1. Gets the report URL for the current date
    2. Downloads the PDF report
    3. Parses the PDF tables
    4. Loads the extracted data into an SQLite database
    """

    @task
    def get_report_url_task() -> str | None:
        """
        Gets the report URL for the current execution date.
        Returns the URL if found, None otherwise.
        """
        logger = logging.getLogger("airflow.task")
        context = get_current_context()
        logical_date = context["logical_date"]

        logger.info(f"Getting report URL for date: {logical_date}")
        report_url = get_report_url(logical_date)
        
        if report_url:
            logger.info(f"Found report URL: {report_url}")
        else:
            logger.warning(f"No report URL found for date: {logical_date}")
        
        return report_url

    @task
    def download_daily_pdf(report_url: str | None) -> str | None:
        """
        Downloads the PDF from the provided URL.
        Returns the path to the downloaded PDF file, or None if download fails.
        """
        logger = logging.getLogger("airflow.task")
        context = get_current_context()
        logical_date = context["logical_date"]

        if not report_url:
            logger.error("No report URL provided. Skipping download.")
            return None

        pdf_filename = f"report_{logical_date.strftime('%Y-%m-%d')}.pdf"
        local_pdf_path = os.path.join(DOWNLOAD_DIR, pdf_filename)

        logger.info(f"Attempting to download PDF from: {report_url}")
        retries = 3
        delay = 10 # seconds
        for attempt in range(retries):
            try:
                response = requests.get(report_url, stream=True, timeout=60)
                response.raise_for_status()
                with open(local_pdf_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                logger.info(f"Successfully downloaded PDF to: {local_pdf_path}")
                return local_pdf_path
            except requests.exceptions.RequestException as e:
                logger.warning(f"Download attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to download PDF after {retries} attempts from {report_url}")
                    return None
        return None # Should not be reached if retries are exhausted and error logged

    @task
    def parse_pdf_to_dataframes(downloaded_pdf_path: str | None) -> list | None:
        """
        Parses the downloaded PDF and returns a list of DataFrames.
        `downloaded_pdf_path` is pulled from XCom from the download_daily_pdf task.
        The returned list of dataframes will be pushed to XCom.
        Consider implications if this list is very large.
        """
        logger = logging.getLogger("airflow.task")
        if not downloaded_pdf_path or not os.path.exists(downloaded_pdf_path):
            logger.error("No valid PDF path received or file does not exist. Skipping parsing.")
            return None # Propagate failure or indicate no data

        logger.info(f"Parsing PDF: {downloaded_pdf_path}")
        try:
            # Call your refactored PDF parsing function
            list_of_dataframes = main_pdf_processing_logic(pdf_path=downloaded_pdf_path)
            if list_of_dataframes is None: # Ensure it's not None before checking len
                 list_of_dataframes = []
            logger.info(f"PDF parsing complete. Extracted {len(list_of_dataframes)} DataFrames.")
            # Note: If DataFrames are very large, XCom might not be ideal.
            # In such cases, save DFs to disk (e.g., pickle, parquet) and pass file paths via XCom.
            # For now, assuming list of DFs is manageable for XCom.
            return list_of_dataframes
        except Exception as e:
            logger.error(f"Error during PDF parsing for {downloaded_pdf_path}: {e}", exc_info=True)
            # raise AirflowFailException(f"PDF parsing failed for {downloaded_pdf_path}")
            return None # Indicate failure


    @task
    def load_dataframes_to_db(dataframes_list: list | None, db_path: str):
        """
        Loads the list of DataFrames into the SQLite database.
        `dataframes_list` is pulled from XCom from the parse_pdf_to_dataframes task.
        """
        logger = logging.getLogger("airflow.task")
        if not dataframes_list: # Handles None or empty list
            logger.info("No DataFrames to load into the database. Skipping insertion.")
            return

        logger.info(f"Loading {len(dataframes_list)} DataFrames into database: {db_path}")
        try:
            # Call your refactored data insertion function
            automate_data_insertion_from_list(dataframes_list=dataframes_list, db_name=db_path)
            logger.info("Data loading step completed successfully.")
        except Exception as e:
            logger.error(f"Error during data insertion into {db_path}: {e}", exc_info=True)
            # raise AirflowFailException(f"Data insertion failed for {db_path}")
            # Depending on your Airflow setup, raising AirflowFailException marks task as failed
            raise # Re-raise the exception to mark the task as failed


    # Define Task Flow
    report_url = get_report_url_task()
    pdf_path = download_daily_pdf(report_url=report_url)
    parsed_dataframes = parse_pdf_to_dataframes(downloaded_pdf_path=pdf_path)
    load_dataframes_to_db(dataframes_list=parsed_dataframes, db_path=DATABASE_PATH)

# Instantiate the DAG
pdf_processing_dag = pdf_to_sqlite_dag()