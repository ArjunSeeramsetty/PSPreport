from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.rldc_daily_psp import LocalReportInput, run_rldc_local_pdf_ingestion


def _parse_date_from_name(path: Path) -> datetime.date | None:
    compact = re.search(r"daily(\d{2})(\d{2})(\d{2})", path.name, flags=re.IGNORECASE)
    if compact:
        d, mth, y = compact.group(1), compact.group(2), compact.group(3)
        y = f"20{y}"
        try:
            return datetime(int(y), int(mth), int(d)).date()
        except ValueError:
            return None

    m = re.search(r"(\d{2})[-._](\d{2})[-._](\d{2,4})", path.name)
    if not m:
        return None
    d, mth, y = m.group(1), m.group(2), m.group(3)
    if len(y) == 2:
        y = f"20{y}"
    try:
        return datetime(int(y), int(mth), int(d)).date()
    except ValueError:
        return None


def main() -> None:
    configure_logging("INFO")
    parser = argparse.ArgumentParser(description="Ingest local RLDC PSP PDFs into SQLite.")
    parser.add_argument("--rldc", required=True, help="Rldc key like srldc or nrldc.")
    parser.add_argument("--input-dir", type=Path, required=True, help="Folder containing local PSP PDFs.")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "sqlite" / "rldc_daily_psp.db")
    args = parser.parse_args()

    files = sorted(args.input_dir.glob("*.pdf"))
    reports: list[LocalReportInput] = []
    for f in files:
        dt = _parse_date_from_name(f)
        if not dt:
            continue
        reports.append(LocalReportInput(rldc=args.rldc.lower(), local_path=f, report_date=dt))

    result = run_rldc_local_pdf_ingestion(sqlite_db_path=args.db, local_reports=reports)
    print(result)


if __name__ == "__main__":
    main()
