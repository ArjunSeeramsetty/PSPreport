"""CLI wrapper to run the Grid-India NLDC corpus inventory and export a diagnostic summary."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.quality.nldc_corpus_inventory import build_nldc_corpus_inventory

LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Run NLDC corpus inventory and save a structured JSON summary."""
    parser = argparse.ArgumentParser(description="Grid-India NLDC corpus inventory runner.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "downloads" / "NLDC_PSP",
        help="Directory containing downloaded NLDC PSP PDFs.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "nldc_corpus_inventory.json",
        help="Output destination for JSON summary.",
    )
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Validate every local PDF instead of monthly anchor samples only.",
    )
    args = parser.parse_args()

    configure_logging("INFO")
    summary = build_nldc_corpus_inventory(
        args.input_dir,
        anchor_sample_only=not args.all_files,
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
    LOGGER.info(
        "nldc_inventory_complete valid=%d total_evaluated=%d total_files=%d output=%s",
        summary.valid_psp_count,
        summary.anchor_sample_count,
        summary.total_pdf_count,
        args.summary,
    )


if __name__ == "__main__":
    main()
