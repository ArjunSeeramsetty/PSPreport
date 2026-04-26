from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber


DB_PATH = Path("data/sqlite/rldc_daily_psp.db")
PDF_DIR = Path("downloads/SRLDC_PSP")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS psp_raw_cell (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rldc TEXT NOT NULL,
            report_file TEXT NOT NULL,
            report_date TEXT,
            page_no INTEGER NOT NULL,
            table_no INTEGER NOT NULL,
            row_no INTEGER NOT NULL,
            col_no INTEGER NOT NULL,
            cell_text TEXT,
            extracted_at TEXT NOT NULL,
            UNIQUE(report_file, page_no, table_no, row_no, col_no)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS psp_raw_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rldc TEXT NOT NULL,
            report_file TEXT NOT NULL,
            report_date TEXT,
            page_no INTEGER NOT NULL,
            line_no INTEGER NOT NULL,
            line_text TEXT NOT NULL,
            extracted_at TEXT NOT NULL,
            UNIQUE(report_file, page_no, line_no)
        )
        """
    )
    conn.commit()


def parse_date_from_name(name: str) -> str | None:
    try:
        return datetime.strptime(name[:10], "%d-%m-%Y").date().isoformat()
    except ValueError:
        return None


def extract_pdf(conn: sqlite3.Connection, pdf_path: Path) -> tuple[int, int]:
    report_date = parse_date_from_name(pdf_path.name)
    extracted_at = datetime.now(timezone.utc).isoformat()
    raw_cell_count = 0
    raw_line_count = 0

    with pdfplumber.open(str(pdf_path)) as pdf:
        for p_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            for l_idx, line in enumerate(lines, start=1):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO psp_raw_line(
                        rldc, report_file, report_date, page_no, line_no, line_text, extracted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("srldc", pdf_path.name, report_date, p_idx, l_idx, line, extracted_at),
                )
                raw_line_count += 1

            tables = page.extract_tables() or []
            for t_idx, table in enumerate(tables, start=1):
                for r_idx, row in enumerate(table or [], start=1):
                    for c_idx, cell in enumerate(row or [], start=1):
                        value = (str(cell).strip() if cell is not None else "")
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO psp_raw_cell(
                                rldc, report_file, report_date, page_no, table_no, row_no, col_no, cell_text, extracted_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            ("srldc", pdf_path.name, report_date, p_idx, t_idx, r_idx, c_idx, value, extracted_at),
                        )
                        raw_cell_count += 1
    conn.commit()
    return raw_line_count, raw_cell_count


def run(pdf_dir: Path = PDF_DIR, db_path: Path = DB_PATH, force_reprocess: bool = False) -> dict[str, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    ensure_schema(conn)
    done = set()
    if not force_reprocess:
        done = {r[0] for r in conn.execute("SELECT DISTINCT report_file FROM psp_raw_line")}
    counts = {"pdf_seen": 0, "pdf_skipped": 0, "pdf_processed": 0, "raw_lines": 0, "raw_cells": 0}
    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        counts["pdf_seen"] += 1
        if not force_reprocess and pdf_path.name in done:
            counts["pdf_skipped"] += 1
            continue
        lines, cells = extract_pdf(conn, pdf_path)
        counts["raw_lines"] += lines
        counts["raw_cells"] += cells
        counts["pdf_processed"] += 1
    conn.close()
    return counts


if __name__ == "__main__":
    print(run())
