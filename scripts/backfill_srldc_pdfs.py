from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.acquisition.downloaders.srldc import download_srldc_range
from psp_pipeline.core.logging import configure_logging


def main() -> None:
    """Backfill SRLDC PSP PDFs for the current NLDC-aligned project range."""
    configure_logging("INFO")
    summary = download_srldc_range(
        start_date=date(2023, 4, 1),
        end_date=date(2025, 7, 10),
        output_dir=ROOT / "downloads" / "SRLDC_PSP",
        max_attempts=3,
    )
    print(summary)


if __name__ == "__main__":
    main()
