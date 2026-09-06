"""IEGC 2023 frequency-band and thermal-flexibility classifiers.

Physically impossible values are flagged for quarantine. Physically plausible
excursions outside the IEGC operating band are promoted and marked as
regulatory violations so compliance dashboards can alert without discarding
true grid events.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Iterable

# CERC IEGC 2023 national reference frequency operating band.
IEGC_FREQUENCY_MIN_HZ = 49.90
IEGC_FREQUENCY_MAX_HZ = 50.05
IEGC_NOMINAL_HZ = 50.0
# Values outside this envelope cannot be a real Indian grid frequency.
PHYSICAL_FREQUENCY_MIN_HZ = 30.0
PHYSICAL_FREQUENCY_MAX_HZ = 70.0
# IEGC 2023 thermal unit minimum turndown as a fraction of MCR.
IEGC_THERMAL_TURNDOWN_MCR = 0.55
MCR_OVERLOAD_CEILING = 1.20

INTEGRITY_OK = "ok"
INTEGRITY_IEGC_VIOLATION = "iegc_violation"
INTEGRITY_PHYSICALLY_IMPOSSIBLE = "physically_impossible"

FREQUENCY_HZ_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "FactSRLDCRegionalDaily",
        ("MaximumFrequencyHz", "MinimumFrequencyHz", "AverageFrequencyHz"),
    ),
    (
        "FactNRLDCFrequencyDaily",
        ("MaximumFrequencyHz", "MinimumFrequencyHz", "AverageFrequencyHz"),
    ),
    (
        "FactWRLDCFrequencyDaily",
        ("MaximumFrequencyHz", "MinimumFrequencyHz", "AverageFrequencyHz"),
    ),
    (
        "FactERLDCFrequencyDaily",
        ("MaximumFrequencyHz", "MinimumFrequencyHz", "AverageFrequencyHz"),
    ),
    (
        "FactNERLDCFrequencyDaily",
        ("MaximumFrequencyHz", "MinimumFrequencyHz", "AverageFrequencyHz"),
    ),
)

IEGC_FLAG_COLUMNS = (
    "IegcBandViolation",
    "FrequencyIntegrity",
)


@dataclass(frozen=True)
class FrequencyClassification:
    """Outcome of comparing one Hz reading against physical and IEGC bounds."""

    integrity: str
    iegc_band_violation: bool
    should_quarantine: bool
    reason: str

    @property
    def promote(self) -> bool:
        """Return whether the value may land in a curated fact table."""

        return not self.should_quarantine


@dataclass(frozen=True)
class ThermalMcrClassification:
    """Outcome of comparing reported MW against installed MCR."""

    ratio: float | None
    status: str
    below_min_turndown: bool
    reason: str


def classify_frequency_hz(value: float | None) -> FrequencyClassification:
    """Classify a single frequency reading.

    ``50.39`` Hz is a real high-frequency excursion and must be promoted with
    ``iegc_violation``. ``70`` Hz is treated as parse/OCR corruption.
    """

    if value is None:
        return FrequencyClassification(
            integrity=INTEGRITY_OK,
            iegc_band_violation=False,
            should_quarantine=False,
            reason="missing",
        )
    hz = float(value)
    if hz <= PHYSICAL_FREQUENCY_MIN_HZ or hz >= PHYSICAL_FREQUENCY_MAX_HZ:
        return FrequencyClassification(
            integrity=INTEGRITY_PHYSICALLY_IMPOSSIBLE,
            iegc_band_violation=True,
            should_quarantine=True,
            reason="physically_impossible",
        )
    if hz < IEGC_FREQUENCY_MIN_HZ or hz > IEGC_FREQUENCY_MAX_HZ:
        return FrequencyClassification(
            integrity=INTEGRITY_IEGC_VIOLATION,
            iegc_band_violation=True,
            should_quarantine=False,
            reason="iegc_operating_band",
        )
    return FrequencyClassification(
        integrity=INTEGRITY_OK,
        iegc_band_violation=False,
        should_quarantine=False,
        reason="within_iegc_band",
    )


def classify_frequency_readings(
    values: Iterable[float | None],
) -> FrequencyClassification:
    """Combine several Hz columns from one fact row, failing closed to the worst."""

    combined = classify_frequency_hz(None)
    for value in values:
        current = classify_frequency_hz(value)
        if current.should_quarantine:
            return current
        if current.iegc_band_violation:
            combined = current
    return combined


def classify_thermal_mcr_ratio(
    generation_mw: float | None,
    installed_capacity_mw: float | None,
) -> ThermalMcrClassification:
    """Compare a thermal unit's reported MW against installed MCR.

    A ratio below 55% demonstrates operation under the mandated turndown
    floor. A ratio above 120% is treated as physically implausible.
    """

    if generation_mw is None or installed_capacity_mw in (None, 0):
        return ThermalMcrClassification(
            ratio=None,
            status="unknown",
            below_min_turndown=False,
            reason="missing_capacity_or_generation",
        )
    ratio = float(generation_mw) / float(installed_capacity_mw)
    if ratio < 0 or ratio > MCR_OVERLOAD_CEILING:
        return ThermalMcrClassification(
            ratio=ratio,
            status=INTEGRITY_PHYSICALLY_IMPOSSIBLE,
            below_min_turndown=False,
            reason="physically_impossible_mcr_ratio",
        )
    if ratio < IEGC_THERMAL_TURNDOWN_MCR:
        return ThermalMcrClassification(
            ratio=ratio,
            status=INTEGRITY_IEGC_VIOLATION,
            below_min_turndown=True,
            reason="below_min_turndown",
        )
    return ThermalMcrClassification(
        ratio=ratio,
        status=INTEGRITY_OK,
        below_min_turndown=False,
        reason="within_turndown_band",
    )


def apply_iegc_frequency_flags(
    conn: sqlite3.Connection,
    report_document_id: int | None = None,
) -> int:
    """Stamp IEGC integrity columns on curated frequency fact rows.

    Missing tables or columns are skipped. Returns the number of updated rows.
    """

    updated = 0
    for table_name, columns in FREQUENCY_HZ_TARGETS:
        if not _table_exists(conn, table_name):
            continue
        present = _present_columns(conn, table_name)
        if not present.issuperset(IEGC_FLAG_COLUMNS):
            continue
        hz_columns = [name for name in columns if name in present]
        if not hz_columns:
            continue
        select_cols = ", ".join(["rowid", *hz_columns])
        sql = f"SELECT {select_cols} FROM {table_name}"
        params: tuple[object, ...] = ()
        if report_document_id is not None and "ReportDocumentID" in present:
            sql += " WHERE ReportDocumentID = ?"
            params = (report_document_id,)
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            rowid = int(row[0])
            classification = classify_frequency_readings(row[1:])
            conn.execute(
                f"UPDATE {table_name} SET IegcBandViolation = ?, FrequencyIntegrity = ? "
                "WHERE rowid = ?",
                (
                    1 if classification.iegc_band_violation else 0,
                    classification.integrity,
                    rowid,
                ),
            )
            updated += 1
    _flag_nldc_duration_bands(conn, report_document_id)
    return updated


def _flag_nldc_duration_bands(
    conn: sqlite3.Connection,
    report_document_id: int | None,
) -> None:
    """Flag NLDC duration-outside-band rows without Hz extrema columns."""

    table_name = "FactNLDCDailyFrequency"
    if not _table_exists(conn, table_name):
        return
    present = _present_columns(conn, table_name)
    if not present.issuperset(IEGC_FLAG_COLUMNS):
        return
    needed = {"Below_49_9", "Above_50_05"}
    if not needed.issubset(present):
        return
    sql = "SELECT rowid, Below_49_9, Above_50_05 FROM FactNLDCDailyFrequency"
    params: tuple[object, ...] = ()
    if report_document_id is not None:
        sql += " WHERE ReportDocumentID = ?"
        params = (report_document_id,)
    for rowid, below, above in conn.execute(sql, params):
        outside = (below or 0) > 0 or (above or 0) > 0
        conn.execute(
            "UPDATE FactNLDCDailyFrequency SET IegcBandViolation = ?, FrequencyIntegrity = ? "
            "WHERE rowid = ?",
            (
                1 if outside else 0,
                INTEGRITY_IEGC_VIOLATION if outside else INTEGRITY_OK,
                int(rowid),
            ),
        )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _present_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}
