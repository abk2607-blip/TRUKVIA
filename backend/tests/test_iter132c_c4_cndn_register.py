"""Iter132c C4 · Credit Note / Debit Note Register — targeted test suite (T1-T20).

Contract (LOCKED before impl):
  * `db.credit_debit_notes` is the SINGLE source of truth. The endpoint
    never recomputes tax, totals, sign, or effective balance.
  * JSON, XLSX, PDF are PURE PROJECTIONS of one canonical payload
    (`_cndn_register_payload`).
  * Streaming Mongo cursor + $in customer/invoice preloads — NO
    to_list() truncation. Proven at 10 000 notes in T19.
  * Filter matrix (from/to/kind/customer_id/status/reason_code) narrows
    the query in Mongo (not in Python), and reconciliation compares
    endpoint counts/totals to Mongo $group over the identical filter.
  * Register row values MUST equal persisted note fields (verbatim).
  * Effective-balance parity: sum of register credit_total per invoice_id
    == services._effective_invoice_totals(inv, notes)["credits_total"]
    (and same for debits).

Isolation:
  Every seed uses a fresh randomly-prefixed note_number and a fresh
  test customer per test function. Seeds are cleaned up in a `finally`
  block. NO shared state with C3.1/C3.2/C3.5 seeds.
"""
import os
import io
import uuid
import asyncio
import httpx
import openpyxl
import motor.motor_asyncio
import fitz
import pytest
from datetime import datetime, timezone


BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


# ─── Helpers ──────────────────────────────────────────────────────────────

def _company_header():
    r = httpx.get(f"{API}/companies", headers=HDR, timeout=15)
    assert r.status_code == 200, r.text
    cid = r.json()[0]["id"]
    return cid, {**HDR, "X-Company-Id": cid}


def _current_uid() -> str:
    r = httpx.get(f"{API}/auth/me", headers=HDR, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


def _mongo():
    """Return (client, db). Caller closes client in finally."""
    client = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


def _tag() -> str:
    return f"c4t_{uuid.uuid4().hex[:8]}"


async def _seed_customer(db, uid, cid, *, name, state="Telangana", gstin=""):
    d = {
        "id": f"cust_{uuid.uuid4().hex[:12]}",
        "user_id": uid, "company_id": cid,
        "name": name, "state": state, "gstin": (gstin or "").upper(),
        "phone": "", "email": "",
    }
    await db.customers.insert_one(d)
    return d["id"]


async def _seed_invoice(db, uid, cid, cust_id, *, date="2029-05-15", inv_num=None,
                        total=10000.0, gst_type="cgst_sgst"):
    inv_id = f"inv_{uuid.uuid4().hex[:12]}"
    doc = {
        "id": inv_id, "user_id": uid, "company_id": cid,
        "invoice_number": inv_num or f"C4T/{uuid.uuid4().hex[:6].upper()}",
        "invoice_date": date, "customer_id": cust_id, "trip_ids": [],
        "subtotal": total, "cgst_amount": 0.0, "sgst_amount": 0.0,
        "igst_amount": 500.0 if gst_type == "igst" else 0.0,
        "total_tax": 500.0 if gst_type == "igst" else 0.0,
        "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
        "total_amount": total + (500.0 if gst_type == "igst" else 0.0),
        "gst_type": gst_type, "rcm": False, "status": "issued",
        "amount_paid": 0.0, "balance_due": total, "payments": [],
    }
    await db.invoices.insert_one(doc)
    return inv_id, doc["invoice_number"]


async def _seed_note(db, uid, cid, inv_id, inv_num, cust_id, *,
                     kind="credit", note_date="2029-05-20",
                     total=1000.0, subtotal=None, apply_gst=True,
                     reason_code="rate_correction", status="issued",
                     note_number=None, gst_type="cgst_sgst"):
    """Persist a CN/DN doc byte-for-byte in the shape services.py expects."""
    sub = subtotal if subtotal is not None else total
    cgst = sgst = igst = 0.0
    total_tax = 0.0
    if apply_gst:
        if gst_type == "igst":
            igst = round(sub * 0.05, 2)
        else:
            cgst = round(sub * 0.025, 2); sgst = round(sub * 0.025, 2)
        total_tax = round(cgst + sgst + igst, 2)
    nid = f"cdn_{uuid.uuid4().hex[:12]}"
    doc = {
        "id": nid, "user_id": uid, "company_id": cid,
        "kind": kind,
        "note_number": note_number or (f"C4CN/{uuid.uuid4().hex[:6].upper()}" if kind == "credit" else f"C4DN/{uuid.uuid4().hex[:6].upper()}"),
        "note_date": note_date,
        "invoice_id": inv_id, "invoice_number_snapshot": inv_num,
        "customer_id": cust_id,
        "reason_code": reason_code,
        "reason_text": "Seed for C4 test — automated fixture.",
        "lines": [{"id": f"cdnl_{uuid.uuid4().hex[:8]}", "description": "test",
                    "hsn_sac": "996791", "quantity": 1.0, "rate": sub,
                    "taxable_value": sub}],
        "subtotal": sub,
        "gst_type": gst_type,
        "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
        "cgst_amount": cgst, "sgst_amount": sgst, "igst_amount": igst,
        "total_tax": total_tax,
        "total_amount": round(sub + total_tax, 2),
        "round_off": 0.0,
        "rcm": True,
        "apply_gst": bool(apply_gst),
        "status": status,
        "created_by": uid, "approved_by": uid if status == "issued" else None,
        "approved_at": datetime.now(timezone.utc).isoformat() if status == "issued" else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_historical": False, "deadline_override": False,
    }
    await db.credit_debit_notes.insert_one(doc)
    return nid, doc


def _get_json(h, **params):
    return httpx.get(f"{API}/reports/cndn-register", headers=h,
                     params=params, timeout=180)


def _get_xlsx(h, **params):
    return httpx.get(f"{API}/reports/cndn-register.xlsx", headers=h,
                     params=params, timeout=180)


def _get_pdf(h, **params):
    return httpx.get(f"{API}/reports/cndn-register.pdf", headers=h,
                     params=params, timeout=180)


# ─── T1 · Canonical JSON shape and content-type ─────────────────────────

def test_t1_json_endpoint_reachable_and_canonical_shape():
    _, h = _company_header()
    r = _get_json(h, **{"from": "2029-05-01", "to": "2029-05-31"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    d = r.json()
    # Canonical top-level keys
    for k in ("period", "filters", "company_id", "issuer_gstin",
              "note_count", "rows", "kpis", "tax_summary",
              "by_reason", "by_customer", "reconciliation", "warnings"):
        assert k in d, f"canonical key missing: {k}"
    for k in ("total_count", "credit_count", "credit_total",
              "debit_count", "debit_total", "net_amount",
              "gst_applied_count", "gst_applied_total",
              "gst_excluded_count", "gst_excluded_total",
              "issued_count", "draft_count", "cancelled_count"):
        assert k in d["kpis"], f"kpi key missing: {k}"
    for k in ("taxable", "cgst", "sgst", "igst", "total_tax", "total_amount"):
        assert k in d["tax_summary"], f"tax_summary key missing: {k}"


# ─── T2 · Bad kind returns 400 ──────────────────────────────────────────

def test_t2_bad_kind_returns_400():
    _, h = _company_header()
    r = _get_json(h, **{"from": "2029-05-01", "to": "2029-05-31", "kind": "bogus"})
    assert r.status_code == 400


# ─── T3 · Bad status and reversed dates return 400 ──────────────────────

def test_t3_bad_status_and_reversed_dates_return_400():
    _, h = _company_header()
    r = _get_json(h, **{"from": "2029-05-01", "to": "2029-05-31", "status": "weird"})
    assert r.status_code == 400
    r = _get_json(h, **{"from": "2029-05-31", "to": "2029-05-01"})
    assert r.status_code == 400
    r = _get_json(h, **{"from": "bad-date"})
    assert r.status_code == 400


# ─── T4 · Defaults to current-month range when from/to omitted ──────────

def test_t4_default_month_range_when_omitted():
    _, h = _company_header()
    r = _get_json(h)
    assert r.status_code == 200
    d = r.json()
    p = d["period"]
    today = datetime.now(timezone.utc).date()
    assert p["start"].startswith(f"{today.year:04d}-{today.month:02d}-01")
    assert p["end"].startswith(f"{today.year:04d}-{today.month:02d}-")


# ─── T5 · kind filter narrows rows to credit-only or debit-only ─────────

def test_t5_kind_filter_narrows_correctly():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        tag = _tag()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{tag}-Cust", state="Karnataka")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2029-05-05")
            await _seed_note(db, uid, cid, iid, inum, cust, kind="credit",
                             note_date="2029-05-10", total=1000.0)
            await _seed_note(db, uid, cid, iid, inum, cust, kind="debit",
                             note_date="2029-05-11", total=500.0)

            # customer_id filter isolates our seed
            j_all = _get_json(h, **{"from": "2029-05-01", "to": "2029-05-31",
                                    "kind": "all", "customer_id": cust}).json()
            assert j_all["note_count"] == 2
            kinds = {r["kind"] for r in j_all["rows"]}
            assert kinds == {"credit", "debit"}

            j_cn = _get_json(h, **{"from": "2029-05-01", "to": "2029-05-31",
                                   "kind": "credit", "customer_id": cust}).json()
            assert j_cn["note_count"] == 1
            assert {r["kind"] for r in j_cn["rows"]} == {"credit"}

            j_dn = _get_json(h, **{"from": "2029-05-01", "to": "2029-05-31",
                                   "kind": "debit", "customer_id": cust}).json()
            assert j_dn["note_count"] == 1
            assert {r["kind"] for r in j_dn["rows"]} == {"debit"}
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T6 · customer_id filter narrows to that customer only ──────────────

def test_t6_customer_id_filter():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cA = await _seed_customer(db, uid, cid, name=f"{_tag()}-A", state="Karnataka")
            cB = await _seed_customer(db, uid, cid, name=f"{_tag()}-B", state="Telangana")
            iA, iAn = await _seed_invoice(db, uid, cid, cA, date="2029-06-01")
            iB, iBn = await _seed_invoice(db, uid, cid, cB, date="2029-06-02")
            await _seed_note(db, uid, cid, iA, iAn, cA, note_date="2029-06-03")
            await _seed_note(db, uid, cid, iB, iBn, cB, note_date="2029-06-04")

            jA = _get_json(h, **{"from": "2029-06-01", "to": "2029-06-30", "customer_id": cA}).json()
            assert jA["note_count"] == 1
            assert jA["rows"][0]["customer_id"] == cA
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid,
                                                    "customer_id": {"$in": [cA, cB]}})
            await db.invoices.delete_many({"user_id": uid, "id": {"$in": [iA, iB]}})
            await db.customers.delete_many({"user_id": uid, "id": {"$in": [cA, cB]}})
            client.close()
    asyncio.run(_run())


# ─── T7 · reason_code filter ────────────────────────────────────────────

def test_t7_reason_code_filter_narrows_correctly():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-R", state="Karnataka")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2029-07-01")
            await _seed_note(db, uid, cid, iid, inum, cust, note_date="2029-07-05",
                             reason_code="sales_return")
            await _seed_note(db, uid, cid, iid, inum, cust, note_date="2029-07-06",
                             reason_code="post_invoice_discount")

            j = _get_json(h, **{"from": "2029-07-01", "to": "2029-07-31",
                                "customer_id": cust,
                                "reason_code": "sales_return"}).json()
            assert j["note_count"] == 1
            assert j["rows"][0]["reason_code"] == "sales_return"
            assert j["rows"][0]["reason_code_gstr1_9b"] == "01"
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T8 · status filter (issued vs draft vs cancelled) ──────────────────

def test_t8_status_filter_isolates_lifecycle_stage():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-S", state="Karnataka")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2029-08-01")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2029-08-05", status="issued")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2029-08-06", status="draft",
                             note_number="")
            j_issued = _get_json(h, **{"from": "2029-08-01", "to": "2029-08-31",
                                       "customer_id": cust, "status": "issued"}).json()
            assert j_issued["note_count"] == 1
            j_draft = _get_json(h, **{"from": "2029-08-01", "to": "2029-08-31",
                                      "customer_id": cust, "status": "draft"}).json()
            assert j_draft["note_count"] == 1
            j_all = _get_json(h, **{"from": "2029-08-01", "to": "2029-08-31",
                                    "customer_id": cust, "status": "all"}).json()
            assert j_all["note_count"] == 2
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T9 · Signed amount convention (credit = -, debit = +) ──────────────

def test_t9_signed_amount_sign_convention():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-SIGN", state="Karnataka")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2029-09-01")
            _, cn_doc = await _seed_note(db, uid, cid, iid, inum, cust, kind="credit",
                                         note_date="2029-09-05", total=2000.0)
            _, dn_doc = await _seed_note(db, uid, cid, iid, inum, cust, kind="debit",
                                         note_date="2029-09-06", total=700.0)
            j = _get_json(h, **{"from": "2029-09-01", "to": "2029-09-30",
                                "customer_id": cust}).json()
            by_kind = {r["kind"]: r for r in j["rows"]}
            assert by_kind["credit"]["signed_amount"] == -by_kind["credit"]["total_amount"]
            assert by_kind["debit"]["signed_amount"] == by_kind["debit"]["total_amount"]
            # Net = debit_total - credit_total
            assert abs(j["kpis"]["net_amount"] - (by_kind["debit"]["total_amount"]
                                                  - by_kind["credit"]["total_amount"])) < 0.01
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T10 · Row values equal persisted note fields byte-for-byte ─────────

def test_t10_row_values_equal_persisted_note_fields():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-V", state="Karnataka",
                                        gstin="29AAAAA1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2029-10-01",
                                            gst_type="igst")
            _, seed = await _seed_note(db, uid, cid, iid, inum, cust,
                                       note_date="2029-10-05", total=1500.0,
                                       gst_type="igst", apply_gst=True)
            j = _get_json(h, **{"from": "2029-10-01", "to": "2029-10-31",
                                "customer_id": cust}).json()
            row = j["rows"][0]
            for k in ("subtotal", "cgst_amount", "sgst_amount", "igst_amount",
                      "total_tax", "total_amount", "round_off",
                      "cgst_rate", "sgst_rate", "igst_rate", "gst_type",
                      "apply_gst", "rcm", "reason_code", "reason_text",
                      "note_number", "note_date", "status", "customer_id"):
                assert row[k] == seed[k], f"drift on {k}: register={row[k]} db={seed[k]}"
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T11 · Fail-loud reconciliation vs Mongo ground truth ───────────────

def test_t11_reconciliation_reconciled_when_matches_mongo_ground_truth():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-REC", state="Karnataka")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2029-11-01")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2029-11-05", total=1000.0)
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2029-11-06", total=2000.0)
            j = _get_json(h, **{"from": "2029-11-01", "to": "2029-11-30",
                                "customer_id": cust}).json()
            rec = j["reconciliation"]
            assert rec["reconciled"] is True, rec
            assert rec["endpoint_row_count"] == rec["ground_truth_row_count"] == 2
            assert abs(rec["endpoint_total"] - rec["ground_truth_total"]) < 0.01
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T12 · KPI derivation matches ─────────────────────────────────────

def test_t12_kpis_match_derived_sums():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-K", state="Karnataka")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2029-12-01")
            await _seed_note(db, uid, cid, iid, inum, cust, kind="credit",
                             note_date="2029-12-05", total=1000.0)
            await _seed_note(db, uid, cid, iid, inum, cust, kind="credit",
                             note_date="2029-12-06", total=250.0)
            await _seed_note(db, uid, cid, iid, inum, cust, kind="debit",
                             note_date="2029-12-07", total=400.0, apply_gst=False)
            j = _get_json(h, **{"from": "2029-12-01", "to": "2029-12-31",
                                "customer_id": cust}).json()
            k = j["kpis"]
            # Derived from persisted totals: CN sum, DN sum
            cn_sum = sum(r["total_amount"] for r in j["rows"] if r["kind"] == "credit")
            dn_sum = sum(r["total_amount"] for r in j["rows"] if r["kind"] == "debit")
            assert k["credit_count"] == 2
            assert k["debit_count"] == 1
            assert abs(k["credit_total"] - cn_sum) < 0.01
            assert abs(k["debit_total"] - dn_sum) < 0.01
            assert abs(k["net_amount"] - (dn_sum - cn_sum)) < 0.01
            assert k["gst_excluded_count"] == 1
            assert k["gst_applied_count"] == 2
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T13 · Tax summary equals sum of persisted note tax fields ──────────

def test_t13_tax_summary_matches_persisted_sums():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-T", state="Karnataka")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2030-01-01",
                                            gst_type="cgst_sgst")
            await _seed_note(db, uid, cid, iid, inum, cust, note_date="2030-01-05",
                             total=1000.0, gst_type="cgst_sgst")
            await _seed_note(db, uid, cid, iid, inum, cust, note_date="2030-01-06",
                             total=2000.0, gst_type="cgst_sgst")
            j = _get_json(h, **{"from": "2030-01-01", "to": "2030-01-31",
                                "customer_id": cust}).json()
            tax = j["tax_summary"]
            expected_taxable = round(sum(r["subtotal"] for r in j["rows"]), 2)
            expected_cgst    = round(sum(r["cgst_amount"] for r in j["rows"]), 2)
            expected_sgst    = round(sum(r["sgst_amount"] for r in j["rows"]), 2)
            expected_total   = round(sum(r["total_amount"] for r in j["rows"]), 2)
            assert abs(tax["taxable"] - expected_taxable) < 0.01
            assert abs(tax["cgst"] - expected_cgst) < 0.01
            assert abs(tax["sgst"] - expected_sgst) < 0.01
            assert abs(tax["total_amount"] - expected_total) < 0.01
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T14 · By-reason breakdown carries GSTR-1 §9B remap ─────────────────

def test_t14_by_reason_carries_gstr1_9b_remap():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-9B", state="Karnataka")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2030-02-01")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2030-02-05", reason_code="sales_return")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2030-02-06", reason_code="post_invoice_discount")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2030-02-07", reason_code="other")
            j = _get_json(h, **{"from": "2030-02-01", "to": "2030-02-28",
                                "customer_id": cust}).json()
            br_map = {b["reason_code"]: b for b in j["by_reason"]}
            assert br_map["sales_return"]["gstr1_9b_reason_code"] == "01"
            assert br_map["post_invoice_discount"]["gstr1_9b_reason_code"] == "02"
            assert br_map["other"]["gstr1_9b_reason_code"] == "07"
            # Every row also carries the remap
            for r in j["rows"]:
                assert r["reason_code_gstr1_9b"] in {"01", "02", "03", "04", "05", "06", "07", "08"}
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T15 · XLSX endpoint + 4 sheets named correctly (approved spec) ─────

def test_t15_xlsx_endpoint_and_four_sheets():
    """Approved C4 spec locks the sheet names + order to EXACTLY:
        Summary · Register · By_Customer · By_Reason
    NO Credit_Notes / Debit_Notes sheets."""
    _, h = _company_header()
    r = _get_xlsx(h, **{"from": "2030-03-01", "to": "2030-03-31"})
    assert r.status_code == 200
    assert r.headers["content-type"] == \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "Register", "By_Customer", "By_Reason"], \
        f"XLSX sheet names drifted from approved C4 spec: {wb.sheetnames}"


# ─── T16 · XLSX Register + By_Customer + By_Reason parity vs JSON ───────

def test_t16_xlsx_register_and_by_customer_parity_with_json():
    """Register sheet row count MUST equal len(payload['rows']) — flat
    register, both credit and debit rows in one sheet. By_Customer sheet
    row count MUST equal len(payload['by_customer']). By_Reason sheet
    row count MUST equal len(payload['by_reason'])."""
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            tag = _tag()
            # Seed across two customers so By_Customer has >1 group.
            cA = await _seed_customer(db, uid, cid, name=f"{tag}-A", state="Karnataka")
            cB = await _seed_customer(db, uid, cid, name=f"{tag}-B", state="Karnataka")
            iA, iAn = await _seed_invoice(db, uid, cid, cA, date="2030-04-01")
            iB, iBn = await _seed_invoice(db, uid, cid, cB, date="2030-04-01")
            await _seed_note(db, uid, cid, iA, iAn, cA, kind="credit",
                             note_date="2030-04-05", total=1000.0)
            await _seed_note(db, uid, cid, iA, iAn, cA, kind="credit",
                             note_date="2030-04-06", total=1500.0)
            await _seed_note(db, uid, cid, iB, iBn, cB, kind="debit",
                             note_date="2030-04-07", total=800.0)
            params = {"from": "2030-04-01", "to": "2030-04-30"}
            # Narrow by customer set via two independent queries then
            # verify each sheet against the payload the endpoint returns
            # with the wider filter that covers both seeds.
            paramsAB = {"from": "2030-04-01", "to": "2030-04-30"}
            j = _get_json(h, **paramsAB).json()
            r = _get_xlsx(h, **paramsAB)
            wb = openpyxl.load_workbook(io.BytesIO(r.content))

            reg_rows = max(wb["Register"].max_row - 4, 0)
            bc_rows  = max(wb["By_Customer"].max_row - 4, 0)
            br_rows  = max(wb["By_Reason"].max_row - 4, 0)

            # Register row count == flat JSON rows count (CN + DN).
            assert reg_rows == len(j["rows"]), \
                f"Register rows {reg_rows} != len(rows) {len(j['rows'])}"
            # By_Customer row count == canonical by_customer length.
            assert bc_rows == len(j["by_customer"]), \
                f"By_Customer rows {bc_rows} != len(by_customer) {len(j['by_customer'])}"
            # By_Reason row count == canonical by_reason length.
            assert br_rows == len(j["by_reason"]), \
                f"By_Reason rows {br_rows} != len(by_reason) {len(j['by_reason'])}"

            # By_Customer VALUES must equal the canonical aggregation
            # (no independent recomputation in the exporter).
            ws = wb["By_Customer"]
            xlsx_bc = []
            for row_idx in range(5, 5 + bc_rows):
                xlsx_bc.append({
                    "customer_name": ws.cell(row_idx, 1).value or "",
                    "customer_id":   ws.cell(row_idx, 2).value or "",
                    "count":         int(ws.cell(row_idx, 3).value or 0),
                    "credit_total":  float(ws.cell(row_idx, 4).value or 0),
                    "debit_total":   float(ws.cell(row_idx, 5).value or 0),
                    "signed_amount": float(ws.cell(row_idx, 6).value or 0),
                })
            def _key(x): return (x.get("customer_id") or "", x.get("customer_name") or "")
            xlsx_sorted = sorted(xlsx_bc, key=_key)
            json_bc = [{
                "customer_name": bc.get("customer_name") or "\u2014",
                "customer_id":   bc.get("customer_id") or "",
                "count":         int(bc.get("count", 0) or 0),
                "credit_total":  float(bc.get("credit_total", 0) or 0),
                "debit_total":   float(bc.get("debit_total", 0) or 0),
                "signed_amount": float(bc.get("signed_amount", 0) or 0),
            } for bc in j["by_customer"]]
            json_sorted = sorted(json_bc, key=_key)
            # Restrict to just our two seeded customer_ids so we don't
            # collide with any pre-existing demo-tenant notes.
            wanted = {cA, cB}
            xlsx_ours = [r for r in xlsx_sorted if r["customer_id"] in wanted]
            json_ours = [r for r in json_sorted if r["customer_id"] in wanted]
            assert xlsx_ours == json_ours, \
                f"By_Customer drift.\n xlsx={xlsx_ours}\n json={json_ours}"
        finally:
            await db.credit_debit_notes.delete_many(
                {"user_id": uid, "customer_id": {"$in": [cA, cB]}})
            await db.invoices.delete_many({"user_id": uid, "id": {"$in": [iA, iB]}})
            await db.customers.delete_many({"user_id": uid, "id": {"$in": [cA, cB]}})
            client.close()
    asyncio.run(_run())


# ─── T17 · PDF endpoint returns A4 landscape with Page X of Y ───────────

def test_t17_pdf_endpoint_a4_landscape_and_page_x_of_y():
    _, h = _company_header()
    r = _get_pdf(h, **{"from": "2030-05-01", "to": "2030-05-31"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    d = fitz.open(stream=r.content, filetype="pdf")
    rect = d[0].rect
    assert rect.width > rect.height, "PDF is not landscape"
    assert abs(rect.width - 842) < 5 and abs(rect.height - 595) < 5
    txt = d[0].get_text()
    assert f"Page 1 of {d.page_count}" in txt, "Page X of Y footer missing"


# ─── T18 · PDF disclosure banner + rupee glyph present ──────────────────

def test_t18_pdf_disclosure_and_rupee_glyph():
    _, h = _company_header()
    r = _get_pdf(h, **{"from": "2030-06-01", "to": "2030-06-30"})
    assert r.status_code == 200
    d = fitz.open(stream=r.content, filetype="pdf")
    page1 = d[0].get_text()
    assert "\u20b9" in page1, "U+20B9 (₹) glyph missing"
    assert "\ufffd" not in page1, "PDF contains replacement chars"
    assert "NOT a GST portal upload file" in page1


# ─── T19 · High-volume streaming (10 000 notes) — no truncation ─────────

@pytest.mark.slow
def test_t19_streaming_10k_notes_via_mongo_seed():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        tag = _tag()
        seed_month = "2035-03"
        seed_from = f"{seed_month}-01"
        seed_to = f"{seed_month}-31"
        try:
            # 200 customers to keep $in preload bounded but not trivial.
            customer_ids = []
            for i in range(200):
                cust = await _seed_customer(db, uid, cid,
                                            name=f"{tag}-c{i:03d}",
                                            state="Karnataka",
                                            gstin=f"29AAAAA{i:04d}A1Z5")
                customer_ids.append(cust)

            # Preload invoices per customer, one each
            inv_map = {}
            invoice_ids = []
            for cust in customer_ids:
                iid, inum = await _seed_invoice(db, uid, cid, cust, date=seed_from)
                inv_map[cust] = (iid, inum)
                invoice_ids.append(iid)

            # 10 000 notes across those customers, deterministic minor total.
            batch = []
            for i in range(10000):
                cust = customer_ids[i % 200]
                iid, inum = inv_map[cust]
                doc = {
                    "id": f"cdn_{tag}_{i:05d}",
                    "user_id": uid, "company_id": cid,
                    "kind": "credit" if i % 3 == 0 else "debit",
                    "note_number": f"{tag}/{i:05d}",
                    "note_date": f"{seed_month}-{(i % 28) + 1:02d}",
                    "invoice_id": iid,
                    "invoice_number_snapshot": inum,
                    "customer_id": cust,
                    "reason_code": "rate_correction",
                    "reason_text": "seed T19",
                    "lines": [],
                    "subtotal": 100.0,
                    "gst_type": "cgst_sgst",
                    "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
                    "cgst_amount": 2.5, "sgst_amount": 2.5, "igst_amount": 0.0,
                    "total_tax": 5.0, "total_amount": 105.0, "round_off": 0.0,
                    "rcm": True, "apply_gst": True,
                    "status": "issued", "created_by": uid,
                    "approved_by": uid,
                    "approved_at": "2035-03-15T00:00:00+00:00",
                    "created_at": "2035-03-15T00:00:00+00:00",
                    "is_historical": False, "deadline_override": False,
                }
                batch.append(doc)
                if len(batch) >= 500:
                    await db.credit_debit_notes.insert_many(batch)
                    batch = []
            if batch:
                await db.credit_debit_notes.insert_many(batch)

            r = _get_json(h, **{"from": seed_from, "to": seed_to})
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["note_count"] >= 10000, \
                f"streaming truncated: expected >=10000, got {j['note_count']}"
            assert j["reconciliation"]["reconciled"] is True
            # KPIs must match derived counts
            assert j["kpis"]["credit_count"] + j["kpis"]["debit_count"] \
                == j["kpis"]["total_count"]

            # PDF must also succeed at this volume
            rp = _get_pdf(h, **{"from": seed_from, "to": seed_to})
            assert rp.status_code == 200
            doc = fitz.open(stream=rp.content, filetype="pdf")
            assert doc.page_count > 5, \
                f"expected many-page PDF for 10k notes, got {doc.page_count}"
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid,
                                                    "id": {"$regex": f"^cdn_{tag}_"}})
            await db.invoices.delete_many({"user_id": uid,
                                           "id": {"$in": invoice_ids}})
            await db.customers.delete_many({"user_id": uid,
                                            "id": {"$in": customer_ids}})
            client.close()

    asyncio.run(_run())


# ─── T20 · Static column-width envelope guardrail ≤ 273mm ───────────────

def test_t20_pdf_col_widths_within_landscape_envelope():
    from pdf.cndn_register import _all_col_widths_mm
    for name, widths in _all_col_widths_mm():
        total = sum(widths)
        assert total <= 273.0, f"{name} sum={total}mm exceeds 273mm envelope"


# ─── Bonus · effective-balance parity (Iter132a helper) ─────────────────

def test_t21_effective_balance_parity_with_services_helper():
    """Register's per-invoice CN + DN sums must equal what
    services._effective_invoice_totals(inv, notes) computes when handed
    the same set of persisted notes. This is the invariant that keeps
    the register consistent with the invoice's effective balance
    displayed everywhere else."""
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-EB", state="Karnataka")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2030-07-01",
                                            total=100000.0)
            await _seed_note(db, uid, cid, iid, inum, cust, kind="credit",
                             note_date="2030-07-05", total=5000.0)
            await _seed_note(db, uid, cid, iid, inum, cust, kind="credit",
                             note_date="2030-07-06", total=2500.0)
            await _seed_note(db, uid, cid, iid, inum, cust, kind="debit",
                             note_date="2030-07-07", total=1000.0)

            j = _get_json(h, **{"from": "2030-07-01", "to": "2030-07-31",
                                "customer_id": cust}).json()
            cn = sum(r["total_amount"] for r in j["rows"] if r["kind"] == "credit")
            dn = sum(r["total_amount"] for r in j["rows"] if r["kind"] == "debit")

            # Now call the LOCKED helper directly with the raw persisted notes.
            from services import _effective_invoice_totals
            inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
            notes = await db.credit_debit_notes.find(
                {"user_id": uid, "invoice_id": iid, "status": "issued"},
                {"_id": 0}).to_list(500)
            eff = await _effective_invoice_totals(inv, notes)
            assert abs(eff["credits_total"] - round(cn, 2)) < 0.01
            assert abs(eff["debits_total"] - round(dn, 2)) < 0.01
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())
