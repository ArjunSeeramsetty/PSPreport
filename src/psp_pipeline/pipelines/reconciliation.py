from __future__ import annotations

from psp_pipeline.agents.recon_agent import ReconAgent


def compute_variance_pct(operational_value: float | None, settlement_value: float | None) -> float | None:
    return ReconAgent().run(
        operational_value=operational_value,
        settlement_value=settlement_value,
    )

