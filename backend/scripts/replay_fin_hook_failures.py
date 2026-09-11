"""Iter150A-2 · Phase 1 — Replay CLI for fin_hook_failures.

Drains pending / retrying rows in `fin_hook_failures`. Optional
`--dry-run` reports what would be retried. `--company-id` scopes the
sweep to a single tenant. Failure records are NEVER silently deleted —
records past `MAX_RETRIES` remain in the DB with `status =
permanently_failed` for human investigation.

Usage:
  python -m scripts.replay_fin_hook_failures --dry-run --verbose
  python -m scripts.replay_fin_hook_failures --company-id <cid> --limit 500
  python -m scripts.replay_fin_hook_failures --ignore-schedule --verbose
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services_fin_txn_hooks import (                                 # noqa: E402
    ensure_hook_indexes,
    replay_pending_failures,
)


def _fmt(d: dict) -> str:
    return json.dumps(d, indent=2, default=str)


async def _amain(args: argparse.Namespace) -> int:
    await ensure_hook_indexes()
    report = await replay_pending_failures(
        user_id=args.user_id or None,
        company_id=args.company_id or None,
        limit=args.limit,
        dry_run=args.dry_run,
        ignore_schedule=args.ignore_schedule,
        verbose=args.verbose,
    )
    print(_fmt(report))
    # Non-zero exit if permanently_failed rows exist and we're not in dry-run.
    if report.get("permanently_failed") and not args.dry_run:
        return 2
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Iter150A-2 fin_hook_failures replay CLI")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would be retried, write nothing")
    p.add_argument("--company-id", default="",
                   help="scope sweep to a company_id")
    p.add_argument("--user-id", default="",
                   help="scope sweep to a user_id")
    p.add_argument("--limit", type=int, default=100,
                   help="max rows attempted per invocation (default 100)")
    p.add_argument("--ignore-schedule", action="store_true",
                   help="replay all non-terminal rows regardless of next_attempt_at")
    p.add_argument("--verbose", action="store_true",
                   help="include per-row detail in the JSON report")
    args = p.parse_args()
    rc = asyncio.run(_amain(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
