"""Phase 3 · Gate 6g · live Python↔Node parity harness for ship-sites read.

Covers only:
  * GET /api/customers/{cid}/ship-sites

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6g_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant/login.
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
DB = f"trukvia_gate6g_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8157, 8158
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _site(**over: Any) -> dict[str, Any]:
    base = {"id": "s-x", "site_name": "X", "address": "", "gstin": "",
            "state": "", "state_code": "", "pincode": "",
            "phone": "", "contact_person": "", "is_active": True}
    base.update(over)
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
            {"id": "co-a", "user_id": "u1", "is_default": True, "state": "Karnataka",
             "invoice_prefix": "INV", "next_invoice_number": 1},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "state": "Karnataka",
             "invoice_prefix": "INV", "next_invoice_number": 1},
            {"id": "co-b", "user_id": "u2", "is_default": True, "state": "Karnataka",
             "invoice_prefix": "INV", "next_invoice_number": 1},
        ],
        "customers": [
            {"id": "cust-1", "user_id": "u1", "company_id": "co-a", "name": "Acme",
             "state": "Karnataka",
             "ship_sites": [
                 _site(id="s-active-true", site_name="Active True", is_active=True),
                 _site(id="s-active-false", site_name="Active False", is_active=False),
                 _site(id="s-active-null", site_name="Active Null", is_active=None),
                 _site(id="s-active-str", site_name="Active Str", is_active="anything"),
                 _site(id="s-active-zero", site_name="Active Zero", is_active=0),
                 _site(id="s-active-empty", site_name="Active Empty", is_active=""),
             ]},
            {"id": "cust-empty", "user_id": "u1", "company_id": "co-a", "name": "Empty",
             "state": "Karnataka", "ship_sites": []},
            {"id": "cust-missing", "user_id": "u1", "company_id": "co-a", "name": "Missing",
             "state": "Karnataka"},
            # Same id under alt-company for X-Company-Id override target
            {"id": "cust-1", "user_id": "u1", "company_id": "co-a-alt", "name": "Acme-Alt",
             "state": "Karnataka",
             "ship_sites": [_site(id="s-alt", site_name="Alt")]},
            {"id": "cust-u2", "user_id": "u2", "company_id": "co-b", "name": "Beta",
             "state": "Karnataka",
             "ship_sites": [_site(id="s-u2", site_name="U2 Site")]},
            # Raw-preservation fixture
            {"id": "cust-raw", "user_id": "u1", "company_id": "co-a", "name": "Raw",
             "state": "Karnataka",
             "ship_sites": [{"id": "s-raw", "site_name": "  Dirty  ",
                             "gstin": "  gst: 29abcde1234f1z5  ",
                             "state": "", "state_code": "", "pincode": "",
                             "is_active": True, "extra_field": "preserved"}]},
        ],
    }


TRACKED = ("user_sessions", "users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "counters",
           "fin_hook_failures")


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
        stdout=open("/tmp/gate6g_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6g_node.log", "wb"), stderr=subprocess.STDOUT,
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
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=5)
        except Exception:
            try: p.kill()
            except Exception: pass


HDR = {"owner":   {"Authorization": "Bearer tok-owner"},
       "u2":      {"Authorization": "Bearer tok-u2"},
       "expired": {"Authorization": "Bearer tok-expired"},
       "bad":     {"Authorization": "Bearer nope"},
       "none":    {}}


CASES = [
    {"n": 1,  "d": "happy path — all variants returned",
     "url": "/api/customers/cust-1/ship-sites", "hk": "owner", "expect": 200},
    {"n": 2,  "d": "empty ship_sites → items=[]",
     "url": "/api/customers/cust-empty/ship-sites", "hk": "owner", "expect": 200},
    {"n": 3,  "d": "missing ship_sites → items=[]",
     "url": "/api/customers/cust-missing/ship-sites", "hk": "owner", "expect": 200},
    {"n": 4,  "d": "active_only omitted → false",
     "url": "/api/customers/cust-1/ship-sites", "hk": "owner", "expect": 200},
    {"n": 5,  "d": "active_only=true → filter is_active=false",
     "url": "/api/customers/cust-1/ship-sites?active_only=true", "hk": "owner", "expect": 200},
    {"n": 6,  "d": "active_only=false → all sites",
     "url": "/api/customers/cust-1/ship-sites?active_only=false", "hk": "owner", "expect": 200},
    # True tokens
    {"n": 7,  "d": "active_only=True (mixed case)",
     "url": "/api/customers/cust-1/ship-sites?active_only=True", "hk": "owner", "expect": 200},
    {"n": 8,  "d": "active_only=yes",
     "url": "/api/customers/cust-1/ship-sites?active_only=yes", "hk": "owner", "expect": 200},
    {"n": 9,  "d": "active_only=1",
     "url": "/api/customers/cust-1/ship-sites?active_only=1", "hk": "owner", "expect": 200},
    {"n": 10, "d": "active_only=on",
     "url": "/api/customers/cust-1/ship-sites?active_only=on", "hk": "owner", "expect": 200},
    {"n": 11, "d": "active_only=t",
     "url": "/api/customers/cust-1/ship-sites?active_only=t", "hk": "owner", "expect": 200},
    # False tokens
    {"n": 12, "d": "active_only=NO",
     "url": "/api/customers/cust-1/ship-sites?active_only=NO", "hk": "owner", "expect": 200},
    {"n": 13, "d": "active_only=0",
     "url": "/api/customers/cust-1/ship-sites?active_only=0", "hk": "owner", "expect": 200},
    {"n": 14, "d": "active_only=off",
     "url": "/api/customers/cust-1/ship-sites?active_only=off", "hk": "owner", "expect": 200},
    {"n": 15, "d": "active_only=f",
     "url": "/api/customers/cust-1/ship-sites?active_only=f", "hk": "owner", "expect": 200},
    {"n": 16, "d": "active_only=n",
     "url": "/api/customers/cust-1/ship-sites?active_only=n", "hk": "owner", "expect": 200},
    # Invalid tokens
    {"n": 17, "d": "invalid boolean 'maybe' → 422",
     "url": "/api/customers/cust-1/ship-sites?active_only=maybe", "hk": "owner", "expect": 422},
    {"n": 18, "d": "invalid boolean '2' → 422",
     "url": "/api/customers/cust-1/ship-sites?active_only=2", "hk": "owner", "expect": 422},
    {"n": 19, "d": "invalid boolean '1.0' → 422",
     "url": "/api/customers/cust-1/ship-sites?active_only=1.0", "hk": "owner", "expect": 422},
    # Auth / tenant
    {"n": 20, "d": "missing customer → 404 'Customer not found'",
     "url": "/api/customers/does-not-exist/ship-sites", "hk": "owner", "expect": 404},
    {"n": 21, "d": "cross-user → 404",
     "url": "/api/customers/cust-u2/ship-sites", "hk": "owner", "expect": 404},
    {"n": 22, "d": "no auth → 401",
     "url": "/api/customers/cust-1/ship-sites", "hk": "none", "expect": 401},
    {"n": 23, "d": "invalid bearer → 401",
     "url": "/api/customers/cust-1/ship-sites", "hk": "bad", "expect": 401},
    {"n": 24, "d": "expired session → 401",
     "url": "/api/customers/cust-1/ship-sites", "hk": "expired", "expect": 401},
    # X-Company-Id
    {"n": 25, "d": "owned X-Company-Id override → alt customer view",
     "url": "/api/customers/cust-1/ship-sites",
     "hk": "owner", "expect": 200, "extra_hdr": {"X-Company-Id": "co-a-alt"}},
    {"n": 26, "d": "unowned X-Company-Id → default fallback",
     "url": "/api/customers/cust-1/ship-sites",
     "hk": "owner", "expect": 200, "extra_hdr": {"X-Company-Id": "co-b"}},
    # Raw preservation
    {"n": 27, "d": "raw stored values preserved (dirty GSTIN untouched)",
     "url": "/api/customers/cust-raw/ship-sites", "hk": "owner", "expect": 200},
]


async def run() -> int:
    print(f"[gate6g] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6g] seeded")
        py = start_py()
        node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6g] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6g_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6g_node.log").read()[-2000:])
            return 2

        results = []
        pass_count = fail_count = node_write_events = 0

        for c in CASES:
            hdr = dict(HDR[c["hk"]])
            hdr.update(c.get("extra_hdr", {}))
            url = c["url"]
            _ = await snap(cli, DB)
            rp = requests.get(PY_BASE + url, headers=hdr, timeout=10)
            after_py = await snap(cli, DB)
            rn = requests.get(NODE_BASE + url, headers=hdr, timeout=10)
            after_nd = await snap(cli, DB)
            nd_diff = diff_snap(after_py, after_nd)
            if nd_diff:
                node_write_events += 1

            status_ok = (rp.status_code == rn.status_code == c["expect"])
            try: pjson = rp.json()
            except Exception: pjson = rp.text
            try: njson = rn.json()
            except Exception: njson = rn.text

            # 422 body-shape divergence tolerated per Gate 6c/6d convention.
            body_ok = True if c["expect"] == 422 else (pjson == njson)

            ok = status_ok and body_ok
            if ok: pass_count += 1
            else: fail_count += 1
            results.append({
                "case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                "py_status": rp.status_code, "node_status": rn.status_code,
                "status_ok": status_ok, "body_ok": body_ok,
                "node_write_colls": list(nd_diff.keys()),
                "py_body": rp.text[:400] if not body_ok else "",
                "node_body": rn.text[:400] if not body_ok else "",
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
        print("PHASE 3 · GATE 6g · LIVE PARITY MATRIX (Customer Ship-Sites)")
        print("=" * 72)
        for r in results:
            py_s = r.get("py_status", "-")
            nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
            if r["verdict"] == "FAIL":
                print(f"      py_body : {r.get('py_body', '')}")
                print(f"      node_body: {r.get('node_body', '')}")
        print("-" * 72)
        print(f"  cases: {len(results)}   passed: {pass_count}   failed: {fail_count}   node write events: {node_write_events}")
        print("=" * 72)

        out = Path("/tmp/gate6g_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6g] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6g] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6g] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
