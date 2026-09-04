"""Resolve PSP table layouts from headers or exclusive numeric occupancy.

Row width and ``max(column)`` are never used as schema evidence. Callers must
quarantine ``ambiguous`` and ``unsupported`` results instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal, Mapping


LayoutStatus = Literal["resolved", "ambiguous", "unsupported"]


@dataclass(frozen=True)
class LayoutResolution:
    """Outcome of choosing one fixture-verified mapping for a table extract."""

    status: LayoutStatus
    layout_id: str | None = None
    mapping: dict[str, int] | None = None
    evidence: dict[str, object] = field(default_factory=dict)
    quarantine_reason: str | None = None

    @property
    def resolved(self) -> bool:
        """Return whether a unique mapping is safe to apply."""

        return self.status == "resolved" and bool(self.mapping)

    @classmethod
    def from_mapping(
        cls,
        layout_id: str,
        mapping: Mapping[str, int],
        **evidence: object,
    ) -> "LayoutResolution":
        """Build a resolved result from a known column map."""

        return cls(
            status="resolved",
            layout_id=layout_id,
            mapping={str(name): int(column) for name, column in mapping.items()},
            evidence=dict(evidence),
            quarantine_reason=None,
        )

    @classmethod
    def ambiguous(
        cls,
        *,
        candidates: Iterable[str],
        **evidence: object,
    ) -> "LayoutResolution":
        """Build a fail-closed result when two layouts both fit the extract."""

        names = tuple(str(name) for name in candidates)
        return cls(
            status="ambiguous",
            layout_id=None,
            mapping=None,
            evidence={"candidates": names, **evidence},
            quarantine_reason="ambiguous_layout",
        )

    @classmethod
    def unsupported(
        cls,
        reason: str = "unsupported_layout",
        **evidence: object,
    ) -> "LayoutResolution":
        """Build a fail-closed result when no fixture-verified layout matches."""

        return cls(
            status="unsupported",
            layout_id=None,
            mapping=None,
            evidence=dict(evidence),
            quarantine_reason=reason,
        )


def compact_label(value: object) -> str:
    """Normalize publisher labels for token comparison."""

    return "".join(_cell_text(value).split()).lower()


def resolve_header_layout(
    header_rows: Iterable[Mapping[int, object]],
    field_tokens: Mapping[str, tuple[str, ...]],
    *,
    layout_id: str = "header",
) -> LayoutResolution:
    """Bind columns from published labels when every required field is unique.

    A field binds from one cell only when that cell contains every required
    token. When no complete single-cell map exists, alphabetic labels are
    concatenated per column so two-tier stacked headers can bind. Incomplete
    or non-unique header hits are not a mapping. Callers should fall through
    to a fixture-verified numeric signature rather than guess the missing
    fields.
    """

    rows = [dict(row) for row in header_rows]
    resolved: dict[str, int] = {}
    for row in rows:
        for column, cell in row.items():
            normalized = compact_label(cell)
            if not normalized:
                continue
            for field_name, tokens in field_tokens.items():
                if field_name in resolved:
                    continue
                if _column_matches_tokens(normalized, tokens):
                    resolved[field_name] = int(column)
        if len(resolved) == len(field_tokens):
            return LayoutResolution.from_mapping(
                layout_id,
                resolved,
                source="header",
            )
    stacked = _bind_unique_stacked_fields(rows, field_tokens)
    if stacked is not None:
        return LayoutResolution.from_mapping(
            layout_id,
            stacked,
            source="stacked_header",
        )
    stacked_partial = _stacked_field_hits(rows, field_tokens)
    return LayoutResolution.unsupported(
        "incomplete_header_layout",
        bound_fields=tuple(sorted(resolved)),
        missing_fields=tuple(sorted(set(field_tokens) - set(resolved))),
        stacked_bound_fields=tuple(
            sorted(name for name, columns in stacked_partial.items() if len(columns) == 1)
        ),
        stacked_ambiguous_fields=tuple(
            sorted(name for name, columns in stacked_partial.items() if len(columns) > 1)
        ),
    )


def _cell_text(value: object) -> str:
    """Return the printable text of a raw or ``(id, text)`` cell."""

    text = value[1] if isinstance(value, tuple) and len(value) > 1 else value
    return str(text or "")


def _is_numeric_cell(value: object) -> bool:
    """Return whether a cell is a bare numeric value rather than a label."""

    raw = _cell_text(value).replace(",", "").strip()
    if not raw:
        return False
    try:
        float(raw)
    except ValueError:
        return False
    return True


def _column_matches_tokens(normalized: str, tokens: tuple[str, ...]) -> bool:
    """Return whether compacted label text contains every required token."""

    return bool(normalized) and all(token in normalized for token in tokens)


def _aggregate_column_labels(
    header_rows: Iterable[Mapping[int, object]],
) -> dict[int, str]:
    """Join non-numeric labels in each column for stacked-header matching."""

    materialized = [dict(row) for row in header_rows]
    columns: set[int] = set()
    for row in materialized:
        columns.update(int(column) for column in row)
    aggregated: dict[int, str] = {}
    for column in sorted(columns):
        parts: list[str] = []
        for row in materialized:
            if column not in row:
                continue
            cell = row[column]
            if _is_numeric_cell(cell):
                continue
            label = compact_label(cell)
            if label:
                parts.append(label)
        aggregated[column] = "".join(parts)
    return aggregated


def _stacked_field_hits(
    header_rows: Iterable[Mapping[int, object]],
    field_tokens: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[int, ...]]:
    """Return stacked-header column hits for each required field."""

    hits: dict[str, list[int]] = {name: [] for name in field_tokens}
    for column, label in _aggregate_column_labels(header_rows).items():
        if not label:
            continue
        for field_name, tokens in field_tokens.items():
            if _column_matches_tokens(label, tokens):
                hits[field_name].append(int(column))
    return {name: tuple(columns) for name, columns in hits.items()}


def _bind_unique_stacked_fields(
    header_rows: Iterable[Mapping[int, object]],
    field_tokens: Mapping[str, tuple[str, ...]],
) -> dict[str, int] | None:
    """Bind fields from stacked labels only when every field is unique.

    A field that matches zero columns, two columns, or a column already bound
    to another field is not a mapping.
    """

    hits = _stacked_field_hits(header_rows, field_tokens)
    resolved: dict[str, int] = {}
    used_columns: set[int] = set()
    for field_name in field_tokens:
        columns = hits[field_name]
        if len(columns) != 1:
            return None
        column = columns[0]
        if column in used_columns:
            return None
        used_columns.add(column)
        resolved[field_name] = column
    return resolved


def resolve_exclusive_layouts(
    *,
    layouts: Mapping[str, Mapping[str, int]],
    exclusive_columns: Mapping[str, frozenset[int]],
    populated: Callable[[int], bool],
    default_layout_id: str | None = None,
) -> LayoutResolution:
    """Pick a layout when exactly one exclusive column set is populated.

    ``default_layout_id`` is used only when no exclusive set has values, which
    covers sparse rows of a fixture-verified family. Competing layouts fail
    closed as ``ambiguous``.
    """

    hits = {
        layout_id: tuple(
            sorted(column for column in exclusive_columns[layout_id] if populated(column))
        )
        for layout_id in layouts
    }
    candidates = [layout_id for layout_id, columns in hits.items() if columns]
    evidence = {"exclusive_hits": hits}
    if len(candidates) == 1:
        layout_id = candidates[0]
        return LayoutResolution.from_mapping(
            layout_id,
            layouts[layout_id],
            **evidence,
        )
    if len(candidates) > 1:
        return LayoutResolution.ambiguous(candidates=candidates, **evidence)
    if default_layout_id and default_layout_id in layouts:
        return LayoutResolution.from_mapping(
            default_layout_id,
            layouts[default_layout_id],
            default=True,
            **evidence,
        )
    return LayoutResolution.unsupported("no_matching_layout", **evidence)
