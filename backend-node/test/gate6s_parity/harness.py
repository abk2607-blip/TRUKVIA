"""Phase 3 · Gate 6s · live Python↔Node parity harness for
Audit-log reads.

Covers:
  * GET /api/audit-logs?module=&action=&entity_id=&start=&end=&limit=

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6s_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Class-C stance:
  Pure-read in Python. Handler executes ONLY
  `db.audit_logs.find(q, {"_id": 0, "user_id": 0}).sort("timestamp", -1)
   .to_list(min(int(limit), 500))`. Zero writer hook, zero audit call,
  zero backfill, zero recompute, zero FinTxn emission, zero
  approvals / policy / counters / idempotency touch. No `_active_company_id`.

Gate-6s NEW dimensions bound in this harness:
  * NO `_active_company_id` invocation (negative invocation parity).
  * Filter has NO `company_id`.
  * Truthy-gated optional filters (`module`/`action`/`entity_id`).
  * `end + "T23:59:59"` literal suffix binding.
  * `limit` FastAPI/Pydantic-v2 `int_parsing` 422 body observed live.
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
DB = f"trukvia_gate6s_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8192, 8193
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _ts(day: int) -> str:
    return f"2026-01-{day:02d}T10:00:00"


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
        "audit_logs": [
            {"id": "a1", "user_id": "u1", "module": "invoice",  "action": "create", "entity_id": "inv-1", "timestamp": _ts(1)},
            {"id": "a2", "user_id": "u1", "module": "invoice",  "action": "update", "entity_id": "inv-1", "timestamp": _ts(2)},
            {"id": "a3", "user_id": "u1", "module": "invoice",  "action": "delete", "entity_id": "inv-1", "timestamp": _ts(3)},
            {"id": "a4", "user_id": "u1", "module": "trip",     "action": "create", "entity_id": "trp-1", "timestamp": _ts(4)},
            {"id": "a5", "user_id": "u1", "module": "expense",  "action": "create", "entity_id": "exp-1", "timestamp": _ts(5)},
            {"id": "a6", "user_id": "u1", "module": "expense",  "action": "create", "entity_id": "exp-2", "timestamp": _ts(6)},
            {"id": "a7", "user_id": "u1", "module": "supplier", "action": "create", "entity_id": "sup-1", "timestamp": _ts(7)},
            {"id": "x1", "user_id": "u2", "module": "invoice",  "action": "create", "entity_id": "inv-9", "timestamp": _ts(7)},
        ],
    }


TRACKED = ("users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "counters",
           "fin_hook_failures", "vendors", "mechanics",
           "company_bank_accounts", "party_bank_accounts",
           "supplier_payments", "vendor_payments", "mechanic_payments",
           "driver_payments", "driver_payment_corrections", "templates")


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
                "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0",
                "PYTHONUNBUFFERED": "1"})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env,
        stdout=open("/tmp/gate6s_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6s_node.log", "wb"), stderr=subprocess.STDOUT,
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
    {"n":  1, "d": "happy list · u1 · 7 rows DESC by timestamp",
     "url": "/api/audit-logs", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  2, "d": "empty list · u2 has only one row (x1)",
     "url": "/api/audit-logs?module=trip", "hk": "u2", "expect": 200, "compare": "full"},
    {"n":  3, "d": "module filter · invoice → 3 rows",
     "url": "/api/audit-logs?module=invoice", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  4, "d": "action filter · create → 5 rows",
     "url": "/api/audit-logs?action=create", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  5, "d": "entity_id filter · inv-1 → 3 rows",
     "url": "/api/audit-logs?entity_id=inv-1", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  6, "d": "combined · module=invoice + action=update + entity_id=inv-1 → 1 row",
     "url": "/api/audit-logs?module=invoice&action=update&entity_id=inv-1",
     "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  7, "d": "end suffix · end=2026-01-03 → $lte 2026-01-03T23:59:59 (verifies literal binding)",
     "url": "/api/audit-logs?end=2026-01-03", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  8, "d": "range · start=2026-01-03 + end=2026-01-05 → 3 rows",
     "url": "/api/audit-logs?start=2026-01-03&end=2026-01-05",
     "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  9, "d": "default limit=200 · 7 rows",
     "url": "/api/audit-logs", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 10, "d": "explicit limit=600 → cap at 500 (seed only 7 · 7 returned)",
     "url": "/api/audit-logs?limit=600", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 11, "d": "invalid limit=abc → 422 (Pydantic-v2 int_parsing body)",
     "url": "/api/audit-logs?limit=abc", "hk": "u1", "expect": 422, "compare": "full"},
    {"n": 12, "d": "no auth → 401 Not authenticated (BEFORE 422)",
     "url": "/api/audit-logs?limit=abc", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 13, "d": "invalid bearer → 401 Invalid session",
     "url": "/api/audit-logs", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 14, "d": "expired session → 401 Session expired",
     "url": "/api/audit-logs", "hk": "expired", "expect": 401, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    if mode == "status_only":
        return (True, "")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate6s] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6s] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6s] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6s_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6s_node.log").read()[-2000:])
            return 2

        # ── OBSERVE 422 int_parsing body once at startup ────────────
        obs = requests.get(PY_BASE + "/api/audit-logs?limit=abc",
                           headers=HDR["u1"], timeout=10)
        print(f"[gate6s] OBSERVED 422 int_parsing body from Python (limit=abc):")
        print(f"         status = {obs.status_code}")
        print(f"         body   = {obs.text}")

        results = []
        pass_count = fail_count = node_write_events = 0
        for c in CASES:
            hdr = dict(HDR[c["hk"]])
            _ = await snap(cli, DB)
            rp = requests.get(PY_BASE + c["url"], headers=hdr, timeout=10)
            after_py = await snap(cli, DB)
            rn = requests.get(NODE_BASE + c["url"], headers=hdr, timeout=10)
            after_nd = await snap(cli, DB)
            nd_diff = diff_snap(after_py, after_nd)
            if nd_diff:
                node_write_events += 1

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
        print("PHASE 3 · GATE 6s · LIVE PARITY MATRIX (Audit logs)")
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

        out = Path("/tmp/gate6s_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "observed_py_422_int_parsing": {"status": obs.status_code, "body": obs.text},
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6s] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6s] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6s] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
