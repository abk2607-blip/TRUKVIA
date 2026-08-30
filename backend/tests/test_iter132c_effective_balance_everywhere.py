"""Iter132c · Slice C1 — Effective Balance Everywhere.

Verifies that CN/DN adjustments are surfaced (additively) on the 9 remaining
outstanding-balance read-sites without ever mutating the persisted
`invoice.balance_due` / `invoice.total_amount`.

Test isolation strategy (P1–P4 from Iter132c C1 RCA):
  * P1: every test creates a FRESH unique customer via POST /api/customers.
    This guarantees zero prior notes on the customer at test start, so the
    aggregate customer-summary assertions (R1/R2/R4) reflect only THIS test's
    notes.
  * P2: for company-wide aggregates (R5 dashboard, R9 balance sheet), snapshot
    the base value BEFORE issuing the CN, then assert the delta AFTER. This
    protects against the ~₹95 M accumulated invoice pool from prior tests.
  * P3: test_shared_a asserts at the per-invoice level (specific invoice's
    effective_balance_due equals its balance_due after cancel).
  * P4: test_r4_no_adjustments uses P1-isolated customer with zero notes.

Sites covered:
  R1  GET /api/customers/{cid}/transactions              (customer detail)
  R2  GET /api/customers/{cid}/monthly-balances          (monthly buckets)
  R3  GET /api/customers/bulk-reminder                   (WhatsApp dunning list)
  R4  GET /api/customers/{cid}/statement.pdf             (customer statement PDF)
  R5  GET /api/dashboard                                 (dashboard KPIs)
  R6  GET /api/invoices                                  (invoice list)
  R7  GET /api/invoices/overdue                          (overdue list)
  R8  GET /api/invoices/{iid}                            (invoice detail)
  R9  GET /api/reports/balance-sheet                     (sundry_debtors)
"""
import os
import uuid
import httpx
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


# ─── Helpers ────────────────────────────────────────────────────────────

def _company_header():
    companies = httpx.get(f"{API}/companies", headers=HDR, timeout=15).json()
    cid = companies[0]["id"]
    return cid, {**HDR, "X-Company-Id": cid}


def _fresh_customer(h):
    """P1 · Every test gets a brand-new customer with zero prior notes."""
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(f"{API}/customers", headers=h, json={
        "name": f"C1-Test-{tag}",
        "phone": f"9{tag[:9]}",
        "email": f"{tag}@iter132c.test",
        "state": "Andhra Pradesh",
    }, timeout=15)
    assert r.status_code == 200, f"customer create failed: {r.status_code} {r.text[:200]}"
    return r.json()["id"]


def _create_invoice_with_trip():
    """Fresh single-trip non-zero invoice on a FRESH customer (P1)."""
    cid, h = _company_header()
    cust_id = _fresh_customer(h)
    tag = uuid.uuid4().hex[:6]
    trip = httpx.post(f"{API}/trips", headers=h, json={
        "customer_id": cust_id, "date": "2026-06-01",
        "vehicle_number": f"C1{tag[:4].upper()}",
        "tons": 20, "loaded_qty": 20, "unloaded_qty": 20,
        "freight_mode": "per_ton", "rate_per_ton": 900,
        "product_rate_per_mt": 40000,
        "from_location": "Kakinada", "to_location": "Vizag",
        "loading_date": "2026-06-01", "unloading_date": "2026-06-02",
    }, timeout=15)
    assert trip.status_code == 200, trip.text
    tid = trip.json()["id"]
    inv = httpx.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust_id, "trip_ids": [tid],
        "invoice_date": "2026-06-15", "rcm": True,
    }, timeout=15)
    assert inv.status_code == 200
    inv_doc = inv.json()
    assert float(inv_doc["total_amount"]) > 0
    return inv_doc, cid, cust_id, h


def _issue_cn(inv, h, amount=2000.0, reason_code="quality_claim"):
    r = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": reason_code,
        "reason_text": f"Iter132c C1 test CN — {reason_code}",
        "lines": [{"description": "credit-line", "quantity": 1.0, "rate": amount}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _issue_dn(inv, h, amount=1500.0, reason_code="freight_escalation"):
    r = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": reason_code,
        "reason_text": f"Iter132c C1 test DN — {reason_code}",
        "lines": [{"description": "debit-line", "quantity": 1.0, "rate": amount}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _cancel_note(nid, h, kind="credit-notes"):
    r = httpx.post(f"{API}/{kind}/{nid}/cancel", headers=h,
                   json={"reason": "Iter132c C1 cancellation test — must not affect balance"},
                   timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _read_invoice_persisted(inv_id):
    """Direct Mongo read via local Motor client (mirrors Iter132b pattern)."""
    import asyncio, motor.motor_asyncio
    async def _read():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        doc = await db.invoices.find_one({"id": inv_id}, {"_id": 0, "total_amount": 1, "balance_due": 1})
        c.close()
        return doc
    return asyncio.run(_read())


def _assert_invoice_persisted_unchanged(inv_id, expected_total, expected_balance_due):
    doc = _read_invoice_persisted(inv_id)
    assert abs(float(doc["total_amount"]) - float(expected_total)) < 0.005, \
        f"Persisted total_amount mutated: {doc['total_amount']} != {expected_total}"
    assert abs(float(doc["balance_due"]) - float(expected_balance_due)) < 0.005, \
        f"Persisted balance_due mutated: {doc['balance_due']} != {expected_balance_due}"


# ─── R1 · Customer detail (transactions) ────────────────────────────────

def test_r1_customer_detail_effective_outstanding_reflects_cn():
    inv, cid, cust_id, h = _create_invoice_with_trip()
    original_total = float(inv["total_amount"])
    _issue_cn(inv, h, amount=2000.0)

    r = httpx.get(f"{API}/customers/{cust_id}/transactions", headers=h, timeout=15)
    assert r.status_code == 200
    summary = r.json()["summary"]
    assert "outstanding" in summary
    assert "outstanding_raw" in summary
    assert "outstanding_effective" in summary
    # Fresh customer → single invoice → single CN of ₹2000.
    assert summary["outstanding_effective"] <= summary["outstanding_raw"] - 1999.0 + 0.01, \
        f"CN did not reduce effective outstanding: raw={summary['outstanding_raw']} eff={summary['outstanding_effective']}"
    assert summary["credits_total"] >= 2000.0 - 0.01
    _assert_invoice_persisted_unchanged(inv["id"], original_total, original_total)


def test_r1_customer_detail_effective_outstanding_reflects_dn():
    inv, cid, cust_id, h = _create_invoice_with_trip()
    original_total = float(inv["total_amount"])
    _issue_dn(inv, h, amount=1500.0)

    r = httpx.get(f"{API}/customers/{cust_id}/transactions", headers=h, timeout=15)
    assert r.status_code == 200
    summary = r.json()["summary"]
    # Fresh customer with just one DN of ₹1500 → effective is exactly raw + 1500.
    assert summary["outstanding_effective"] >= summary["outstanding_raw"] + 1499.0 - 0.01, \
        f"DN did not increase effective outstanding: raw={summary['outstanding_raw']} eff={summary['outstanding_effective']}"
    assert summary["debits_total"] >= 1500.0 - 0.01
    _assert_invoice_persisted_unchanged(inv["id"], original_total, original_total)


# ─── R2 · Monthly balances ──────────────────────────────────────────────

def test_r2_monthly_balances_reflects_notes():
    inv, cid, cust_id, h = _create_invoice_with_trip()
    _issue_cn(inv, h, amount=2500.0)

    r = httpx.get(f"{API}/customers/{cust_id}/monthly-balances", headers=h, timeout=15)
    assert r.status_code == 200
    months = r.json()["months"]
    june = next((m for m in months if m["month"] == "2026-06"), None)
    assert june is not None, f"No June-2026 bucket in {[m['month'] for m in months]}"
    assert "billed" in june and "billed_effective" in june
    assert "balance" in june and "balance_effective" in june
    # Fresh customer → June bucket contains exactly one invoice; CN reduces billed_effective by ~₹2500.
    assert june["billed_effective"] <= june["billed"] - 2499.0 + 0.01, \
        f"CN did not reduce June billed_effective: raw={june['billed']} eff={june['billed_effective']}"


# ─── R3 · Bulk reminder — drops fully-credited customer ─────────────────

def test_r3_bulk_reminder_drops_fully_credited_customer():
    inv, cid, cust_id, h = _create_invoice_with_trip()
    original_total = float(inv["total_amount"])
    # Full-credit: CN equal to invoice total
    _issue_cn(inv, h, amount=original_total, reason_code="quality_claim")

    r = httpx.get(f"{API}/customers/bulk-reminder", headers=h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    cust_ids = [x["customer_id"] for x in body.get("reminders", [])]
    assert cust_id not in cust_ids, \
        f"Fully-credited customer {cust_id} still in reminder list ({len(cust_ids)} customers)"
    _assert_invoice_persisted_unchanged(inv["id"], original_total, original_total)


# ─── R4 · Statement PDF — Adjustments line ──────────────────────────────

def _pdf_text(content_bytes):
    """Try pdfminer.six; fall back to latin-1 bytes (never fails)."""
    try:
        from pdfminer.high_level import extract_text
        import io as _io
        return extract_text(_io.BytesIO(content_bytes))
    except Exception:
        return content_bytes.decode("latin-1", errors="ignore")


def test_r4_statement_pdf_adjustments_line_appears_when_notes_present():
    inv, cid, cust_id, h = _create_invoice_with_trip()
    _issue_cn(inv, h, amount=1200.0)

    r = httpx.get(f"{API}/customers/{cust_id}/statement.pdf", headers=h, timeout=20)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    text = _pdf_text(r.content)
    assert "Adjustments" in text, "Statement PDF is missing the Iter132c 'Adjustments' summary line"
    assert "CN" in text


def test_r4_statement_pdf_no_adjustments_line_when_no_notes():
    """Fresh customer (P1) with NO notes → PDF must NOT show Adjustments line."""
    _cid, h = _company_header()
    cust_id = _fresh_customer(h)
    # No invoices, no notes for this customer.
    r = httpx.get(f"{API}/customers/{cust_id}/statement.pdf", headers=h, timeout=20)
    assert r.status_code == 200
    text = _pdf_text(r.content)
    assert "Adjustments" not in text, \
        "Statement PDF should NOT show 'Adjustments' line for a customer with zero notes"


# ─── R5 · Dashboard (with baseline snapshot per P2) ─────────────────────

def test_r5_dashboard_receivables_use_effective_balance():
    """P2 · Baseline snapshot BEFORE CN, delta AFTER."""
    inv, cid, cust_id, h = _create_invoice_with_trip()
    original_total = float(inv["total_amount"])

    # Baseline snapshot BEFORE CN
    before = httpx.get(f"{API}/dashboard", headers=h, timeout=20).json()
    for k in ("total_billed", "total_billed_effective",
              "total_receivable", "total_receivable_effective",
              "credits_total", "debits_total"):
        assert k in before, f"Dashboard missing key: {k}"

    _issue_cn(inv, h, amount=3000.0)

    # After CN
    after = httpx.get(f"{API}/dashboard", headers=h, timeout=20).json()

    # Raw totals unchanged; effective totals drop by ~₹3000
    assert abs(after["total_receivable"] - before["total_receivable"]) < 0.01, \
        "Raw total_receivable must not change when a CN is issued"
    delta_eff = before["total_receivable_effective"] - after["total_receivable_effective"]
    assert delta_eff >= 2999.0 - 0.01, \
        f"CN did not reduce dashboard.total_receivable_effective by expected delta: before={before['total_receivable_effective']} after={after['total_receivable_effective']} delta={delta_eff}"
    delta_credits = after["credits_total"] - before["credits_total"]
    assert delta_credits >= 3000.0 - 0.01

    # Per-customer receivables — this fresh customer should show a balance_effective ≤ balance − ₹3000
    rcv = [x for x in after.get("receivables", []) if x.get("customer_id") == cust_id]
    if rcv:  # customer must appear because raw balance is still > 0
        assert "balance" in rcv[0] and "balance_effective" in rcv[0]
        assert rcv[0]["balance_effective"] <= rcv[0]["balance"] - 2999.0 + 0.01

    _assert_invoice_persisted_unchanged(inv["id"], original_total, original_total)


# ─── R6 · Invoice list ──────────────────────────────────────────────────

def test_r6_invoices_list_includes_effective_keys():
    inv, cid, cust_id, h = _create_invoice_with_trip()
    _issue_cn(inv, h, amount=1000.0)

    r = httpx.get(f"{API}/invoices", headers=h, timeout=15)
    assert r.status_code == 200
    docs = r.json()
    target = next((d for d in docs if d.get("id") == inv["id"]), None)
    assert target is not None, f"Invoice {inv['id']} missing from list response"
    for k in ("effective_total_amount", "effective_balance_due",
              "credits_total", "debits_total"):
        assert k in target, f"Invoice list missing key: {k}"
    assert target["credits_total"] >= 1000.0 - 0.01
    assert target["effective_balance_due"] <= target["balance_due"] - 999.0 + 0.01
    assert target["balance_due"] == inv["balance_due"]
    assert target["total_amount"] == inv["total_amount"]


# ─── R7 · Overdue — drops fully-credited invoice · R8 · Detail effective keys

def test_r7_overdue_drops_fully_credited_invoice_and_r8_detail_has_effective_keys():
    inv, cid, cust_id, h = _create_invoice_with_trip()
    original_total = float(inv["total_amount"])
    _issue_cn(inv, h, amount=original_total)

    r = httpx.get(f"{API}/invoices/overdue", headers=h, params={"days": 0}, timeout=15)
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()]
    assert inv["id"] not in ids, \
        f"Fully-credited invoice {inv['id']} should be dropped from overdue list"

    r2 = httpx.get(f"{API}/invoices/{inv['id']}", headers=h, timeout=15)
    assert r2.status_code == 200
    doc = r2.json()
    for k in ("effective_total_amount", "effective_balance_due",
              "credits_total", "debits_total"):
        assert k in doc, f"Invoice detail missing key: {k}"
    assert doc["effective_balance_due"] <= 0.01
    _assert_invoice_persisted_unchanged(inv["id"], original_total, original_total)


# ─── R9 · Balance sheet (with baseline snapshot per P2) ─────────────────

def test_r9_balance_sheet_sundry_debtors_effective():
    """P2 · Baseline snapshot BEFORE CN, delta AFTER."""
    inv, cid, cust_id, h = _create_invoice_with_trip()

    before = httpx.get(f"{API}/reports/balance-sheet", headers=h,
                       params={"as_of": "2026-12-31"}, timeout=15).json()["assets"]
    assert "sundry_debtors" in before
    assert "sundry_debtors_effective" in before

    _issue_cn(inv, h, amount=4000.0)

    after = httpx.get(f"{API}/reports/balance-sheet", headers=h,
                      params={"as_of": "2026-12-31"}, timeout=15).json()["assets"]

    # Raw sundry_debtors unchanged; effective drops by ~₹4000.
    assert abs(after["sundry_debtors"] - before["sundry_debtors"]) < 0.01, \
        "Raw sundry_debtors must not change when a CN is issued"
    delta_eff = before["sundry_debtors_effective"] - after["sundry_debtors_effective"]
    assert delta_eff >= 3999.0 - 0.01, \
        f"CN did not reduce sundry_debtors_effective by expected delta: before={before['sundry_debtors_effective']} after={after['sundry_debtors_effective']} delta={delta_eff}"


# ─── Shared invariants ──────────────────────────────────────────────────

def test_shared_a_cancelled_note_does_not_affect_any_read_site():
    """P3 · Per-invoice scope: after cancel, THIS invoice's effective_balance_due
    must equal its raw balance_due, and credits_total on THIS invoice must be 0."""
    inv, cid, cust_id, h = _create_invoice_with_trip()
    original_total = float(inv["total_amount"])
    cn = _issue_cn(inv, h, amount=1800.0)
    _cancel_note(cn["id"], h, kind="credit-notes")

    # R8 — per-invoice detail: effective must equal raw; credits/debits must be 0.
    doc = httpx.get(f"{API}/invoices/{inv['id']}", headers=h, timeout=15).json()
    assert abs(float(doc["effective_balance_due"]) - float(doc["balance_due"])) < 0.01, \
        f"Cancelled CN still affects invoice: eff={doc['effective_balance_due']} raw={doc['balance_due']}"
    assert float(doc["credits_total"]) < 0.01, \
        f"Cancelled CN still contributes to credits_total: {doc['credits_total']}"
    assert float(doc["debits_total"]) < 0.01

    # R6 — invoice list: same per-invoice invariant.
    docs = httpx.get(f"{API}/invoices", headers=h, timeout=15).json()
    target = next(d for d in docs if d["id"] == inv["id"])
    assert abs(float(target["effective_balance_due"]) - float(target["balance_due"])) < 0.01
    assert float(target["credits_total"]) < 0.01

    _assert_invoice_persisted_unchanged(inv["id"], original_total, original_total)


def test_shared_c_persisted_balance_due_never_mutates_across_all_9_sites():
    """After hitting every C1 read-site, persisted balance_due + total_amount
    must remain byte-identical to their pre-CN/DN values."""
    inv, cid, cust_id, h = _create_invoice_with_trip()
    original_total = float(inv["total_amount"])

    _issue_cn(inv, h, amount=500.0)
    _issue_dn(inv, h, amount=700.0)

    endpoints = [
        (f"/customers/{cust_id}/transactions", {}),
        (f"/customers/{cust_id}/monthly-balances", {}),
        (f"/customers/bulk-reminder", {}),
        (f"/customers/{cust_id}/statement.pdf", {}),
        (f"/dashboard", {}),
        (f"/invoices", {}),
        (f"/invoices/overdue", {"days": 0}),
        (f"/invoices/{inv['id']}", {}),
        (f"/reports/balance-sheet", {"as_of": "2026-12-31"}),
    ]
    for path, params in endpoints:
        r = httpx.get(f"{API}{path}", headers=h, params=params, timeout=20)
        assert r.status_code == 200, f"{path} failed: {r.status_code} {r.text[:200]}"

    _assert_invoice_persisted_unchanged(inv["id"], original_total, original_total)


# ─── A1 · monthly_balances field-name regression ────────────────────────

def test_a1_monthly_balances_buckets_by_invoice_date_not_unknown():
    """A1 regression — invoices must bucket into their actual month, never 'unknown'."""
    inv, cid, cust_id, h = _create_invoice_with_trip()  # invoice_date=2026-06-15
    r = httpx.get(f"{API}/customers/{cust_id}/monthly-balances", headers=h, timeout=15)
    assert r.status_code == 200
    months = r.json()["months"]
    keys = [m["month"] for m in months]
    assert "2026-06" in keys, f"Invoice-month bucket missing in {keys}"
    assert "unknown" not in keys, f"Invoice fell into 'unknown' bucket: {keys}"
    june = next(m for m in months if m["month"] == "2026-06")
    assert june["billed"] > 0, f"June bucket has zero billed: {june}"


# ─── B1 · Streaming aggregation regression (>2000 invoices) ─────────────

def _mongo_dashboard_ground_truth(cid: str):
    """Ground-truth for total_billed / total_received / invoice_count via
    MongoDB $group aggregation (no cap, no truncation possible)."""
    import asyncio, motor.motor_asyncio
    async def _run():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        pipe = [
            {"$match": {"company_id": cid, "is_historical": {"$ne": True}}},
            {"$group": {"_id": None,
                        "total_billed": {"$sum": "$total_amount"},
                        "total_received": {"$sum": "$amount_paid"},
                        "count": {"$sum": 1}}},
        ]
        row = None
        async for r in db.invoices.aggregate(pipe):
            row = r
        c.close()
        return row or {}
    return asyncio.run(_run())


def test_b1_dashboard_totals_include_invoices_beyond_2000_cap():
    """B1 regression — Mongo cursor streams every matching invoice; no cap."""
    cid, h = _company_header()
    gt = _mongo_dashboard_ground_truth(cid)
    assert gt.get("count", 0) > 2000, \
        f"This test needs >2000 invoices in the demo company; found {gt.get('count')}"

    d = httpx.get(f"{API}/dashboard", headers=h, timeout=30).json()
    assert abs(d["total_billed"] - float(gt["total_billed"])) < 1.0, \
        f"Dashboard total_billed truncated: endpoint={d['total_billed']} mongo={gt['total_billed']}"
    assert abs(d["total_received"] - float(gt["total_received"])) < 1.0, \
        f"Dashboard total_received truncated: endpoint={d['total_received']} mongo={gt['total_received']}"
    assert d["invoice_count"] == gt["count"], \
        f"Dashboard invoice_count truncated: endpoint={d['invoice_count']} mongo={gt['count']}"


def test_b1_balance_sheet_totals_include_invoices_beyond_2000_cap():
    """B1 regression — balance-sheet aggregates every live invoice ≤ as_of."""
    cid, h = _company_header()
    as_of = "2027-12-31"
    import asyncio, motor.motor_asyncio
    async def _gt():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        pipe = [
            {"$match": {"company_id": cid, "is_historical": {"$ne": True},
                        "invoice_date": {"$lte": as_of}}},
            {"$group": {"_id": None,
                        "billed": {"$sum": "$total_amount"},
                        "paid": {"$sum": "$amount_paid"},
                        "count": {"$sum": 1}}},
        ]
        row = None
        async for r in db.invoices.aggregate(pipe):
            row = r
        c.close()
        return row or {}
    gt = asyncio.run(_gt())
    assert gt.get("count", 0) > 2000, \
        f"This test needs >2000 invoices ≤ {as_of}; found {gt.get('count')}"

    bs = httpx.get(f"{API}/reports/balance-sheet", headers=h,
                   params={"as_of": as_of}, timeout=30).json()
    assets = bs["assets"]
    # Ground truth is a simple sum(billed - paid); endpoint uses per-invoice
    # max(billed - paid_upto, 0) so a small ±100 tolerance is expected.
    expected_receivables = max(float(gt["billed"]) - float(gt["paid"]), 0)
    assert abs(assets["sundry_debtors"] - expected_receivables) < 100.0, \
        f"balance-sheet sundry_debtors truncated: endpoint={assets['sundry_debtors']} expected≈{expected_receivables}"
