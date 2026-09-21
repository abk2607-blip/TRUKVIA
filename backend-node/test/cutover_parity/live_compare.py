"""Phase 4 · cutover parity check — live Python vs live Node over the FROZEN allowlist,
against whatever database both servers are already pointed at (real data, not fixtures).

Why this exists
---------------
The gate harnesses (gate3..gate9e) seed their own deterministic fixtures and compare
responses BYTE-exactly. Run against real production-shaped data, one documented
difference appears on every route that returns a whole-number BSON double:

    Python  "opening_balance":0.0        (pymongo keeps double vs int32 distinct)
    Node    "opening_balance":0          (the driver promotes both to a JS number,
                                          so JSON.stringify cannot tell them apart)

Non-integral floats are identical (`24.539334` both sides), the parsed values are equal,
and no client can observe the difference. It is therefore NOT a cutover blocker, but it
does mean "byte-identical" is the wrong pass criterion on real data.

This checker's contract:
  FAIL  - status codes differ, bodies parse to different JSON, or a body is not JSON
  WARN  - bodies differ in bytes only, and parse equal (the float-format case above)
  PASS  - byte-identical

Usage
-----
    python backend-node/test/cutover_parity/live_compare.py
      --py http://127.0.0.1:8001 --node http://127.0.0.1:8002
      --mongo mongodb://127.0.0.1:27017 --db <database> --token <session token>

The token must be a session that exists in that database. Routes whose path parameters
cannot be filled from the data are reported as SKIP, never as PASS.
Read-only: issues GET requests only and reads ids from Mongo. Exit code 1 on any FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from pymongo import MongoClient

ALLOWLIST = Path(__file__).resolve().parents[2] / ".migration-allowlist"

# route segment preceding a path parameter -> collection that holds those ids
SEGMENT_COLLECTION = {
    "supplier-payments": "supplier_payments", "invoices": "invoices",
    "credit-notes": "credit_debit_notes", "debit-notes": "credit_debit_notes",
    "customers": "customers", "suppliers": "suppliers", "expenses": "expenses",
    "vendors": "vendors", "mechanics": "mechanics", "mechanic-payments": "mechanic_payments",
    "vendor-payments": "vendor_payments", "driver-payments": "driver_payments",
    "templates": "templates", "repair-events": "repair_events",
    "mechanic-work-orders": "mechanic_work_orders", "vendor-bills": "vendor_bills",
    "drivers": "drivers", "approvals": "approvals", "fin-txn": "fin_txn",
    "vehicles": "vehicles", "sessions": "chat_sessions",
}


def routes() -> list[str]:
    return [r.strip() for r in ALLOWLIST.read_text(encoding="utf-8").splitlines()
            if r.strip() and not r.lstrip().startswith("#")]


def fill(route: str, db, user_id: str | None) -> str | None:
    """Substitute real ids for :params. None when the data cannot supply one."""
    parts = route.split("/")
    url = route
    for i, part in enumerate(parts):
        if not part.startswith(":"):
            continue
        if part == ":close_date":
            doc = db.fin_day_closures.find_one({}, {"_id": 0, "close_date": 1})
            value = (doc or {}).get("close_date")
        else:
            coll = SEGMENT_COLLECTION.get(parts[i - 1], parts[i - 1].replace("-", "_"))
            scoped = {"user_id": user_id} if user_id else {}
            doc = db[coll].find_one(scoped, {"_id": 0, "id": 1}) or db[coll].find_one({}, {"_id": 0, "id": 1})
            value = (doc or {}).get("id")
        if not value:
            return None
        url = url.replace(part, str(value), 1)
    return url


def classify(a: httpx.Response, b: httpx.Response) -> tuple[str, str]:
    if a.status_code != b.status_code:
        return "FAIL", f"status py={a.status_code} node={b.status_code}"
    if a.content == b.content:
        return "PASS", f"{a.status_code} {len(a.content)}B"
    try:
        ja, jb = a.json(), b.json()
    except ValueError:
        return "FAIL", f"{a.status_code} body differs and is not JSON"
    if ja != jb:
        return "FAIL", f"{a.status_code} parsed JSON differs ({len(a.content)} vs {len(b.content)}B)"
    return "WARN", f"{a.status_code} bytes {len(a.content)} vs {len(b.content)} (parses equal)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--py", default="http://127.0.0.1:8001")
    ap.add_argument("--node", default="http://127.0.0.1:8002")
    ap.add_argument("--mongo", default="mongodb://127.0.0.1:27017")
    ap.add_argument("--db", required=True)
    ap.add_argument("--token", required=True, help="session_token present in --db")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    db = MongoClient(args.mongo)[args.db]
    session = db.user_sessions.find_one({"session_token": args.token}, {"_id": 0, "user_id": 1})
    if not session:
        print(f"no session for that token in {args.db}", file=sys.stderr)
        return 2
    user_id = session.get("user_id")
    headers = {"Authorization": f"Bearer {args.token}"}

    results: list[tuple[str, str, str]] = []
    for route in routes():
        url = fill(route, db, user_id)
        if url is None:
            results.append((route, "SKIP", "no data to fill path parameters"))
            continue
        try:
            a = httpx.get(args.py + url, headers=headers, timeout=args.timeout)
            b = httpx.get(args.node + url, headers=headers, timeout=args.timeout)
        except Exception as exc:  # network/timeout is a real problem, not a skip
            results.append((route, "FAIL", f"{type(exc).__name__}: {exc}"))
            continue
        verdict, detail = classify(a, b)
        results.append((route, verdict, detail))

    counts = {k: sum(1 for _, v, _ in results if v == k) for k in ("PASS", "WARN", "FAIL", "SKIP")}
    for kind in ("FAIL", "WARN", "SKIP", "PASS"):
        rows = [r for r in results if r[1] == kind]
        if not rows:
            continue
        print(f"\n== {kind} ({len(rows)})")
        for route, _, detail in rows:
            print(f"   {route:48} {detail}")

    print(f"\nallowlist routes: {len(results)}   "
          f"PASS {counts['PASS']}   WARN {counts['WARN']}   FAIL {counts['FAIL']}   SKIP {counts['SKIP']}")
    print("criterion: status equal AND parsed JSON equal. Byte differences that parse equal are WARN "
          "(documented whole-number double rendering: Python 0.0 vs Node 0).")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
