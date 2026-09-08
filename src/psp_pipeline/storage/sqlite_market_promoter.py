"""Promote header-anchored ER/NER market matrices with raw-cell lineage."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import logging
import math
import re
import sqlite3
from typing import Callable


LOGGER = logging.getLogger(__name__)
Row = dict[int, tuple[int, str]]
Participant = Callable[[str], tuple[int, int | None] | None]


def _text(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.lower())


def _mechanism(value: str) -> str | None:
    token = _text(value)
    aliases = {
        "gnaschedule": "GNASchedule",
        "tgnabilateral": "TGNABilateral",
        "tgnabilateralmw": "TGNABilateral",
        "bilateralmw": "TGNABilateral",
        "tgnabiltschedule": "TGNABilateral",
        "gdamschedule": "GDAMSchedule",
        "damschedule": "DAMSchedule",
        "rtmschedule": "RTMSchedule",
        "totalmu": "Total",
    }
    if token in aliases:
        return aliases[token]
    for exchange in ("iex", "pxil", "pxi", "hpx"):
        for product in ("gdam", "hpdam", "dam", "rtm"):
            if token == exchange + product + "mw":
                return ("PXIL" if exchange == "pxi" else exchange.upper()) + product.upper()
    return None


def ensure_market_tables(conn: sqlite3.Connection) -> None:
    """Add market grains without changing existing ER energy/extrema facts."""
    for source in ("ERLDC", "NERLDC"):
        conn.execute(f"""CREATE TABLE IF NOT EXISTS Fact{source}MarketPointDaily (
            ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL,
            EntityID INTEGER NOT NULL, StateID INTEGER,
            TimeCategory TEXT NOT NULL CHECK(TimeCategory IN ('peak', 'off_peak')),
            Mechanism TEXT NOT NULL, ScheduledMW REAL NOT NULL,
            PRIMARY KEY(ReportDocumentID, DateID, EntityID, TimeCategory, Mechanism)
        )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS FactNERLDCMarketEnergyDaily (
        ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL,
        EntityID INTEGER NOT NULL, StateID INTEGER,
        GNAScheduleMU REAL, TGNABilateralMU REAL, GDAMScheduleMU REAL,
        DAMScheduleMU REAL, RTMScheduleMU REAL, TotalMU REAL,
        PRIMARY KEY(ReportDocumentID, DateID, EntityID)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS FactNERLDCMarketExtremaDaily (
        ReportDocumentID INTEGER NOT NULL, DateID INTEGER NOT NULL,
        EntityID INTEGER NOT NULL, StateID INTEGER, Mechanism TEXT NOT NULL,
        MaximumMW REAL, MinimumMW REAL,
        PRIMARY KEY(ReportDocumentID, DateID, EntityID, Mechanism)
    )""")


def promote_market_rows(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    source: str,
    rows: list[Row],
    participant: Participant,
) -> None:
    """Promote published market headings; leave ambiguous spans unresolved.

    ER energy/extrema remain owned by its existing promoter. NER accepts only
    participants resolved by its caller. Blank cells never become zeros.
    """
    if source not in {"ERLDC", "NERLDC"}:
        raise ValueError(f"Unsupported market source: {source}")
    for index, row in enumerate(rows[:-1]):
        groups = []
        for col, (_, value) in sorted(row.items()):
            token = _text(value)
            if token == "offpeakhours":
                groups.append((col, "off_peak"))
            elif token == "peakhours":
                groups.append((col, "peak"))
        if groups:
            header = rows[index + 1]
            specs = []
            for col, (_, value) in sorted(header.items()):
                mechanism = _mechanism(value)
                categories = [category for start, category in groups if start <= col]
                if mechanism and categories:
                    specs.append((col, categories[-1], mechanism))
            keys = Counter((category, mechanism) for _, category, mechanism in specs)
            for start, category, mechanism in specs:
                if keys[category, mechanism] != 1:
                    LOGGER.warning("Ambiguous market header report=%s %s %s", report, category, mechanism)
                    continue
                end = min((col for col, (_, value) in header.items()
                           if col > start and value.strip()), default=max(header) + 1)
                _promote_span(conn, report, date_id, source, rows[index + 2:],
                              participant, "Point", {"ScheduledMW": (start, end)},
                              {"TimeCategory": category, "Mechanism": mechanism})
        if source != "NERLDC":
            continue
        if any(_text(value) == "dayenergymu" for _, value in row.values()):
            header = rows[index + 1]
            columns = [(col, _mechanism(value)) for col, (_, value) in header.items()]
            columns = [(col, name) for col, name in columns if name]
            required = {"GNASchedule", "TGNABilateral", "GDAMSchedule", "DAMSchedule", "RTMSchedule", "Total"}
            if {name for _, name in columns} == required and len(columns) == len(required):
                _promote_span(conn, report, date_id, source, rows[index + 2:], participant,
                              "Energy", {name + "MU": (col, col + 1) for col, name in columns}, {})
        mechanisms = [(col, _mechanism(value)) for col, (_, value) in sorted(row.items())]
        mechanisms = [(col, name) for col, name in mechanisms if name]
        subheader = rows[index + 1]
        for pos, (start, mechanism) in enumerate(mechanisms):
            if sum(name == mechanism for _, name in mechanisms) != 1:
                continue
            end = mechanisms[pos + 1][0] if pos + 1 < len(mechanisms) else max(subheader) + 1
            maxima = [col for col in range(start, end) if _text(subheader.get(col, (0, ""))[1]) == "maximum"]
            minima = [col for col in range(start, end) if _text(subheader.get(col, (0, ""))[1]) == "minimum"]
            if len(maxima) == len(minima) == 1:
                _promote_span(conn, report, date_id, source, rows[index + 2:], participant,
                              "Extrema", {"MaximumMW": (maxima[0], minima[0]),
                                          "MinimumMW": (minima[0], end)},
                              {"Mechanism": mechanism})


def _promote_span(
    conn: sqlite3.Connection,
    report: int,
    date_id: int,
    source: str,
    rows: list[Row],
    participant: Participant,
    kind: str,
    fields: dict[str, tuple[int, int]],
    dimensions: dict[str, str],
) -> None:
    table = f"Fact{source}Market{kind}Daily"
    for row in rows:
        label = row.get(1, (0, ""))[1].strip()
        if not label:
            continue
        compact_label = _text(label)
        if (
            compact_label in {"state", "total"}
            or compact_label.startswith(("subtotal", "regionaltotal"))
            or re.match(r"^\d+\s*\(", label)
        ):
            break
        values, raw_ids = {}, {}
        for field, (start, end) in fields.items():
            candidates = []
            for col in range(start, end):
                raw, text = row.get(col, (None, ""))
                try:
                    value = float(text.replace(",", "").strip())
                except ValueError:
                    continue
                if math.isfinite(value):
                    candidates.append((value, raw))
            if len(candidates) == 1:
                values[field], raw_ids[field] = candidates[0]
            elif candidates:
                LOGGER.warning("Ambiguous market values report=%s field=%s label=%s", report, field, label)
        if not values:
            continue
        identity = participant(label)
        if identity is None:
            continue
        entity, state = identity
        payload = {"ReportDocumentID": report, "DateID": date_id, "EntityID": entity,
                   "StateID": state, **dimensions, **values}
        conn.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(payload)}) "
                     f"VALUES ({', '.join('?' for _ in payload)})", tuple(payload.values()))
        key = f"report={report};date={date_id};entity={entity}"
        key += "".join(f";{name}={value}" for name, value in dimensions.items())
        for field, raw in raw_ids.items():
            conn.execute("""INSERT OR IGNORE INTO curated_field_lineage
                (ReportDocumentID, DestinationTable, DestinationKey, DestinationColumn,
                 RawCellID, ExtractionMethod, Confidence, CreatedAt)
                VALUES (?, ?, ?, ?, ?, 'pdfplumber', 1.0, ?)""",
                         (report, table, key, field, raw, datetime.now(timezone.utc).isoformat()))
