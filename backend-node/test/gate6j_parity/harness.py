"""Phase 3 · Gate 6j · live Python↔Node parity harness for Vendor reads.

Covers:
  * GET /api/vendors
  * GET /api/vendors/{vid}

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6j_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Class-C stance:
  Both handlers are pure-read in Python (`find` / `find_one` only).
  Aggregate assertion: zero Node business writes across every case.

Regex parity:
  Python builds `{"$regex": q, "$options": "i"}` and Mongo evaluates
  server-side. Node passes the identical filter shape through the
  driver — no local RegExp construction, no escaping. Byte parity
  guaranteed for identical seed data.
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
DB = f"trukvia_gate6j_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8173, 8174
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _ven(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "v-x", "user_id": "u1", "company_id": "co-a",
        "name": "Vendor X", "mobile": "9999999999",
        "contact_person": "PersonX", "address": "", "gstin": "",
        "pan": "", "state": "", "opening_balance": 0.0, "is_active": True,
        "created_at": now_iso(),
    }
    base.update(kw)
    return base


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    return {
        "user_sessions": [
            {"session_token": "tok-owner", "user_id": "u1", "effective_role": "owner",
             "expires_at": future(3600), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner",
             "expires_at": past(60), "last_refreshed_at": now},
            {"session_token": "tok-u2", "user_id": "u2", "effective_role": "owner",
             "expires_at": future(3600), "last_refreshed_at": now},
        ],
        "users": [
            {"user_id": "u1", "email": "u1@x", "name": "U1", "picture": "", "created_at": now},
            {"user_id": "u2", "email": "u2@x", "name": "U2", "picture": "", "created_at": now},
        ],
        "companies": [
            {"id": "co-a", "user_id": "u1", "is_default": True, "name": "Acme"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b", "user_id": "u2", "is_default": True, "name": "Beta"},
        ],
        "vendors": [
            _ven(id="v-alpha", name="Alpha Parts",      mobile="9111111111",
                 contact_person="Alice",   is_active=True),
            _ven(id="v-beta",  name="Beta Tools",       mobile="9222222222",
                 contact_person="Bob",     is_active=True, extra_field="preserved"),
            _ven(id="v-gamma", name="Gamma Workshop",   mobile="9333333333",
                 contact_person="Charlie", is_active=False),
            _ven(id="v-delta", name="Delta Enterprise", mobile="9444444444",
                 contact_person="Dave",    is_active=True),
            # Same user, alt company (X-Company-Id override target)
            _ven(id="v-alt", user_id="u1", company_id="co-a-alt",
                 name="Alt Vendor", mobile="9555555555", contact_person="Eve"),
            # Cross-user isolation
            _ven(id="v-u2", user_id="u2", company_id="co-b",
                 name="U2 Vendor", mobile="9666666666", contact_person="Frank"),
        ],
    }


TRACKED = ("user_sessions", "users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "counters",
           "fin_hook_failures", "vendors")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    fx = fixtures()
    for coll, rows in fx.items():
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
        stdout=open("/tmp/gate6j_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6j_node.log", "wb"), stderr=subprocess.STDOUT,
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


HDR = {"owner":     {"Authorization": "Bearer tok-owner"},
       "u2":        {"Authorization": "Bearer tok-u2"},
       "expired":   {"Authorization": "Bearer tok-expired"},
       "bad":       {"Authorization": "Bearer nope"},
       "none":      {}}


CASES: list[dict[str, Any]] = [
    # LIST — happy + active_only
    {"n": 1,  "d": "list happy path (default scope)",
     "url": "/api/vendors", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 2,  "d": "active_only=true → filters inactive",
     "url": "/api/vendors?active_only=true", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 3,  "d": "active_only=false → all vendors",
     "url": "/api/vendors?active_only=false", "hk": "owner", "expect": 200, "compare": "full"},
    # LIST — boolean tokens
    {"n": 4,  "d": "active_only=YES (TRUE token)",
     "url": "/api/vendors?active_only=YES", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 5,  "d": "active_only=0 (FALSE token)",
     "url": "/api/vendors?active_only=0", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 6,  "d": "active_only=on (TRUE token)",
     "url": "/api/vendors?active_only=on", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 7,  "d": "active_only=off (FALSE token)",
     "url": "/api/vendors?active_only=off", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 8,  "d": "invalid boolean → 422",
     "url": "/api/vendors?active_only=maybe", "hk": "owner", "expect": 422, "compare": "status_only"},
    # LIST — q regex
    {"n": 9,  "d": "q matches name (lowercase)",
     "url": "/api/vendors?q=alpha", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 10, "d": "q matches name UPPERCASE (case-insensitive)",
     "url": "/api/vendors?q=ALPHA", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 11, "d": "q matches mobile",
     "url": "/api/vendors?q=9222222222", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 12, "d": "q matches contact_person",
     "url": "/api/vendors?q=Charlie", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 13, "d": "q partial substring on mobile",
     "url": "/api/vendors?q=3333", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 14, "d": "q no match → empty array",
     "url": "/api/vendors?q=zzzznomatch", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 15, "d": "empty q → filter omitted",
     "url": "/api/vendors?q=", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 16, "d": "active_only + q combined",
     "url": "/api/vendors?active_only=true&q=Beta", "hk": "owner", "expect": 200, "compare": "full"},
    # LIST — isolation
    {"n": 17, "d": "cross-user isolation (u2 view)",
     "url": "/api/vendors", "hk": "u2", "expect": 200, "compare": "full"},
    {"n": 18, "d": "owned X-Company-Id override → alt company rows",
     "url": "/api/vendors", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n": 19, "d": "unowned X-Company-Id → default fallback",
     "url": "/api/vendors", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},
    # LIST — auth failures
    {"n": 20, "d": "list no auth → 401",
     "url": "/api/vendors", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 21, "d": "list invalid bearer → 401",
     "url": "/api/vendors", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 22, "d": "list expired → 401",
     "url": "/api/vendors", "hk": "expired", "expect": 401, "compare": "full"},
    # DETAIL
    {"n": 23, "d": "detail happy path",
     "url": "/api/vendors/v-alpha", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 24, "d": "detail extra fields preserved",
     "url": "/api/vendors/v-beta", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 25, "d": "detail inactive vendor STILL RETURNED (no is_active filter)",
     "url": "/api/vendors/v-gamma", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 26, "d": "detail missing → 404",
     "url": "/api/vendors/does-not-exist", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 27, "d": "detail cross-user → 404",
     "url": "/api/vendors/v-u2", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 28, "d": "detail cross-company → 404",
     "url": "/api/vendors/v-alt", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 29, "d": "detail owned X-Company-Id override → alt row",
     "url": "/api/vendors/v-alt", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n": 30, "d": "detail no auth → 401",
     "url": "/api/vendors/v-alpha", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 31, "d": "detail invalid bearer → 401",
     "url": "/api/vendors/v-alpha", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 32, "d": "detail expired → 401",
     "url": "/api/vendors/v-alpha", "hk": "expired", "expect": 401, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    if mode == "status_only":
        return (True, "")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate6j] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6j] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6j] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6j_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6j_node.log").read()[-2000:])
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
                "py_body": rp.text[:600] if not body_ok else "",
                "node_body": rn.text[:600] if not body_ok else "",
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
        print("PHASE 3 · GATE 6j · LIVE PARITY MATRIX (Vendor reads)")
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

        out = Path("/tmp/gate6j_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6j] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6j] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6j] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
