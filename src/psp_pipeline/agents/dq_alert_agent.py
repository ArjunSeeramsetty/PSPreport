from __future__ import annotations

from typing import Dict, List

from psp_pipeline.agents.base import BaseAgent


class DQAlertAgent(BaseAgent):
    def __init__(self):
        super().__init__("dq_alert_agent")

    def run(self, *, drift_result: Dict[str, List[str]], min_expected_sources: int, actual_sources: int) -> List[str]:
        alerts: List[str] = []
        if actual_sources < min_expected_sources:
            alerts.append(
                f"source_coverage_below_threshold expected={min_expected_sources} actual={actual_sources}"
            )
        if drift_result:
            alerts.append(f"schema_drift_candidates={list(drift_result.keys())}")
        for alert in alerts:
            self.logger.warning("DQ alert: %s", alert)
        return alerts

