"""CLI wrapper to run the ERLDC corpus inventory and export a diagnostic summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.quality.erldc_corpus_inventory import (
    audit_erldc_anchor_templates,
    build_erldc_corpus_inventory,
)


def main() -> None:
    """Run ERLDC corpus inventory and save a structured JSON summary."""
    parser = argparse.ArgumentParser(description="ERLDC corpus inventory runner.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "downloads" / "ERLDC_PSP",
        help="Directory containing downloaded ERLDC PSP PDFs.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "erldc_corpus_inventory.json",
        help="Output destination for JSON summary.",
    )
    parser.add_argument(
        "--audit-templates",
        action="store_true",
        help="Run template structure and matching audit across anchor reports.",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "erldc_template_audit.json",
        help="Output destination for template audit JSON summary.",
    )
    args = parser.parse_args()

    configure_logging("INFO")
    summary = build_erldc_corpus_inventory(args.input_dir)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
    print(
        f"ERLDC Inventory completed: {summary.valid_psp_count}/{summary.anchor_sample_count} "
        f"valid anchors from {summary.total_pdf_count} PDFs. Written to {args.summary}"
    )

    if args.audit_templates:
        audit_result = audit_erldc_anchor_templates(summary)
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.write_text(json.dumps(audit_result, indent=2), encoding="utf-8")
        print(f"ERLDC Template audit completed and written to {args.audit_output}")


if __name__ == "__main__":
    main()
