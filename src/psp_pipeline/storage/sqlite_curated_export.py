"""Export curated daily facts into portable time-series observations."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from dataclasses import dataclass
import sqlite3
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from psp_pipeline.models.contracts import FactObservation, ObservationLineage
from psp_pipeline.storage.observation_identity import (
    build_revision_uuid,
    build_series_key,
)


SOURCE_REGION = "SR"
REPORT_TYPE = "srldc_daily_psp"
_DIMENSION_COLUMNS = {
    "ReportDocumentID",
    "DateID",
    "RegionID",
    "StateID",
    "EntityID",
    "GenerationSourceID",
    "StationID",
    "GeneratingUnitID",
    "AggregateID",
    "ElementID",
    "VoltageNodeID",
    "ReservoirID",
    "CountryID",
    "MechanismID",
    "IsTotalRow",
    "BlockStartTime",
}


@dataclass(frozen=True)
class TableExportSpec:
    """Declarative projection of one curated fact table."""

    table_name: str
    entity_expression: str
    joins: str = ""
    lineage_expressions: tuple[tuple[str, str], ...] = ()
    excluded_numeric_columns: tuple[str, ...] = ()
    block_start_time_column: str | None = None


@dataclass(frozen=True)
class RLDCExportConfig:
    """Source metadata and table projections for one regional PSP family."""

    source_id: str
    metric_prefix: str
    report_type: str
    source_region: str
    tables: tuple[TableExportSpec, ...]


def export_srldc_daily_observations(
    conn: sqlite3.Connection,
    report_document_id: int | None = None,
    *,
    ingested_at: datetime | None = None,
) -> list[FactObservation]:
    """Return governed numeric SRLDC facts as bitemporal observations.

    The function is intentionally read-only.  The calling persistence stage owns
    the Timescale transaction and may retain every later ingestion as a new
    system-time version.
    """
    return export_registered_daily_observations(
        conn,
        "srldc",
        report_document_id=report_document_id,
        ingested_at=ingested_at,
    )


def export_nrldc_daily_observations(
    conn: sqlite3.Connection,
    report_document_id: int | None = None,
    *,
    ingested_at: datetime | None = None,
) -> list[FactObservation]:
    """Return curated NRLDC facts as portable bitemporal observations."""

    recorded_at = ingested_at or datetime.now(timezone.utc)
    common = {
        "report_document_id": report_document_id,
        "ingested_at": recorded_at,
        "source_id": "nrldc",
        "metric_prefix": "nrldc",
        "report_type": "nrldc_daily_psp",
        "source_region": "NR",
    }
    return [
        *_export_table(
            conn,
            table_name="FactNRLDCRegionalDaily",
            entity_expression="'NR:region:' || region.RegionName",
            joins="JOIN DimRegions AS region ON region.RegionID = fact.RegionID",
            **common,
        ),
        *_export_table(
            conn,
            table_name="FactNRLDCStateDaily",
            entity_expression="'NR:state:' || state.StateCode",
            joins="JOIN DimStates AS state ON state.StateID = fact.StateID",
            **common,
        ),
        *_export_table(
            conn,
            table_name="FactNRLDCGenerationDaily",
            entity_expression="'NR:generation:' || entity.EntityName",
            joins="JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID",
            **common,
        ),
        *_export_table(
            conn,
            table_name="FactNRLDCFrequencyDaily",
            entity_expression="'NR:region:' || region.RegionName",
            joins="JOIN DimRegions AS region ON region.RegionID = fact.RegionID",
            **common,
        ),
        *_export_table(
            conn,
            table_name="FactNRLDCVoltageProfile",
            entity_expression="'NR:voltage:' || node.NodeName",
            joins="JOIN DimVoltageNodes AS node ON node.VoltageNodeID = fact.VoltageNodeID",
            **common,
        ),
        *_export_table(
            conn,
            table_name="FactNRLDCReservoirDaily",
            entity_expression="'NR:reservoir:' || reservoir.ReservoirName",
            joins="JOIN DimReservoirs AS reservoir ON reservoir.ReservoirID = fact.ReservoirID",
            **common,
        ),
        *_export_table(
            conn,
            table_name="FactNRLDCInterRegionalExchange",
            entity_expression="'NR:line:' || element.ElementName",
            joins=(
                "JOIN DimTransmissionElements AS element "
                "ON element.ElementID = fact.ElementID"
            ),
            **common,
        ),
        *_export_table(
            conn,
            table_name="FactNRLDCInterRegionalScheduleExchange",
            entity_expression=(
                "'NR:interregional-schedule:' || fact.CounterpartyRegion"
            ),
            joins="",
            **common,
        ),
        *_export_table(
            conn,
            table_name="FactNRLDCInternationalExchange",
            entity_expression="'NR:international-line:' || element.ElementName",
            joins=(
                "JOIN DimTransmissionElements AS element "
                "ON element.ElementID = fact.ElementID"
            ),
            **common,
        ),
    ]


def export_wrldc_daily_observations(
    conn: sqlite3.Connection,
    report_document_id: int | None = None,
    *,
    ingested_at: datetime | None = None,
) -> list[FactObservation]:
    """Return curated WRLDC facts as portable bitemporal observations."""

    return export_registered_daily_observations(
        conn,
        "wrldc",
        report_document_id=report_document_id,
        ingested_at=ingested_at,
    )


def export_erldc_daily_observations(
    conn: sqlite3.Connection,
    report_document_id: int | None = None,
    *,
    ingested_at: datetime | None = None,
) -> list[FactObservation]:
    """Return curated ERLDC facts as portable bitemporal observations."""
    return export_registered_daily_observations(
        conn,
        "erldc",
        report_document_id=report_document_id,
        ingested_at=ingested_at,
    )


def export_nerldc_daily_observations(
    conn: sqlite3.Connection,
    report_document_id: int | None = None,
    *,
    ingested_at: datetime | None = None,
) -> list[FactObservation]:
    """Return curated NERLDC facts as portable bitemporal observations."""
    return export_registered_daily_observations(
        conn,
        "nerldc",
        report_document_id=report_document_id,
        ingested_at=ingested_at,
    )


# Compatibility mapping retained for external callers during the registry
# transition. New orchestration code uses RLDC_EXPORT_CONFIG directly.
RLDC_EXPORTERS = {
    "srldc": export_srldc_daily_observations,
    "nrldc": export_nrldc_daily_observations,
    "wrldc": export_wrldc_daily_observations,
    "erldc": export_erldc_daily_observations,
    "nerldc": export_nerldc_daily_observations,
}


RLDC_EXPORT_CONFIG: dict[str, RLDCExportConfig] = {
    "srldc": RLDCExportConfig(
        "srldc", "srldc", REPORT_TYPE, "SR", (
            TableExportSpec(
                "FactSRLDCRegionalDaily",
                "'SR:region:' || region.RegionName",
                "JOIN DimRegions AS region ON region.RegionID = fact.RegionID",
            ),
            TableExportSpec(
                "FactSRLDCStateDaily",
                "'SR:state:' || state.StateCode",
                "JOIN DimStates AS state ON state.StateID = fact.StateID",
                excluded_numeric_columns=(
                    "ActualDemandMU",
                    "ForecastDeviationPct",
                ),
            ),
            TableExportSpec(
                "FactSRLDCGenerationDaily",
                "'SR:generation:' || entity.EntityName || ':section:' "
                "|| COALESCE(fact.SectionName, 'unspecified')",
                "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID",
                (("SectionName", "fact.SectionName"),),
            ),
            TableExportSpec(
                "FactSRLDCInterRegionalExchange",
                "'SR:line:' || element.ElementName || ':category:' "
                "|| COALESCE(fact.ExchangeCategory, 'unspecified') || ':direction:' "
                "|| COALESCE(fact.Direction, 'unspecified')",
                "JOIN DimTransmissionElements AS element "
                "ON element.ElementID = fact.ElementID",
                (
                    ("ExchangeCategory", "fact.ExchangeCategory"),
                    ("Direction", "fact.Direction"),
                ),
            ),
            TableExportSpec(
                "FactSRLDCVoltageProfile",
                "'SR:voltage:' || node.NodeName",
                "JOIN DimVoltageNodes AS node "
                "ON node.VoltageNodeID = fact.VoltageNodeID",
            ),
            TableExportSpec(
                "FactSRLDCReservoirDaily",
                "'SR:reservoir:' || reservoir.ReservoirName",
                "JOIN DimReservoirs AS reservoir "
                "ON reservoir.ReservoirID = fact.ReservoirID",
            ),
            TableExportSpec(
                "FactSRLDCMarketTransaction",
                "'SR:state:' || state.StateCode || ':market:' "
                "|| mechanism.MechanismName || ':time:' "
                "|| COALESCE(fact.TimeCategory, 'unspecified')",
                "JOIN DimStates AS state ON state.StateID = fact.StateID "
                "JOIN DimExchangeMechanisms AS mechanism "
                "ON mechanism.MechanismID = fact.MechanismID",
                (
                    ("MechanismName", "mechanism.MechanismName"),
                    ("TimeCategory", "fact.TimeCategory"),
                ),
            ),
            TableExportSpec(
                "FactSRLDCRegionalMarketTransaction",
                "'SR:region:' || region.RegionName || ':market:' "
                "|| mechanism.MechanismName || ':time:' "
                "|| COALESCE(fact.TimeCategory, 'unspecified')",
                "JOIN DimRegions AS region ON region.RegionID = fact.RegionID "
                "JOIN DimExchangeMechanisms AS mechanism "
                "ON mechanism.MechanismID = fact.MechanismID",
                (
                    ("MechanismName", "mechanism.MechanismName"),
                    ("TimeCategory", "fact.TimeCategory"),
                ),
            ),
        ),
    ),
    "nrldc": RLDCExportConfig(
        "nrldc", "nrldc", "nrldc_daily_psp", "NR", (
            TableExportSpec("FactNRLDCRegionalDaily", "'NR:region:' || region.RegionName", "JOIN DimRegions AS region ON region.RegionID = fact.RegionID"),
            TableExportSpec("FactNRLDCStateDaily", "'NR:state:' || state.StateCode", "JOIN DimStates AS state ON state.StateID = fact.StateID"),
            TableExportSpec("FactNRLDCGenerationDaily", "'NR:generation:' || entity.EntityName", "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID"),
            TableExportSpec("FactNRLDCFrequencyDaily", "'NR:region:' || region.RegionName", "JOIN DimRegions AS region ON region.RegionID = fact.RegionID"),
            TableExportSpec("FactNRLDCVoltageProfile", "'NR:voltage:' || node.NodeName", "JOIN DimVoltageNodes AS node ON node.VoltageNodeID = fact.VoltageNodeID"),
            TableExportSpec("FactNRLDCReservoirDaily", "'NR:reservoir:' || reservoir.ReservoirName", "JOIN DimReservoirs AS reservoir ON reservoir.ReservoirID = fact.ReservoirID"),
            TableExportSpec("FactNRLDCInterRegionalExchange", "'NR:line:' || element.ElementName", "JOIN DimTransmissionElements AS element ON element.ElementID = fact.ElementID"),
            TableExportSpec("FactNRLDCInterRegionalScheduleExchange", "'NR:interregional-schedule:' || fact.CounterpartyRegion"),
            TableExportSpec("FactNRLDCInternationalExchange", "'NR:international-line:' || element.ElementName", "JOIN DimTransmissionElements AS element ON element.ElementID = fact.ElementID"),
            TableExportSpec("FactNRLDCStateMarketDaily", "'NR:state:' || state.StateCode || ':market:day-energy'", "JOIN DimStates AS state ON state.StateID = fact.StateID"),
            TableExportSpec("FactNRLDCStateMarketPointDaily", "'NR:state:' || state.StateCode || ':market:point:' || fact.TimeCategory", "JOIN DimStates AS state ON state.StateID = fact.StateID", (("TimeCategory", "fact.TimeCategory"),)),
            TableExportSpec("FactNRLDCStateMarketExtremaDaily", "'NR:state:' || state.StateCode || ':market:extrema:' || fact.Mechanism", "JOIN DimStates AS state ON state.StateID = fact.StateID", (("Mechanism", "fact.Mechanism"),)),
        ),
    ),
    "wrldc": RLDCExportConfig(
        "wrldc", "wrldc", "wrldc_daily_psp", "WR", (
            TableExportSpec("FactWRLDCRegionalDaily", "'WR:region:' || region.RegionName", "JOIN DimRegions AS region ON region.RegionID = fact.RegionID"),
            TableExportSpec("FactWRLDCStateDaily", "'WR:state:' || state.StateName", "JOIN DimStates AS state ON state.StateID = fact.StateID"),
            TableExportSpec("FactWRLDCGenerationDaily", "'WR:generation:' || entity.EntityName || ':section:' || fact.SectionName", "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID", (("SectionName", "fact.SectionName"),)),
            TableExportSpec("FactWRLDCFrequencyDaily", "'WR:region:' || region.RegionName", "JOIN DimRegions AS region ON region.RegionID = fact.RegionID"),
            TableExportSpec("FactWRLDCVoltageProfile", "'WR:voltage:' || node.NodeName", "JOIN DimVoltageNodes AS node ON node.VoltageNodeID = fact.VoltageNodeID", (), ("NominalVoltageKV",)),
            TableExportSpec("FactWRLDCReservoirDaily", "'WR:reservoir:' || reservoir.ReservoirName", "JOIN DimReservoirs AS reservoir ON reservoir.ReservoirID = fact.ReservoirID"),
            TableExportSpec("FactWRLDCMarketEnergyDaily", "'WR:market-participant:' || entity.EntityName || ':market:day-energy'", "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID"),
            TableExportSpec("FactWRLDCMarketPointDaily", "'WR:market-participant:' || entity.EntityName || ':market:point:' || fact.TimeCategory || ':' || fact.Mechanism", "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID", (("TimeCategory", "fact.TimeCategory"), ("Mechanism", "fact.Mechanism"))),
            TableExportSpec("FactWRLDCMarketExtremaDaily", "'WR:market-participant:' || entity.EntityName || ':market:extrema:' || fact.Mechanism", "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID", (("Mechanism", "fact.Mechanism"),)),
            TableExportSpec("FactWRLDCInterRegionalExchange", "'WR:line:' || element.ElementName", "JOIN DimTransmissionElements AS element ON element.ElementID = fact.ElementID"),
        ),
    ),
    "erldc": RLDCExportConfig(
        "erldc", "erldc", "erldc_daily_psp", "ER", (
            TableExportSpec("FactERLDCRegionalDaily", "'ER:region:' || region.RegionName", "JOIN DimRegions AS region ON region.RegionID = fact.RegionID"),
            TableExportSpec("FactERLDCStateDaily", "'ER:state:' || state.StateName", "JOIN DimStates AS state ON state.StateID = fact.StateID"),
            TableExportSpec(
                "FactERLDCGenerationDaily",
                "'ER:generation:' || entity.EntityName || ':section:' || fact.SectionName",
                "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID",
                (("SectionName", "fact.SectionName"),),
            ),
            TableExportSpec("FactERLDCFrequencyDaily", "'ER:region:' || region.RegionName", "JOIN DimRegions AS region ON region.RegionID = fact.RegionID"),
            TableExportSpec(
                "FactERLDCVoltageProfile",
                "'ER:voltage:' || node.NodeName",
                "JOIN DimVoltageNodes AS node ON node.VoltageNodeID = fact.VoltageNodeID",
                (),
                ("NominalVoltageKV",),
            ),
            TableExportSpec("FactERLDCReservoirDaily", "'ER:reservoir:' || reservoir.ReservoirName", "JOIN DimReservoirs AS reservoir ON reservoir.ReservoirID = fact.ReservoirID"),
            TableExportSpec("FactERLDCInterRegionalExchange", "'ER:line:' || element.ElementName", "JOIN DimTransmissionElements AS element ON element.ElementID = fact.ElementID"),
            TableExportSpec("FactERLDCInternationalExchange", "'ER:country:' || country.CountryName", "JOIN DimCountries AS country ON country.CountryID = fact.CountryID"),
            TableExportSpec(
                "FactERLDCMarketEnergyDaily",
                "'ER:market-participant:' || entity.EntityName || ':market:day-energy'",
                "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID",
            ),
            TableExportSpec(
                "FactERLDCMarketExtremaDaily",
                "'ER:market-participant:' || entity.EntityName || ':market:extrema:' || fact.Mechanism",
                "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID",
                (("Mechanism", "fact.Mechanism"),),
            ),
        ),
    ),
    "nerldc": RLDCExportConfig(
        "nerldc", "nerldc", "nerldc_daily_psp", "NER", (
            TableExportSpec("FactNERLDCRegionalDaily", "'NER:region:' || region.RegionName", "JOIN DimRegions AS region ON region.RegionID = fact.RegionID"),
            TableExportSpec("FactNERLDCStateDaily", "'NER:state:' || state.StateName", "JOIN DimStates AS state ON state.StateID = fact.StateID"),
            TableExportSpec(
                "FactNERLDCGenerationDaily",
                "'NER:generation:' || entity.EntityName || ':section:' || fact.SectionName",
                "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID",
                (("SectionName", "fact.SectionName"),),
            ),
            TableExportSpec("FactNERLDCFrequencyDaily", "'NER:region:' || region.RegionName", "JOIN DimRegions AS region ON region.RegionID = fact.RegionID"),
            TableExportSpec(
                "FactNERLDCVoltageProfile",
                "'NER:voltage:' || node.NodeName",
                "JOIN DimVoltageNodes AS node ON node.VoltageNodeID = fact.VoltageNodeID",
                (),
                ("NominalVoltageKV",),
            ),
            TableExportSpec(
                "FactNERLDCReservoirDaily",
                "'NER:reservoir:' || reservoir.ReservoirName",
                "JOIN DimReservoirs AS reservoir ON reservoir.ReservoirID = fact.ReservoirID",
            ),
            TableExportSpec("FactNERLDCInterRegionalExchange", "'NER:line:' || element.ElementName", "JOIN DimTransmissionElements AS element ON element.ElementID = fact.ElementID"),
            TableExportSpec("FactNERLDCInternationalExchange", "'NER:country:' || country.CountryName", "JOIN DimCountries AS country ON country.CountryID = fact.CountryID"),
        ),
    ),
    "grid_india_national": RLDCExportConfig(
        "grid_india_national", "nldc", "nldc_daily_psp", "ALL", (
            TableExportSpec("FactNLDCDailyNational", "'NLDC:national'", ""),
            TableExportSpec("FactNLDCDailyRegional", "'NLDC:region:' || region.RegionName", "JOIN DimRegions AS region ON region.RegionID = fact.RegionID"),
            TableExportSpec("FactNLDCDailyFrequency", "'NLDC:frequency'", ""),
            TableExportSpec("FactNLDCDailyInterRegionalExchange", "'NLDC:line:' || element.ElementName", "JOIN DimTransmissionElements AS element ON element.ElementID = fact.ElementID"),
            TableExportSpec("FactNLDCDailyControlAreaDrawal", "'NLDC:control-area:' || entity.EntityName", "JOIN DimGridEntities AS entity ON entity.EntityID = fact.EntityID"),
            TableExportSpec(
                "FactNLDC15MinuteGridSnapshot",
                "'NLDC:all-india-grid'",
                "",
                excluded_numeric_columns=(),
                block_start_time_column="BlockStartTime",
            ),
            TableExportSpec(
                "FactNLDCCrossBorderExchangeDaily",
                "'NLDC:country:' || country.CountryName || ':cross-border:' || fact.Direction",
                "JOIN DimCountries AS country ON country.CountryID = fact.CountryID",
                (("Direction", "fact.Direction"),),
            ),
        ),
    ),
}


def export_registered_daily_observations(
    conn: sqlite3.Connection,
    rldc: str,
    report_document_id: int | None = None,
    *,
    ingested_at: datetime | None = None,
) -> list[FactObservation]:
    """Export one region through the declarative registry without changing defaults."""

    config = RLDC_EXPORT_CONFIG[rldc.lower()]
    recorded_at = ingested_at or datetime.now(timezone.utc)
    observations: list[FactObservation] = []
    for table in config.tables:
        observations.extend(
            _export_table(
                conn,
                table_name=table.table_name,
                entity_expression=table.entity_expression,
                joins=table.joins,
                lineage_expressions=table.lineage_expressions,
                excluded_numeric_columns=table.excluded_numeric_columns,
                block_start_time_column=table.block_start_time_column,
                report_document_id=report_document_id,
                ingested_at=recorded_at,
                source_id=config.source_id,
                metric_prefix=config.metric_prefix,
                report_type=config.report_type,
                source_region=config.source_region,
            )
        )
    return observations


def export_all_daily_observations(
    conn: sqlite3.Connection,
    rldcs: Iterable[str] | None = None,
    report_document_id: int | None = None,
    *,
    ingested_at: datetime | None = None,
) -> list[FactObservation]:
    """Export curated facts across specified or all supported RLDCs.

    Args:
        conn: SQLite connection with curated facts.
        rldcs: Optional collection of RLDC identifiers (e.g. ['srldc', 'erldc']).
            If None, exports across all 5 RLDCs present in the database.
        report_document_id: Optional specific report document ID filter.
        ingested_at: Optional timestamp override for system-time versioning.

    Returns:
        Consolidated list of FactObservation instances.
    """
    target_rldcs = (
        [r.lower() for r in rldcs]
        if rldcs is not None
        else list(RLDC_EXPORT_CONFIG.keys())
    )

    if rldcs is None:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'psp_report_document'"
        ).fetchone()
        if table_exists:
            present_rldcs = {
                row[0].lower()
                for row in conn.execute(
                    "SELECT DISTINCT rldc FROM psp_report_document WHERE rldc IS NOT NULL"
                ).fetchall()
            }
            filtered = [r for r in RLDC_EXPORT_CONFIG if r in present_rldcs]
            if filtered:
                target_rldcs = filtered

    all_observations: list[FactObservation] = []
    for rldc in target_rldcs:
        if rldc not in RLDC_EXPORT_CONFIG:
            continue
        try:
            obs = export_registered_daily_observations(
                conn,
                rldc,
                report_document_id=report_document_id,
                ingested_at=ingested_at,
            )
            all_observations.extend(obs)
        except Exception:
            continue
    return all_observations


def _export_table(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    entity_expression: str,
    joins: str,
    lineage_expressions: tuple[tuple[str, str], ...] = (),
    excluded_numeric_columns: tuple[str, ...] = (),
    block_start_time_column: str | None = None,
    report_document_id: int | None,
    ingested_at: datetime,
    source_id: str,
    metric_prefix: str,
    report_type: str,
    source_region: str,
) -> Iterable[FactObservation]:
    """Yield each non-null numeric fact column from one daily curated table."""

    numeric_columns = [
        column
        for column in _numeric_columns(conn, table_name)
        if column not in excluded_numeric_columns
    ]
    if not numeric_columns:
        return []
    predicates = ["document.rldc = ?"]
    parameters: list[object] = [source_id]
    if report_document_id is not None:
        predicates.append("fact.ReportDocumentID = ?")
        parameters.append(report_document_id)
    dimension_columns = _present_dimension_columns(conn, table_name)
    lineage_columns = [name for name, _ in lineage_expressions]
    selected_columns = [
        "fact.ReportDocumentID",
        _report_content_hash_expression(conn),
        "date.ActualDate",
        entity_expression,
        (
            f"fact.{block_start_time_column}"
            if block_start_time_column is not None
            else "NULL"
        ),
        *(f"fact.{column}" for column in dimension_columns),
        *(f"{expression} AS {name}" for name, expression in lineage_expressions),
        *(f"fact.{column}" for column in numeric_columns),
    ]
    rows = conn.execute(
        f"""
        SELECT {', '.join(selected_columns)}
        FROM {table_name} AS fact
        JOIN DimDates AS date ON date.DateID = fact.DateID
        JOIN psp_report_document AS document ON document.id = fact.ReportDocumentID
        {joins}
        WHERE {' AND '.join(predicates)}
        ORDER BY fact.ReportDocumentID
        """,
        parameters,
    ).fetchall()
    observations: list[FactObservation] = []
    for row in rows:
        report_id, content_hash, actual_date, entity_key, block_start_time, *remaining = row
        dimension_values = remaining[: len(dimension_columns)]
        lineage_values = remaining[
            len(dimension_columns) : len(dimension_columns) + len(lineage_columns)
        ]
        values = remaining[len(dimension_columns) + len(lineage_columns) :]
        destination_dimensions = dict(zip(dimension_columns, dimension_values, strict=True))
        destination_dimensions.update(
            zip(lineage_columns, lineage_values, strict=True)
        )
        valid_from = datetime.combine(
            datetime.fromisoformat(str(actual_date)).date(),
            time.min,
            tzinfo=timezone.utc,
        )
        time_block = None
        valid_to = None
        if block_start_time is not None:
            time_block = str(block_start_time)
            parsed_time = time.fromisoformat(time_block)
            valid_from = datetime.combine(
                datetime.fromisoformat(str(actual_date)).date(),
                parsed_time,
                tzinfo=timezone.utc,
            )
            valid_to = valid_from + timedelta(minutes=15)
        for column, value in zip(numeric_columns, values, strict=True):
            if value is None:
                continue
            metric_name = f"{metric_prefix}.{table_name}.{column}"
            metric_id = f"{table_name}.{column}"
            series_key = build_series_key(
                entity_key=str(entity_key),
                metric_name=metric_name,
                time_block=time_block,
                report_type=report_type,
                source_region=source_region,
                valid_from=valid_from.isoformat(),
                valid_to=valid_to.isoformat() if valid_to else None,
            )
            observations.append(
                FactObservation(
                    entity_key=str(entity_key),
                    metric_name=metric_name,
                    time_block=time_block,
                    operational_value=float(value),
                    settlement_value=None,
                    variance_pct=None,
                    report_type=report_type,
                    source_region=source_region,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    version_no=1,
                    ingested_at=ingested_at,
                    timeseries_uuid=build_revision_uuid(series_key, str(content_hash)),
                    series_key=series_key,
                    content_hash=str(content_hash),
                    report_document_id=int(report_id),
                    source_id=source_id,
                    destination_table=table_name,
                    destination_key=_resolve_destination_key(
                        conn,
                        report_document_id=int(report_id),
                        destination_table=table_name,
                        destination_column=column,
                        dimensions=destination_dimensions,
                    ),
                    destination_column=column,
                    metric_id=metric_id,
                )
            )
    return observations


def _report_content_hash_expression(conn: sqlite3.Connection) -> str:
    """Return a backwards-compatible artifact hash expression for SQLite exports."""

    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(psp_report_document)")
    }
    if "content_hash" in columns:
        return "COALESCE(document.content_hash, 'legacy:' || fact.ReportDocumentID)"
    return "'legacy:' || fact.ReportDocumentID"


def _present_dimension_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Return fact dimension columns that identify a promoted-row grain."""

    return [
        str(name)
        for _, name, _, _, _, _ in conn.execute(f"PRAGMA table_info({table_name})")
        if str(name) in _DIMENSION_COLUMNS and str(name) != "ReportDocumentID"
    ]


def _resolve_destination_key(
    conn: sqlite3.Connection,
    *,
    report_document_id: int,
    destination_table: str,
    destination_column: str,
    dimensions: dict[str, object],
) -> str | None:
    """Resolve one lineage key only when its fact dimensions identify it exactly."""

    candidates = conn.execute(
        """
        SELECT DISTINCT DestinationKey
        FROM curated_field_lineage
        WHERE ReportDocumentID = ?
          AND DestinationTable = ?
          AND DestinationColumn = ?
        """,
        (report_document_id, destination_table, destination_column),
    ).fetchall()
    matching = []
    for (candidate,) in candidates:
        tokens = _destination_key_tokens(str(candidate))
        if all(
            _destination_dimension_matches(tokens, key, value)
            for key, value in dimensions.items()
            if value is not None
        ):
            matching.append(str(candidate))
    return matching[0] if len(matching) == 1 else None


def _destination_key_tokens(destination_key: str) -> dict[str, str]:
    """Parse the stable semicolon-delimited keys emitted by curated promoters."""

    return {
        key.strip().lower(): value.strip()
        for part in destination_key.split(";")
        if "=" in part
        for key, value in [part.split("=", 1)]
    }


def _destination_dimension_matches(
    tokens: dict[str, str],
    column: str,
    value: object,
) -> bool:
    """Match dimensions to their established promoter-key spellings.

    Some dimensions such as generation source refine a fact grain but are not
    encoded in historical destination keys.  They are intentionally ignored;
    the caller still requires exactly one matching key before exporting lineage.
    """

    key_names = {
        "DateID": ("date",),
        "RegionID": ("region",),
        "StateID": ("state",),
        "EntityID": ("entity",),
        "StationID": ("station",),
        "GeneratingUnitID": ("unit",),
        "AggregateID": ("aggregate",),
        "ElementID": ("element",),
        "VoltageNodeID": ("node", "voltage_node"),
        "ReservoirID": ("reservoir",),
        "CountryID": ("country",),
        "SectionName": ("section",),
        "ExchangeCategory": ("category",),
        "Direction": ("direction",),
        "MechanismName": ("mechanism",),
        "TimeCategory": ("time",),
        "BlockStartTime": ("block",),
    }.get(column)
    if not key_names:
        return True
    present_keys = [key_name for key_name in key_names if key_name in tokens]
    if not present_keys:
        return True
    return any(tokens[key_name] == str(value) for key_name in present_keys)


def export_observation_lineage(
    conn: sqlite3.Connection,
    observations: Iterable[FactObservation],
) -> list[ObservationLineage]:
    """Project exact curated-cell lineage for exported observations.

    Facts with an unresolved destination key are deliberately omitted: assigning
    one raw cell to several similarly shaped fact rows would corrupt provenance.
    """

    if not _raw_lineage_tables_exist(conn):
        return []
    lineage: list[ObservationLineage] = []
    for observation in observations:
        if not all(
            (
                observation.report_document_id is not None,
                observation.destination_table,
                observation.destination_key,
                observation.destination_column,
                observation.source_id,
                observation.content_hash,
            )
        ):
            continue
        rows = conn.execute(
            """
            SELECT lineage.RawCellID, lineage.RawTextItemID, lineage.RawLineID,
                   lineage.Confidence, lineage.ExtractionMethod,
                   cell.page_no, cell.table_no, cell.row_no, cell.col_no,
                   text_item.page_no, raw_line.page_no
            FROM curated_field_lineage AS lineage
            LEFT JOIN psp_raw_cell AS cell ON cell.id = lineage.RawCellID
            LEFT JOIN psp_raw_text_item AS text_item ON text_item.id = lineage.RawTextItemID
            LEFT JOIN psp_raw_line AS raw_line ON raw_line.id = lineage.RawLineID
            WHERE lineage.ReportDocumentID = ?
              AND lineage.DestinationTable = ?
              AND lineage.DestinationKey = ?
              AND lineage.DestinationColumn = ?
            """,
            (
                observation.report_document_id,
                observation.destination_table,
                observation.destination_key,
                observation.destination_column,
            ),
        ).fetchall()
        for row in rows:
            raw_kind, raw_item_id, page_no, table_no, row_no, col_no = _raw_lineage_details(row)
            lineage_key = str(
                uuid5(
                    NAMESPACE_URL,
                    "|".join(
                        (
                            observation.timeseries_uuid,
                            raw_kind,
                            str(raw_item_id),
                            observation.destination_table,
                            observation.destination_key,
                            observation.destination_column,
                        )
                    ),
                )
            )
            lineage.append(
                ObservationLineage(
                    lineage_key=lineage_key,
                    timeseries_uuid=observation.timeseries_uuid,
                    source_id=observation.source_id,
                    report_document_id=observation.report_document_id,
                    content_hash=observation.content_hash,
                    destination_table=observation.destination_table,
                    destination_key=observation.destination_key,
                    destination_column=observation.destination_column,
                    raw_kind=raw_kind,
                    raw_item_id=raw_item_id,
                    page_no=page_no,
                    table_no=table_no,
                    row_no=row_no,
                    col_no=col_no,
                    confidence=float(row[3]),
                    extraction_method=str(row[4]),
                )
            )
    return lineage


def _raw_lineage_tables_exist(conn: sqlite3.Connection) -> bool:
    """Return whether raw source tables required by the bridge are available."""

    names = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    return {
        "curated_field_lineage",
        "psp_raw_cell",
        "psp_raw_text_item",
        "psp_raw_line",
    }.issubset(names)


def _raw_lineage_details(
    row: tuple[object, ...],
) -> tuple[str, int, int | None, int | None, int | None, int | None]:
    """Return one raw-item identity and optional spatial coordinates."""

    raw_cell_id, raw_text_item_id, raw_line_id = row[:3]
    if raw_cell_id is not None:
        return (
            "cell",
            int(raw_cell_id),
            int(row[5]) if row[5] is not None else None,
            int(row[6]) if row[6] is not None else None,
            int(row[7]) if row[7] is not None else None,
            int(row[8]) if row[8] is not None else None,
        )
    if raw_text_item_id is not None:
        return (
            "text_item",
            int(raw_text_item_id),
            int(row[9]) if row[9] is not None else None,
            None,
            None,
            None,
        )
    return (
        "line",
        int(raw_line_id),
        int(row[10]) if row[10] is not None else None,
        None,
        None,
        None,
    )


def _numeric_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Return numeric measure columns, excluding physical keys and dimensions."""

    return [
        str(name)
        for _, name, column_type, _, _, _ in conn.execute(
            f"PRAGMA table_info({table_name})"
        )
        if str(name) not in _DIMENSION_COLUMNS
        and str(column_type).upper() in {"REAL", "INTEGER"}
    ]
