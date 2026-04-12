import os
import requests
import logging
import time
import json
import glob

def download_daily_pdf(report_url: str | None, local_pdf_path: str) -> str | None:
    """
    Downloads the PDF from the provided URL to the specified local path.
    Returns the path to the downloaded PDF file, or None if download fails.
    """
    logger = logging.getLogger("pdf_download")
    if not report_url:
        logger.error("No report URL provided. Skipping download.")
        return None

    os.makedirs(os.path.dirname(local_pdf_path), exist_ok=True)
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

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    base_dir = os.path.join("Output", "NLDC_PSP_URLS")
    for fy in os.listdir(base_dir):
        fy_path = os.path.join(base_dir, fy)
        if not os.path.isdir(fy_path):
            continue
        for month in os.listdir(fy_path):
            month_path = os.path.join(fy_path, month)
            if not os.path.isdir(month_path):
                continue
            urls_json = os.path.join(month_path, "urls.json")
            reports_dir = os.path.join(month_path, "reports")
            if not os.path.exists(urls_json):
                logging.warning(f"No urls.json found in {month_path}, skipping.")
                continue
            with open(urls_json, "r", encoding="utf-8") as f:
                urls = json.load(f)
            os.makedirs(reports_dir, exist_ok=True)
            for url in urls:
                pdf_name = url.split("/")[-1]
                local_pdf_path = os.path.join(reports_dir, pdf_name)
                if os.path.exists(local_pdf_path):
                    logging.info(f"Already downloaded: {local_pdf_path}, skipping.")
                    continue
                result = download_daily_pdf(url, local_pdf_path)
                if result:
                    logging.info(f"Downloaded: {result}")
                else:
                    logging.error(f"Failed to download: {url}")
