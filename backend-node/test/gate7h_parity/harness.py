"""Phase 3 · Gate 7h · live Python↔Node parity harness for Fuel vehicle maps list.

Covers:
  * GET /api/fuel/vehicle-maps

STRICT UAT-DATA PRESERVATION:
  Isolated timestamped DB `trukvia_gate7h_parity_<ts>`, dropped in
  `finally`. Never touches `test_database` or any TRUKVIA UAT tenant.

Class-C stance:
  Pure-read in Python. Handler executes ONLY
    db.fuel_vehicle_maps.find(q, {_id:0, user_id:0})
      .sort("source_vehicle_ref", 1).to_list(5000)
  Zero writer hook / audit / backfill / recompute / FinTxn / counters /
  idempotency / cross-collection reads.

Contract highlights:
  * source: Optional[str] = None  — NO 422 surface
  * Predicate added ONLY when raw source ∈ {"iocl","bpcl"} (case-sensitive)
  * Every other value silently ignored — 200, base-only result
  * Projection strips _id AND user_id
  * Sort source_vehicle_ref ASC
  * Cap 5000
  * Bare-array response, empty → 200 []
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
DB = f"trukvia_gate7h_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8222, 8223
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _fvm(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "user_id": "u1", "company_id": "co-a",
        "source": "iocl", "source_vehicle_ref": "IOCL-A",
        "vehicle_id": "v1", "vehicle_number": "AP16TA1234",
        "created_by": "u1", "created_at": now_iso(),
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
            {"id": "co-a",       "user_id": "u1", "is_default": True,  "name": "Acme Co"},
            {"id": "co-a-alt",   "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-a-empty", "user_id": "u1", "is_default": False, "name": "Empty"},
            {"id": "co-b",       "user_id": "u2", "is_default": True,  "name": "Beta Co"},
        ],
        "fuel_vehicle_maps": [
            _fvm(id="m1", source="iocl", source_vehicle_ref="IOCL-A"),
            _fvm(id="m2", source="iocl", source_vehicle_ref="IOCL-B"),
            _fvm(id="m3", source="bpcl", source_vehicle_ref="BPCL-Z", vehicle_number="AP16TA9999"),
            _fvm(id="m-alt", company_id="co-a-alt", source="iocl", source_vehicle_ref="ALT-IOCL-1"),
            _fvm(id="m-u2-1", user_id="u2", company_id="co-b", source="iocl", source_vehicle_ref="U2-IOCL-1"),
            _fvm(id="m-u2-2", user_id="u2", company_id="co-b", source="bpcl", source_vehicle_ref="U2-BPCL-1"),
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
           "policy_change_events", "fuel_vehicle_maps")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    for coll, rows in fixtures().items():
        if rows:
            await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        try:
            docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(6000)
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
        stdout=open("/tmp/gate7h_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate7h_node.log", "wb"), stderr=subprocess.STDOUT,
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
     "url": "/api/fuel/vehicle-maps", "hk": "none", "expect": 401, "compare": "full"},
    {"n":  2, "d": "invalid bearer → 401 Invalid session",
     "url": "/api/fuel/vehicle-maps", "hk": "bad", "expect": 401, "compare": "full"},
    {"n":  3, "d": "expired bearer → 401 Session expired",
     "url": "/api/fuel/vehicle-maps", "hk": "expired", "expect": 401, "compare": "full"},

    # Tenant scoping
    {"n":  4, "d": "no-header default co-a → m3, m1, m2 ASC",
     "url": "/api/fuel/vehicle-maps", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  5, "d": "owned X-Company-Id co-a-alt → only m-alt",
     "url": "/api/fuel/vehicle-maps", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n":  6, "d": "unowned X-Company-Id co-b → fallback co-a",
     "url": "/api/fuel/vehicle-maps", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},

    # Source filter — accepted values
    {"n":  7, "d": "source=iocl → only iocl rows (m1, m2 ASC)",
     "url": "/api/fuel/vehicle-maps?source=iocl", "hk": "u1", "expect": 200, "compare": "full"},
    {"n":  8, "d": "source=bpcl → only bpcl rows (m3)",
     "url": "/api/fuel/vehicle-maps?source=bpcl", "hk": "u1", "expect": 200, "compare": "full"},

    # Source filter — silently ignored (case-sensitive, exact-match only)
    {"n":  9, "d": "source='' → predicate dropped → base set",
     "url": "/api/fuel/vehicle-maps?source=", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 10, "d": "source=other → predicate dropped (NO 422)",
     "url": "/api/fuel/vehicle-maps?source=other", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 11, "d": "source=IOCL uppercase → predicate dropped",
     "url": "/api/fuel/vehicle-maps?source=IOCL", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 12, "d": "source=iOcl mixed → predicate dropped",
     "url": "/api/fuel/vehicle-maps?source=iOcl", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 13, "d": "source=bp prefix → predicate dropped (exact-match only)",
     "url": "/api/fuel/vehicle-maps?source=bp", "hk": "u1", "expect": 200, "compare": "full"},
    {"n": 14, "d": "source=zzz arbitrary → 200 base set (NO 422 / 400)",
     "url": "/api/fuel/vehicle-maps?source=zzz%20%21%40%23", "hk": "u1", "expect": 200, "compare": "full"},

    # Cross-user
    {"n": 15, "d": "cross-user u2 default → own co-b rows only ASC",
     "url": "/api/fuel/vehicle-maps", "hk": "u2", "expect": 200, "compare": "full"},
    {"n": 16, "d": "cross-user u2 source=iocl → own U2-IOCL-1",
     "url": "/api/fuel/vehicle-maps?source=iocl", "hk": "u2", "expect": 200, "compare": "full"},

    # Empty result
    {"n": 17, "d": "owned empty tenant co-a-empty → 200 []",
     "url": "/api/fuel/vehicle-maps", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-empty"}, "expect": 200, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate7h] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate7h] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate7h] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate7h_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate7h_node.log").read()[-2000:])
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
        print("PHASE 3 · GATE 7h · LIVE PARITY MATRIX (Fuel vehicle maps list)")
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

        out = Path("/tmp/gate7h_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate7h] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate7h] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7h] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
