"""Phase 3 · Gate 6c · live Python↔Node parity harness for invoice reads.

Covers:
  * GET /api/invoices/{iid}
  * GET /api/invoices/{iid}/notes
  * GET /api/invoices/next-preview

STRICT UAT-DATA PRESERVATION:
  Uses an isolated timestamped DB (`trukvia_gate6c_parity_<ts>`) that is
  dropped in `finally`. Never touches `test_database` nor any existing
  TRUKVIA UAT tenant / login.

Class-B stance (Gate-6c):
  Python `get_invoice` invokes `_recompute_invoice` which may write
  `db.invoices.$set` on totals/tax/balance fields. Node intentionally
  does NOT reproduce that write. Fixtures satisfy invariants I1–I11 so
  Python's write is a no-op (identical values) and responses match
  byte-for-byte.
"""
from __future__ import annotations
import asyncio, json, os, signal, subprocess, sys, time
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any
import requests
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate6c_parity_{int(time.time())}"
PY_PORT, NODE_PORT = 8117, 8118
PY_BASE, NODE_BASE = f"http://127.0.0.1:{PY_PORT}", f"http://127.0.0.1:{NODE_PORT}"


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()
def today_iso() -> str: return datetime.now(timezone.utc).date().isoformat()
def tomorrow_iso() -> str: return (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()


def _fy_from_iso(iso: str) -> str:
    d = date.fromisoformat(iso)
    yr = d.year % 100
    yr_next = (d.year + 1) % 100
    return f"{yr:02d}-{yr_next:02d}" if d.month >= 4 else f"{yr-1:02d}-{yr:02d}"


# ── Fixture builder ──────────────────────────────────────────────────
# Invoices satisfy I1–I11: linked trip totals match stored invoice
# totals so Python's `_recompute_invoice` $set is a no-op.
def _trip(**over: Any) -> dict[str, Any]:
    base = {
        "id": "tr-x", "company_id": "co-a", "user_id": "u1",
        "customer_id": "cust-1", "date": "2026-02-01",
        "vehicle_number": "AB01AA0000", "vehicle_id": "v1", "vehicle_type": "own",
        "loaded_qty": 30.0, "unloaded_qty": 30.0,
        "excess_qty": 0.0, "shortage_qty": 0.0,
        "shortage_amount": 0.0, "excess_amount": 0.0,
        "shortage_amount_override": False, "excess_amount_override": False,
        "total_halting_days": 0, "grace_days": 0, "chargeable_halting_days": 0,
        "halting_rate_per_day": 0.0, "halting_amount": 0.0,
        "halting_amount_override": False,
        "supplier_id": "", "supplier_name": "", "supplier_freight": 0.0,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 0.0,
        "supplier_fixed_amount": 0.0, "supplier_advance": 0.0, "supplier_diesel": 0.0,
        "supplier_halting_days": 0.0, "supplier_halting_rate_per_day": 0.0,
        "supplier_halting_amount": 0.0, "supplier_halting_remarks": "",
        "supplier_diesel_entries": [], "supplier_advance_entries": [],
        "supplier_shortage_deduction": 0.0,
        "supplier_shortage_deduction_override": False,
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
        "rate_per_km_per_ton": 0.0,
        "freight_amount": 1000.0,
        "product_rate_per_mt": 0.0,
        # expenses.shortage_amount=0 & cash_advance_received=0 → no advance ded
        "expenses": {"diesel": 0.0, "toll": 0.0, "batta": 0.0, "repair": 0.0,
                     "other": 0.0, "firewood": 0.0,
                     "diesel_from_customer_qty": 0.0,
                     "diesel_from_customer_rate": 0.0,
                     "diesel_from_customer_amount": 0.0,
                     "cash_advance_received": 0.0, "shortage_amount": 0.0},
        "total_expense": 0.0, "profit": 0.0, "net_settlement": 0.0,
        "status": "invoiced", "is_historical": False,
        "created_at": "2026-02-01T00:00:00+00:00",
        "applied_freight_method": "per_ton_loading",
        "customer_receipts": [],
        "lr_number": "",
        "external_invoice_no": "", "customer_invoice_no": "", "waybill_no": "",
        "freight_amount_override": 0.0, "freight_qty_used": 30.0,
    }
    base.update(over)
    return base


def _invoice(**over: Any) -> dict[str, Any]:
    subtotal = 1000.0
    base = {
        "id": "inv-x", "company_id": "co-a", "user_id": "u1",
        "invoice_number": "INV/25-26/0001", "fy_string": "25-26",
        "customer_id": "cust-1", "invoice_date": "2026-02-01",
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
        "created_at": "2026-02-01T00:00:00+00:00",
        "imported_from": "", "imported_ref": "", "imported_batch": "",
        "is_historical": False,
    }
    base.update(over)
    return base


def _cdn(**over: Any) -> dict[str, Any]:
    base = {
        "id": "cdn-x", "kind": "credit", "company_id": "co-a", "user_id": "u1",
        "note_number": "CN/25-26/0001", "note_date": "2026-02-05",
        "invoice_id": "inv-x", "invoice_number_snapshot": "INV/25-26/0001",
        "customer_id": "cust-1", "reason_code": "rate_correction",
        "reason_text": "harness parity note", "lines": [],
        "subtotal": 100.0, "gst_type": "cgst_sgst",
        "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
        "cgst_amount": 0.0, "sgst_amount": 0.0, "igst_amount": 0.0,
        "total_tax": 0.0, "total_amount": 100.0, "round_off": 0.0, "rcm": True,
        "apply_gst": False,
        "status": "issued", "is_historical": False,
        "created_at": "2026-02-05T00:00:00+00:00",
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
            {"id": "co-a", "user_id": "u1", "is_default": True,
             "state": "Karnataka", "invoice_prefix": "INV",
             "next_invoice_number": 1,
             "next_invoice_number_by_fy": {"25-26": 42}},
            {"id": "co-a-legacy", "user_id": "u1", "is_default": False,
             "state": "Karnataka", "invoice_prefix": "INV",
             "next_invoice_number": 15},
            {"id": "co-a-fyprefix", "user_id": "u1", "is_default": False,
             "state": "Karnataka", "invoice_prefix": "VBK/25-26",
             "next_invoice_number": 1},
            {"id": "co-b", "user_id": "u2", "is_default": True,
             "state": "Karnataka", "invoice_prefix": "INV",
             "next_invoice_number": 1},
        ],
        "customers": [
            {"id": "cust-1", "user_id": "u1", "company_id": "co-a",
             "name": "Acme Traders", "state": "Karnataka"},
            {"id": "cust-b", "user_id": "u2", "company_id": "co-b",
             "name": "Beta Corp", "state": "Karnataka"},
        ],
        "trips": [
            _trip(id="tr-happy"),
            _trip(id="tr-cn"),
            _trip(id="tr-dn"),
            _trip(id="tr-mixed"),
            _trip(id="tr-cnx"),
            _trip(id="tr-legacy", company_id=""),
            _trip(id="tr-hist", is_historical=True, status="archived_historical"),
        ],
        "invoices": [
            _invoice(id="inv-happy", trip_ids=["tr-happy"]),
            _invoice(id="inv-cn", trip_ids=["tr-cn"]),
            _invoice(id="inv-dn", trip_ids=["tr-dn"]),
            _invoice(id="inv-mixed", trip_ids=["tr-mixed"]),
            _invoice(id="inv-cnx", trip_ids=["tr-cnx"]),
            # legacy company_id="" — _recompute_invoice falls back to
            # is_default=True company (co-a, state=Karnataka); customer
            # also Karnataka → gst_type=cgst_sgst → invariants hold.
            _invoice(id="inv-legacy", company_id="", trip_ids=["tr-legacy"]),
            _invoice(id="inv-hist", trip_ids=["tr-hist"],
                     is_historical=True, imported_from="legacy",
                     imported_ref="batch-1", imported_batch="b1"),
            # u2 tenant invoice — for cross-tenant 404 case
            _invoice(id="inv-of-u2", user_id="u2", company_id="co-b",
                     customer_id="cust-b", trip_ids=[]),
        ],
        "credit_debit_notes": [
            _cdn(id="n1", invoice_id="inv-cn", kind="credit",
                 total_amount=200.0, note_date="2026-02-10", status="issued"),
            _cdn(id="n2", invoice_id="inv-dn", kind="debit",
                 total_amount=150.0, note_date="2026-02-12", status="issued"),
            _cdn(id="n3", invoice_id="inv-mixed", kind="credit",
                 total_amount=300.0, note_date="2026-02-06", status="issued"),
            _cdn(id="n4", invoice_id="inv-mixed", kind="debit",
                 total_amount=200.0, note_date="2026-02-07", status="issued"),
            _cdn(id="n5", invoice_id="inv-cnx", kind="credit",
                 total_amount=500.0, note_date="2026-02-03", status="cancelled",
                 cancelled_at=now_iso(), cancelled_by="u1",
                 cancelled_reason="mistake"),
            _cdn(id="n6", invoice_id="inv-cnx", kind="debit",
                 total_amount=250.0, note_date="2026-02-08", status="draft"),
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
        stdout=open("/tmp/gate6c_py.log", "wb"), stderr=subprocess.STDOUT,
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
        stdout=open("/tmp/gate6c_node.log", "wb"), stderr=subprocess.STDOUT,
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
    # ── GET /api/invoices/{iid} ────────────────────────────────────────
    {"n": 1,  "d": "detail: happy",
     "url": "/api/invoices/inv-happy",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200,
     "effective_keys": True},
    {"n": 2,  "d": "detail: issued CN",
     "url": "/api/invoices/inv-cn",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200,
     "effective_keys": True},
    {"n": 3,  "d": "detail: issued DN",
     "url": "/api/invoices/inv-dn",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200,
     "effective_keys": True},
    {"n": 4,  "d": "detail: mixed CN+DN",
     "url": "/api/invoices/inv-mixed",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200,
     "effective_keys": True},
    {"n": 5,  "d": "detail: cancelled+draft excluded",
     "url": "/api/invoices/inv-cnx",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200,
     "effective_keys": True},
    {"n": 6,  "d": "detail: legacy company_id=''",
     "url": "/api/invoices/inv-legacy",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200,
     "effective_keys": True},
    {"n": 7,  "d": "detail: historical invoice",
     "url": "/api/invoices/inv-hist",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200,
     "effective_keys": True},
    {"n": 8,  "d": "detail: not found",
     "url": "/api/invoices/does-not-exist",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 404},
    {"n": 9,  "d": "detail: wrong tenant → 404",
     "url": "/api/invoices/inv-of-u2",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 404},
    {"n": 10, "d": "detail: no auth",
     "url": "/api/invoices/inv-happy",
     "hdr": {}, "expect": 401},
    {"n": 11, "d": "detail: invalid bearer",
     "url": "/api/invoices/inv-happy",
     "hdr": {"Authorization": "Bearer nope"}, "expect": 401},
    {"n": 12, "d": "detail: expired session",
     "url": "/api/invoices/inv-happy",
     "hdr": {"Authorization": "Bearer tok-expired"}, "expect": 401},
    # ── GET /api/invoices/{iid}/notes ─────────────────────────────────
    {"n": 13, "d": "notes: no notes → []",
     "url": "/api/invoices/inv-happy/notes",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 14, "d": "notes: 1 issued CN",
     "url": "/api/invoices/inv-cn/notes",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 15, "d": "notes: cancelled+draft both returned",
     "url": "/api/invoices/inv-cnx/notes",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 16, "d": "notes: mixed statuses ordered by note_date",
     "url": "/api/invoices/inv-mixed/notes",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 17, "d": "notes: unowned invoice → []",
     "url": "/api/invoices/inv-of-u2/notes",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 18, "d": "notes: no auth → 401",
     "url": "/api/invoices/inv-cn/notes",
     "hdr": {}, "expect": 401},
    # ── GET /api/invoices/next-preview ────────────────────────────────
    {"n": 19, "d": "preview: existing FY bucket",
     "url": "/api/invoices/next-preview?invoice_date=2026-02-15",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 200},
    {"n": 20, "d": "preview: legacy scalar fallback (today)",
     "url": f"/api/invoices/next-preview?invoice_date={today_iso()}",
     "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-legacy"},
     "expect": 200},
    {"n": 21, "d": "preview: FY boundary Mar 31",
     "url": "/api/invoices/next-preview?invoice_date=2025-03-31",
     "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-legacy"},
     "expect": 200},
    {"n": 22, "d": "preview: FY boundary Apr 1",
     "url": "/api/invoices/next-preview?invoice_date=2025-04-01",
     "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-legacy"},
     "expect": 200},
    {"n": 23, "d": "preview: future date → 400",
     "url": f"/api/invoices/next-preview?invoice_date={tomorrow_iso()}",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 400},
    {"n": 24, "d": "preview: invalid ISO → 400",
     "url": "/api/invoices/next-preview?invoice_date=2026-02-31",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 400},
    {"n": 25, "d": "preview: missing invoice_date → 422",
     "url": "/api/invoices/next-preview",
     "hdr": {"Authorization": "Bearer tok-owner"}, "expect": 422},
    {"n": 26, "d": "preview: owned X-Company-Id override",
     "url": "/api/invoices/next-preview?invoice_date=2026-02-15",
     "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-fyprefix"},
     "expect": 200},
    {"n": 27, "d": "preview: unowned X-Company-Id → default fallback",
     "url": "/api/invoices/next-preview?invoice_date=2026-02-15",
     "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-b"},
     "expect": 200},
    {"n": 28, "d": "preview: no auth",
     "url": "/api/invoices/next-preview?invoice_date=2026-02-15",
     "hdr": {}, "expect": 401},
    {"n": 29, "d": "preview: fresh company (past FY) → seq=1",
     "url": "/api/invoices/next-preview?invoice_date=2024-01-01",
     "hdr": {"Authorization": "Bearer tok-owner", "X-Company-Id": "co-a-legacy"},
     "expect": 200},
]


async def run() -> int:
    print(f"[gate6c] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        print("[gate6c] seeded")
        py = start_py()
        node = start_node()
        okp = wait(f"{PY_BASE}/api/", 40)
        okn = wait(f"{NODE_BASE}/health/live", 40)
        print(f"[gate6c] py={okp} node={okn}")
        if not (okp and okn):
            if not okp:
                print(open("/tmp/gate6c_py.log").read()[-2000:])
            if not okn:
                print(open("/tmp/gate6c_node.log").read()[-2000:])
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

            # 422 shape divergence contract-tolerated (FastAPI vs Zod detail shape).
            if c["expect"] == 422:
                body_ok = True
            elif c["expect"] == 200 and isinstance(pjson, dict) and isinstance(njson, dict):
                body_ok = (pjson == njson)
            elif c["expect"] == 200 and isinstance(pjson, list) and isinstance(njson, list):
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
            # unused-variable guard
            _ = before

        # Final case — aggregate zero-write assertion across all cases.
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
        print("PHASE 3 · GATE 6c · LIVE PARITY MATRIX (Invoice reads)")
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

        out = Path("/tmp/gate6c_parity_results.json")
        out.write_text(json.dumps({
            "db": DB, "cases": len(results), "passed": pass_count,
            "failed": fail_count, "node_write_events": node_write_events,
            "results": results,
        }, indent=2, default=str))
        print(f"[gate6c] results → {out}")
        return 0 if fail_count == 0 and node_write_events == 0 else 1
    finally:
        stop(py)
        stop(node)
        try:
            await cli.drop_database(DB)
            print(f"[gate6c] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate6c] drop failed: {e}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
