"""Small JSON manifests exchanged between Airflow pipeline tasks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_stage_payload(
    project_root: Path,
    run_id: str,
    stage_name: str,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Persist a stage payload and return a compact XCom-safe reference."""

    directory = project_root / "data" / "airflow_staging" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stage_name}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
    return {"run_id": run_id, "path": str(path)}


def read_stage_payload(reference: dict[str, str]) -> dict[str, Any]:
    """Load a stage payload previously written by ``write_stage_payload``."""

    path = Path(reference["path"])
    return json.loads(path.read_text(encoding="utf-8"))
