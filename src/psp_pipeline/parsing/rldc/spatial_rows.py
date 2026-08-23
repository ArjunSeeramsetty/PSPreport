"""Deterministic reconstruction of sparse PSP rows from spatial text items."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SpatialTextItem:
    """One persisted spatial text item with its raw database identity."""

    raw_text_item_id: int
    page_no: int
    text: str
    x: float
    y: float


@dataclass(frozen=True)
class ReconstructedSpatialRow:
    """A table-like row rebuilt from positioned text without OCR inference."""

    page_no: int
    y: float
    label: str
    label_item_ids: tuple[int, ...]
    values: Mapping[str, str]
    value_item_ids: Mapping[str, int]


def reconstruct_generation_rows(
    items: Sequence[SpatialTextItem],
    *,
    column_centers: Mapping[str, float],
    label_x_max: float = 105.0,
    row_tolerance: float = 3.0,
    label_tolerance: float = 9.0,
    minimum_value_count: int = 6,
) -> list[ReconstructedSpatialRow]:
    """Rebuild generation rows from the fixed-width NRLDC continuation layout.

    A row anchor is a horizontal cluster containing enough numeric or time
    values to be a published generation record.  Nearby left-column text is
    attached as the station label.  No values are synthesized or inferred.
    """

    candidates = [item for item in items if item.x >= label_x_max and _is_value(item.text)]
    anchors = _cluster_y_positions(candidates, row_tolerance)
    rows: list[ReconstructedSpatialRow] = []
    for index, (anchor_y, value_items) in enumerate(anchors):
        if len(value_items) < minimum_value_count:
            continue
        values, value_item_ids = _assign_columns(value_items, column_centers)
        if len(values) < minimum_value_count:
            continue
        lower_bound = (
            (anchors[index - 1][0] + anchor_y) / 2.0
            if index > 0
            else anchor_y - label_tolerance
        )
        upper_bound = (
            (anchor_y + anchors[index + 1][0]) / 2.0
            if index + 1 < len(anchors)
            else anchor_y + label_tolerance
        )
        label_items = sorted(
            (
                item
                for item in items
                if (
                    item.x < label_x_max
                    and lower_bound <= item.y < upper_bound
                )
            ),
            key=lambda item: (item.y, item.x, item.raw_text_item_id),
        )
        label = " ".join(item.text.strip() for item in label_items if item.text.strip())
        if not label:
            continue
        rows.append(
            ReconstructedSpatialRow(
                page_no=value_items[0].page_no,
                y=anchor_y,
                label=re.sub(r"\s+", " ", label).strip(),
                label_item_ids=tuple(item.raw_text_item_id for item in label_items),
                values=values,
                value_item_ids=value_item_ids,
            )
        )
    return rows


def _cluster_y_positions(
    items: Sequence[SpatialTextItem],
    tolerance: float,
) -> list[tuple[float, list[SpatialTextItem]]]:
    """Group items that share a printed baseline within a narrow tolerance."""

    clusters: list[list[SpatialTextItem]] = []
    for item in sorted(items, key=lambda value: (value.y, value.x)):
        if clusters and abs(item.y - _mean_y(clusters[-1])) <= tolerance:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    return [(_mean_y(cluster), cluster) for cluster in clusters]


def _assign_columns(
    items: Sequence[SpatialTextItem],
    column_centers: Mapping[str, float],
) -> tuple[dict[str, str], dict[str, int]]:
    """Assign positioned values to their nearest approved column center."""

    values: dict[str, str] = {}
    item_ids: dict[str, int] = {}
    for item in items:
        field_name, distance = min(
            ((name, abs(item.x - center)) for name, center in column_centers.items()),
            key=lambda candidate: candidate[1],
        )
        if distance > 24.0 or field_name in values:
            continue
        values[field_name] = item.text.strip()
        item_ids[field_name] = item.raw_text_item_id
    return values, item_ids


def _is_value(text: str) -> bool:
    """Return whether a spatial item is a printed numeric, time, or dash value."""

    normalized = text.strip().replace(",", "").replace("−", "-")
    return bool(
        re.fullmatch(r"-?\d+(?:\.\d+)?", normalized)
        or re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", normalized)
        or normalized == "-"
    )


def _mean_y(items: Sequence[SpatialTextItem]) -> float:
    """Return the mean baseline for a non-empty spatial-item group."""

    return sum(item.y for item in items) / len(items)
