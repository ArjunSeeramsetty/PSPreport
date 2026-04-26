from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.core.settings import load_settings
from psp_pipeline.pipelines.bronze_pipeline import run_bronze


def main() -> None:
    configure_logging("INFO")
    settings = load_settings()
    result = run_bronze(settings, include_controlled=False)
    print(result)


if __name__ == "__main__":
    main()
