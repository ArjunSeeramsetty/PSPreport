"""Locate and bind RPC table columns from published headers, not page numbers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence


HeaderRow = Mapping[int, str] | Sequence[str]


@dataclass(frozen=True)
class FieldSpec:
    """One target-schema field and the publisher labels that identify it."""

    aliases: tuple[str, ...]
    required: bool = False
    is_label: bool = False
    pair_group: str | None = None


@dataclass(frozen=True)
class ColumnBinding:
    """Result of matching one header row against a strict field contract.

    Duplicate aliases (for example two columns both labeled ``Minimum``) are
    skipped as a group rather than guessed. Required fields that remain unbound
    make ``contract_matched`` false so the caller can refuse promotion.
    """

    columns: dict[str, int]
    skipped_fields: tuple[str, ...]
    skipped_reasons: dict[str, str]
    missing_required: tuple[str, ...]
    duplicate_tokens: tuple[str, ...]

    @property
    def contract_matched(self) -> bool:
        """Return whether every required field bound to a unique column."""

        return not self.missing_required


_UNIT_SUFFIX_RE = re.compile(r"(?:rupees|mwh|pct|percent|percentage|rs|mu|mw)$")


def normalize_header_token(value: str) -> str:
    """Collapse punctuation and trailing units so publisher variants compare equal.

    ``DSM Charges (Rs)`` and ``DSM Charges`` therefore share a token, while two
    columns that both collapse onto that token are still detected as duplicates.
    """

    text = str(value or "").lower().replace("₹", "rs")
    text = text.replace("rupees", "rs").replace("inr", "rs").replace("rs.", "rs")
    text = re.sub(r"\((?:rs|mu|mw|mwh|pct|percent|%)\)", "", text)
    compact = re.sub(r"[^a-z0-9]", "", text)
    while True:
        stripped = _UNIT_SUFFIX_RE.sub("", compact)
        if stripped == compact:
            return compact
        compact = stripped


def header_cells(row: HeaderRow) -> dict[int, str]:
    """Return 1-based column indexes with their raw header text."""

    if isinstance(row, Mapping):
        return {
            int(column): str(text or "")
            for column, text in row.items()
            if str(text or "").strip()
        }
    return {
        index + 1: str(text or "")
        for index, text in enumerate(row)
        if str(text or "").strip()
    }


def locate_header_row(
    rows: Sequence[HeaderRow],
    specs: Mapping[str, FieldSpec],
    *,
    min_required_hits: int | None = None,
) -> int | None:
    """Return the first row that uniquely identifies the required contract.

    Page numbers are ignored. A later narrative section that shifts the table
    still matches because only header tokens are consulted.
    """

    required = [name for name, spec in specs.items() if spec.required]
    needed = min_required_hits
    if needed is None:
        needed = max(len(required), 2)
    for index, row in enumerate(rows):
        binding = bind_header_columns(row, specs)
        bound_required = [name for name in required if name in binding.columns]
        if len(bound_required) >= needed and binding.contract_matched:
            return index
        if len(binding.columns) >= needed and not binding.missing_required:
            return index
    return None


def bind_header_columns(row: HeaderRow, specs: Mapping[str, FieldSpec]) -> ColumnBinding:
    """Bind unique header tokens onto the target schema.

    When two columns collapse onto the same alias, every field that would have
    used that token is skipped. Pair groups such as frequency-linked versus
    additional DSM charges are dropped together so a duplicated ``Minimum``
    label cannot leak into the remaining valid mechanism columns.
    """

    cells = header_cells(row)
    token_columns: dict[str, list[int]] = {}
    for column, text in cells.items():
        token = normalize_header_token(text)
        if token:
            token_columns.setdefault(token, []).append(column)

    duplicate_tokens = tuple(
        sorted(token for token, columns in token_columns.items() if len(columns) > 1)
    )
    skipped_fields: list[str] = []
    skipped_reasons: dict[str, str] = {}
    columns: dict[str, int] = {}
    skipped_groups: set[str] = set()

    for field_name, spec in specs.items():
        alias_tokens = tuple(
            dict.fromkeys(token for alias in spec.aliases if (token := normalize_header_token(alias)))
        )
        matches = [
            (alias, token_columns[alias][0])
            for alias in alias_tokens
            if alias in token_columns and len(token_columns[alias]) == 1
        ]
        duplicated = [alias for alias in alias_tokens if alias in duplicate_tokens]
        if duplicated:
            skipped_fields.append(field_name)
            skipped_reasons[field_name] = "duplicate_header:" + ",".join(duplicated)
            if spec.pair_group:
                skipped_groups.add(spec.pair_group)
            continue
        if not matches:
            continue
        if len({column for _, column in matches}) > 1:
            skipped_fields.append(field_name)
            skipped_reasons[field_name] = "ambiguous_alias_columns"
            if spec.pair_group:
                skipped_groups.add(spec.pair_group)
            continue
        columns[field_name] = matches[0][1]

    for field_name, spec in specs.items():
        if spec.pair_group in skipped_groups and field_name in columns:
            skipped_fields.append(field_name)
            skipped_reasons[field_name] = f"malformed_pair:{spec.pair_group}"
            columns.pop(field_name, None)

    missing_required = tuple(
        name for name, spec in specs.items() if spec.required and name not in columns
    )
    return ColumnBinding(
        columns=columns,
        skipped_fields=tuple(dict.fromkeys(skipped_fields)),
        skipped_reasons=skipped_reasons,
        missing_required=missing_required,
        duplicate_tokens=duplicate_tokens,
    )
