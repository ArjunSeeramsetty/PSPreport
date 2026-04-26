from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.rldc_daily_psp import run_rldc_daily_psp_collection


if __name__ == "__main__":
    configure_logging("INFO")
    print(
        run_rldc_daily_psp_collection(
            config_path=ROOT / "config" / "rldc_report_sources.yaml",
            sqlite_db_path=ROOT / "data" / "sqlite" / "rldc_daily_psp.db",
            download_root=ROOT / "data" / "raw" / "rldc_daily_psp",
            target_rldcs={"nrldc"},
            max_reports_per_rldc=5,
        )
    )
