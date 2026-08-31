"""Report source-specific PSP promotion holds from a curated SQLite replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from psp_pipeline.quality.promotion_quarantine import summarize_promotion_quarantine


def main() -> int:
    """Emit a stable JSON summary of unresolved promotion prerequisites."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    summary = summarize_promotion_quarantine(args.db)
    payload = json.dumps(summary, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
