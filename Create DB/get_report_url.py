import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException
import time
import os
from urllib.parse import urljoin
import calendar
import json

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ReportScraper:
    """Manages the scraping of PSP report URLs from the Grid India website."""
    
    def __init__(self, base_url: str = "https://grid-india.in/reports/daily-psp-report"):
        """
        Initializes the ReportScraper.

        Args:
            base_url: The base URL for the PSP reports page.
        """
        self.base_url = base_url
        self.driver = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def _setup_driver(self):
    """Set up and return a configured Chrome WebDriver."""
        if self.driver is None:
            self.logger.info("Setting up new WebDriver session...")
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
            # Create a new Chrome driver instance
            self.driver = webdriver.Chrome(options=chrome_options)
        return self.driver

    def _close_driver(self):
        """Closes the WebDriver session if it exists."""
        if self.driver:
            self.logger.info("Closing WebDriver session.")
            self.driver.quit()
            self.driver = None

    def _select_dropdown_option(self, dropdown_container_selector: str, option_text: str, wait: WebDriverWait):
        """
        Helper function to handle custom react-select dropdowns.
        
        Args:
            dropdown_container_selector: CSS selector for the main container of the dropdown.
            option_text: The visible text of the option to select.
            wait: The WebDriverWait instance.
        """
        try:
            # 1. Click the dropdown to open the options list
            dropdown = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, dropdown_container_selector)))
            dropdown.click()
            self.logger.info(f"Clicked dropdown container: '{dropdown_container_selector}'")
            
            # 2. Wait for the dropdown menu to appear and then find the option
            # Use a more flexible approach to find the option
            time.sleep(2)  # Give time for dropdown to fully open
            
            # Try multiple strategies to find the option
            option_found = False
            
            # Strategy 1: Look for option with exact text match
            try:
                option_xpath = f"//div[contains(@class, 'my-select__option') and normalize-space(text())='{option_text}']"
                option = wait.until(EC.element_to_be_clickable((By.XPATH, option_xpath)))
                option.click()
                self.logger.info(f"Selected option '{option_text}' using exact match")
                option_found = True
            except TimeoutException:
                self.logger.debug(f"Exact match failed for '{option_text}', trying partial match")
            
            # Strategy 2: Look for option containing the text
            if not option_found:
                try:
                    option_xpath = f"//div[contains(@class, 'my-select__option') and contains(text(), '{option_text}')]"
                    option = wait.until(EC.element_to_be_clickable((By.XPATH, option_xpath)))
                    option.click()
                    self.logger.info(f"Selected option '{option_text}' using partial match")
                    option_found = True
                except TimeoutException:
                    self.logger.debug(f"Partial match failed for '{option_text}', trying broader search")
            
            # Strategy 3: Look for any element with the text in the dropdown area
            if not option_found:
                try:
                    option_xpath = f"//div[contains(@class, 'my-select__menu')]//div[contains(text(), '{option_text}')]"
                    option = wait.until(EC.element_to_be_clickable((By.XPATH, option_xpath)))
                    option.click()
                    self.logger.info(f"Selected option '{option_text}' using menu search")
                    option_found = True
                except TimeoutException:
                    self.logger.debug(f"Menu search failed for '{option_text}'")
            
            if not option_found:
                raise TimeoutException(f"Could not find option '{option_text}' in any dropdown")
            
            time.sleep(1) # Allow a moment for the state to update post-selection
            
        except TimeoutException:
            self.logger.error(f"Timed out waiting for dropdown or option '{option_text}'.")
            raise
        except ElementClickInterceptedException:
            self.logger.error(f"Could not click on option '{option_text}', it might be obscured.")
            raise

    def get_historical_report_urls(self, financial_year: str, month: str) -> list[str]:
        """
        Gets all unique PDF report URLs for a given financial year and month.

        Args:
            financial_year: The financial year in 'YYYY-YY' format (e.g., '2025-26').
            month: The full month name (e.g., 'June', 'July') or 'All'.

        Returns:
            List of unique PDF report URLs for the specified period.
        """
        self.logger.info(f"Initiating historical scrape for FY '{financial_year}', Month '{month}'.")
        found_urls = set()

        try:
            self._setup_driver()
            self.driver.get(self.base_url)
            wait = WebDriverWait(self.driver, 30)  # Increased timeout

            # Wait for page to load completely
            time.sleep(3)
            
            # --- Interact with Dropdowns ---
            # 1. Select Financial Year - try different selectors
            try:
                # First try the original selector
                self._select_dropdown_option("div[class*='my-select__control']", financial_year, wait)
            except TimeoutException:
                self.logger.warning("First dropdown selector failed, trying alternative...")
                # Try alternative selector
                self._select_dropdown_option("div[class*='select__control']", financial_year, wait)
            
            # Wait for the page to update after financial year selection
            time.sleep(3)
            
            # 2. Select Month - try multiple approaches
            month_selected = False
            
            # Approach 1: Try to find all dropdowns and select the second one
            try:
                dropdowns = self.driver.find_elements(By.CSS_SELECTOR, "div[class*='my-select__control']")
                if len(dropdowns) >= 2:
                    self.logger.info(f"Found {len(dropdowns)} dropdowns, selecting the second one for month")
                    # Click the second dropdown directly
                    dropdowns[1].click()
                    time.sleep(2)
                    
                    # Now try to select the month option
                    option_xpath = f"//div[contains(@class, 'my-select__option') and contains(text(), '{month}')]"
                    option = wait.until(EC.element_to_be_clickable((By.XPATH, option_xpath)))
                    option.click()
                    self.logger.info(f"Selected month '{month}' using direct dropdown access")
                    month_selected = True
                else:
                    self.logger.warning(f"Only found {len(dropdowns)} dropdowns, expected at least 2")
            except Exception as e:
                self.logger.debug(f"Direct dropdown access failed: {e}")
            
            # Approach 2: Try alternative selector for second dropdown
            if not month_selected:
                try:
                    self._select_dropdown_option("div[class*='select__control']:nth-of-type(2)", month, wait)
                    month_selected = True
                except TimeoutException:
                    self.logger.warning("Alternative second dropdown selector failed")
            
            # Approach 3: Try to find dropdown by looking for month-related elements
            if not month_selected:
                try:
                    # Look for any element that might be a month dropdown
                    month_selectors = [
                        "div[class*='month']",
                        "div[class*='Month']", 
                        "select[name*='month']",
                        "select[id*='month']"
                    ]
                    
                    for selector in month_selectors:
                        try:
                            elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            if elements:
                                self.logger.info(f"Found potential month selector: {selector}")
                                elements[0].click()
                                time.sleep(2)
                                
                                # Try to select the month
                                option_xpath = f"//div[contains(text(), '{month}')]"
                                option = wait.until(EC.element_to_be_clickable((By.XPATH, option_xpath)))
                                option.click()
                                self.logger.info(f"Selected month '{month}' using selector: {selector}")
                                month_selected = True
                                break
                        except Exception:
                            continue
                            
                except Exception as e:
                    self.logger.debug(f"Month selector search failed: {e}")
            
            # Approach 4: If month selection fails, try to proceed without it
            if not month_selected:
                self.logger.warning(f"Could not select month '{month}', proceeding with financial year only")
                # The page might show all months for the selected financial year
            
            # Wait for the page to update after selections
            time.sleep(3)

            # 3. Set Pagination to show 100 entries to get all monthly reports at once
            try:
                pagination_select_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select[aria-label='Choose a page size']")))
                select = Select(pagination_select_element)
                select.select_by_value("100")
                self.logger.info("Set pagination to show 100 items per page.")
                # Wait for the table to potentially refresh after changing pagination
                time.sleep(3)
            except TimeoutException:
                self.logger.warning("Pagination control not found or could not be set. Proceeding with default.")

            # --- Scrape Results ---
            # Wait for table to be present and populated
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.tableOverFlow table")))
            time.sleep(2)  # Give extra time for table to populate
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            table = soup.select_one('div.tableOverFlow table')
            if not table:
                self.logger.warning("Search returned no results table.")
                return []

            # Look for table body
            tbody = table.find('tbody')
            if not tbody:
                self.logger.warning("No table body found.")
                return []

            rows = tbody.find_all('tr')
            self.logger.info(f"Found {len(rows)} rows in the table")
            
            for row in rows:
                cells = row.find_all('td')
                if not cells: 
                    continue
                link_tag = cells[-1].find('a', href=True)
                if link_tag and link_tag['href'].lower().endswith('.pdf'):
                    report_url = urljoin(self.base_url, link_tag['href'])
                    found_urls.add(report_url)
            
            self.logger.info(f"Found {len(found_urls)} unique PDF links for the specified period.")
            return sorted(list(found_urls))

        except (WebDriverException, Exception) as e:
            self.logger.error(f"An error occurred during historical scraping: {e}", exc_info=True)
            return []
        finally:
            self._close_driver()

    def download_pdf(self, pdf_url: str, save_path: str) -> str | None:
        """
        Downloads a PDF from a URL and saves it locally.
        
        Args:
            pdf_url: The URL of the PDF to download.
            save_path: The local path where the PDF should be saved.
            
        Returns:
            The path where the PDF was saved if successful, None otherwise.
        """
        self.logger.info(f"Downloading PDF from: {pdf_url}")
        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            response = requests.get(pdf_url, stream=True, timeout=60)
            response.raise_for_status()
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            self.logger.info(f"Successfully downloaded PDF to: {save_path}")
            return save_path
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to download PDF: {e}")
            return None

    def _get_link_from_table_row(self, date: str) -> str | None:
        """Finds a hyperlink in a table row on the given URL,
    identifying the row by the specific text format 'DD.MM.YY_NLDC_PSP'.

    Args:
        date: The date to be used to identify the row (format: DD-MM-YYYY or YYYY-MM-DD).

        Returns: The hyperlink from the row corresponding to the date provided, or None.
    """
    max_retries = 3
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
                self.logger.info(f"Searching for text: {search_text}")
        except ValueError as e:
                self.logger.error(f"Invalid date format. Please use YYYY-MM-DD or DD-MM-YYYY. Error: {e}")
            return None

        # Loop for retries
        for attempt in range(max_retries):
            try:
                    self.logger.info(f"Page load attempt {attempt + 1} of {max_retries}...")
                    self._setup_driver()
                    self.driver.set_page_load_timeout(10)
                    self.logger.info(f"Loading page: {self.base_url} (Timeout set to 10 seconds)")
                    self.driver.get(self.base_url)
                    wait = WebDriverWait(self.driver, 10)
                table = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.tableOverFlow table"))
                )
                    self.logger.info("Page loaded successfully!")
                break
            except TimeoutException:
                        self.logger.warning(f"Page failed to load within 10 seconds on attempt {attempt + 1}.")
                        self._close_driver()
                if attempt < max_retries - 1:
                            self.logger.info("Waiting for 5 seconds before retrying...")
                    time.sleep(5)
                    continue
                else:
                            self.logger.error("Failed to load page after all retries.")
                    return None
            except WebDriverException as e:
            self.logger.error(f"An unexpected WebDriver error occurred on attempt {attempt + 1}: {e}", exc_info=True)
            self._close_driver()
                return None

        # If we couldn't get a working driver after all retries, return None
        if not self.driver:
            return None

        # Get the page source after JavaScript has rendered
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        table = soup.select_one('div.tableOverFlow table')
        if not table:
            self.logger.warning("No table found after JavaScript rendering")
            return None
        rows = table.find('tbody').find_all('tr')
        self.logger.info(f"Found {len(rows)} rows in the table")
        for row in rows:
            cells = row.find_all('td')
            if not cells:
                continue
            cell_text = cells[0].get_text(strip=True)
                    self.logger.debug(f"Checking cell text: {cell_text}")
            if search_text in cell_text:
                download_cell = cells[-1]
                link = download_cell.find('a')
                if link and link.has_attr('href'):
                    report_url = link['href']
                    if report_url.lower().endswith('.pdf'):
                                self.logger.info(f"Found matching PDF report for {search_text}")
                        return report_url
                    else:
                                self.logger.warning(f"Found matching text {search_text} but link is not a PDF: {report_url}")
                        continue
                else:
                            self.logger.warning(f"Found matching text {search_text} but no download link")
                    continue
                self.logger.warning(f"No report found for date: {date} (searching for {search_text})")
        return None
    except Exception as e:
                self.logger.error(f"Error while processing page: {e}", exc_info=True)
        return None

    def get_report_url(self, date: datetime | str) -> str | None:
    """
    Get the URL for the PSP report for a specific date.

    Args:
        date: A datetime object or string in format 'YYYY-MM-DD' or 'DD-MM-YYYY'

    Returns:
        The URL of the report if found, None otherwise.
    """
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
                        self.logger.error(f"Invalid date format. Please use YYYY-MM-DD or DD-MM-YYYY")
                        return None
            self.logger.info(f"Searching for report with date: {search_date}")
            return self._get_link_from_table_row(search_date)
        except Exception as e:
            self.logger.error(f"Error getting report URL: {e}")
                    return None
        finally:
            self._close_driver()

    def close(self):
        """Closes the WebDriver session and cleans up resources."""
        self._close_driver()

def main():
    """Main function to fetch all PSP report URLs for multiple financial years and months, saving them in a structured folder layout."""
    import calendar
    import json
    from datetime import datetime
    
    # Define financial years and months
    financial_years = ["2025-26"
                       #, "2024-25", "2023-24"
    ]
    months = [
        # "APRIL", "MAY", "JUNE",
        "JULY"
        #, "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER", "JANUARY", "FEBRUARY", "MARCH"
    ]
    month_to_num = {m: i for i, m in enumerate(months, start=4)}  # APRIL=4, ..., MARCH=3 (next year)
    
    # Output base path
    output_base = r"C:\Users\arjun\Desktop\PSPreport\Output\NLDC_PSP_URLS"
    
    scraper = ReportScraper()
    
    try:
        today = datetime.today()
        current_year = today.year
        current_month = today.month
        # Determine the current financial year string
        if today.month >= 4:
            current_fy = f"{today.year}-{str(today.year+1)[-2:]}"
        else:
            current_fy = f"{today.year-1}-{str(today.year)[-2:]}"
        for fy in financial_years:
            fy_folder = os.path.join(output_base, fy)
            os.makedirs(fy_folder, exist_ok=True)
            # For the current FY, only include months up to the current month
            if fy == current_fy:
                # Build a list of months up to the current month
                months_to_iterate = []
                for m in months:
                    # For APRIL-MARCH, handle year wrap
                    m_num = month_to_num[m] if month_to_num[m] <= 12 else month_to_num[m] - 12
                    # For APRIL-MARCH, APRIL=4, ..., DECEMBER=12, JANUARY=1, ..., MARCH=3
                    # If month is in the current year (APR-DEC)
                    if m_num >= 4 and m_num <= 12 and current_month >= m_num and current_year == int(fy[:4]):
                        months_to_iterate.append(m)
                    # If month is in the next year (JAN-MAR)
                    elif m_num < 4 and current_month >= m_num and current_year == int(fy[5:7]) + 2000:
                        months_to_iterate.append(m)
                # If script runs in April, only APRIL is included
                if not months_to_iterate:
                    months_to_iterate = [months[0]]
            else:
                months_to_iterate = months
            for month in months_to_iterate:
                month_folder = os.path.join(fy_folder, month)
                os.makedirs(month_folder, exist_ok=True)
                print(f"Fetching URLs for {fy} - {month}...")
                urls = scraper.get_historical_report_urls(fy, month)
                # Save URLs to a file in the month folder
                url_file = os.path.join(month_folder, f"urls.json")
                with open(url_file, "w", encoding="utf-8") as f:
                    json.dump(urls, f, indent=2)
                print(f"  Saved {len(urls)} URLs to {url_file}")
    finally:
        scraper.close()

if __name__ == "__main__":
    main()