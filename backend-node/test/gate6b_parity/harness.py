"""Phase 3 · Gate 6b · live Python↔Node parity harness for GET /api/trips.

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6b_parity_<ts>`) that is
  dropped in `finally`. Never touches `test_database` nor any existing
  TRUKVIA UAT tenant / login. Fresh multi-company fixtures neutralise the
  Python-only Class-B `_backfill_to_default` write path (it becomes a
  no-op on these fixtures).
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
DB = f"trukvia_gate6b_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8107, 8108
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def _trip(**over: Any) -> dict[str, Any]:
    base = {
        "id": "trip_x", "company_id": "co-a", "user_id": "u1",
        "customer_id": "cust-1", "date": "2026-02-01",
        "vehicle_number": "AB01AA0000", "vehicle_id": "v1", "vehicle_type": "own",
        "loaded_qty": 30.0, "unloaded_qty": 30.0,
        "excess_qty": 0.0, "shortage_qty": 0.0,
        "shortage_amount": 0.0, "excess_amount": 0.0,
        "shortage_amount_override": False, "excess_amount_override": False,
        "total_halting_days": 0, "grace_days": 4, "chargeable_halting_days": 0,
        "halting_rate_per_day": 0.0, "halting_amount": 0.0, "halting_amount_override": False,
        "supplier_id": "", "supplier_name": "", "supplier_freight": 0.0,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 0.0,
        "supplier_fixed_amount": 0.0, "supplier_advance": 0.0, "supplier_diesel": 0.0,
        "supplier_halting_days": 0.0, "supplier_halting_rate_per_day": 0.0,
        "supplier_halting_amount": 0.0, "supplier_halting_remarks": "",
        "supplier_diesel_entries": [], "supplier_advance_entries": [],
        "supplier_shortage_deduction": 0.0, "supplier_shortage_deduction_override": False,
        "supplier_shortage_original_amount": 0.0,
        "supplier_shortage_override_reason": "", "supplier_shortage_override_by": "",
        "supplier_shortage_override_at": "",
        "supplier_other_recoveries": 0.0, "supplier_other_income": 0.0,
        "supplier_net_payable": 0.0, "supplier_quantity": 0.0,
        "supplier_round_trip_kms": 0.0, "supplier_rate_per_km_per_ton": 0.0,
        "supplier_loading_point": "", "supplier_unloading_point": "",
        "supplier_material": "",
        "driver_id": None, "driver_name": "", "driver_mobile": "",
        "product_id": None, "load_details": "", "hsn_sac": "",
        "consignor_id": None, "consignor_name": "",
        "consignee_id": None, "consignee_name": "",
        "ship_site_id": "", "customer_reference_number": "",
        "tons": 30.0, "from_location": "", "to_location": "",
        "from_pincode": "", "to_pincode": "",
        "freight_mode": "per_ton", "rate_per_ton": 1000.0,
        "fixed_amount": 0.0, "round_trip_kms": 0.0,
        "rate_per_km_per_ton": 0.0, "freight_amount": 30000.0,
        "product_rate_per_mt": 0.0,
        "expenses": {}, "total_expense": 0.0, "profit": 0.0, "net_settlement": 0.0,
        "status": "posted", "is_historical": False,
        "created_at": "2026-02-01T00:00:00+00:00",
        "applied_freight_method": "per_ton_loading",
        "customer_receipts": [],
        "lr_number": "",
        "external_invoice_no": "", "customer_invoice_no": "", "waybill_no": "",
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
        "customers": [
            {"id": "cust-1", "user_id": "u1", "company_id": "co-a", "name": "Acme Traders"},
            {"id": "cust-2", "user_id": "u2", "company_id": "co-b", "name": "Beta Corp"},
        ],
        "trips": [
            _trip(id="t1", vehicle_number="AB01AA0001", date="2026-02-05",
                  created_at="2026-02-05T10:00:00+00:00"),
            _trip(id="t2", vehicle_number="AB01AA0002", date="2026-02-03",
                  created_at="2026-02-03T09:00:00+00:00"),
            _trip(id="t3", vehicle_number="ZZ99ZZ9999", date="2026-02-01",
                  created_at="2026-02-01T08:00:00+00:00",
                  customer_id="cust-1", halting_amount=500.0,
                  customer_reference_number=""),
            _trip(id="t4", vehicle_number="AB01AA0004", date="2026-01-15",
                  created_at="2026-01-15T09:00:00+00:00",
                  company_id="co-a-alt", supplier_id="sup-1", status="invoiced"),
            _trip(id="t5", vehicle_number="AB01AA0005", date="2026-02-02",
                  created_at="2026-02-02T07:00:00+00:00",
                  user_id="u2", company_id="co-b", customer_id="cust-2"),
            _trip(id="t6", vehicle_number="AB01AA0006", date="2026-02-04",
                  created_at="2026-02-04T09:00:00+00:00",
                  customer_reference_number="CRN-123"),
            _trip(id="t7", vehicle_number="AB01AA0007", date="2026-01-30",
                  created_at="2026-01-30T09:00:00+00:00",
                  is_historical=True, status="archived_historical"),
        ],
    }


TRACKED = ("user_sessions", "users", "companies", "customers",
           "trips", "vehicles", "suppliers", "expenses", "driver_ledger",
           "fin_txn", "audit_logs", "payment_corrections",
           "invoices", "approvals", "counters")


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    fx = fixtures()
    for coll, rows in fx.items():
        if rows: await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def snap(cli, dbname):
    out = {}
    for c in TRACKED:
        try:
            docs = await cli[dbname][c].find({}, {"_id": 0}).to_list(2000)
        except Exception:
            docs = []
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
        stdout=open("/tmp/gate6b_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6b_node.log", "wb"), stderr=subprocess.STDOUT,
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
        try: p.send_signal(signal.SIGTERM); p.wait(timeout=5)
        except Exception:
            try: p.kill()
            except Exception: pass


CASES = [
    {"n": 1,  "d": "happy: no filters",              "url": "/api/trips",                                            "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 2,  "d": "empty result",                   "url": "/api/trips?customer_id=nope",                           "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 3,  "d": "limit=1 offset=0",               "url": "/api/trips?limit=1&offset=0",                           "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 4,  "d": "limit=1 offset=1",               "url": "/api/trips?limit=1&offset=1",                           "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 5,  "d": "offset beyond",                  "url": "/api/trips?limit=10&offset=100",                        "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 6,  "d": "customer_id",                    "url": "/api/trips?customer_id=cust-1",                         "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 7,  "d": "vehicle_id",                     "url": "/api/trips?vehicle_id=v1",                              "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 8,  "d": "supplier_id (co-a-alt)",         "url": "/api/trips?supplier_id=sup-1",                          "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-alt"}, "expect": 200},
    {"n": 9,  "d": "status=invoiced (co-a-alt)",     "url": "/api/trips?status=invoiced",                            "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-alt"}, "expect": 200},
    {"n": 10, "d": "exact date",                      "url": "/api/trips?date=2026-02-01",                           "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 11, "d": "date_from/date_to",               "url": "/api/trips?date_from=2026-02-03&date_to=2026-02-05",   "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 12, "d": "q → vehicle_number",              "url": "/api/trips?q=ZZ99",                                    "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 13, "d": "q → customer.name",               "url": "/api/trips?q=Acme",                                    "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 14, "d": "halting_only=true",               "url": "/api/trips?halting_only=true",                          "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 15, "d": "missing_cust_ref=true",           "url": "/api/trips?missing_cust_ref=true",                      "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 16, "d": "ids=t1,t2 short-circuit",         "url": "/api/trips?ids=t1,t2",                                  "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 17, "d": "ids='' → []",                     "url": "/api/trips?ids=",                                       "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 18, "d": "no auth",                         "url": "/api/trips",                                            "hdr": {},                                                                    "expect": 401},
    {"n": 19, "d": "bad token",                       "url": "/api/trips",                                            "hdr": {"Authorization": "Bearer nope"},                                     "expect": 401},
    {"n": 20, "d": "expired",                         "url": "/api/trips",                                            "hdr": {"Authorization": "Bearer tok-expired"},                              "expect": 401},
    {"n": 21, "d": "owned X-Company-Id",              "url": "/api/trips",                                            "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-alt"},   "expect": 200},
    {"n": 22, "d": "unowned → default fallback",      "url": "/api/trips",                                            "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-b"},        "expect": 200},
    {"n": 23, "d": "u2 sees only own tenant",         "url": "/api/trips",                                            "hdr": {"Authorization": "Bearer tok-u2"},                                   "expect": 200},
    {"n": 24, "d": "invalid limit → 422",             "url": "/api/trips?limit=0",                                    "hdr": {"Authorization": "Bearer tok-owner"},                                "expect": 422},
    {"n": 25, "d": "date precedence over range",      "url": "/api/trips?date=2026-02-01&date_from=2026-01-01&date_to=2026-12-31", "hdr": {"Authorization": "Bearer tok-owner"},               "expect": 200},
]


def strip_id(rows):
    return [{k: v for k, v in r.items() if k not in ('id', 'created_at')} for r in rows] if isinstance(rows, list) else rows


async def run() -> int:
    print(f"[gate6b] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB); print("[gate6b] seeded")
        py = start_py(); node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40); okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6b] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print(open("/tmp/gate6b_py.log").read()[-2000:])
            if not okn: print(open("/tmp/gate6b_node.log").read()[-2000:])
            return 2

        results = []
        pass_count = fail_count = 0
        node_write_events = 0

        for c in CASES:
            hdr = c["hdr"]
            url = c["url"]
            before = await snap(cli, DB)
            rp = requests.get(PY_BASE + url, headers=hdr, timeout=8)
            after_py = await snap(cli, DB)
            rn = requests.get(NODE_BASE + url, headers=hdr, timeout=8)
            after_nd = await snap(cli, DB)

            nd_diff = diff(after_py, after_nd)
            if nd_diff: node_write_events += 1

            status_ok = (rp.status_code == rn.status_code == c["expect"])
            try: pjson = rp.json()
            except Exception: pjson = rp.text
            try: njson = rn.json()
            except Exception: njson = rn.text

            # 422 shape divergence contract-tolerated.
            if c["expect"] == 422:
                body_ok = True
            else:
                body_ok = (pjson == njson)

            # For 200 with ids short-circuit: verify absence of pagination headers on BOTH.
            hdr_ok = True
            if c["expect"] == 200:
                if url.startswith("/api/trips?ids=") and url != "/api/trips?ids=":
                    hdr_ok = ('x-total-count' not in {k.lower(): v for k, v in rn.headers.items()}
                              and 'x-total-count' not in {k.lower(): v for k, v in rp.headers.items()})
                else:
                    py_tc = rp.headers.get("X-Total-Count"); nd_tc = rn.headers.get("X-Total-Count")
                    py_hm = rp.headers.get("X-Has-More"); nd_hm = rn.headers.get("X-Has-More")
                    hdr_ok = (py_tc == nd_tc and py_hm == nd_hm)

            ok = status_ok and body_ok and hdr_ok
            (pass_count if ok else fail_count).__class__  # placeholder to keep parser happy
            if ok: pass_count += 1
            else: fail_count += 1

            results.append({"case": c["n"], "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                            "py_status": rp.status_code, "node_status": rn.status_code,
                            "hdr_ok": hdr_ok, "body_ok": body_ok, "status_ok": status_ok,
                            "node_write_colls": list(nd_diff.keys()),
                            "py_body": rp.text[:400] if not body_ok else "",
                            "node_body": rn.text[:400] if not body_ok else ""})

        results.append({"case": 26, "desc": "read-only — Node write events across all cases",
                        "verdict": "PASS" if node_write_events == 0 else "FAIL",
                        "node_write_events": node_write_events})
        if node_write_events == 0: pass_count += 1
        else: fail_count += 1

        print("\n" + "=" * 70)
        print("PHASE 3 · GATE 6b · LIVE PARITY MATRIX (GET /api/trips)")
        print("=" * 70)
        for r in results:
            py_s = r.get("py_status", "-"); nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
        print("-" * 70)
        print(f"  cases: {len(results)}   passed: {pass_count}   failed: {fail_count}   node write events: {node_write_events}")
        print("=" * 70)

        out = Path("/tmp/gate6b_parity_results.json")
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": pass_count,
                                   "failed": fail_count, "node_write_events": node_write_events,
                                   "results": results}, indent=2, default=str))
        print(f"[gate6b] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py); stop(node)
        try:
            await cli.drop_database(DB); print(f"[gate6b] dropped {DB} (UAT data untouched)")
        except Exception as e: print(f"[gate6b] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
