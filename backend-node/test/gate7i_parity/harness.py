"""Phase 3 · Gate 7i · live Python↔Node parity harness for Files list read.

Covers:
  * GET /api/files

STRICT UAT-DATA PRESERVATION:
  Isolated timestamped DB `trukvia_gate7i_parity_<ts>`, dropped in
  `finally`. Never touches `test_database` or any TRUKVIA UAT tenant.

Class-C stance:
  Pure-read in Python. Handler executes ONLY
    db.files.find(q, {_id: 0, user_id: 0}).sort("created_at", -1).to_list(500)
  Zero writer hook / audit / backfill / recompute / FinTxn / counters /
  idempotency / cross-collection reads. No object-store call on this
  GET path.

CRITICAL parity axis for Gate 7i:
  USER-ONLY scope. Base filter is
    {"user_id": uid, "is_deleted": False}
  There is NO `company_id` predicate. Same-user rows across different
  company_id values MUST remain visible; cross-user rows excluded.
"""
from __future__ import annotations
import asyncio, json, os, signal, subprocess, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import requests
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7i_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8224, 8225
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _fr(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "user_id": "u1", "is_deleted": False,
        "category": "general", "linked_type": "", "linked_id": "",
        "storage_path": "bitumen-accounting/uploads/u1/aaa.jpg",
        "original_filename": "aaa.jpg", "content_type": "image/jpeg",
        "size": 12345,
    }
    base.update(kw)
    return base


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    return {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u3",      "user_id": "u3", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner", "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now},
            {"user_id": "u2", "email": "u2@x", "name": "U2", "picture": "", "created_at": now},
            {"user_id": "u3", "email": "u3@x", "name": "U3", "picture": "", "created_at": now},
        ],
        "companies": [
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme Co"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta Co"},
        ],
        "files": [
            # u1 rows across different company_id values — MUST remain visible
            _fr(id="f1", created_at="2026-01-01T10:00:00+00:00", category="general"),
            _fr(id="f2", created_at="2026-01-02T10:00:00+00:00", category="invoice",
                 linked_type="invoice", linked_id="inv-9"),
            _fr(id="f3", created_at="2026-01-03T10:00:00+00:00", category="vehicle",
                 linked_type="vehicle", linked_id="v-7", company_id="co-a"),
            _fr(id="f-alt", created_at="2026-01-04T10:00:00+00:00",
                 category="general", company_id="co-a-alt"),
            _fr(id="f-nocid", created_at="2026-01-05T10:00:00+00:00", category="general"),
            # Deleted — MUST be excluded
            _fr(id="f-del", created_at="2026-01-06T10:00:00+00:00", is_deleted=True),
            # Missing is_deleted field — Python exact-equality EXCLUDES
            {"user_id": "u1", "id": "f-nodel", "created_at": "2026-01-07T10:00:00+00:00",
             "category": "general", "storage_path": "x", "original_filename": "x",
             "content_type": "image/png", "size": 1},
            # Cross-user
            _fr(id="f-u2-1", user_id="u2", company_id="co-b",
                 created_at="2026-01-08T10:00:00+00:00", category="general"),
            _fr(id="f-u2-2", user_id="u2", company_id="co-b",
                 created_at="2026-01-09T10:00:00+00:00", category="invoice",
                 linked_type="invoice", linked_id="inv-U2"),
        ],
    }


TRACKED = ("users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "approval_revisions",
           "approval_audits", "counters",
           "fin_hook_failures", "vendors", "mechanics",
           "company_bank_accounts", "party_bank_accounts",
           "supplier_payments", "vendor_payments", "mechanic_payments",
           "driver_payments", "driver_payment_corrections", "templates",
           "repair_events", "mechanic_work_orders", "vendor_bills",
           "wallet_adjustments", "wallet_transfers", "wallet_recharges",
           "policy_change_events", "fuel_vehicle_maps", "files")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    for coll, rows in fixtures().items():
        if rows:
            await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        try:
            docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(2000)
        except Exception:
            docs = []
        for d in docs:
            for k, v in list(d.items()):
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
        docs.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
        out[c] = docs
    return out


def diff_snap(a, b):
    d = {}
    for c in a:
        if json.dumps(a[c], sort_keys=True, default=str) != json.dumps(b[c], sort_keys=True, default=str):
            d[c] = {"before_n": len(a[c]), "after_n": len(b[c])}
    return d


def start_py():
    env = os.environ.copy()
    env.update({"MONGO_URL": MONGO, "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0",
                "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0", "PYTHONUNBUFFERED": "1"})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env,
        stdout=open("/tmp/gate7i_py.log", "wb"), stderr=subprocess.STDOUT,
    )


def start_node():
    env = os.environ.copy()
    env.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent",
                "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                "NODE_MONGO_URL": MONGO, "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                "NODE_REQUEST_ID_HEADER": "x-request-id",
                "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
    return subprocess.Popen(
        ["node", str(REPO / "backend-node/dist/server.js")],
        cwd=str(REPO / "backend-node"), env=env,
        stdout=open("/tmp/gate7i_node.log", "wb"), stderr=subprocess.STDOUT,
    )


def wait(url, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(url, timeout=1).status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def stop(p):
    if p and hasattr(p, "poll") and p.poll() is None:
        try:
            p.send_signal(signal.SIGTERM); p.wait(timeout=5)
        except Exception:
            try: p.kill()
            except Exception: pass


HDR = {
    "u1":      {"Authorization": "Bearer tok-u1"},
    "u2":      {"Authorization": "Bearer tok-u2"},
    "u3":      {"Authorization": "Bearer tok-u3"},
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad":     {"Authorization": "Bearer nope"},
    "none":    {},
}


CASES: list[dict[str, Any]] = [
    # Auth
    {"n":  1, "d": "no bearer → 401 Not authenticated",
     "url": "/api/files", "hk": "none", "expect": 401, "compare": "full"},
    {"n":  2, "d": "invalid bearer → 401 Invalid session",
     "url": "/api/files", "hk": "bad", "expect": 401, "compare": "full"},
    {"n":  3, "d": "expired bearer → 401 Session expired",
     "url": "/api/files", "hk": "expired", "expect": 401, "compare": "full"},

    # USER-ONLY scope (critical Gate 7i axis) — same u1 across companies
    {"n":  4, "d": "no query — all u1 non-deleted rows across mixed company_id DESC",
     "url": "/api/files", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  5, "d": "X-Company-Id co-a-alt MUST NOT narrow — same as no header",
     "url": "/api/files", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n":  6, "d": "X-Company-Id co-b (unowned) MUST NOT narrow — same as no header",
     "url": "/api/files", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},

    # Cross-user isolation
    {"n":  7, "d": "cross-user u2 default → only u2 rows DESC",
     "url": "/api/files", "hk": "u2", "expect": 200, "compare": "full"},

    # Deleted semantics (exact {is_deleted: False})
    {"n":  8, "d": "is_deleted=true excluded (f-del)",
     "url": "/api/files", "hk": "u1", "expect": 200, "compare": "full",
     "note": "captured in default case 4 too — this case re-asserts by hash"},

    # category filter
    {"n":  9, "d": "category=general → f-alt, f-nocid, f1 DESC",
     "url": "/api/files?category=general", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 10, "d": "category=invoice → only f2",
     "url": "/api/files?category=invoice", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 11, "d": "category=General (uppercase) → [] (case-sensitive)",
     "url": "/api/files?category=General", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 12, "d": "category=nonexistent → []",
     "url": "/api/files?category=nonexistent", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 13, "d": "blank category → predicate dropped → full default set",
     "url": "/api/files?category=", "hk": "u1", "expect": 200, "compare": "full"},

    # linked_type / linked_id
    {"n": 14, "d": "linked_type=invoice → only f2",
     "url": "/api/files?linked_type=invoice", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 15, "d": "linked_id=v-7 → only f3",
     "url": "/api/files?linked_id=v-7", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 16, "d": "blank linked_type → predicate dropped",
     "url": "/api/files?linked_type=", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 17, "d": "blank linked_id → predicate dropped",
     "url": "/api/files?linked_id=", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 18, "d": "unknown linked_type → []",
     "url": "/api/files?linked_type=xyz", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 19, "d": "unknown linked_id → []",
     "url": "/api/files?linked_id=zzz", "hk": "u1", "expect": 200, "compare": "full"},

    # Combined
    {"n": 20, "d": "category=invoice + linked_type=invoice + linked_id=inv-9 → f2",
     "url": "/api/files?category=invoice&linked_type=invoice&linked_id=inv-9", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 21, "d": "conflicting combo → []",
     "url": "/api/files?category=invoice&linked_id=nope", "hk": "u1", "expect": 200, "compare": "full"},

    # Empty user
    {"n": 22, "d": "u3 (no files) → 200 []",
     "url": "/api/files", "hk": "u3", "expect": 200, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate7i] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate7i] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate7i] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate7i_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate7i_node.log").read()[-2000:])
            return 2

        results = []
        pass_count = fail_count = node_write_events = 0
        for c in CASES:
            hdr = dict(HDR[c["hk"]])
            hdr.update(c.get("extra_hdr", {}))
            _ = await snap(cli, DB)
            rp = requests.get(PY_BASE + c["url"], headers=hdr, timeout=10)
            after_py = await snap(cli, DB)
            rn = requests.get(NODE_BASE + c["url"], headers=hdr, timeout=10)
            after_nd = await snap(cli, DB)
            nd_diff = diff_snap(after_py, after_nd)
            if nd_diff: node_write_events += 1

            status_ok = (rp.status_code == rn.status_code == c["expect"])
            try: pjson = rp.json()
            except Exception: pjson = rp.text
            try: njson = rn.json()
            except Exception: njson = rn.text
            body_ok, body_err = compare_bodies(c["compare"], pjson, njson)
            ok = status_ok and body_ok
            if ok: pass_count += 1
            else: fail_count += 1
            results.append({
                "case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                "py_status": rp.status_code, "node_status": rn.status_code,
                "status_ok": status_ok, "body_ok": body_ok, "body_err": body_err,
                "node_write_colls": list(nd_diff.keys()),
                "py_body": rp.text[:1200] if not body_ok else "",
                "node_body": rn.text[:1200] if not body_ok else "",
            })

        results.append({
            "case": len(CASES) + 1,
            "desc": "read-only — Node write events across all cases",
            "verdict": "PASS" if node_write_events == 0 else "FAIL",
            "node_write_events": node_write_events,
        })
        if node_write_events == 0: pass_count += 1
        else: fail_count += 1

        print("\n" + "=" * 72)
        print("PHASE 3 · GATE 7i · LIVE PARITY MATRIX (Files list · USER-SCOPED)")
        print("=" * 72)
        for r in results:
            py_s = r.get("py_status", "-"); nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
            if r["verdict"] == "FAIL":
                if r.get("body_err"): print(f"      body_err: {r['body_err']}")
                print(f"      py_body : {r.get('py_body', '')}")
                print(f"      node_body: {r.get('node_body', '')}")
        print("-" * 72)
        print(f"  cases: {len(results)}   passed: {pass_count}   failed: {fail_count}   node write events: {node_write_events}")
        print("=" * 72)

        out = Path("/tmp/gate7i_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate7i] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate7i] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7i] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
