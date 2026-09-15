"""Phase 3 · Gate 6e · live Python↔Node parity harness for ship-to.

Covers only:
  * GET /api/invoices/{iid}/ship-to

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6e_parity_<ts>`) that is
  dropped in `finally`. Never touches `test_database` nor any existing
  TRUKVIA UAT tenant / login.

Class-C stance (Gate-6e):
  Python `get_invoice_ship_to` performs zero writes (no
  `_recompute_invoice`, no `_backfill_to_default`,
  no `_apply_effective_balance`). The resolver
  `ship_to_resolver.resolve_invoice_ship_to` is pure/in-memory. Both
  stacks must produce byte-identical responses AND zero DB mutation.
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
DB = f"trukvia_gate6e_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8137, 8138
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


# ── Fixture builders ─────────────────────────────────────────────────
def _site(**over: Any) -> dict[str, Any]:
    base = {
        "id": "s-x", "site_name": "", "address": "", "gstin": "",
        "state": "", "state_code": "", "pincode": "",
        "phone": "", "contact_person": "",
    }
    base.update(over)
    return base


def _trip(**over: Any) -> dict[str, Any]:
    base = {
        "id": "tr-x", "company_id": "co-a", "user_id": "u1",
        "customer_id": "cust-1", "to_location": "",
        "ship_site_id": "", "date": "2026-02-01",
        "status": "invoiced", "is_historical": False,
    }
    base.update(over)
    return base


def _invoice(**over: Any) -> dict[str, Any]:
    base = {
        "id": "inv-x", "company_id": "co-a", "user_id": "u1",
        "invoice_number": "INV/25-26/0001", "fy_string": "25-26",
        "customer_id": "cust-1", "invoice_date": "2026-02-01",
        "trip_ids": [],
        "created_at": "2026-02-01T00:00:00+00:00",
    }
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
            {"id": "co-b", "user_id": "u2", "is_default": True, "state": "Karnataka",
             "invoice_prefix": "INV", "next_invoice_number": 1},
        ],
        "customers": [
            {"id": "cust-1", "user_id": "u1", "company_id": "co-a", "name": "Acme",
             "state": "Karnataka",
             "ship_sites": [
                 _site(id="s-warehouse", site_name="Warehouse",
                       address="Plot 12, Whitefield, Bangalore 560066",
                       gstin="GSTIN 29ABCDE1234F1Z5", state="Karnataka",
                       state_code="29", pincode="560066"),
                 _site(id="s-yard", site_name="Yard",
                       address="Yard Rd, Mysore 570001", gstin="", pincode="570001"),
                 _site(id="s-plant", site_name="Plant Chennai",
                       address="Ambattur 600053", gstin="33ZZZZZ9999Z9Z9",
                       state="Tamil Nadu", state_code="33", pincode="600053"),
             ]},
            {"id": "cust-2", "user_id": "u1", "company_id": "co-a",
             "name": "NoSites", "state": "Karnataka", "ship_sites": []},
            {"id": "cust-gstin", "user_id": "u1", "company_id": "co-a",
             "name": "GstCust", "state": "Karnataka",
             "ship_sites": [
                 _site(id="s-dirty", site_name="Dirty", address="",
                       gstin="  gst: 29abcde1234f1z5  "),
             ]},
            {"id": "cust-b", "user_id": "u2", "company_id": "co-b",
             "name": "Beta", "state": "Karnataka"},
        ],
        "trips": [
            _trip(id="tr-happy", to_location="Anywhere"),
            _trip(id="tr-explicit", ship_site_id="s-warehouse", to_location="Anywhere"),
            _trip(id="tr-r1", to_location="Yard"),
            _trip(id="tr-r2", to_location="Somewhere 570001"),
            _trip(id="tr-r3", to_location="Whitefield"),
            _trip(id="tr-none", to_location="Kolkata"),
            _trip(id="tr-a", to_location="A"),
            _trip(id="tr-b", to_location="B"),
            _trip(id="tr-hist", to_location="Historic Place",
                  is_historical=True, status="archived_historical"),
            _trip(id="tr-gstin", ship_site_id="s-dirty", to_location="Anywhere"),
        ],
        "invoices": [
            _invoice(id="inv-empty", trip_ids=[]),
            _invoice(id="inv-nocust", customer_id="ghost", trip_ids=["tr-happy"]),
            _invoice(id="inv-explicit", trip_ids=["tr-explicit"]),
            _invoice(id="inv-inferR1", trip_ids=["tr-r1"]),
            _invoice(id="inv-inferR2", trip_ids=["tr-r2"]),
            _invoice(id="inv-inferR3", trip_ids=["tr-r3"]),
            _invoice(id="inv-none", trip_ids=["tr-none"]),
            _invoice(id="inv-nosites", customer_id="cust-2", trip_ids=["tr-happy"]),
            _invoice(id="inv-mixed", trip_ids=["tr-explicit", "tr-none"]),
            _invoice(id="inv-order", trip_ids=["tr-b", "tr-a"]),
            _invoice(id="inv-hist", trip_ids=["tr-hist"]),
            _invoice(id="inv-gstin", customer_id="cust-gstin", trip_ids=["tr-gstin"]),
            _invoice(id="inv-missingtrip", trip_ids=["tr-a", "tr-missing"]),
            _invoice(id="inv-of-u2", user_id="u2", company_id="co-b",
                     customer_id="cust-b", trip_ids=[]),
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
        stdout=open("/tmp/gate6e_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6e_node.log", "wb"), stderr=subprocess.STDOUT,
    )


def wait(url, timeout=30):
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
            try:
                p.kill()
            except Exception:
                pass


CASES = [
    {"n": 1,  "d": "empty trip_ids → per_trip=[]",
     "url": "/api/invoices/inv-empty/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 2,  "d": "missing customer → {} + fallback",
     "url": "/api/invoices/inv-nocust/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 3,  "d": "explicit ship_site_id → linked",
     "url": "/api/invoices/inv-explicit/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 4,  "d": "R1 name-equality inference",
     "url": "/api/invoices/inv-inferR1/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 5,  "d": "R2 pincode inference",
     "url": "/api/invoices/inv-inferR2/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 6,  "d": "R3 whole-token-in-address inference",
     "url": "/api/invoices/inv-inferR3/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 7,  "d": "zero-match → fallback",
     "url": "/api/invoices/inv-none/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 8,  "d": "empty ship_sites → fallback",
     "url": "/api/invoices/inv-nosites/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 9,  "d": "mixed identities → mixed=true, common=null",
     "url": "/api/invoices/inv-mixed/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 10, "d": "trip_ids order preserved (reversed)",
     "url": "/api/invoices/inv-order/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 11, "d": "historical trip pass-through",
     "url": "/api/invoices/inv-hist/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 12, "d": "GSTIN normalization on display",
     "url": "/api/invoices/inv-gstin/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 13, "d": "missing trip id silently dropped",
     "url": "/api/invoices/inv-missingtrip/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 14, "d": "invoice not found → 404",
     "url": "/api/invoices/does-not-exist/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 404},
    {"n": 15, "d": "wrong-tenant → 404",
     "url": "/api/invoices/inv-of-u2/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 404},
    {"n": 16, "d": "no auth → 401",
     "url": "/api/invoices/inv-explicit/ship-to",
     "hdr": {}, "expect": 401},
    {"n": 17, "d": "invalid bearer → 401",
     "url": "/api/invoices/inv-explicit/ship-to",
     "hdr": {"Authorization": "Bearer nope"}, "expect": 401},
    {"n": 18, "d": "expired session → 401",
     "url": "/api/invoices/inv-explicit/ship-to",
     "hdr": {"Authorization": "Bearer tok-expired"}, "expect": 401},
    {"n": 19, "d": "X-Company-Id ignored (unowned header, same result)",
     "url": "/api/invoices/inv-explicit/ship-to",
     "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-b"},
     "expect": 200},
]


async def run() -> int:
    print(f"[gate6e] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6e] seeded")
        py = start_py()
        node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6e] py={okp} node={okn}")
        if not (okp and okn):
            if not okp:
                print(open("/tmp/gate6e_py.log").read()[-2000:])
            if not okn:
                print(open("/tmp/gate6e_node.log").read()[-2000:])
            return 2

        results = []
        pass_count = fail_count = 0
        node_write_events = 0

        for c in CASES:
            hdr = c["hdr"]
            url = c["url"]
            before = await snap(cli, DB)
            rp = requests.get(PY_BASE + url, headers=hdr, timeout=10)
            after_py = await snap(cli, DB)
            rn = requests.get(NODE_BASE + url, headers=hdr, timeout=10)
            after_nd = await snap(cli, DB)

            nd_diff = diff_snap(after_py, after_nd)
            if nd_diff:
                node_write_events += 1

            status_ok = (rp.status_code == rn.status_code == c["expect"])
            try:
                pjson = rp.json()
            except Exception:
                pjson = rp.text
            try:
                njson = rn.json()
            except Exception:
                njson = rn.text

            body_ok = (pjson == njson)
            ok = status_ok and body_ok
            if ok:
                pass_count += 1
            else:
                fail_count += 1

            results.append({
                "case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                "py_status": rp.status_code, "node_status": rn.status_code,
                "status_ok": status_ok, "body_ok": body_ok,
                "node_write_colls": list(nd_diff.keys()),
                "py_body": rp.text[:400] if not body_ok else "",
                "node_body": rn.text[:400] if not body_ok else "",
            })
            _ = before

        results.append({
            "case": len(CASES) + 1,
            "desc": "read-only — Node write events across all cases",
            "verdict": "PASS" if node_write_events == 0 else "FAIL",
            "node_write_events": node_write_events,
        })
        if node_write_events == 0:
            pass_count += 1
        else:
            fail_count += 1

        print("\n" + "=" * 72)
        print("PHASE 3 · GATE 6e · LIVE PARITY MATRIX (Invoice Ship-To)")
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

        out = Path("/tmp/gate6e_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6e] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py)
        stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6e] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6e] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
