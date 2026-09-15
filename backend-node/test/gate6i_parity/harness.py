"""Phase 3 · Gate 6i · live Python↔Node parity harness for Expense reads.

Covers:
  * GET /api/expenses
  * GET /api/expenses/{eid}

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6i_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Class-C stance:
  Both handlers are pure-read in Python (no writer hook, audit,
  backfill, recompute, effective-balance, FinTxn, or paired-linkage
  refresh). Aggregate assertion: zero Node business writes across
  every case.
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
DB = f"trukvia_gate6i_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8171, 8172
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _exp(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "e-x", "user_id": "u1", "company_id": "co-a",
        "date": "2026-01-15", "amount": 100.0, "category": "Diesel",
        "source_type": "manual", "party_type": "vendor",
        "party_id": "v1", "party_name": "",
        "trip_id": "", "vehicle_id": "", "repair_event_id": "",
        "vendor_bill_id": "", "mechanic_work_order_id": "",
        "is_deleted": False, "is_reversed": False,
        "narration": "", "remarks": "",
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
        # Every company row carries company_id in the schema for suppliers/expenses.
        # `list_invoices` performs a legacy backfill; `list_expenses` does NOT, so
        # our seed does not require pre-assignment beyond correctness.
        "companies": [
            {"id": "co-a", "user_id": "u1", "is_default": True, "name": "Acme"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b", "user_id": "u2", "is_default": True, "name": "Beta"},
        ],
        "expenses": [
            _exp(id="e-1", date="2026-01-10", category="Diesel",
                 source_type="quick_op", trip_id="t-1", vehicle_id="veh-1"),
            _exp(id="e-2", date="2026-01-20", category="Toll",
                 source_type="fastag_import", trip_id="t-1", vehicle_id="veh-2",
                 party_type="vendor", party_id="v2"),
            _exp(id="e-3", date="2026-01-05", category="Repair",
                 source_type="manual", repair_event_id="rev-1",
                 vendor_bill_id="vb-1", party_type="vendor", party_id="v3"),
            _exp(id="e-4", date="2026-01-25", category="Labour",
                 source_type="manual", mechanic_work_order_id="wo-1",
                 party_type="mechanic", party_id="m1", extra_field="preserved"),
            _exp(id="e-5", date="2026-01-15", category="Diesel",
                 source_type="fleet_card_import", vehicle_id="veh-1"),
            # Guarded variants — is_deleted
            _exp(id="e-del-true",  date="2026-01-11", is_deleted=True),
            _exp(id="e-del-false", date="2026-01-12", is_deleted=False),
            _exp(id="e-del-null",  date="2026-01-13", is_deleted=None),
            _exp(id="e-del-zero",  date="2026-01-14", is_deleted=0),
            _exp(id="e-del-str",   date="2026-01-16", is_deleted=""),
            # Guarded variants — is_reversed
            _exp(id="e-rev-true",  date="2026-01-17", is_reversed=True),
            _exp(id="e-rev-false", date="2026-01-18", is_reversed=False),
            _exp(id="e-rev-null",  date="2026-01-19", is_reversed=None),
            # Alt-company (same user)
            _exp(id="e-alt", user_id="u1", company_id="co-a-alt",
                 date="2026-02-01", category="Diesel"),
            # Cross-user isolation
            _exp(id="e-u2", user_id="u2", company_id="co-b",
                 date="2026-01-30", category="Diesel"),
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
        stdout=open("/tmp/gate6i_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6i_node.log", "wb"), stderr=subprocess.STDOUT,
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
    # LIST — happy + guard behaviour
    {"n": 1,  "d": "list happy path (default guards)",
     "url": "/api/expenses", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 2,  "d": "include_cancelled=true surfaces deleted",
     "url": "/api/expenses?include_cancelled=true", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 3,  "d": "include_reversed=true surfaces reversed",
     "url": "/api/expenses?include_reversed=true", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 4,  "d": "both include flags true",
     "url": "/api/expenses?include_cancelled=true&include_reversed=true", "hk": "owner", "expect": 200, "compare": "full"},
    # LIST — filters
    {"n": 5,  "d": "trip_id filter",
     "url": "/api/expenses?trip_id=t-1", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 6,  "d": "vehicle_id filter",
     "url": "/api/expenses?vehicle_id=veh-1", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 7,  "d": "repair_event_id filter",
     "url": "/api/expenses?repair_event_id=rev-1", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 8,  "d": "vendor_bill_id filter",
     "url": "/api/expenses?vendor_bill_id=vb-1", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 9,  "d": "mechanic_work_order_id filter",
     "url": "/api/expenses?mechanic_work_order_id=wo-1", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 10, "d": "party_type filter",
     "url": "/api/expenses?party_type=mechanic", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 11, "d": "party_id filter",
     "url": "/api/expenses?party_id=v2", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 12, "d": "category filter",
     "url": "/api/expenses?category=Diesel", "hk": "owner", "expect": 200, "compare": "full"},
    # LIST — source_type parsing
    {"n": 13, "d": "source_type single equality",
     "url": "/api/expenses?source_type=quick_op", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 14, "d": "source_type CSV → $in",
     "url": "/api/expenses?source_type=quick_op,fastag_import", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 15, "d": "source_type empty → filter omitted",
     "url": "/api/expenses?source_type=", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 16, "d": "source_type CSV with padding + empty parts",
     "url": "/api/expenses?source_type=%20quick_op%20%2C%20%2C%20fastag_import%20",
     "hk": "owner", "expect": 200, "compare": "full"},
    # LIST — date bounds
    {"n": 17, "d": "date_from lower bound",
     "url": "/api/expenses?date_from=2026-01-20", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 18, "d": "date_to upper bound",
     "url": "/api/expenses?date_to=2026-01-10", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 19, "d": "both date bounds inclusive",
     "url": "/api/expenses?date_from=2026-01-12&date_to=2026-01-18", "hk": "owner", "expect": 200, "compare": "full"},
    # LIST — isolation
    {"n": 20, "d": "cross-user isolation (u2 view)",
     "url": "/api/expenses", "hk": "u2", "expect": 200, "compare": "full"},
    {"n": 21, "d": "owned X-Company-Id override → alt company rows",
     "url": "/api/expenses", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n": 22, "d": "unowned X-Company-Id → default fallback",
     "url": "/api/expenses", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},
    # LIST — boolean parity
    {"n": 23, "d": "include_reversed=YES (TRUE token)",
     "url": "/api/expenses?include_reversed=YES", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 24, "d": "include_reversed=0 (FALSE token)",
     "url": "/api/expenses?include_reversed=0", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 25, "d": "include_cancelled=t (TRUE token)",
     "url": "/api/expenses?include_cancelled=t", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 26, "d": "include_cancelled=off (FALSE token)",
     "url": "/api/expenses?include_cancelled=off", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 27, "d": "invalid boolean → 422",
     "url": "/api/expenses?include_reversed=maybe", "hk": "owner", "expect": 422, "compare": "status_only"},
    # LIST — auth
    {"n": 28, "d": "list no auth → 401",
     "url": "/api/expenses", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 29, "d": "list invalid bearer → 401",
     "url": "/api/expenses", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 30, "d": "list expired → 401",
     "url": "/api/expenses", "hk": "expired", "expect": 401, "compare": "full"},
    # DETAIL
    {"n": 31, "d": "detail happy path",
     "url": "/api/expenses/e-1", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 32, "d": "detail extra fields preserved",
     "url": "/api/expenses/e-4", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 33, "d": "detail missing → 404",
     "url": "/api/expenses/does-not-exist", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 34, "d": "detail is_deleted=true → 404",
     "url": "/api/expenses/e-del-true", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 35, "d": "detail is_deleted=null → visible",
     "url": "/api/expenses/e-del-null", "hk": "owner", "expect": 200, "compare": "full"},
    {"n": 36, "d": "detail cross-user → 404",
     "url": "/api/expenses/e-u2", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 37, "d": "detail cross-company → 404",
     "url": "/api/expenses/e-alt", "hk": "owner", "expect": 404, "compare": "full"},
    {"n": 38, "d": "detail owned X-Company-Id override → alt row",
     "url": "/api/expenses/e-alt", "hk": "owner",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n": 39, "d": "detail no auth → 401",
     "url": "/api/expenses/e-1", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 40, "d": "detail invalid bearer → 401",
     "url": "/api/expenses/e-1", "hk": "bad", "expect": 401, "compare": "full"},
    {"n": 41, "d": "detail expired → 401",
     "url": "/api/expenses/e-1", "hk": "expired", "expect": 401, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    if mode == "status_only":
        return (True, "")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate6i] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6i] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6i] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6i_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6i_node.log").read()[-2000:])
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
        print("PHASE 3 · GATE 6i · LIVE PARITY MATRIX (Expense reads)")
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

        out = Path("/tmp/gate6i_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6i] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6i] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6i] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
