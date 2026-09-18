"""Phase 3 · Gate 7l · live Python↔Node parity harness for Approval detail read.

Covers:
  * GET /api/approvals/{aid}

Class-C stance:
  Pure-read in Python. Handler executes at most three
    db.approvals.find_one({id, user_id, company_id}, {_id:0})
    db.approval_revisions.find({approval_id, user_id, company_id}, {_id:0})
      .sort("revision_index", 1).to_list(200)
    db.approval_audits.find({approval_id, user_id, company_id}, {_id:0})
      .sort("at", 1).to_list(500)
  Zero writes / audits / backfill / recompute / hooks.

Projection axis: strips ONLY `_id` — user_id PRESERVED across all three
collections (contrast Gates 7a–7f which also stripped user_id).
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
DB = f"trukvia_gate7l_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8230, 8231
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    return {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner", "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner", "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now},
            {"user_id": "u2", "email": "u2@x", "name": "U2", "picture": "", "created_at": now},
        ],
        "companies": [
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme Co"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta Co"},
        ],
        "approvals": [
            {"id": "apr-1", "user_id": "u1", "company_id": "co-a", "status": "PENDING_APPROVAL",
             "entity_kind": "invoice", "entity_id": "inv-1", "created_at": "2026-01-01T10:00:00+00:00"},
            {"id": "apr-2", "user_id": "u1", "company_id": "co-a", "status": "APPROVED",
             "entity_kind": "trip", "entity_id": "trip-1", "created_at": "2026-01-02T10:00:00+00:00"},
            {"id": "apr-alt", "user_id": "u1", "company_id": "co-a-alt", "status": "PENDING_APPROVAL",
             "entity_kind": "invoice", "entity_id": "inv-alt", "created_at": "2026-01-03T10:00:00+00:00"},
            {"id": "apr-u2", "user_id": "u2", "company_id": "co-b", "status": "PENDING_APPROVAL",
             "entity_kind": "invoice", "entity_id": "inv-U2", "created_at": "2026-01-04T10:00:00+00:00"},
        ],
        "approval_revisions": [
            {"approval_id": "apr-1", "user_id": "u1", "company_id": "co-a", "revision_index": 2, "payload": {"note": "v2"}},
            {"approval_id": "apr-1", "user_id": "u1", "company_id": "co-a", "revision_index": 1, "payload": {"note": "v1"}},
            {"approval_id": "apr-1", "user_id": "u1", "company_id": "co-a", "revision_index": 3, "payload": {"note": "v3"}},
            {"approval_id": "apr-2", "user_id": "u1", "company_id": "co-a", "revision_index": 1, "payload": {"note": "t1"}},
            # wrong-user leak fixture — must NOT surface in u1's detail
            {"approval_id": "apr-1", "user_id": "u2", "company_id": "co-b", "revision_index": 99, "payload": {"note": "leak"}},
        ],
        "approval_audits": [
            {"approval_id": "apr-1", "user_id": "u1", "company_id": "co-a", "at": "2026-01-01T11:00:00+00:00", "action": "created"},
            {"approval_id": "apr-1", "user_id": "u1", "company_id": "co-a", "at": "2026-01-01T10:30:00+00:00", "action": "submitted"},
            {"approval_id": "apr-1", "user_id": "u1", "company_id": "co-a", "at": "2026-01-01T12:00:00+00:00", "action": "notified"},
            {"approval_id": "apr-1", "user_id": "u2", "company_id": "co-b", "at": "2026-01-01T09:00:00+00:00", "action": "leak"},
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
        stdout=open("/tmp/gate7l_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate7l_node.log", "wb"), stderr=subprocess.STDOUT,
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
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad":     {"Authorization": "Bearer nope"},
    "none":    {},
}


CASES: list[dict[str, Any]] = [
    # Auth
    {"n":  1, "d": "no bearer → 401 Not authenticated",
     "url": "/api/approvals/apr-1", "hk": "none", "expect": 401},
    {"n":  2, "d": "invalid bearer → 401 Invalid session",
     "url": "/api/approvals/apr-1", "hk": "bad", "expect": 401},
    {"n":  3, "d": "expired bearer → 401 Session expired",
     "url": "/api/approvals/apr-1", "hk": "expired", "expect": 401},

    # Primary hit — full wrapper deep-equal
    {"n":  4, "d": "u1 apr-1 → wrapper {approval, revisions, audits}",
     "url": "/api/approvals/apr-1", "hk": "u1", "expect": 200},
    {"n":  5, "d": "u1 apr-2 → 1 revision, 0 audits",
     "url": "/api/approvals/apr-2", "hk": "u1", "expect": 200},

    # 404 verbatim
    {"n":  6, "d": "nonexistent aid → 404 Approval not found",
     "url": "/api/approvals/no-such-aid", "hk": "u1", "expect": 404},

    # Isolation
    {"n":  7, "d": "cross-user u2 requesting u1 apr-1 → 404",
     "url": "/api/approvals/apr-1", "hk": "u2", "expect": 404},
    {"n":  8, "d": "u1 default co-a cannot see co-a-alt apr-alt → 404",
     "url": "/api/approvals/apr-alt", "hk": "u1", "expect": 404},
    {"n":  9, "d": "owned X-Company-Id co-a-alt → apr-alt visible",
     "url": "/api/approvals/apr-alt", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200},
    {"n": 10, "d": "unowned X-Company-Id co-b → fallback co-a → apr-1 visible",
     "url": "/api/approvals/apr-1", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200},

    # Static-route precedence (must NOT collide with 7f /summary/pending)
    {"n": 11, "d": "aid='summary' → 404 (not intercepted by /summary/pending)",
     "url": "/api/approvals/summary", "hk": "u1", "expect": 404},
    {"n": 12, "d": "u2 apr-u2 → own approval visible",
     "url": "/api/approvals/apr-u2", "hk": "u2", "expect": 200},
]


async def run() -> int:
    print(f"[gate7l] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate7l] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate7l] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate7l_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate7l_node.log").read()[-2000:])
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
            body_ok = (pjson == njson)
            ok = status_ok and body_ok
            if ok: pass_count += 1
            else: fail_count += 1
            results.append({
                "case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                "py_status": rp.status_code, "node_status": rn.status_code,
                "status_ok": status_ok, "body_ok": body_ok,
                "node_write_colls": list(nd_diff.keys()),
                "py_body": rp.text[:2000] if not body_ok else "",
                "node_body": rn.text[:2000] if not body_ok else "",
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
        print("PHASE 3 · GATE 7l · LIVE PARITY MATRIX (Approval detail)")
        print("=" * 72)
        for r in results:
            py_s = r.get("py_status", "-"); nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
            if r["verdict"] == "FAIL":
                print(f"      py_body : {r.get('py_body', '')}")
                print(f"      node_body: {r.get('node_body', '')}")
        print("-" * 72)
        print(f"  cases: {len(results)}   passed: {pass_count}   failed: {fail_count}   node write events: {node_write_events}")
        print("=" * 72)

        out = Path("/tmp/gate7l_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate7l] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate7l] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7l] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
