"""CLI wrapper to run the WRLDC corpus inventory and export a diagnostic summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.quality.wrldc_corpus_inventory import (
    audit_wrldc_anchor_templates,
    build_wrldc_corpus_inventory,
)


def main() -> None:
    """Run WRLDC corpus inventory and save a structured JSON summary."""
    parser = argparse.ArgumentParser(description="WRLDC corpus inventory runner.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "downloads" / "WRLDC_PSP",
        help="Directory containing downloaded WRLDC PSP PDFs.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "data" / "diagnostics" / "wrldc_corpus_inventory.json",
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
        default=ROOT / "data" / "diagnostics" / "wrldc_template_audit.json",
        help="Output destination for template audit JSON summary.",
    )
    args = parser.parse_args()

    configure_logging("INFO")
    summary = build_wrldc_corpus_inventory(args.input_dir)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
    print(
        f"WRLDC Inventory completed: {summary.valid_psp_count}/{summary.anchor_sample_count} "
        f"valid anchors from {summary.total_pdf_count} PDFs. Written to {args.summary}"
    )

    if args.audit_templates:
        audit_result = audit_wrldc_anchor_templates(args.input_dir)
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.write_text(json.dumps(audit_result, indent=2), encoding="utf-8")
        print(
            f"WRLDC Template Audit completed: {audit_result['matched_count']}/{audit_result['total_anchors']} "
            f"matched, {audit_result['semantic_review_count']} review required. Written to {args.audit_output}"
        )


if __name__ == "__main__":
    main()
