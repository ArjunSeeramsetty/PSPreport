"""Inspect local SRLDC PDFs and report deterministic template clusters."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from psp_pipeline.schema_design.service import (
    build_template_inventory,
    cluster_template_inventory,
    select_monthly_anchor_paths,
    summarize_template_inventory,
)


def main() -> None:
    """Run read-only layout clustering over local SRLDC reports."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("downloads/SRLDC_PSP"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--mode",
        choices=("clusters", "inventory", "monthly-anchors"),
        default="clusters",
    )
    args = parser.parse_args()
    paths = sorted(args.input_dir.glob("*.pdf"))
    if args.limit is not None:
        paths = paths[: args.limit]
    if args.mode == "monthly-anchors":
        sampled = select_monthly_anchor_paths(paths)
        inventory = build_template_inventory([sample.pdf_path for sample in sampled])
        by_path = {record.pdf_path: record for record in inventory}
        payload = {
            "summary": summarize_template_inventory(inventory),
            "reports": [
                {
                    "month": sample.month_key,
                    "anchor": sample.anchor,
                    "report_name": sample.pdf_path.name,
                    "report_date": sample.report_date,
                    "exact_day_match": sample.exact_day_match,
                    "fingerprint": by_path[sample.pdf_path].fingerprint,
                    "structural_family": by_path[sample.pdf_path].structure.structural_family,
                    "page_count": by_path[sample.pdf_path].structure.page_count,
                    "table_count": by_path[sample.pdf_path].structure.table_count,
                    "template_id": by_path[sample.pdf_path].template_match.template_id,
                    "template_version": by_path[sample.pdf_path].template_match.template_version,
                    "template_confidence": by_path[sample.pdf_path].template_match.confidence,
                    "semantic_pass_required": by_path[sample.pdf_path].template_match.semantic_pass_required,
                    "reasons": list(by_path[sample.pdf_path].template_match.reasons),
                }
                for sample in sampled
            ],
        }
    else:
        inventory = build_template_inventory(paths)
        if args.mode == "inventory":
            payload = {
                "summary": summarize_template_inventory(inventory),
                "reports": [
                    {
                        "report_name": record.pdf_path.name,
                        "report_date": record.report_date,
                        "fingerprint": record.fingerprint,
                        "structural_family": record.structure.structural_family,
                        "page_count": record.structure.page_count,
                        "table_count": record.structure.table_count,
                        "template_id": record.template_match.template_id,
                        "template_version": record.template_match.template_version,
                        "template_confidence": record.template_match.confidence,
                        "semantic_pass_required": record.template_match.semantic_pass_required,
                        "reasons": list(record.template_match.reasons),
                    }
                    for record in inventory
                ],
            }
        else:
            clusters = cluster_template_inventory(inventory)
            payload = {
                "summary": summarize_template_inventory(inventory),
                "clusters": [
                    {
                        "fingerprint": cluster.fingerprint,
                        "report_count": len(cluster.report_paths),
                        "first_report": cluster.report_paths[0].name,
                        "last_report": cluster.report_paths[-1].name,
                        "representatives": [path.name for path in cluster.representative_paths],
                        "structural_family": cluster.structure.structural_family,
                        "page_count": cluster.structure.page_count,
                        "table_count": cluster.structure.table_count,
                        "matched_template_ids": list(cluster.matched_template_ids),
                        "semantic_pass_required_count": cluster.semantic_pass_required_count,
                    }
                    for cluster in clusters
                ],
            }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
