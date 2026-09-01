"""Approve or reject a pending canonical identity issue from SQLite."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psp_pipeline.core.logging import configure_logging
from psp_pipeline.core.settings import load_settings
from psp_pipeline.pipelines.stages import (
    apply_canonical_identity_adjudication,
    audit_pending_identity_adjudications,
)


LOGGER = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    """Parse list or apply options for one identity decision."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--list-pending", action="store_true")
    parser.add_argument("--issue-id", type=int)
    parser.add_argument("--decision", choices=["approved", "rejected"])
    parser.add_argument("--entity-id")
    parser.add_argument("--entity-key")
    parser.add_argument("--decided-by", default="operator")
    parser.add_argument(
        "--publish-postgres",
        action="store_true",
        help="Republish identity and backfill current fact IDs after apply.",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    """List pending issues or apply one human approve/reject decision."""

    configure_logging("INFO")
    args = _parse_args()
    if args.list_pending:
        payload = audit_pending_identity_adjudications(args.db)
    else:
        if args.issue_id is None or args.decision is None:
            LOGGER.error("apply requires --issue-id and --decision")
            return 2
        settings = load_settings()
        payload = apply_canonical_identity_adjudication(
            args.db,
            issue_id=args.issue_id,
            decision=args.decision,
            decided_by=args.decided_by,
            entity_id=args.entity_id,
            observation_entity_key=args.entity_key,
            postgres_dsn=settings.postgres_dsn if args.publish_postgres else None,
        )
    serialized = json.dumps(payload, indent=2, sort_keys=True, default=str)
    LOGGER.info("canonical_identity_adjudication_cli result=%s", payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
