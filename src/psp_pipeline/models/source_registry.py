from __future__ import annotations

from typing import Iterable, List

from .contracts import SourceDefinition


def load_default_sources() -> List[SourceDefinition]:
    return [
        SourceDefinition(
            source_id="srldc_daily_reports",
            domain="RLDC",
            region="SR",
            report_family="daily_psp",
            url="https://www.srldc.in/Daily-Reports",
            fmt="html/pdf",
            cadence="daily",
        ),
        SourceDefinition(
            source_id="srldc_weekly_reports",
            domain="RLDC",
            region="SR",
            report_family="weekly_psp",
            url="https://www.srldc.in/Weekly-Reports",
            fmt="html/pdf",
            cadence="weekly",
        ),
        SourceDefinition(
            source_id="srldc_monthly_reports",
            domain="RLDC",
            region="SR",
            report_family="monthly_psp",
            url="https://www.srldc.in/Monthly-Reports",
            fmt="html/pdf",
            cadence="monthly",
        ),
        SourceDefinition(
            source_id="nrldc_portal",
            domain="RLDC",
            region="NR",
            report_family="daily_weekly_monthly_psp",
            url="https://www.nrldc.in/",
            fmt="html/pdf/xlsx",
            cadence="daily",
        ),
        SourceDefinition(
            source_id="nrldc_outage",
            domain="RLDC",
            region="NR",
            report_family="outage",
            url="https://oms.nrldc.in/outageReport/",
            fmt="html/xlsx",
            cadence="daily",
        ),
        SourceDefinition(
            source_id="nerldc_psp",
            domain="RLDC",
            region="NER",
            report_family="daily_weekly_monthly_psp",
            url="https://www.nerldc.in/power-supply-position-psp-report/",
            fmt="html/pdf",
            cadence="daily",
        ),
        SourceDefinition(
            source_id="wrl_dc_reports",
            domain="RLDC",
            region="WR",
            report_family="psp_tripping",
            url="https://www.wrldc.in/",
            fmt="html/pdf/xlsx",
            cadence="daily",
        ),
        SourceDefinition(
            source_id="wrl_dc_tripping",
            domain="RLDC",
            region="WR",
            report_family="tripping",
            url="https://portal.wrldc.in/Trippingnew/",
            fmt="html/xlsx",
            cadence="daily",
        ),
        SourceDefinition(
            source_id="erldc_js_portal",
            domain="RLDC",
            region="ER",
            report_family="psp_outage_constraints",
            url="https://erldc.in/",
            fmt="js/html/pdf/xlsx",
            cadence="daily",
        ),
        SourceDefinition(
            source_id="erpc_commercial",
            domain="RPC",
            region="ER",
            report_family="rea_dsm_reactive_as",
            url="https://erpc.gov.in/en/commercial/",
            fmt="html/pdf/xlsx",
            cadence="weekly_monthly",
        ),
        SourceDefinition(
            source_id="nrpc_commercial",
            domain="RPC",
            region="NR",
            report_family="rea_dsm",
            url="https://www.nrpc.gov.in/",
            fmt="html/pdf/xlsx",
            cadence="weekly_monthly",
        ),
        SourceDefinition(
            source_id="srpc_uploads",
            domain="RPC",
            region="SR",
            report_family="rea_dsm",
            url="https://www.srpc.kar.nic.in/html/recent_uploads.html",
            fmt="html/pdf/xlsx",
            cadence="weekly_monthly",
        ),
        SourceDefinition(
            source_id="wrpc_portal",
            domain="RPC",
            region="WR",
            report_family="rea_dsm_rta_rtda",
            url="https://www.wrpc.gov.in/",
            fmt="js/html/pdf/xlsx",
            cadence="weekly_monthly",
        ),
        SourceDefinition(
            source_id="nerpc_uploads",
            domain="RPC",
            region="NER",
            report_family="rea_dsm",
            url="https://nerpc.gov.in/",
            fmt="html/pdf/xlsx",
            cadence="weekly_monthly",
        ),
        SourceDefinition(
            source_id="grid_india_national",
            domain="NLDC",
            region="NATIONAL",
            report_family="daily_psp_interregional_ttc_atc",
            url="https://www.grid-india.in/",
            fmt="html/pdf/xlsx",
            cadence="daily_monthly",
        ),
        SourceDefinition(
            source_id="wbes_national",
            domain="WBES",
            region="ALL",
            report_family="15min_schedule_actual",
            url="https://newwbes.grid-india.in/",
            fmt="js/json/xlsx",
            cadence="15min_daily",
            access_mode="controlled",
            notes="Credential + possible IP allowlist required.",
        ),
    ]


def filter_sources(
    sources: Iterable[SourceDefinition],
    *,
    include_controlled: bool = False,
) -> List[SourceDefinition]:
    if include_controlled:
        return list(sources)
    return [s for s in sources if s.access_mode == "public"]

