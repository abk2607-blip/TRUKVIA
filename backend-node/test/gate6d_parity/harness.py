"""Phase 3 · Gate 6d · live Python↔Node parity harness for invoice list reads.

Covers:
  * GET /api/invoices
  * GET /api/invoices/overdue

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6d_parity_<ts>`) that
  is dropped in `finally`. Never touches `test_database` nor any
  existing TRUKVIA UAT tenant / login.

Class-B stance (Gate-6d):
  Python `list_invoices` invokes `_backfill_to_default(user_id)` which
  fan-outs `update_many` across ten collections when any doc lacks
  `company_id`. Node intentionally does NOT reproduce that write.
  Fixtures pre-assign `company_id` on every row so Python's backfill
  matches zero documents and the observation is a no-op.
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
DB = f"trukvia_gate6d_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8121, 8122
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()
def today_iso() -> str: return datetime.now(timezone.utc).date().isoformat()


def _invoice(**over: Any) -> dict[str, Any]:
    subtotal = 1000.0
    base = {
        "id": "inv-x", "company_id": "co-a", "user_id": "u1",
        "invoice_number": "INV/25-26/0001", "fy_string": "25-26",
        "customer_id": "cust-1", "invoice_date": "2020-01-01",
        "trip_ids": ["tr-x"],
        "subtotal": subtotal, "hsn_sac": "996791",
        "freight_total": subtotal, "halting_total": 0.0, "excess_total": 0.0,
        "shortage_total": 0.0, "diesel_deduction_total": 0.0,
        "advance_deduction_total": 0.0,
        "gst_type": "cgst_sgst", "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
        "cgst_amount": 25.0, "sgst_amount": 25.0, "igst_amount": 0.0,
        "total_tax": 50.0, "gross_total": subtotal, "round_off": 0.0,
        "total_amount": subtotal, "rcm": True,
        "payments": [], "amount_paid": 0.0, "balance_due": subtotal,
        "share_token": None, "notes": "",
        "created_at": "2020-01-01T00:00:00+00:00",
        "imported_from": "", "imported_ref": "", "imported_batch": "",
        "is_historical": False,
    }
    base.update(over)
    return base


def _cdn(**over: Any) -> dict[str, Any]:
    base = {
        "id": "cdn-x", "kind": "credit", "company_id": "co-a", "user_id": "u1",
        "note_number": "CN/25-26/0001", "note_date": "2020-06-01",
        "invoice_id": "inv-x", "invoice_number_snapshot": "INV/25-26/0001",
        "customer_id": "cust-1", "reason_code": "rate_correction",
        "reason_text": "harness parity note", "lines": [],
        "subtotal": 100.0, "gst_type": "cgst_sgst",
        "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
        "cgst_amount": 0.0, "sgst_amount": 0.0, "igst_amount": 0.0,
        "total_tax": 0.0, "total_amount": 100.0, "round_off": 0.0, "rcm": True,
        "apply_gst": False,
        "status": "issued", "is_historical": False,
        "created_at": "2020-06-01T00:00:00+00:00",
        "cancelled_at": None, "cancelled_by": None, "cancelled_reason": None,
        "created_by": "u1", "approved_by": None, "approved_at": None,
        "deadline_override": False, "share_token": None,
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
            # pre-assigned company_id + is_default=True → Python
            # `_backfill_to_default` finds an existing default and its
            # `_backfill_company_id` fan-out matches zero rows.
            {"id": "co-a", "user_id": "u1", "is_default": True,
             "state": "Karnataka", "invoice_prefix": "INV",
             "next_invoice_number": 1},
            {"id": "co-b", "user_id": "u2", "is_default": True,
             "state": "Karnataka", "invoice_prefix": "INV",
             "next_invoice_number": 1},
        ],
        "customers": [
            {"id": "cust-1", "user_id": "u1", "company_id": "co-a",
             "name": "Acme Traders", "phone": "+91-90000-11111",
             "email": "ops@acme.example", "state": "Karnataka"},
            {"id": "cust-b", "user_id": "u2", "company_id": "co-b",
             "name": "Beta Corp", "phone": "+91-90000-22222",
             "email": "ops@beta.example", "state": "Karnataka"},
        ],
        # Sufficient set to exercise every branch of both routes.
        "invoices": [
            _invoice(id="inv-a", created_at="2020-01-01T00:00:00+00:00",
                     invoice_date="2020-01-01"),
            _invoice(id="inv-b", created_at="2020-06-01T00:00:00+00:00",
                     invoice_date="2020-06-01"),
            _invoice(id="inv-c", created_at="2021-01-01T00:00:00+00:00",
                     invoice_date="2021-01-01"),
            _invoice(id="inv-hist", is_historical=True,
                     imported_from="legacy", imported_batch="b1",
                     created_at="2019-06-01T00:00:00+00:00",
                     invoice_date="2019-06-01"),
            _invoice(id="inv-overdue-a", invoice_date="2020-01-01",
                     balance_due=500.0, amount_paid=500.0,
                     created_at="2020-01-01T00:00:00+00:00"),
            _invoice(id="inv-overdue-b", invoice_date="2020-03-01",
                     balance_due=1000.0, amount_paid=0.0,
                     created_at="2020-03-01T00:00:00+00:00"),
            _invoice(id="inv-paid", invoice_date="2020-01-01",
                     balance_due=0.0, amount_paid=1000.0,
                     created_at="2020-01-01T00:00:00+00:00"),
            _invoice(id="inv-recent", invoice_date=today_iso(),
                     balance_due=1000.0, amount_paid=0.0,
                     created_at=f"{today_iso()}T00:00:00+00:00"),
            _invoice(id="inv-offset", invoice_date="2020-01-01",
                     balance_due=1000.0, amount_paid=0.0,
                     created_at="2020-01-01T00:00:00+00:00"),
            # u2 tenant
            _invoice(id="inv-u2", user_id="u2", company_id="co-b",
                     customer_id="cust-b",
                     invoice_date="2020-01-01", balance_due=500.0,
                     amount_paid=0.0,
                     created_at="2020-01-01T00:00:00+00:00"),
        ],
        "credit_debit_notes": [
            _cdn(id="n-off", invoice_id="inv-offset", kind="credit",
                 total_amount=1000.0, note_date="2020-06-01", status="issued"),
            _cdn(id="n-part", invoice_id="inv-overdue-b", kind="credit",
                 total_amount=300.0, note_date="2020-04-01", status="issued"),
            _cdn(id="n-draft", invoice_id="inv-overdue-a", kind="credit",
                 total_amount=999.0, note_date="2020-02-01", status="draft"),
        ],
    }


TRACKED = ("user_sessions", "users", "companies", "customers", "trips",
           "invoices", "credit_debit_notes", "vehicles", "suppliers",
           "expenses", "driver_ledger_entries", "fin_txn", "audit_logs",
           "payment_corrections", "approvals", "counters",
           "fin_hook_failures", "files", "fuel", "drivers", "products",
           "parties")


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
        stdout=open("/tmp/gate6d_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6d_node.log", "wb"), stderr=subprocess.STDOUT,
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
            try:
                p.kill()
            except Exception:
                pass


CASES = [
    # ── GET /api/invoices ────────────────────────────────────────────
    {"n": 1,  "d": "list: happy (co-a, DESC created_at)",
     "url": "/api/invoices",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 2,  "d": "list: empty tenant → []",
     "url": "/api/invoices",
     "hdr": {"Authorization": "Bearer tok-u2", "X-Company-Id": "co-a"},
     "expect": 200},
    {"n": 3,  "d": "list: u2 → own invoice only",
     "url": "/api/invoices",
     "hdr": {"Authorization": "Bearer tok-u2"}, "expect": 200},
    {"n": 4,  "d": "list: no auth",
     "url": "/api/invoices",
     "hdr": {}, "expect": 401},
    {"n": 5,  "d": "list: invalid bearer",
     "url": "/api/invoices",
     "hdr": {"Authorization": "Bearer nope"}, "expect": 401},
    {"n": 6,  "d": "list: expired session",
     "url": "/api/invoices",
     "hdr": {"Authorization": "Bearer tok-expired"}, "expect": 401},
    # ── GET /api/invoices/overdue ────────────────────────────────────
    {"n": 7,  "d": "overdue: default days=30",
     "url": "/api/invoices/overdue",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 8,  "d": "overdue: days=7",
     "url": "/api/invoices/overdue?days=7",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 9,  "d": "overdue: days=99999 → []",
     "url": "/api/invoices/overdue?days=99999",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 10, "d": "overdue: days=0 (today cutoff)",
     "url": "/api/invoices/overdue?days=0",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 11, "d": "overdue: non-int days → 422",
     "url": "/api/invoices/overdue?days=abc",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 422},
    {"n": 12, "d": "overdue: u2 → own overdue only",
     "url": "/api/invoices/overdue?days=30",
     "hdr": {"Authorization": "Bearer tok-u2"}, "expect": 200},
    {"n": 13, "d": "overdue: no auth",
     "url": "/api/invoices/overdue",
     "hdr": {}, "expect": 401},
    {"n": 14, "d": "overdue: expired session",
     "url": "/api/invoices/overdue",
     "hdr": {"Authorization": "Bearer tok-expired"}, "expect": 401},
]


async def run() -> int:
    print(f"[gate6d] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6d] seeded")
        py = start_py()
        node = start_node()
        okp = wait(f"{PY_BASE}/api/", 45)
        okn = wait(f"{NODE_BASE}/health/live", 45)
        print(f"[gate6d] py={okp} node={okn}")
        if not (okp and okn):
            if not okp:
                print(open("/tmp/gate6d_py.log").read()[-2000:])
            if not okn:
                print(open("/tmp/gate6d_node.log").read()[-2000:])
            return 2

        results = []
        pass_count = fail_count = 0
        node_write_events = 0

        # Warm the Python server once so its startup migration
        # (`server.py:1106-1125` bulk update_many on trips) settles
        # BEFORE the per-case snapshot windows — mirrors the diagnosis
        # documented in the Gate-6c UAT+Lock-Clearance report.
        try:
            requests.get(f"{PY_BASE}/api/invoices",
                         headers={"Authorization": "Bearer tok-owner"},
                         timeout=10)
        except Exception:
            pass
        time.sleep(1.0)

        for c in CASES:
            hdr = c["hdr"]
            url = c["url"]
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

            if c["expect"] == 422:
                body_ok = True  # FastAPI vs Zod detail-shape tolerance
            elif c["expect"] == 200 and isinstance(pjson, list) and isinstance(njson, list):
                body_ok = (pjson == njson)
            elif c["expect"] == 200 and isinstance(pjson, dict) and isinstance(njson, dict):
                body_ok = (pjson == njson)
            else:
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
        print("PHASE 3 · GATE 6d · LIVE PARITY MATRIX (Invoice list reads)")
        print("=" * 72)
        for r in results:
            py_s = r.get("py_status", "-")
            nd_s = r.get("node_status", "-")
            print(f"  [{r['verdict']}] case {r['case']:>2} py={py_s} node={nd_s}  {r['desc']}")
            if r["verdict"] == "FAIL":
                print(f"      py_body : {r.get('py_body', '')}")
                print(f"      node_body: {r.get('node_body', '')}")
                if r.get("node_write_colls"):
                    print(f"      writes  : {r['node_write_colls']}")
        print("-" * 72)
        print(f"  cases: {len(results)}   passed: {pass_count}   failed: {fail_count}   node write events: {node_write_events}")
        print("=" * 72)

        out = Path("/tmp/gate6d_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6d] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py)
        stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6d] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6d] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
