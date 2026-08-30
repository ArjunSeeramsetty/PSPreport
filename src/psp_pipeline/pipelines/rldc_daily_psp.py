from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx
import pdfplumber
import yaml

from psp_pipeline.acquisition.adapters import (
    BaseRLDCAdapter,
    DiscoveredLink,
    ERLDCAdapter,
    GridIndiaNLDCAdapter,
    NERLDCAdapter,
    NRLDCAdapter,
    SRLDCAdapter,
    WRLDCAdapter,
    grid_india_verified_client,
)
from psp_pipeline.parsing.rldc.pdf_tables import extract_page_tables
from psp_pipeline.parsing.rldc.templates import TemplateMatch, inspect_report_structure, match_report_template
from psp_pipeline.storage.sqlite_curated_promoter import promote_report_to_curated
from psp_pipeline.storage.sqlite_curated_schema import ensure_curated_sqlite_schema

logger = logging.getLogger(__name__)

_NRLDC_SPATIAL_TEMPLATE_IDS = frozenset(
    {
        "nrldc_daily_psp_v2025_standard_11_column_generation",
        "nrldc_daily_psp_v2026_standard_11_column_storage",
    }
)
_NRLDC_CONTINUATION_PAGES = (6, 7, 8, 9)


@dataclass(frozen=True)
class RldcSource:
    key: str
    mode: str


@dataclass(frozen=True)
class DownloadedReport:
    rldc: str
    source_url: str
    local_path: Path
    content_hash: str
    fetched_at: datetime
    report_date: date
    report_family: str
    discovery_confidence: float
    response_content_length: int | None
    response_last_modified: str | None


@dataclass(frozen=True)
class LocalReportInput:
    rldc: str
    local_path: Path
    report_date: date
    report_family: str = "psp"
    confidence: float = 1.0


@dataclass(frozen=True)
class OcrAssessment:
    should_use_ocr: bool
    score: float
    reason: str
    extracted_char_count: int


@dataclass(frozen=True)
class RawLine:
    """Raw line extracted from a PSP PDF page."""

    page_no: int
    line_no: int
    line_text: str
    extraction_method: str


@dataclass(frozen=True)
class RawCell:
    """Raw table cell extracted from a PSP PDF page."""

    page_no: int
    table_no: int
    row_no: int
    col_no: int
    cell_text: str
    extraction_method: str


@dataclass(frozen=True)
class RawTextItem:
    """Spatial text item extracted by LiteParse for layout-drift forensics."""

    page_no: int
    item_no: int
    text: str
    x: float | None
    y: float | None
    width: float | None
    height: float | None
    confidence: float | None
    extraction_method: str


@dataclass(frozen=True)
class ParsedPspContent:
    """Parsed PSP content containing normalized fields and raw extraction layers."""

    fields: dict[str, float]
    text_char_count: int
    raw_lines: list[RawLine]
    raw_cells: list[RawCell]
    raw_text_items: list[RawTextItem]
    extraction_methods: tuple[str, ...]
    template_match: TemplateMatch


FIELD_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "regional_max_demand_met_mw": [
        re.compile(r"maximum demand met.*?(\d+(?:\.\d+)?)", re.IGNORECASE),
        re.compile(r"max(?:imum)?\s+demand.*?(\d+(?:\.\d+)?)", re.IGNORECASE),
    ],
    "regional_peak_shortage_mw": [
        re.compile(r"peak shortage.*?(\d+(?:\.\d+)?)", re.IGNORECASE),
    ],
    "regional_energy_met_mu": [
        re.compile(r"energy met.*?(\d+(?:\.\d+)?)", re.IGNORECASE),
    ],
    "regional_energy_shortage_mu": [
        re.compile(r"energy shortage.*?(\d+(?:\.\d+)?)", re.IGNORECASE),
        re.compile(r"shortage.*?(\d+(?:\.\d+)?)", re.IGNORECASE),
    ],
}


def load_rldc_sources(config_path: Path) -> list[RldcSource]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    sources: list[RldcSource] = []
    for key, value in data.get("rldc_sources", {}).items():
        sources.append(
            RldcSource(
                key=key.lower(),
                mode=value.get("mode", "generic").lower(),
            )
        )
    return sources


def _get_adapter(source_key: str) -> BaseRLDCAdapter | None:
    source = source_key.lower()
    if source == "srldc":
        return SRLDCAdapter()
    if source == "nrldc":
        return NRLDCAdapter()
    if source == "wrldc":
        return WRLDCAdapter()
    if source == "erldc":
        return ERLDCAdapter()
    if source == "nerldc":
        return NERLDCAdapter()
    if source == "grid_india_national":
        return GridIndiaNLDCAdapter()
    return None


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_sample_text(pdf_path: Path, max_pages: int = 2) -> str:
    chunks: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages[:max_pages]:
            text = page.extract_text() or ""
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def _extract_pdfplumber_raw(pdf_path: Path) -> tuple[str, list[RawLine], list[RawCell]]:
    """Extract raw text lines and table cells using pdfplumber."""

    chunks: list[str] = []
    raw_lines: list[RawLine] = []
    raw_cells: list[RawCell] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text:
                chunks.append(text)
            for line_idx, line in enumerate((line.strip() for line in text.splitlines()), start=1):
                if line:
                    raw_lines.append(
                        RawLine(
                            page_no=page_idx,
                            line_no=line_idx,
                            line_text=line,
                            extraction_method="pdfplumber",
                        )
                    )
            for table_idx, table in enumerate(extract_page_tables(page), start=1):
                for row_idx, row in enumerate(table or [], start=1):
                    for col_idx, cell in enumerate(row or [], start=1):
                        raw_cells.append(
                            RawCell(
                                page_no=page_idx,
                                table_no=table_idx,
                                row_no=row_idx,
                                col_no=col_idx,
                                cell_text=str(cell).strip() if cell is not None else "",
                                extraction_method="pdfplumber",
                            )
                        )
            page.flush_cache()
    return "\n".join(chunks), raw_lines, raw_cells


def _liteparse_available() -> bool:
    """Return whether a local LiteParse CLI can be invoked."""

    command = _liteparse_command()
    if not command:
        return False
    try:
        completed = subprocess.run(
            [*command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _liteparse_command() -> list[str] | None:
    """Return the installed LiteParse CLI, falling back to an npx invocation."""

    for candidate in (
        Path(r"C:\Users\arjun\AppData\Roaming\npm\lit.cmd"),
        Path(shutil.which("lit.cmd") or ""),
        Path(shutil.which("lit") or ""),
    ):
        if candidate.is_file():
            return [str(candidate)]
    npx = _npx_command()
    return [npx, "-y", "@llamaindex/liteparse"] if npx else None


def _npx_command() -> str | None:
    """Return the platform-specific npx executable path."""

    for candidate in (
        r"C:\Program Files\nodejs\npx.cmd",
        shutil.which("npx.cmd"),
        shutil.which("npx"),
    ):
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def _run_liteparse(
    pdf_path: Path,
    target_pages: str | None = None,
    timeout_seconds: int = 240,
) -> dict[str, Any] | None:
    """Run LiteParse locally and return parsed JSON, or None on failure.

    ``timeout_seconds`` defaults to the production forensic budget. Tests may
    supply a smaller budget to make command availability failures explicit.
    """

    launcher = _liteparse_command()
    if not launcher:
        logger.warning("liteparse_unavailable reason=cli_not_found")
        return None

    with tempfile.TemporaryDirectory(prefix="psp_liteparse_") as tmp_dir:
        output_path = Path(tmp_dir) / "liteparse.json"
        command = [
            *launcher,
            "parse",
            str(pdf_path),
            "--format",
            "json",
            "-o",
            str(output_path),
        ]
        if target_pages:
            command.extend(["--target-pages", target_pages])

        env = os.environ.copy()
        tessdata = Path(r"C:\Program Files\Tesseract-OCR\tessdata")
        if tessdata.exists():
            env["TESSDATA_PREFIX"] = str(tessdata)

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            logger.warning("liteparse_invocation_failed path=%s error=%s", pdf_path, exc)
            return None

        if completed.returncode != 0 or not output_path.exists():
            logger.warning(
                "liteparse_failed path=%s returncode=%s stderr=%s",
                pdf_path,
                completed.returncode,
                completed.stderr[-500:],
            )
            return None
        try:
            return json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("liteparse_json_decode_failed path=%s error=%s", pdf_path, exc)
            return None


def _extract_liteparse_content(
    pdf_path: Path,
    target_pages: str | None = None,
    timeout_seconds: int = 240,
) -> tuple[str, list[RawTextItem]]:
    """Extract LiteParse text and spatial items from selected local PDF pages."""

    payload = _run_liteparse(
        pdf_path,
        target_pages=target_pages,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        return "", []

    chunks: list[str] = []
    raw_items: list[RawTextItem] = []
    pages = payload.get("pages", [])
    if not isinstance(pages, list):
        return "", []

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_no = int(page.get("page") or len(chunks) + 1)
        text = str(page.get("text") or "")
        if text:
            chunks.append(text)
        # LiteParse 0.x used camelCase while the current 2.x CLI emits
        # snake_case keys.  Accept both to keep historical diagnostics replayable.
        text_items = page.get("text_items", page.get("textItems", []))
        if not isinstance(text_items, list):
            continue
        for item_idx, item in enumerate(text_items, start=1):
            if not isinstance(item, dict):
                continue
            raw_items.append(
                RawTextItem(
                    page_no=page_no,
                    item_no=item_idx,
                    text=str(item.get("text") or "").strip(),
                    x=_optional_float(item.get("x")),
                    y=_optional_float(item.get("y")),
                    width=_optional_float(item.get("width")),
                    height=_optional_float(item.get("height")),
                    confidence=_optional_float(item.get("confidence")),
                    extraction_method="liteparse",
                )
            )
    return "\n".join(chunks), [item for item in raw_items if item.text]


def _optional_float(value: Any) -> float | None:
    """Convert a loosely typed value to float when possible."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def assess_ocr_need(pdf_path: Path) -> OcrAssessment:
    text = _read_sample_text(pdf_path)
    char_count = len(text.strip())
    digit_count = len(re.findall(r"\d", text))
    numeric_density = digit_count / max(char_count, 1)
    score = 0.0
    reason = "native text extraction is healthy"

    if char_count < 1200:
        score += 0.7
        reason = "very low extracted text volume"
    if numeric_density < 0.03:
        score += 0.3
        reason = "text present but weak numeric density for table-heavy PSP"
    return OcrAssessment(
        should_use_ocr=score >= 0.7,
        score=round(score, 2),
        reason=reason,
        extracted_char_count=char_count,
    )


PSP_VALIDATION_RULES = {
    "required_keywords": ["power supply position", "psp", "generation", "demand", "shortage"],
    "min_keyword_hits": 2,
    "min_page_count": 1,
    "max_page_count": 15,
}


def validate_report_family(pdf_path: Path, declared_family: str) -> bool:
    if declared_family != "psp":
        return True
    with pdfplumber.open(str(pdf_path)) as pdf:
        page_count = len(pdf.pages)
        text = " ".join((page.extract_text() or "") for page in pdf.pages[:3]).lower()
    keyword_hits = sum(1 for kw in PSP_VALIDATION_RULES["required_keywords"] if kw in text)
    if keyword_hits < PSP_VALIDATION_RULES["min_keyword_hits"]:
        logger.warning("report_family_mismatch path=%s keyword_hits=%s", pdf_path, keyword_hits)
        return False
    if not (PSP_VALIDATION_RULES["min_page_count"] <= page_count <= PSP_VALIDATION_RULES["max_page_count"]):
        logger.warning("report_page_count_out_of_range path=%s pages=%s", pdf_path, page_count)
        return False
    return True


def _extract_numeric_fields(text: str) -> dict[str, float]:
    result: dict[str, float] = {}
    normalized = re.sub(r"\s+", " ", text)
    for field_name, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(normalized)
            if not match:
                continue
            try:
                result[field_name] = float(match.group(1))
                break
            except ValueError:
                continue
    return result


def _parse_numeric_cell(value: str) -> float | None:
    """Parse a numeric PDF table cell while rejecting times and blanks."""

    text = value.strip().replace(",", "")
    if not text or text in {"-", "--", "Nil", "NIL"}:
        return None
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        return None
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _slug(value: str, fallback: str, max_length: int = 70) -> str:
    """Return a stable lowercase field-name component."""

    normalized = re.sub(r"\s+", "_", value.strip().lower())
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = fallback
    return normalized[:max_length].strip("_") or fallback


def _nearest_column_label(rows: dict[int, dict[int, str]], row_no: int, col_no: int) -> str:
    """Find the nearest non-numeric text above a table cell."""

    for previous_row in range(row_no - 1, 0, -1):
        text = rows.get(previous_row, {}).get(col_no, "")
        if text and _parse_numeric_cell(text) is None:
            return text
    return f"col_{col_no}"


def _row_label(row: dict[int, str], row_no: int) -> str:
    """Find a non-numeric label for a table row."""

    for col_no in sorted(row):
        text = row[col_no]
        if text and _parse_numeric_cell(text) is None:
            return text
    return f"row_{row_no}"


def _extract_table_fallback_fields(raw_cells: Iterable[RawCell]) -> dict[str, float]:
    """Create stable fallback observations for every numeric PDF table cell."""

    tables: dict[tuple[int, int], dict[int, dict[int, str]]] = {}
    for cell in raw_cells:
        table = tables.setdefault((cell.page_no, cell.table_no), {})
        row = table.setdefault(cell.row_no, {})
        row[cell.col_no] = cell.cell_text

    fields: dict[str, float] = {}
    for (page_no, table_no), rows in tables.items():
        for row_no, row in rows.items():
            row_name = _slug(_row_label(row, row_no), f"row_{row_no}")
            for col_no, cell_text in row.items():
                number = _parse_numeric_cell(cell_text)
                if number is None:
                    continue
                col_name = _slug(_nearest_column_label(rows, row_no, col_no), f"col_{col_no}")
                field_name = (
                    f"regional_table_p{page_no}_t{table_no}_{row_name}_{col_name}"
                    f"_r{row_no}_c{col_no}"
                )
                fields[field_name] = number
    return fields


def _extract_line_total_metric(lines: list[str], label_patterns: list[str]) -> float | None:
    for line in lines:
        low = line.lower()
        if not any(pattern in low for pattern in label_patterns):
            continue
        nums = re.findall(r"\d+(?:\.\d+)?", line)
        if not nums:
            continue
        try:
            return float(nums[-1])
        except ValueError:
            continue
    return None


def _should_try_liteparse(
    use_liteparse_fallback: bool,
    ocr: OcrAssessment | None,
    extracted_fields: dict[str, float],
    text: str,
    raw_cells: list[RawCell],
) -> bool:
    """Return whether native extraction is insufficient for a spatial fallback."""

    if not use_liteparse_fallback:
        return False
    return (
        (ocr.should_use_ocr if ocr else False)
        or not extracted_fields
        or len(text.strip()) < 1200
        or not raw_cells
    )


def _needs_nrldc_continuation_spatial_items(raw_cells: list[RawCell]) -> bool:
    """Return whether NRLDC continuation rows collapsed into left-column cells."""

    for cell in raw_cells:
        if cell.page_no not in {6, 7, 8, 9} or cell.col_no != 1:
            continue
        numeric_values = re.findall(r"(?<![A-Za-z])[-−]?\d+(?:\.\d+)?", cell.cell_text)
        if len(numeric_values) >= 6:
            return True
    return False


def extract_psp_content(
    pdf_path: Path,
    rldc: str,
    ocr: OcrAssessment | None = None,
    use_liteparse_fallback: bool = True,
) -> ParsedPspContent:
    """Extract normalized PSP fields plus raw lines/cells/spatial items."""

    structure = inspect_report_structure(pdf_path)
    template_match = match_report_template(rldc, structure)
    text, raw_lines, raw_cells = _extract_pdfplumber_raw(pdf_path)
    result = _extract_numeric_fields(text)
    result.update(_extract_table_fallback_fields(raw_cells))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    raw_text_items: list[RawTextItem] = []
    methods = ["pdfplumber"]

    should_try_liteparse = _should_try_liteparse(
        use_liteparse_fallback,
        ocr,
        result,
        text,
        raw_cells,
    )
    continuation_spatial_fallback = (
        rldc == "nrldc" and _needs_nrldc_continuation_spatial_items(raw_cells)
    )
    if (should_try_liteparse or continuation_spatial_fallback) and _liteparse_available():
        liteparse_text, raw_text_items = _extract_liteparse_content(
            pdf_path,
            target_pages="6-9" if continuation_spatial_fallback else None,
        )
        if liteparse_text:
            methods.append("liteparse")
            liteparse_fields = _extract_numeric_fields(liteparse_text)
            for field_name, field_value in liteparse_fields.items():
                result.setdefault(field_name, field_value)
            if len(liteparse_text) > len(text):
                lines = [line.strip() for line in liteparse_text.splitlines() if line.strip()]
                text = liteparse_text

    total_energy_met = _extract_line_total_metric(lines, ["energy met (mu)", "energy met"])
    if total_energy_met is not None:
        result["all_india_energy_met_mu"] = total_energy_met

    total_energy_shortage = _extract_line_total_metric(lines, ["energy shortage (mu)", "energy shortage"])
    if total_energy_shortage is not None:
        result["all_india_energy_shortage_mu"] = total_energy_shortage

    total_peak_shortage = _extract_line_total_metric(lines, ["peak shortage (mw)", "peak shortage"])
    if total_peak_shortage is not None:
        result["all_india_peak_shortage_mw"] = total_peak_shortage

    total_max_demand = _extract_line_total_metric(
        lines,
        ["maximum demand met during the day (mw)", "maximum demand met during the day"],
    )
    if total_max_demand is not None:
        result["all_india_max_demand_met_mw"] = total_max_demand

    return ParsedPspContent(
        fields=result,
        text_char_count=len(text),
        raw_lines=raw_lines,
        raw_cells=raw_cells,
        raw_text_items=raw_text_items,
        extraction_methods=tuple(methods),
        template_match=template_match,
    )


def extract_psp_fields(pdf_path: Path) -> tuple[dict[str, float], int]:
    """Extract normalized PSP fields while preserving the legacy return shape."""

    content = extract_psp_content(pdf_path, rldc="unknown", use_liteparse_fallback=False)
    return content.fields, content.text_char_count


def ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    ensure_curated_sqlite_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS psp_report_document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rldc TEXT NOT NULL,
            source_url TEXT NOT NULL,
            local_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            ocr_score REAL NOT NULL,
            ocr_used INTEGER NOT NULL,
            ocr_reason TEXT NOT NULL,
            extracted_char_count INTEGER NOT NULL,
            report_date TEXT,
            report_family TEXT,
            discovery_confidence REAL,
            response_content_length INTEGER,
            response_last_modified TEXT,
            template_id TEXT,
            template_version TEXT,
            template_confidence REAL,
            semantic_pass_required INTEGER,
            structure_deviation_reason TEXT,
            UNIQUE(rldc, content_hash)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS psp_observation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_document_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            field_value REAL NOT NULL,
            extracted_at TEXT NOT NULL,
            FOREIGN KEY(report_document_id) REFERENCES psp_report_document(id),
            UNIQUE(report_document_id, field_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS psp_raw_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_document_id INTEGER NOT NULL,
            page_no INTEGER NOT NULL,
            line_no INTEGER NOT NULL,
            line_text TEXT NOT NULL,
            extraction_method TEXT NOT NULL,
            extracted_at TEXT NOT NULL,
            FOREIGN KEY(report_document_id) REFERENCES psp_report_document(id),
            UNIQUE(report_document_id, page_no, line_no, extraction_method)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS psp_raw_cell (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_document_id INTEGER NOT NULL,
            page_no INTEGER NOT NULL,
            table_no INTEGER NOT NULL,
            row_no INTEGER NOT NULL,
            col_no INTEGER NOT NULL,
            cell_text TEXT,
            extraction_method TEXT NOT NULL,
            extracted_at TEXT NOT NULL,
            FOREIGN KEY(report_document_id) REFERENCES psp_report_document(id),
            UNIQUE(report_document_id, page_no, table_no, row_no, col_no, extraction_method)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS psp_raw_text_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_document_id INTEGER NOT NULL,
            page_no INTEGER NOT NULL,
            item_no INTEGER NOT NULL,
            item_text TEXT NOT NULL,
            x REAL,
            y REAL,
            width REAL,
            height REAL,
            confidence REAL,
            extraction_method TEXT NOT NULL,
            extracted_at TEXT NOT NULL,
            FOREIGN KEY(report_document_id) REFERENCES psp_report_document(id),
            UNIQUE(report_document_id, page_no, item_no, extraction_method)
        )
        """
    )
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(psp_report_document)")}
    for column, ddl in (
        ("report_date", "ALTER TABLE psp_report_document ADD COLUMN report_date TEXT"),
        ("report_family", "ALTER TABLE psp_report_document ADD COLUMN report_family TEXT"),
        ("discovery_confidence", "ALTER TABLE psp_report_document ADD COLUMN discovery_confidence REAL"),
        ("response_content_length", "ALTER TABLE psp_report_document ADD COLUMN response_content_length INTEGER"),
        ("response_last_modified", "ALTER TABLE psp_report_document ADD COLUMN response_last_modified TEXT"),
        ("template_id", "ALTER TABLE psp_report_document ADD COLUMN template_id TEXT"),
        ("template_version", "ALTER TABLE psp_report_document ADD COLUMN template_version TEXT"),
        ("template_confidence", "ALTER TABLE psp_report_document ADD COLUMN template_confidence REAL"),
        ("semantic_pass_required", "ALTER TABLE psp_report_document ADD COLUMN semantic_pass_required INTEGER"),
        ("structure_deviation_reason", "ALTER TABLE psp_report_document ADD COLUMN structure_deviation_reason TEXT"),
    ):
        if column not in existing_columns:
            conn.execute(ddl)
    # NLDC facts have a real FK to this raw document table, so create them only
    # after the raw persistence contract is established.
    ensure_curated_sqlite_schema(conn)
    conn.commit()


def persist_report(
    conn: sqlite3.Connection,
    report: DownloadedReport,
    ocr: OcrAssessment,
    fields: dict[str, float],
    template_match: TemplateMatch,
    raw_lines: Iterable[RawLine] | None = None,
    raw_cells: Iterable[RawCell] | None = None,
    raw_text_items: Iterable[RawTextItem] | None = None,
) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO psp_report_document(
            rldc, source_url, local_path, content_hash, fetched_at,
            ocr_score, ocr_used, ocr_reason, extracted_char_count,
            report_date, report_family, discovery_confidence,
            response_content_length, response_last_modified,
            template_id, template_version, template_confidence,
            semantic_pass_required, structure_deviation_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report.rldc,
            report.source_url,
            str(report.local_path),
            report.content_hash,
            report.fetched_at.isoformat(),
            ocr.score,
            1 if ocr.should_use_ocr else 0,
            ocr.reason,
            ocr.extracted_char_count,
            report.report_date.isoformat(),
            report.report_family,
            report.discovery_confidence,
            report.response_content_length,
            report.response_last_modified,
            template_match.template_id,
            template_match.template_version,
            template_match.confidence,
            1 if template_match.semantic_pass_required else 0,
            ";".join(template_match.reasons),
        ),
    )
    cursor.execute(
        "SELECT id FROM psp_report_document WHERE rldc = ? AND content_hash = ?",
        (report.rldc, report.content_hash),
    )
    row = cursor.fetchone()
    if not row:
        conn.commit()
        return
    report_id = row[0]
    now = datetime.now(timezone.utc).isoformat()
    for field_name, field_value in fields.items():
        cursor.execute(
            """
            INSERT OR REPLACE INTO psp_observation(report_document_id, field_name, field_value, extracted_at)
            VALUES (?, ?, ?, ?)
            """,
            (report_id, field_name, field_value, now),
        )
    for line in raw_lines or []:
        cursor.execute(
            """
            INSERT INTO psp_raw_line(
                report_document_id, page_no, line_no, line_text, extraction_method, extracted_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_document_id, page_no, line_no, extraction_method)
            DO UPDATE SET line_text = excluded.line_text, extracted_at = excluded.extracted_at
            """,
            (report_id, line.page_no, line.line_no, line.line_text, line.extraction_method, now),
        )
    for cell in raw_cells or []:
        cursor.execute(
            """
            INSERT INTO psp_raw_cell(
                report_document_id, page_no, table_no, row_no, col_no, cell_text, extraction_method, extracted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                report_document_id, page_no, table_no, row_no, col_no, extraction_method
            ) DO UPDATE SET cell_text = excluded.cell_text, extracted_at = excluded.extracted_at
            """,
            (
                report_id,
                cell.page_no,
                cell.table_no,
                cell.row_no,
                cell.col_no,
                cell.cell_text,
                cell.extraction_method,
                now,
            ),
        )
    _upsert_raw_text_items(cursor, report_id, raw_text_items or [], now)
    promote_report_to_curated(conn, report_id)
    conn.commit()


def backfill_nrldc_continuation_spatial_items(
    sqlite_db_path: Path,
) -> dict[str, int]:
    """Add missing LiteParse coordinates for NRLDC 2025/26 continuation pages.

    Existing raw PDF cells and observations are not changed. This enrichment only
    refreshes LiteParse items for pages 6--9 when the full four-page coordinate
    set is absent, then replays curated promotion from the raw persistence layer.
    """

    result = {
        "reports_seen": 0,
        "reports_enriched": 0,
        "reports_already_complete": 0,
        "reports_missing_local_file": 0,
        "reports_without_spatial_items": 0,
        "liteparse_unavailable": 0,
    }
    if not sqlite_db_path.exists():
        return result
    if not _liteparse_available():
        logger.warning("nrldc_spatial_backfill_skipped reason=liteparse_unavailable")
        result["liteparse_unavailable"] = 1
        return result

    with sqlite3.connect(sqlite_db_path) as conn:
        ensure_sqlite_schema(conn)
        placeholders = ", ".join("?" for _ in _NRLDC_SPATIAL_TEMPLATE_IDS)
        reports = conn.execute(
            f"""
            SELECT id, local_path
            FROM psp_report_document
            WHERE rldc = 'nrldc' AND template_id IN ({placeholders})
            ORDER BY report_date, id
            """,
            tuple(sorted(_NRLDC_SPATIAL_TEMPLATE_IDS)),
        ).fetchall()
        result["reports_seen"] = len(reports)
        for report_id, raw_path in reports:
            pages = {
                int(row[0])
                for row in conn.execute(
                    """
                    SELECT DISTINCT page_no
                    FROM psp_raw_text_item
                    WHERE report_document_id = ?
                      AND extraction_method = 'liteparse'
                      AND page_no IN (6, 7, 8, 9)
                    """,
                    (report_id,),
                )
            }
            if pages == set(_NRLDC_CONTINUATION_PAGES):
                result["reports_already_complete"] += 1
                continue
            pdf_path = Path(str(raw_path))
            if not pdf_path.exists():
                logger.warning(
                    "nrldc_spatial_backfill_missing_file report_id=%s path=%s",
                    report_id,
                    pdf_path,
                )
                result["reports_missing_local_file"] += 1
                continue
            _, items = _extract_liteparse_content(pdf_path, target_pages="6-9")
            items = [item for item in items if item.page_no in _NRLDC_CONTINUATION_PAGES]
            if not items:
                logger.warning(
                    "nrldc_spatial_backfill_empty report_id=%s path=%s",
                    report_id,
                    pdf_path,
                )
                result["reports_without_spatial_items"] += 1
                continue
            conn.execute(
                """
                DELETE FROM psp_raw_text_item
                WHERE report_document_id = ?
                  AND extraction_method = 'liteparse'
                  AND page_no IN (6, 7, 8, 9)
                """,
                (report_id,),
            )
            _upsert_raw_text_items(
                conn.cursor(),
                int(report_id),
                items,
                datetime.now(timezone.utc).isoformat(),
            )
            promote_report_to_curated(conn, int(report_id))
            conn.commit()
            result["reports_enriched"] += 1
    return result


def _upsert_raw_text_items(
    cursor: sqlite3.Cursor,
    report_id: int,
    items: Iterable[RawTextItem],
    extracted_at: str,
) -> None:
    """Persist spatial items with idempotent per-page item identities."""

    for item in items:
        cursor.execute(
            """
            INSERT INTO psp_raw_text_item(
                report_document_id, page_no, item_no, item_text, x, y, width, height,
                confidence, extraction_method, extracted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_document_id, page_no, item_no, extraction_method)
            DO UPDATE SET
                item_text = excluded.item_text,
                x = excluded.x,
                y = excluded.y,
                width = excluded.width,
                height = excluded.height,
                confidence = excluded.confidence,
                extracted_at = excluded.extracted_at
            """,
            (
                report_id,
                item.page_no,
                item.item_no,
                item.text,
                item.x,
                item.y,
                item.width,
                item.height,
                item.confidence,
                item.extraction_method,
                extracted_at,
            ),
        )


def _download_report(client: httpx.Client, link: DiscoveredLink, out_dir: Path) -> DownloadedReport | None:
    fetch_url = link.url
    if "srldc.in" in urlparse(fetch_url).netloc and fetch_url.startswith("https://"):
        fetch_url = fetch_url.replace("https://", "http://", 1)
    # HEAD first for cheap availability + lineage metadata.
    retry_client: httpx.Client | None = None
    try:
        try:
            head = client.head(fetch_url)
        except httpx.HTTPError:
            if link.source_id != "grid_india_national":
                return None
            retry_client = grid_india_verified_client(client)
            if retry_client is None:
                return None
            logger.info("NLDC retrying public download with platform trust store")
            head = retry_client.head(fetch_url)
        if head.status_code >= 400:
            return None
        try:
            response = (retry_client or client).get(fetch_url)
        except httpx.HTTPError:
            if link.source_id != "grid_india_national" or retry_client is not None:
                return None
            retry_client = grid_india_verified_client(client)
            if retry_client is None:
                return None
            logger.info("NLDC retrying public download with platform trust store")
            response = retry_client.get(fetch_url)
    except httpx.HTTPError:
        return None
    finally:
        if retry_client is not None:
            retry_client.close()
    if response.status_code >= 400:
        return None
    data = response.content
    if not data:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(urlparse(link.url).path).name or f"{link.source_id}_{int(datetime.now(timezone.utc).timestamp())}.pdf"
    local_path = out_dir / safe_name
    local_path.write_bytes(data)
    return DownloadedReport(
        rldc=link.source_id,
        source_url=link.url,
        local_path=local_path,
        content_hash=_hash_bytes(data),
        fetched_at=datetime.now(timezone.utc),
        report_date=link.report_date,
        report_family=link.report_family,
        discovery_confidence=link.confidence,
        response_content_length=int(head.headers["content-length"]) if head.headers.get("content-length", "").isdigit() else None,
        response_last_modified=head.headers.get("last-modified"),
    )


def run_rldc_daily_psp_collection(
    config_path: Path,
    sqlite_db_path: Path,
    download_root: Path,
    target_rldcs: set[str] | None = None,
    max_reports_per_rldc: int = 3,
    target_date: date | None = None,
) -> dict[str, int]:
    sources = load_rldc_sources(config_path)
    if target_rldcs:
        sources = [source for source in sources if source.key in target_rldcs]

    counts = {
        "sources_scanned": 0,
        "pdf_links_found": 0,
        "reports_downloaded": 0,
        "reports_persisted": 0,
        "ocr_recommended": 0,
        "report_family_rejected": 0,
    }
    run_date = target_date or datetime.now(timezone.utc).date()

    sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(sqlite_db_path))
    ensure_sqlite_schema(conn)

    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        for source in sources:
            counts["sources_scanned"] += 1
            adapter = _get_adapter(source.key)
            if not adapter:
                continue
            try:
                discovered = adapter.discover(client, run_date)
            except httpx.HTTPError:
                continue
            if not discovered:
                continue
            discovered = discovered[:max_reports_per_rldc]
            counts["pdf_links_found"] += len(discovered)

            for link in discovered:
                report = _download_report(client, link, download_root / source.key)
                if not report:
                    continue
                counts["reports_downloaded"] += 1
                if not validate_report_family(report.local_path, report.report_family):
                    counts["report_family_rejected"] += 1
                    continue
                ocr = assess_ocr_need(report.local_path)
                if ocr.should_use_ocr:
                    counts["ocr_recommended"] += 1
                parsed = extract_psp_content(report.local_path, rldc=report.rldc, ocr=ocr)
                persist_report(
                    conn,
                    report,
                    ocr,
                    parsed.fields,
                    parsed.template_match,
                    raw_lines=parsed.raw_lines,
                    raw_cells=parsed.raw_cells,
                    raw_text_items=parsed.raw_text_items,
                )
                counts["reports_persisted"] += 1

    conn.close()
    return counts


def run_rldc_local_pdf_ingestion(
    sqlite_db_path: Path,
    local_reports: list[LocalReportInput],
) -> dict[str, int]:
    counts = {
        "reports_seen": 0,
        "reports_persisted": 0,
        "ocr_recommended": 0,
        "report_family_rejected": 0,
    }
    sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(sqlite_db_path))
    ensure_sqlite_schema(conn)

    for item in local_reports:
        counts["reports_seen"] += 1
        if not item.local_path.exists():
            continue
        if not validate_report_family(item.local_path, item.report_family):
            counts["report_family_rejected"] += 1
            continue
        ocr = assess_ocr_need(item.local_path)
        if ocr.should_use_ocr:
            counts["ocr_recommended"] += 1
        report = DownloadedReport(
            rldc=item.rldc,
            source_url=f"file://{item.local_path}",
            local_path=item.local_path,
            content_hash=_hash_file(item.local_path),
            fetched_at=datetime.now(timezone.utc),
            report_date=item.report_date,
            report_family=item.report_family,
            discovery_confidence=item.confidence,
            response_content_length=item.local_path.stat().st_size,
            response_last_modified=datetime.fromtimestamp(item.local_path.stat().st_mtime, tz=timezone.utc).isoformat(),
        )
        parsed = extract_psp_content(item.local_path, rldc=item.rldc, ocr=ocr)
        persist_report(
            conn,
            report,
            ocr,
            parsed.fields,
            parsed.template_match,
            raw_lines=parsed.raw_lines,
            raw_cells=parsed.raw_cells,
            raw_text_items=parsed.raw_text_items,
        )
        counts["reports_persisted"] += 1

    conn.close()
    return counts
