from __future__ import annotations

from psp_pipeline.agents.base import BaseAgent


class ReconAgent(BaseAgent):
    def __init__(self):
        super().__init__("recon_agent")

    def run(
        self,
        *,
        operational_value: float | None,
        settlement_value: float | None,
    ) -> float | None:
        if operational_value is None or settlement_value is None:
            return None
        if settlement_value == 0:
            return None
        return ((operational_value - settlement_value) / settlement_value) * 100.0

