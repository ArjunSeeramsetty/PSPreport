from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.connectors.playwright_capture import capture_portal_snapshot
from psp_pipeline.core.logging import configure_logging
from psp_pipeline.core.settings import load_settings


def main() -> None:
    configure_logging("INFO")
    settings = load_settings()
    output = capture_portal_snapshot(
        url="https://newwbes.grid-india.in/",
        output_dir=Path("data/wbes_probe"),
        username=settings.wbes_username,
        password=settings.wbes_password,
    )
    print(output)


if __name__ == "__main__":
    main()
