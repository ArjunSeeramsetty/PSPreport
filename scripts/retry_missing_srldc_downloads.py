from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.acquisition.downloaders.srldc import download_srldc_range, missing_dates
from psp_pipeline.core.logging import configure_logging


def main() -> None:
    """Retry missing SRLDC PSP PDFs and write a missing-date manifest."""
    configure_logging("INFO")
    start_date = date(2023, 4, 1)
    end_date = date(2025, 7, 10)
    output_dir = ROOT / "downloads" / "SRLDC_PSP"

    summary = download_srldc_range(
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
        max_attempts=5,
    )
    remaining = missing_dates(start_date, end_date, output_dir)
    manifest = ROOT / "downloads" / "missing_srldc_dates.txt"
    manifest.write_text("\n".join(day.isoformat() for day in remaining), encoding="utf-8")
    print(summary)
    print({"missing_after": len(remaining), "manifest": str(manifest)})


if __name__ == "__main__":
    main()
