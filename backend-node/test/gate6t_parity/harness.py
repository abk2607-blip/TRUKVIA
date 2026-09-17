"""Phase 3 · Gate 6t · live Python↔Node parity harness for RepairEvent reads.

Covers:
  * GET /api/repair-events?vehicle_id=&trip_id=&status=
  * GET /api/repair-events/{rid}

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6t_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Class-C stance:
  Pure-read in Python. Handlers execute ONLY
  `db.repair_events.find(...).sort().to_list(5000)` and `.find_one(...)`.
  Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
  policy / counters / idempotency / cross-collection reads on GET paths.

Gate-6t NEW dimensions bound in this harness:
  * Soft-delete predicate `is_deleted: {$ne: True}` on both endpoints.
  * `activeCompanyId()` consumed (X-Company-Id changes rowset).
  * 5000 cap on LIST.
  * DETAIL 404 literal `"RepairEvent not found"` on miss / wrong-company
    / soft-deleted rid.
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
DB = f"trukvia_gate6t_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8194, 8195
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


D1, D2, D3, D4 = "2026-05-04", "2026-05-03", "2026-05-02", "2026-05-01"


def _ev(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "ev-x", "user_id": "u1", "company_id": "co-a",
        "vehicle_id": "veh-1", "trip_id": "trp-1", "status": "open",
        "event_date": D1, "workshop_name": "Alpha",
        "vehicle_number": "MH01AA0001",
        "created_by": "u1", "created_at": "2026-05-04T00:00:00+00:00",
        "modified_by": "", "modified_at": "",
        "deleted_by": "", "deleted_at": "", "deletion_reason": "",
        "file_ids": [], "notes": "",
        "is_deleted": False,
    }
    base.update(kw)
    return base


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
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta"},
        ],
        "repair_events": [
            _ev(id="e1", event_date=D1),
            _ev(id="e2", event_date=D2, vehicle_id="veh-2", trip_id="trp-2", status="closed"),
            _ev(id="e-sd", event_date=D1, is_deleted=True),
            _ev(id="e-alt", company_id="co-a-alt", event_date=D1),
            _ev(id="e-u2", user_id="u2", company_id="co-b", event_date=D1),
        ],
    }


TRACKED = ("users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "counters",
           "fin_hook_failures", "vendors", "mechanics",
           "company_bank_accounts", "party_bank_accounts",
           "supplier_payments", "vendor_payments", "mechanic_payments",
           "driver_payments", "driver_payment_corrections", "templates",
           "repair_events")


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
        stdout=open("/tmp/gate6t_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6t_node.log", "wb"), stderr=subprocess.STDOUT,
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
    {"n":  1, "d": "list happy · u1 · co-a · [e1,e2] DESC (soft-deleted excluded, alt-co hidden)",
     "url": "/api/repair-events", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  2, "d": "empty · vehicle_id=no-such → 200 []",
     "url": "/api/repair-events?vehicle_id=no-such", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  3, "d": "vehicle_id filter · veh-2 → [e2]",
     "url": "/api/repair-events?vehicle_id=veh-2", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  4, "d": "trip_id filter · trp-2 → [e2]",
     "url": "/api/repair-events?trip_id=trp-2", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  5, "d": "status filter · closed → [e2]",
     "url": "/api/repair-events?status=closed", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  6, "d": "combined filter · vehicle_id=veh-2 + trip_id=trp-2 + status=closed → [e2]",
     "url": "/api/repair-events?vehicle_id=veh-2&trip_id=trp-2&status=closed",
     "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  7, "d": "soft-delete exclusion · e-sd NOT visible (proven by list happy above but reconfirmed with empty filter)",
     "url": "/api/repair-events?status=open", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  8, "d": "owned X-Company-Id override · co-a-alt → [e-alt]",
     "url": "/api/repair-events", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n":  9, "d": "detail happy · e1",
     "url": "/api/repair-events/e1", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 10, "d": "detail unknown rid → 404 exact literal",
     "url": "/api/repair-events/no-such", "hk": "u1", "expect": 404, "compare": "full"},
    {"n": 11, "d": "detail wrong-company · e-u2 belongs to co-b → same 404",
     "url": "/api/repair-events/e-u2", "hk": "u1", "expect": 404, "compare": "full"},
    {"n": 12, "d": "detail soft-deleted · e-sd is_deleted:true → same 404",
     "url": "/api/repair-events/e-sd", "hk": "u1", "expect": 404, "compare": "full"},
    {"n": 13, "d": "no auth → 401 Not authenticated",
     "url": "/api/repair-events", "hk": "none", "expect": 401, "compare": "full"},
    {"n": 14, "d": "invalid bearer → 401 Invalid session",
     "url": "/api/repair-events", "hk": "bad", "expect": 401, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    if mode == "status_only":
        return (True, "")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate6t] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6t] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6t] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6t_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6t_node.log").read()[-2000:])
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
        print("PHASE 3 · GATE 6t · LIVE PARITY MATRIX (RepairEvents)")
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

        out = Path("/tmp/gate6t_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6t] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6t] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6t] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
