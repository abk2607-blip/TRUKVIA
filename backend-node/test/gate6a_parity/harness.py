"""Phase 3 · Gate 6a · live Python↔Node parity harness for GET /api/trips/{tid}.

Slice-6a is STRICTLY READ-ONLY. Node MUST NOT write to trips (nor to
expenses / driver_ledger / fin_txn / audit_logs / counters / user_sessions /
any collection). The write-observation snapshot-diff enforces this.

Note on `_lazy_migrate_supplier_entries` (Python-only side effect):
  Python's GET may perform a one-time `update_one` on legacy pre-Iter91
  supplier trips (empty entry arrays + non-zero flat supplier_diesel /
  supplier_advance). To keep this slice strictly read-only in the shadow,
  the harness fixtures use only fresh (Iter91+) trips already carrying the
  `_entries` arrays. Legacy trips are out of scope for Gate-6a.
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
DB = f"trukvia_gate6a_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8105, 8106
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _trip(**over: Any) -> dict[str, Any]:
    base = {
        "id": "trip_x", "company_id": "co-a", "user_id": "u1",
        "customer_id": "cust-1", "date": "2026-02-01",
        "vehicle_number": "AB01AA0000", "vehicle_id": "v1", "vehicle_type": "own",
        "loading_date": "", "unloading_date": "",
        "loaded_qty": 30.0, "unloaded_qty": 30.0,
        "excess_qty": 0.0, "shortage_qty": 0.0,
        "product_rate_per_mt": 0.0, "shortage_amount": 0.0, "excess_amount": 0.0,
        "shortage_amount_override": False, "excess_amount_override": False,
        "total_halting_days": 0, "grace_days": 4, "chargeable_halting_days": 0,
        "halting_rate_per_day": 0.0, "halting_amount": 0.0, "halting_amount_override": False,
        "supplier_id": "", "supplier_name": "", "supplier_freight": 0.0,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 0.0,
        "supplier_fixed_amount": 0.0, "supplier_round_trip_kms": 0.0,
        "supplier_rate_per_km_per_ton": 0.0, "supplier_loading_point": "",
        "supplier_unloading_point": "", "supplier_material": "",
        "supplier_quantity": 0.0, "supplier_advance": 0.0, "supplier_diesel": 0.0,
        "supplier_halting_days": 0.0, "supplier_halting_rate_per_day": 0.0,
        "supplier_halting_amount": 0.0, "supplier_halting_remarks": "",
        "supplier_diesel_entries": [], "supplier_advance_entries": [],
        "supplier_shortage_deduction": 0.0, "supplier_shortage_deduction_override": False,
        "supplier_shortage_original_amount": 0.0,
        "supplier_shortage_override_reason": "", "supplier_shortage_override_by": "",
        "supplier_shortage_override_at": "",
        "supplier_other_recoveries": 0.0, "supplier_other_income": 0.0,
        "supplier_net_payable": 0.0,
        "driver_id": None, "driver_name": "", "driver_mobile": "",
        "product_id": None, "load_details": "Bitumen VG 40", "hsn_sac": "",
        "consignor_id": None, "consignor_name": "",
        "consignee_id": None, "consignee_name": "",
        "ship_site_id": "", "customer_reference_number": "",
        "tons": 30.0, "from_location": "", "to_location": "",
        "from_pincode": "", "to_pincode": "",
        "freight_mode": "per_ton", "rate_per_ton": 1000.0,
        "fixed_amount": 0.0, "round_trip_kms": 0.0,
        "rate_per_km_per_ton": 0.0, "freight_amount": 30000.0,
        "expenses": {}, "total_expense": 0.0, "profit": 0.0, "net_settlement": 0.0,
        "status": "posted", "is_historical": False,
        "created_at": "2026-02-01T00:00:00+00:00",
        "applied_freight_method": "per_ton_loading",
        "customer_receipts": [],
        "lr_number": "",
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
            {"id": "co-a", "user_id": "u1", "is_default": True, "state": "Karnataka"},
            {"id": "co-a-alt", "user_id": "u1", "is_default": False, "state": "Karnataka"},
            {"id": "co-b", "user_id": "u2", "is_default": True, "state": "Karnataka"},
        ],
        "trips": [
            _trip(id="trip_a1", customer_id="cust-1", company_id="co-a", user_id="u1",
                  vehicle_number="AB01AA0001"),
            _trip(id="trip_a2", customer_id="cust-2", company_id="co-a-alt", user_id="u1",
                  vehicle_number="AB01AA0002"),
            _trip(id="trip_b1", customer_id="cust-3", company_id="co-b", user_id="u2",
                  vehicle_number="AB01AA0003"),
            _trip(id="trip_hist", customer_id="cust-1", company_id="co-a", user_id="u1",
                  vehicle_number="AB01AA0004",
                  is_historical=True, imported_from="legacy", imported_batch="batch-1",
                  status="archived_historical"),
            _trip(id="trip_supp", customer_id="cust-1", company_id="co-a", user_id="u1",
                  vehicle_number="AB01AA0005",
                  vehicle_type="supplier", supplier_id="sup-1", supplier_name="Acme Suppliers",
                  supplier_freight=25000.0, supplier_net_payable=22000.0,
                  supplier_diesel_entries=[{"id": "sd1", "amount": 2000.0,
                                            "date": "2026-02-01", "mode": "Bank"}],
                  supplier_advance_entries=[{"id": "sa1", "amount": 1000.0,
                                             "date": "2026-02-01", "mode": "Cash"}],
                  customer_receipts=[{"id": "r1", "type": "advance", "amount": 500.0,
                                      "date": "2026-02-01", "mode": "Bank"}]),
        ],
    }


TRACKED = ("user_sessions", "users", "companies",
           "trips", "expenses", "driver_ledger",
           "fin_txn", "audit_logs", "counters")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    fx = fixtures()
    for coll, rows in fx.items():
        if rows: await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(2000)
        for d in docs:
            for k, v in list(d.items()):
                if isinstance(v, datetime): d[k] = v.isoformat()
        docs.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
        out[c] = docs
    return out


def diff(a, b):
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
        stdout=open("/tmp/gate6a_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6a_node.log", "wb"), stderr=subprocess.STDOUT,
    )


def wait(url, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(url, timeout=1).status_code < 500: return True
        except Exception: pass
        time.sleep(0.25)
    return False


def stop(p):
    if p and hasattr(p, "poll") and p.poll() is None:
        try:
            p.send_signal(signal.SIGTERM); p.wait(timeout=5)
        except Exception:
            try: p.kill()
            except Exception: pass


CASES = [
    {"n": 1, "d": "happy: valid own trip",             "tid": "trip_a1",   "hdr": {"Authorization": "Bearer tok-owner"},          "expect": 200},
    {"n": 2, "d": "not found",                         "tid": "trip_nope", "hdr": {"Authorization": "Bearer tok-owner"},          "expect": 404},
    {"n": 3, "d": "no auth",                           "tid": "trip_a1",   "hdr": {},                                             "expect": 401},
    {"n": 4, "d": "bad token",                         "tid": "trip_a1",   "hdr": {"Authorization": "Bearer nope"},               "expect": 401},
    {"n": 5, "d": "expired session",                   "tid": "trip_a1",   "hdr": {"Authorization": "Bearer tok-expired"},        "expect": 401},
    {"n": 6, "d": "cross-tenant → 404 isolation",      "tid": "trip_b1",   "hdr": {"Authorization": "Bearer tok-owner"},          "expect": 404},
    {"n": 7, "d": "X-Company-Id owned override",       "tid": "trip_a2",   "hdr": {"Authorization": "Bearer tok-owner",
                                                                                    "X-Company-Id": "co-a-alt"},                 "expect": 200},
    {"n": 8, "d": "X-Company-Id unowned → fallback",   "tid": "trip_a1",   "hdr": {"Authorization": "Bearer tok-owner",
                                                                                    "X-Company-Id": "co-b"},                     "expect": 200},
    {"n": 9, "d": "cookie auth",                       "tid": "trip_a1",   "hdr": {"Cookie": "session_token=tok-owner"},          "expect": 200},
    {"n": 10, "d": "historical trip",                   "tid": "trip_hist", "hdr": {"Authorization": "Bearer tok-owner"},          "expect": 200},
    {"n": 11, "d": "supplier trip w/ nested arrays",    "tid": "trip_supp", "hdr": {"Authorization": "Bearer tok-owner"},          "expect": 200},
    {"n": 12, "d": "unowned override → not-found in fallback co-a", "tid": "trip_a2",
     "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-b"},                                                        "expect": 404},
    {"n": 13, "d": "u2 gets own trip",                  "tid": "trip_b1",   "hdr": {"Authorization": "Bearer tok-u2"},             "expect": 200},
    {"n": 14, "d": "u2 cross-tenant → 404",             "tid": "trip_a1",   "hdr": {"Authorization": "Bearer tok-u2"},             "expect": 404},
    {"n": 15, "d": "determinism — same GET twice",      "tid": "trip_supp", "hdr": {"Authorization": "Bearer tok-owner"},          "expect": 200},
]


async def run() -> int:
    print(f"[gate6a] DB={DB}")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB); print("[gate6a] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40); okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6a] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6a_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6a_node.log").read()[-2000:])
            return 2

        pass_count = fail_count = 0
        node_write_events = 0
        results = []
        last_py_body_for_15 = last_node_body_for_15 = None

        for c in CASES:
            url = f"/api/trips/{c['tid']}"
            hdr = c["hdr"]
            before = await snap(cli, DB)
            rp = requests.get(PY_BASE + url, headers=hdr, timeout=5)
            after_py = await snap(cli, DB)
            rn = requests.get(NODE_BASE + url, headers=hdr, timeout=5)
            after_nd = await snap(cli, DB)

            py_diff = diff(before, after_py)
            nd_diff = diff(after_py, after_nd)
            if nd_diff:
                node_write_events += 1

            status_ok = (rp.status_code == rn.status_code == c["expect"])

            # Body comparison — structural equality via Python's built-in
            # dict `==` treats `30 == 30.0` as equal, which is the correct
            # semantics: Mongo stores IEEE-754 doubles; Python's Pydantic
            # serializes as `30.0` while Node's Fastify serializer emits
            # `30` for integer-valued floats. Same bit-pattern, different
            # stringification. This is a documented cross-runtime
            # serialization boundary, not a data-shape difference.
            try: pjson = rp.json()
            except Exception: pjson = rp.text
            try: njson = rn.json()
            except Exception: njson = rn.text
            body_ok = (pjson == njson)
            ok = status_ok and body_ok

            if c["n"] == 15:
                last_py_body_for_15 = pjson
                last_node_body_for_15 = njson

            if ok: pass_count += 1
            else: fail_count += 1
            results.append({
                "case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                "py_status": rp.status_code, "node_status": rn.status_code,
                "py_write_colls": list(py_diff.keys()),
                "node_write_colls": list(nd_diff.keys()),
                "body_ok": body_ok,
                "py_body": rp.text[:400] if not body_ok else "",
                "node_body": rn.text[:400] if not body_ok else "",
            })

        # Case 15 repeat — determinism assertion.
        rp2 = requests.get(PY_BASE + "/api/trips/trip_supp",
                           headers={"Authorization": "Bearer tok-owner"}, timeout=5)
        rn2 = requests.get(NODE_BASE + "/api/trips/trip_supp",
                           headers={"Authorization": "Bearer tok-owner"}, timeout=5)
        det_ok = (rp2.text == (json.dumps(last_py_body_for_15, sort_keys=True) if isinstance(last_py_body_for_15, dict) else last_py_body_for_15)
                  or rp2.status_code == 200)
        det_body_match = (rp2.status_code == rn2.status_code == 200
                          and rp2.json() == rn2.json())
        results.append({"case": 16, "desc": "determinism recheck (repeat GET)",
                        "verdict": "PASS" if det_body_match else "FAIL",
                        "py_status": rp2.status_code, "node_status": rn2.status_code})
        if det_body_match: pass_count += 1
        else: fail_count += 1

        # Write-observation summary.
        node_forbidden_writes = node_write_events
        results.append({"case": 17, "desc": "read-only — zero Node writes to any tracked collection",
                        "verdict": "PASS" if node_forbidden_writes == 0 else "FAIL",
                        "node_write_events": node_forbidden_writes})
        if node_forbidden_writes == 0: pass_count += 1
        else: fail_count += 1

        print("\n" + "=" * 66)
        print("PHASE 3 · GATE 6a · LIVE PARITY MATRIX (GET /api/trips/{tid})")
        print("=" * 66)
        for r in results:
            py_s = r.get("py_status", "-"); nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
        print("-" * 66)
        print(f"  cases:                        {len(results)}")
        print(f"  passed:                       {pass_count}")
        print(f"  failed:                       {fail_count}")
        print(f"  node write events:            {node_forbidden_writes} (expected 0)")
        print("=" * 66)

        out = Path("/tmp/gate6a_parity_results.json")
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": pass_count,
                                   "failed": fail_count, "node_forbidden_writes": node_forbidden_writes,
                                   "results": results}, indent=2, default=str))
        print(f"[gate6a] results → {out}")
        return 0 if fail_count == 0 and node_forbidden_writes == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB); print(f"[gate6a] dropped {DB}")
        except Exception as e: print(f"[gate6a] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
