"""Iter150A-1 · TRUKVIA FinTxn backfill CLI.

Usage:
    # Dry-run against a specific tenant (default company for a user).
    python -m scripts.backfill_fintxn --dry-run --company-id <cid> --user-id <uid>

    # Real projection (delete-then-insert per source, idempotent).
    python -m scripts.backfill_fintxn --company-id <cid> --user-id <uid>

    # Verbose per-doc error reporting.
    python -m scripts.backfill_fintxn --company-id <cid> --user-id <uid> --verbose

Exits non-zero if any invariant mismatch is detected (safety valve).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow running via `python scripts/backfill_fintxn.py` (not just -m).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import db  # noqa: E402
from services_fin_txn import backfill_tenant, ensure_indexes  # noqa: E402


def _fmt(report: dict) -> str:
    return json.dumps(report, indent=2, default=str)


async def _resolve_uid(user_id: str, email: str) -> str:
    if user_id:
        return user_id
    if email:
        u = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
        if not u:
            raise SystemExit(f"user not found for email {email!r}")
        return u["user_id"]
    raise SystemExit("either --user-id or --email is required")


async def _resolve_cid(uid: str, company_id: str) -> str:
    if company_id:
        return company_id
    # Fall back to user's default company.
    c = await db.companies.find_one(
        {"user_id": uid, "is_default": True}, {"_id": 0, "id": 1})
    if c:
        return c["id"]
    any_c = await db.companies.find_one({"user_id": uid}, {"_id": 0, "id": 1})
    if any_c:
        return any_c["id"]
    raise SystemExit(f"no company found for user {uid!r}")


async def _amain(args: argparse.Namespace) -> int:
    await ensure_indexes()
    uid = await _resolve_uid(args.user_id, args.email)
    cid = await _resolve_cid(uid, args.company_id)
    if args.verbose:
        print(f"[backfill] user_id={uid} company_id={cid} dry_run={args.dry_run}")
    report = await backfill_tenant(
        uid, cid, dry_run=args.dry_run, verbose=args.verbose,
    )
    print(_fmt(report))
    mismatches = (report.get("invariants") or {}).get("mismatches") or []
    if mismatches and not args.dry_run:
        print("[backfill] INVARIANT MISMATCH — see report", file=sys.stderr)
        return 2
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Iter150A-1 FinTxn backfill CLI")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute projection counts without writing")
    parser.add_argument("--company-id", default="",
                        help="target company_id (defaults to user's default company)")
    parser.add_argument("--user-id", default="",
                        help="owner user_id (mutually optional with --email)")
    parser.add_argument("--email", default="",
                        help="owner email (looked up in db.users)")
    parser.add_argument("--verbose", action="store_true",
                        help="print per-doc error details")
    args = parser.parse_args()
    rc = asyncio.run(_amain(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
