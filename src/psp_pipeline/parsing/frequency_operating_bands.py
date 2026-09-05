"""Bind IEGC operating-band duration percentages from published labels.

ERLDC and NERLDC publish a three-bucket frequency profile
(``<49.90``, ``49.90–50.05``, ``>50.05``). A field binds only when its
label tokens are unique. Partial or colliding hits are not a mapping.
"""

from __future__ import annotations

from typing import Mapping

from psp_pipeline.parsing.layout_resolution import compact_label


FREQUENCY_OPERATING_BAND_FIELDS = (
    "DurationBelow49_90Pct",
    "Duration49_90To50_05Pct",
    "DurationAbove50_05Pct",
)

_BAND_TOKEN_ALTERNATIVES: dict[str, tuple[tuple[str, ...], ...]] = {
    "DurationBelow49_90Pct": (("<", "49.90"), ("below", "49.90")),
    "Duration49_90To50_05Pct": (("49.90", "50.05"),),
    "DurationAbove50_05Pct": ((">", "50.05"), ("above", "50.05")),
}


def collect_frequency_operating_bands(
    rows: list[Mapping[int, object]],
) -> tuple[dict[str, float], dict[str, int]]:
    """Return unique band percentages and the raw-cell ids that produced them.

    Header columns win when every band binds uniquely and a later numeric row
    fills those columns. Otherwise each row is treated as a label-plus-value
    pair. Missing or duplicate bands yield an empty mapping.
    """

    header = _bind_header_band_columns(rows)
    if header is not None:
        values, sources = _values_from_header_columns(rows, header)
        if _complete(values):
            return values, sources
    values, sources = _values_from_label_rows(rows)
    if _complete(values):
        return values, sources
    return {}, {}


def _complete(values: Mapping[str, float]) -> bool:
    """Return whether every IEGC operating band has a percentage."""

    return all(field in values for field in FREQUENCY_OPERATING_BAND_FIELDS)


def _label_matches_field(normalized: str, field_name: str) -> bool:
    """Return whether compacted label text uniquely identifies one band."""

    for tokens in _BAND_TOKEN_ALTERNATIVES[field_name]:
        if normalized and all(token in normalized for token in tokens):
            return True
    return False


def _bind_header_band_columns(
    rows: list[Mapping[int, object]],
) -> dict[str, int] | None:
    """Bind band fields from stacked or single-row headers when unique."""

    hits: dict[str, list[int]] = {name: [] for name in FREQUENCY_OPERATING_BAND_FIELDS}
    columns: set[int] = set()
    for row in rows[:4]:
        columns.update(int(column) for column in row)
    for column in sorted(columns):
        parts = [compact_label(row[column]) for row in rows[:4] if column in row]
        normalized = "".join(part for part in parts if part)
        if not normalized:
            continue
        for field_name in FREQUENCY_OPERATING_BAND_FIELDS:
            if _label_matches_field(normalized, field_name):
                hits[field_name].append(column)
    resolved: dict[str, int] = {}
    used: set[int] = set()
    for field_name in FREQUENCY_OPERATING_BAND_FIELDS:
        columns_hit = hits[field_name]
        if len(columns_hit) != 1:
            return None
        column = columns_hit[0]
        if column in used:
            return None
        used.add(column)
        resolved[field_name] = column
    return resolved


def _values_from_header_columns(
    rows: list[Mapping[int, object]],
    columns: Mapping[str, int],
) -> tuple[dict[str, float], dict[str, int]]:
    """Read the first numeric row that fills every bound band column."""

    for row in rows:
        values: dict[str, float] = {}
        sources: dict[str, int] = {}
        for field_name, column in columns.items():
            parsed = _numeric_cell(row.get(column))
            if parsed is None:
                break
            value, raw_id = parsed
            values[field_name] = value
            if raw_id is not None:
                sources[field_name] = raw_id
        if _complete(values):
            return values, sources
    return {}, {}


def _values_from_label_rows(
    rows: list[Mapping[int, object]],
) -> tuple[dict[str, float], dict[str, int]]:
    """Bind one percentage per band from label-in-column-1 rows."""

    values: dict[str, float] = {}
    sources: dict[str, int] = {}
    for row in rows:
        label = compact_label(row.get(1, ""))
        if not label:
            continue
        matches = [
            field_name
            for field_name in FREQUENCY_OPERATING_BAND_FIELDS
            if _label_matches_field(label, field_name)
        ]
        if len(matches) != 1 or matches[0] in values:
            continue
        parsed = _first_numeric_cell(row, skip_columns={1})
        if parsed is None:
            continue
        value, raw_id = parsed
        values[matches[0]] = value
        if raw_id is not None:
            sources[matches[0]] = raw_id
    return values, sources


def _numeric_cell(cell: object | None) -> tuple[float, int | None] | None:
    """Parse a raw or ``(id, text)`` cell as a percentage."""

    if cell is None:
        return None
    raw_id: int | None = None
    text = cell
    if isinstance(cell, tuple) and len(cell) > 1:
        raw_id = int(cell[0]) if cell[0] is not None else None
        text = cell[1]
    try:
        return float(str(text or "").replace(",", "").replace("%", "").strip()), raw_id
    except ValueError:
        return None


def _first_numeric_cell(
    row: Mapping[int, object],
    *,
    skip_columns: set[int],
) -> tuple[float, int | None] | None:
    """Return the first numeric cell in column order, skipping label columns."""

    for column in sorted(int(key) for key in row):
        if column in skip_columns:
            continue
        parsed = _numeric_cell(row.get(column))
        if parsed is not None:
            return parsed
    return None
