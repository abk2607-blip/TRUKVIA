"""Phase 3 · Gate 7e · live Python↔Node parity harness for
supplier-vehicles list reads.

Covers:
  * GET /api/suppliers/{sid}/vehicles

STRICT UAT-DATA PRESERVATION:
  Isolated timestamped DB `trukvia_gate7e_parity_<ts>`, dropped in
  `finally`. Never touches `test_database` or any TRUKVIA UAT tenant.

Class-C stance:
  Pure-read in Python. Handler executes ONLY
    1. `db.suppliers.find_one({id, user_id, company_id}, {_id:0, name:1})`
    2. `db.vehicles.find(q, {_id:0, user_id:0}).sort("vehicle_number", 1)
         .to_list(500)`
  Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
  counters / idempotency / hidden cross-collection writes.

NEW parity axes for Gate 7e:
  * PATH parameter `{sid}`.
  * Cross-collection precheck (suppliers → vehicles).
  * 404 branch `"Supplier not found"` AFTER successful auth.
  * Dynamic anchored case-insensitive `$regex` from stored supplier.name,
    UNESCAPED (verbatim Python semantics; server-side Mongo evaluation).
  * `$or` between exact supplier_id equality and the regex branch.
  * `vehicle_type` literal equality predicate.
  * Ascending sort on vehicle_number, hard cap 500.
  * Bare-array response.
  * No 422 branch, no is_active predicate on the precheck.
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
DB = f"trukvia_gate7e_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8216, 8217
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _veh(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "user_id": "u1", "company_id": "co-a", "vehicle_type": "supplier",
        "supplier_id": "", "supplier_name": "",
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
            {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme Co"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
            {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta Co"},
        ],
        "suppliers": [
            {"id": "sup-1",     "user_id": "u1", "company_id": "co-a",     "name": "Acme Transport", "is_active": True},
            {"id": "sup-2",     "user_id": "u1", "company_id": "co-a",     "name": "Beta Freight",   "is_active": True},
            # Inactive supplier with regex-metacharacter name — verifies NO
            # route-side escaping. Pattern ^Gamma [X]$/i (with `[X]` char
            # class) matches the string "Gamma X" only.
            {"id": "sup-3",     "user_id": "u1", "company_id": "co-a",     "name": "Gamma [X]",       "is_active": False},
            {"id": "sup-alt",   "user_id": "u1", "company_id": "co-a-alt", "name": "Alt Supplier",   "is_active": True},
            # Same name as sup-1 but different user/company — must NOT leak.
            {"id": "sup-cross", "user_id": "u2", "company_id": "co-b",     "name": "Acme Transport", "is_active": True},
        ],
        "vehicles": [
            # u1 / co-a — matches for sup-1
            _veh(id="v1", vehicle_number="KA01AA0001", supplier_id="sup-1", supplier_name="Different Name"),
            _veh(id="v2", vehicle_number="KA01AA0002", supplier_id="",      supplier_name="Acme Transport"),
            _veh(id="v3", vehicle_number="KA01AA0003", supplier_id="",      supplier_name="acme transport"),
            _veh(id="v4", vehicle_number="KA01AA0004", supplier_id="",      supplier_name="ACME TRANSPORT"),
            # No match for sup-1
            _veh(id="v5", vehicle_number="KA01AA0005", supplier_id="",      supplier_name="Not Acme"),
            # Wrong vehicle_type — excluded despite supplier_id=sup-1
            _veh(id="v6", vehicle_number="KA01AA0006", supplier_id="sup-1", supplier_name="", vehicle_type="own"),
            # sup-3 (inactive) matches — id branch + anchored regex-metachar
            _veh(id="v-i1", vehicle_number="KA01AA0100", supplier_id="sup-3", supplier_name="irrelevant"),
            _veh(id="v-i2", vehicle_number="KA01AA0101", supplier_id="",      supplier_name="Gamma X"),
            # u1 / co-a-alt — company isolation
            _veh(id="v-alt-1", company_id="co-a-alt", vehicle_number="KA01AA0201", supplier_id="sup-alt", supplier_name="Alt Supplier"),
            _veh(id="v-alt-2", company_id="co-a-alt", vehicle_number="KA01AA0202", supplier_id="",       supplier_name="alt supplier"),
            # u2 / co-b — cross-user isolation
            _veh(id="v-cross", user_id="u2", company_id="co-b", vehicle_number="KA01AA0007", supplier_id="sup-cross", supplier_name="must not leak"),
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
           "repair_events", "mechanic_work_orders", "vendor_bills",
           "wallet_adjustments", "wallet_transfers", "wallet_recharges",
           "policy_change_events")


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
        stdout=open("/tmp/gate7e_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate7e_node.log", "wb"), stderr=subprocess.STDOUT,
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
    # Auth 401 literals + auth precedence over missing supplier
    {"n":  1, "d": "no auth · valid sid → 401 Not authenticated",
     "url": "/api/suppliers/sup-1/vehicles", "hk": "none", "expect": 401, "compare": "full"},
    {"n":  2, "d": "invalid bearer → 401 Invalid session",
     "url": "/api/suppliers/sup-1/vehicles", "hk": "bad", "expect": 401, "compare": "full"},
    {"n":  3, "d": "expired bearer → 401 Session expired",
     "url": "/api/suppliers/sup-1/vehicles", "hk": "expired", "expect": 401, "compare": "full"},
    {"n":  4, "d": "auth precedence — no auth + missing sid → 401 (not 404)",
     "url": "/api/suppliers/does-not-exist/vehicles", "hk": "none", "expect": 401, "compare": "full"},

    # Happy path
    {"n":  5, "d": "sup-1 · default co-a · id-branch (v1) + name-regex (v2/v3/v4) ASC",
     "url": "/api/suppliers/sup-1/vehicles", "hk": "u1", "expect": 200, "compare": "full"},

    # Empty valid supplier
    {"n":  6, "d": "sup-2 · valid supplier with zero matches → 200 []",
     "url": "/api/suppliers/sup-2/vehicles", "hk": "u1", "expect": 200, "compare": "full"},

    # Inactive supplier + regex metacharacters (unescaped char class)
    {"n":  7, "d": "sup-3 (inactive · name 'Gamma [X]') → v-i1 (id) + v-i2 (regex ^Gamma [X]$/i)",
     "url": "/api/suppliers/sup-3/vehicles", "hk": "u1", "expect": 200, "compare": "full"},

    # 404 branches
    {"n":  8, "d": "missing supplier → 404 Supplier not found",
     "url": "/api/suppliers/does-not-exist/vehicles", "hk": "u1", "expect": 404, "compare": "full"},
    {"n":  9, "d": "wrong-user supplier (u1 accessing u2's sup-cross) → 404",
     "url": "/api/suppliers/sup-cross/vehicles", "hk": "u1", "expect": 404, "compare": "full"},
    {"n": 10, "d": "u2 accessing sup-1 (belongs to u1) → 404",
     "url": "/api/suppliers/sup-1/vehicles", "hk": "u2", "expect": 404, "compare": "full"},

    # X-Company-Id override behavior
    {"n": 11, "d": "owned X-Company-Id co-a-alt + sup-1 → 404 (sup-1 scoped to co-a)",
     "url": "/api/suppliers/sup-1/vehicles", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 404, "compare": "full"},
    {"n": 12, "d": "owned X-Company-Id co-a-alt + sup-alt → v-alt-1, v-alt-2 ASC",
     "url": "/api/suppliers/sup-alt/vehicles", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200, "compare": "full"},
    {"n": 13, "d": "unowned X-Company-Id co-b → fallback co-a → sup-1 rows",
     "url": "/api/suppliers/sup-1/vehicles", "hk": "u1",
     "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200, "compare": "full"},

    # Cross-user path
    {"n": 14, "d": "cross-user u2 · sup-cross → v-cross only (same-name isolation)",
     "url": "/api/suppliers/sup-cross/vehicles", "hk": "u2", "expect": 200, "compare": "full"},

    # URL-encoded whitespace sid mismatch
    {"n": 15, "d": "URL-encoded whitespace sid ' sup-1 ' → 404",
     "url": "/api/suppliers/%20sup-1%20/vehicles", "hk": "u1", "expect": 404, "compare": "full"},
]


def compare_bodies(mode: str, py, nd) -> tuple[bool, str]:
    if mode == "full":
        return (py == nd, "" if py == nd else "body diverge")
    return (False, f"unknown compare mode {mode}")


async def run() -> int:
    print(f"[gate7e] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate7e] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate7e] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate7e_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate7e_node.log").read()[-2000:])
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
        print("PHASE 3 · GATE 7e · LIVE PARITY MATRIX (SupplierVehicles list)")
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

        out = Path("/tmp/gate7e_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate7e] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate7e] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7e] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
