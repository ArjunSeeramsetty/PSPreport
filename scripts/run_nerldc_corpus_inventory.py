"""CLI script to scan and inventory local NERLDC PSP PDFs across monthly anchors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.quality.nerldc_corpus_inventory import run_nerldc_corpus_inventory


def main() -> None:
    """Run NERLDC local corpus inventory and print a human-readable summary."""

    parser = argparse.ArgumentParser(
        description="Scan local NERLDC PSP reports and validate 114 monthly anchors."
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=ROOT / "downloads" / "NERLDC_PSP",
        help="Directory containing local NERLDC PSP PDFs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "nerldc_corpus_inventory.json",
        help="Destination path for inventory summary JSON.",
    )
    args = parser.parse_args()

    if not args.corpus_dir.exists():
        print(f"Error: Corpus directory not found: {args.corpus_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning NERLDC corpus in: {args.corpus_dir}")
    summary = run_nerldc_corpus_inventory(args.corpus_dir, output_path=args.output)

    print("\n--- NERLDC Corpus Inventory Summary ---")
    print(f"Total Local PDFs Found:   {summary['total_pdf_count']}")
    print(f"Monthly Anchors Sampled:  {summary['anchor_sample_count']}")
    print(f"Valid Authentic PSPs:     {summary['valid_psp_count']}")
    print(f"Invalid / Corrupt PDFs:   {summary['invalid_count']}")
    print(f"Page Count Distribution:  {summary['page_count_distribution']}")
    print(f"Page Count Transitions:   {len(summary['page_count_transitions'])}")
    for t in summary["page_count_transitions"]:
        print(f"  - {t['transition_date']}: {t['from_page_count']} pages -> {t['to_page_count']} pages ({t['filename']})")

    print(f"\nDetailed diagnostic written to: {args.output}")


if __name__ == "__main__":
    main()
