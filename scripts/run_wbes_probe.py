from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.wbes.pipeline import probe_wbes_public
from psp_pipeline.wbes.settings import load_wbes_settings


def main() -> int:
    configure_logging("INFO")
    settings = load_wbes_settings(ROOT)
    if not settings.enabled:
        print(
            json.dumps(
                {
                    "status": "disabled",
                    "detail": "Set WBES_ENABLED=true to probe. Public PSP ingestion is unchanged.",
                }
            )
        )
        return 0
    summary = probe_wbes_public(settings)
    print(json.dumps(summary.as_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
