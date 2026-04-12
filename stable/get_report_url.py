import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import time
# from selenium.webdriver.chrome.service import Service

# service = Service(executable_path="PATH_TO_GECKODRIVER")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def setup_driver():
    """Set up and return a configured Chrome WebDriver."""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    
    # Create a new Chrome driver instance
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def get_link_from_table_row(url: str, date: str) -> str | None:
    """
    This function finds a hyperlink in a table row on the given URL,
    identifying the row by the specific text format 'DD.MM.YY_NLDC_PSP'.

    Args:
        url: The URL of the webpage with the table.
        date: The date to be used to identify the row (format: DD-MM-YYYY or YYYY-MM-DD).

    Returns:
        The hyperlink from the row corresponding to the date provided, or None.
    """
    max_retries = 3
    driver = None

    try:
        # Convert input date to the expected format (DD.MM.YY)
        try:
            # First try DD-MM-YYYY format
            try:
                date_obj = datetime.strptime(date, "%d-%m-%Y")
            except ValueError:
                # If that fails, try YYYY-MM-DD format
                date_obj = datetime.strptime(date, "%Y-%m-%d")
            
            # Convert to the search text format
            search_text = date_obj.strftime("%d.%m.%y") + "_NLDC_PSP"
            logger.info(f"Searching for text: {search_text}")
        except ValueError as e:
            logger.error(f"Invalid date format. Please use YYYY-MM-DD or DD-MM-YYYY. Error: {e}")
            return None

        # Loop for retries
        for attempt in range(max_retries):
            try:
                # Initialize a fresh driver for each attempt
                logger.info(f"Page load attempt {attempt + 1} of {max_retries}...")
                driver = setup_driver()
                
                # Set page load timeout to 10 seconds
                driver.set_page_load_timeout(10)
                
                # Attempt to load the page
                logger.info(f"Loading page: {url} (Timeout set to 10 seconds)")
                driver.get(url)
                
                # Wait for the table to be present (up to 10 seconds)
                wait = WebDriverWait(driver, 10)
                table = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.tableOverFlow table"))
                )
                
                # If we get here, the page loaded successfully
                logger.info("Page loaded successfully!")
                break

            except TimeoutException:
                logger.warning(f"Page failed to load within 10 seconds on attempt {attempt + 1}.")
                # Clean up the failed driver session
                if driver:
                    driver.quit()
                    driver = None
                
                if attempt < max_retries - 1:
                    logger.info("Waiting for 5 seconds before retrying...")
                    time.sleep(5)
                    continue
                else:
                    logger.error("Failed to load page after all retries.")
                    return None

            except WebDriverException as e:
                logger.error(f"An unexpected WebDriver error occurred on attempt {attempt + 1}: {e}", exc_info=True)
                if driver:
                    driver.quit()
                    driver = None
                return None

        # If we couldn't get a working driver after all retries, return None
        if not driver:
            return None

        # Get the page source after JavaScript has rendered
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Find the table
        table = soup.select_one('div.tableOverFlow table')
        if not table:
            logger.warning("No table found after JavaScript rendering")
            return None

        # Process rows
        rows = table.find('tbody').find_all('tr')
        logger.info(f"Found {len(rows)} rows in the table")
        
        for row in rows:
            # Get the first cell which contains the file name
            cells = row.find_all('td')
            if not cells:
                continue
                
            # Get the text from the first cell (file name)
            cell_text = cells[0].get_text(strip=True)
            logger.debug(f"Checking cell text: {cell_text}")
            
            if search_text in cell_text:
                # Find the download link in the last column
                download_cell = cells[-1]
                link = download_cell.find('a')
                
                if link and link.has_attr('href'):
                    report_url = link['href']
                    # Check if the link points to a PDF file
                    if report_url.lower().endswith('.pdf'):
                        logger.info(f"Found matching PDF report for {search_text}")
                        return report_url
                    else:
                        logger.warning(f"Found matching text {search_text} but link is not a PDF: {report_url}")
                        continue
                else:
                    logger.warning(f"Found matching text {search_text} but no download link")
                    continue

        logger.warning(f"No report found for date: {date} (searching for {search_text})")
        return None

    except Exception as e:
        logger.error(f"Error while processing page: {e}", exc_info=True)
        return None
    finally:
        if driver:
            logger.info("Closing WebDriver session.")
            driver.quit()

def get_report_url(date: datetime | str) -> str | None:
    """
    Get the URL for the PSP report for a specific date.

    Args:
        date: A datetime object or string in format 'YYYY-MM-DD' or 'DD-MM-YYYY'

    Returns:
        The URL of the report if found, None otherwise.
    """
    target_url = "https://grid-india.in/reports/daily-psp-report"
    
    try:
        # If it's already a datetime object, convert to string in DD-MM-YYYY format
        if isinstance(date, datetime):
            search_date = date.strftime("%d-%m-%Y")
        else:
            # For string input, try both formats
            try:
                # First try DD-MM-YYYY format
                datetime.strptime(date, "%d-%m-%Y")
                search_date = date
            except ValueError:
                try:
                    # Then try YYYY-MM-DD format
                    date_obj = datetime.strptime(date, "%Y-%m-%d")
                    search_date = date_obj.strftime("%d-%m-%Y")
                except ValueError:
                    logger.error(f"Invalid date format. Please use YYYY-MM-DD or DD-MM-YYYY")
                    return None
        
        logger.info(f"Searching for report with date: {search_date}")
        return get_link_from_table_row(target_url, search_date)
        
    except Exception as e:
        logger.error(f"Error getting report URL: {e}")
        return None

if __name__ == "__main__":
    # Example usage with test dates
    test_dates = [
        "2025-06-07",  # A specific date in YYYY-MM-DD
        "05-06-2025"   # A specific date in DD-MM-YYYY
    ]
    
    for date in test_dates:
        logger.info(f"\nTesting date: {date}")
        report_url = get_report_url(date)
        if report_url:
            logger.info(f"Found report URL for {date}: {report_url}")
        else:
            logger.warning(f"No report URL found for {date}")

    # Remove the interactive debugger
    # import code
    # code.interact(local=locals())