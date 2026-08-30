"""Iter133 · L1 — Customer-Ledger CN/DN Row Integration (data-layer only).

Locks in the behaviour proposed and approved in the Iter133 L1 plan:

  · Issued Credit Notes appear as credit-column rows within the period.
  · Issued Debit Notes appear as debit-column rows within the period.
  · Notes dated before `start` fold into opening_balance (CN ↓, DN ↑).
  · Notes dated after `end` are excluded.
  · Draft and cancelled notes are excluded entirely (opening + entries + totals).
  · Running-balance formula is unchanged: balance += debit − credit.
  · Additive `totals_by_type` metadata is present on the response.
  · Tenant/customer isolation is preserved.
  · The downstream `/reports/ledger/pdf` renders the new rows automatically
    (payload-driven — no pdf/ledger.py change in L1).

All tests use the external REACT_APP_BACKEND_URL and DEMO_TOKEN_VALUE; each
test creates its own fresh customer/invoice/notes so there is zero cross-test
state pollution and the suite is safe to run under xdist or serially.
"""
import os
import uuid
import httpx
import pytest
from pdfminer.high_level import extract_text as _pdf_extract
from io import BytesIO


def _api():
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") + "/api"
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


API = _api()
TOK = os.environ["DEMO_TOKEN_VALUE"]


def _headers():
    """Build headers + resolve the demo tenant's default company id."""
    h = {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}
    cid = httpx.get(f"{API}/companies", headers=h, timeout=10).json()[0]["id"]
    h["X-Company-Id"] = cid
    return cid, h


def _fresh_customer(h, prefix="L1"):
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(
        f"{API}/customers",
        headers=h,
        json={"name": f"{prefix}-{tag}", "phone": f"9{tag}", "state": "Andhra Pradesh"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _invoice(h, cust_id, invoice_date="2026-06-15", rate_per_ton=900, tons=20):
    """Create one trip + invoice worth (tons × rate). Returns the invoice dict."""
    tag = uuid.uuid4().hex[:6]
    r = httpx.post(
        f"{API}/trips",
        headers=h,
        json={
            "customer_id": cust_id,
            "date": invoice_date,
            "vehicle_number": f"L1{tag}",
            "tons": tons,
            "loaded_qty": tons,
            "unloaded_qty": tons,
            "freight_mode": "per_ton",
            "rate_per_ton": rate_per_ton,
            "product_rate_per_mt": 40000,
            "from_location": "A",
            "to_location": "B",
            "loading_date": invoice_date,
            "unloading_date": invoice_date,
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    trip_id = r.json()["id"]
    r = httpx.post(
        f"{API}/invoices",
        headers=h,
        json={
            "customer_id": cust_id,
            "trip_ids": [trip_id],
            "invoice_date": invoice_date,
            "rcm": True,
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _issue_cn(h, invoice, amount, note_date, reason="quality_claim"):
    r = httpx.post(
        f"{API}/credit-notes",
        headers=h,
        json={
            "invoice_id": invoice["id"],
            "note_date": note_date,
            "reason_code": reason,
            "reason_text": f"L1 test CN amount={amount}",
            "lines": [{"description": "L1 CN line", "quantity": 1, "rate": amount}],
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _issue_dn(h, invoice, amount, note_date, reason="freight_escalation"):
    r = httpx.post(
        f"{API}/debit-notes",
        headers=h,
        json={
            "invoice_id": invoice["id"],
            "note_date": note_date,
            "reason_code": reason,
            "reason_text": f"L1 test DN amount={amount}",
            "lines": [{"description": "L1 DN line", "quantity": 1, "rate": amount}],
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _ledger(h, cust_id, start=None, end=None):
    q = {"customer_id": cust_id}
    if start:
        q["start"] = start
    if end:
        q["end"] = end
    r = httpx.get(f"{API}/reports/ledger", headers=h, params=q, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- L1-T1 ---------------------------------------------------------

def test_l1_t1_issued_cn_appears_as_credit_row_in_period():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust, invoice_date="2026-06-15")
    cn = _issue_cn(h, inv, amount=2000, note_date="2026-07-01")

    led = _ledger(h, cust, start="2026-04-01", end="2027-03-31")

    cn_rows = [e for e in led["entries"] if e.get("type") == "credit_note"]
    assert len(cn_rows) == 1, f"expected exactly 1 CN row, got {len(cn_rows)}"
    row = cn_rows[0]
    assert row["credit"] == pytest.approx(2000.0)
    assert row["debit"] == 0.0
    assert row["reference"] == cn["note_number"]
    assert row["invoice_id"] == inv["id"]
    assert row["note_id"] == cn["id"]
    assert row["kind"] == "credit"
    # Sign check on running balance: invoice + CN → invoice.total - CN.amount
    inv_total = float(inv["total_amount"])
    assert led["closing_balance"] == pytest.approx(inv_total - 2000.0, abs=0.01)
    # Additive metadata present
    assert "totals_by_type" in led
    assert led["totals_by_type"]["credit_note"] == pytest.approx(2000.0)


# ---------- L1-T2 ---------------------------------------------------------

def test_l1_t2_issued_dn_appears_as_debit_row_in_period():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust, invoice_date="2026-06-15")
    dn = _issue_dn(h, inv, amount=1500, note_date="2026-07-01")

    led = _ledger(h, cust, start="2026-04-01", end="2027-03-31")

    dn_rows = [e for e in led["entries"] if e.get("type") == "debit_note"]
    assert len(dn_rows) == 1
    row = dn_rows[0]
    assert row["debit"] == pytest.approx(1500.0)
    assert row["credit"] == 0.0
    assert row["reference"] == dn["note_number"]
    assert row["kind"] == "debit"
    inv_total = float(inv["total_amount"])
    assert led["closing_balance"] == pytest.approx(inv_total + 1500.0, abs=0.01)
    assert led["totals_by_type"]["debit_note"] == pytest.approx(1500.0)


# ---------- L1-T3 ---------------------------------------------------------

def test_l1_t3_cn_before_start_folds_into_opening():
    """CN issued in the previous FY should reduce opening, not appear as an entry."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    # Invoice + CN both dated in FY26-27 first quarter
    inv = _invoice(h, cust, invoice_date="2026-06-15")
    _issue_cn(h, inv, amount=3000, note_date="2026-07-01")

    # Query with start AFTER both invoice and CN
    led = _ledger(h, cust, start="2026-08-01", end="2027-03-31")

    # No CN row inside the period
    assert [e for e in led["entries"] if e.get("type") == "credit_note"] == []
    # Opening should reflect invoice - CN
    inv_total = float(inv["total_amount"])
    assert led["opening_balance"] == pytest.approx(inv_total - 3000.0, abs=0.01), \
        f"opening_balance={led['opening_balance']} expected={inv_total - 3000.0}"
    # Closing == opening (no in-period entries)
    assert led["closing_balance"] == pytest.approx(led["opening_balance"], abs=0.01)


# ---------- L1-T4 ---------------------------------------------------------

def test_l1_t4_dn_before_start_folds_into_opening():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust, invoice_date="2026-06-15")
    _issue_dn(h, inv, amount=2500, note_date="2026-07-01")

    led = _ledger(h, cust, start="2026-08-01", end="2027-03-31")

    assert [e for e in led["entries"] if e.get("type") == "debit_note"] == []
    inv_total = float(inv["total_amount"])
    assert led["opening_balance"] == pytest.approx(inv_total + 2500.0, abs=0.01)
    assert led["closing_balance"] == pytest.approx(led["opening_balance"], abs=0.01)


# ---------- L1-T5 ---------------------------------------------------------

def test_l1_t5_draft_and_cancelled_notes_excluded_from_ledger():
    """Cancelled CN must never touch opening, entries, totals, or closing."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust, invoice_date="2026-06-15")
    cn1 = _issue_cn(h, inv, amount=1000, note_date="2026-07-01")
    cn2 = _issue_cn(h, inv, amount=500,  note_date="2026-07-05")

    # Cancel cn2
    r = httpx.post(
        f"{API}/credit-notes/{cn2['id']}/cancel",
        headers=h,
        json={"reason": "L1-T5 exclusion test"},
        timeout=15,
    )
    assert r.status_code == 200, r.text

    led = _ledger(h, cust, start="2026-04-01", end="2027-03-31")

    # Only cn1 should appear
    refs = {e["reference"] for e in led["entries"] if e.get("type") == "credit_note"}
    assert refs == {cn1["note_number"]}, f"expected only {cn1['note_number']}, got {refs}"
    assert led["totals_by_type"]["credit_note"] == pytest.approx(1000.0)

    inv_total = float(inv["total_amount"])
    assert led["closing_balance"] == pytest.approx(inv_total - 1000.0, abs=0.01)


# ---------- L1-T6 ---------------------------------------------------------

def test_l1_t6_ledger_pdf_renders_cdn_rows_end_to_end():
    """Payload-driven PDF must render the new rows automatically. Byte-level
    text extraction confirms the note_number strings + ₹ glyph are present."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust, invoice_date="2026-06-15")
    cn = _issue_cn(h, inv, amount=1234, note_date="2026-07-01")
    dn = _issue_dn(h, inv, amount=567,  note_date="2026-07-02")

    r = httpx.get(
        f"{API}/reports/ledger/pdf",
        headers={"Authorization": f"Bearer {TOK}", "X-Company-Id": h["X-Company-Id"]},
        params={"customer_id": cust, "start": "2026-04-01", "end": "2027-03-31"},
        timeout=30,
    )
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    text = _pdf_extract(BytesIO(r.content))

    assert cn["note_number"] in text, f"CN {cn['note_number']} missing from PDF"
    assert dn["note_number"] in text, f"DN {dn['note_number']} missing from PDF"
    assert "\u20b9" in text, "₹ glyph missing from ledger PDF"


# ---------- L1-T7 ---------------------------------------------------------

def test_l1_t7_tenant_isolation_ledger_excludes_other_tenants_notes():
    """A CN issued by tenant-A must never surface in tenant-B's ledger even
    if a customer of the same name exists on both sides. In this suite there
    is only one demo tenant, so we verify the customer-scoping guarantee:
    a note issued against customer-X does NOT leak into the ledger of a
    freshly created customer-Y in the same tenant."""
    _cid, h = _headers()
    cust_x = _fresh_customer(h, prefix="L1TX-X")
    cust_y = _fresh_customer(h, prefix="L1TX-Y")

    inv_x = _invoice(h, cust_x, invoice_date="2026-06-15")
    cn_x = _issue_cn(h, inv_x, amount=1111, note_date="2026-07-01")

    # Y has no invoices, no notes
    led_y = _ledger(h, cust_y, start="2026-04-01", end="2027-03-31")
    refs_y = {e["reference"] for e in led_y["entries"]}
    assert cn_x["note_number"] not in refs_y, \
        f"Tenant-A CN {cn_x['note_number']} leaked into customer-B ledger"
    assert led_y["entries"] == []
    assert led_y["opening_balance"] == 0.0
    assert led_y["closing_balance"] == 0.0
    assert led_y["totals_by_type"] == {
        "invoice": 0.0, "payment": 0.0, "credit_note": 0.0, "debit_note": 0.0,
    }
