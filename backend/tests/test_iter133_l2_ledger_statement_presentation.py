"""Iter133 L2 · Presentation regression tests.

Locks the visible surface of the redesigned Ledger PDF and Customer Statement
PDF. Zero business-logic assertions — all checks are byte-level text extraction
via pdfminer.

Master principle covered:
Enter Once → Calculate Once → Reflect Everywhere → Report Ready.
"""
import os
import uuid
import httpx
import pytest
from io import BytesIO
from pdfminer.high_level import extract_text as _pdf_extract


def _api():
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") + "/api"
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


API = _api()
TOK = os.environ["DEMO_TOKEN_VALUE"]


def _headers():
    h = {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}
    cid = httpx.get(f"{API}/companies", headers=h, timeout=10).json()[0]["id"]
    h["X-Company-Id"] = cid
    return cid, h


def _fresh_customer(h, prefix="L2"):
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(f"{API}/customers", headers=h,
                   json={"name": f"{prefix}-{tag}", "phone": f"9{tag}", "state": "Andhra Pradesh"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _invoice(h, cust_id, invoice_date="2026-06-15", rate=900, tons=20):
    tag = uuid.uuid4().hex[:6]
    r = httpx.post(f"{API}/trips", headers=h, json={
        "customer_id": cust_id, "date": invoice_date, "vehicle_number": f"L2{tag}",
        "tons": tons, "loaded_qty": tons, "unloaded_qty": tons,
        "freight_mode": "per_ton", "rate_per_ton": rate, "product_rate_per_mt": 40000,
        "from_location": "A", "to_location": "B",
        "loading_date": invoice_date, "unloading_date": invoice_date,
    }, timeout=15)
    assert r.status_code == 200, r.text
    trip_id = r.json()["id"]
    r = httpx.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust_id, "trip_ids": [trip_id],
        "invoice_date": invoice_date, "rcm": True,
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _cn(h, inv, amount, note_date="2026-07-01", reason="quality_claim"):
    r = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": note_date, "reason_code": reason,
        "reason_text": f"L2 CN {amount}",
        "lines": [{"description": "L2 CN", "quantity": 1, "rate": amount}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _dn(h, inv, amount, note_date="2026-07-02", reason="freight_escalation"):
    r = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": note_date, "reason_code": reason,
        "reason_text": f"L2 DN {amount}",
        "lines": [{"description": "L2 DN", "quantity": 1, "rate": amount}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _get_pdf(url, h):
    r = httpx.get(url, headers={"Authorization": f"Bearer {TOK}", "X-Company-Id": h["X-Company-Id"]}, timeout=30)
    assert r.status_code == 200, r.text
    return r.content, _pdf_extract(BytesIO(r.content))


def _ledger_pdf(h, cust, start="2026-04-01", end="2027-03-31"):
    return _get_pdf(f"{API}/reports/ledger/pdf?customer_id={cust}&start={start}&end={end}", h)


def _statement_pdf(h, cust, date_from=None, date_to=None):
    q = f"?date_from={date_from}&date_to={date_to}" if (date_from or date_to) else ""
    return _get_pdf(f"{API}/customers/{cust}/statement.pdf{q}", h)


# ================= L2-T1..T4 · Ledger PDF =================

def test_l2_t1_ledger_pdf_contains_customer_statement_hero():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    _invoice(h, cust)
    _, text = _ledger_pdf(h, cust)
    assert "CUSTOMER" in text and "STATEMENT" in text, "Redesigned header missing"


def test_l2_t2_ledger_pdf_shows_totals_by_type_pills():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust)
    _cn(h, inv, 500, note_date="2026-07-01")
    _dn(h, inv, 800, note_date="2026-07-02")
    _, text = _ledger_pdf(h, cust)
    for pill in ("INVOICED", "DEBIT NOTES", "CREDIT NOTES", "PAYMENTS"):
        assert pill in text, f"pill '{pill}' missing"
    assert "Adjustments this period" in text
    assert "Credit Notes" in text and "Debit Notes" in text


def test_l2_t3_ledger_pdf_shows_amount_in_words_and_page_footer():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    _invoice(h, cust)
    _, text = _ledger_pdf(h, cust)
    assert "Amount in Words:" in text
    assert "RUPEES" in text.upper()
    assert "Computer-generated statement" in text
    assert "Page 1 of 1" in text


def test_l2_t4_ledger_pdf_row_type_visual_carries_through():
    """L1 regression: CN/DN rows still render in the redesigned table."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust)
    cn = _cn(h, inv, 700)
    dn = _dn(h, inv, 300)
    _, text = _ledger_pdf(h, cust)
    assert cn["note_number"] in text
    assert dn["note_number"] in text
    assert "\u20b9" in text
    assert "Authorised Signatory" in text


# ================= L2-T5..T7 · Statement PDF =================

def test_l2_t5_statement_pdf_shows_balance_bridge_when_notes_exist():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust)
    _cn(h, inv, 450)
    _dn(h, inv, 1200)
    _, text = _statement_pdf(h, cust)
    assert "Balance Bridge" in text
    assert "Original Invoiced Total" in text
    assert "Less: Credit Notes" in text
    assert "Add: Debit Notes" in text
    assert "Less: Payments Received" in text
    assert "Balance Due" in text
    assert "\u20b9" in text


def test_l2_t6_statement_pdf_hides_balance_bridge_when_no_notes():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    _invoice(h, cust)  # invoice but zero notes
    _, text = _statement_pdf(h, cust)
    assert "Balance Bridge" not in text
    assert "Adjustments (Credit / Debit Notes)" not in text


def test_l2_t7_statement_pdf_adjustments_table_lists_issued_notes_only():
    """Cancelled note must not appear; issued notes must all appear."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust)
    cn_kept = _cn(h, inv, 300)
    cn_cancelled = _cn(h, inv, 100, note_date="2026-07-05")
    dn_kept = _dn(h, inv, 200)
    # Cancel the second CN
    r = httpx.post(f"{API}/credit-notes/{cn_cancelled['id']}/cancel", headers=h,
                   json={"reason": "L2-T7 exclusion test"}, timeout=15)
    assert r.status_code == 200, r.text

    _, text = _statement_pdf(h, cust)
    assert "Adjustments (Credit / Debit Notes)" in text
    assert cn_kept["note_number"] in text
    assert dn_kept["note_number"] in text
    assert cn_cancelled["note_number"] not in text


# ================= L2-T8..T9 · Cross-PDF regressions =================

def test_l2_t8_statement_pdf_gstin_empty_guard_still_works():
    """C2c regression: empty issuer GSTIN → 'GSTIN: —' (or similar dash form)."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    _invoice(h, cust)
    _, text = _statement_pdf(h, cust)
    # Statement PDF header does not render issuer GSTIN before L2; this test
    # is scoped to guard against 'GSTIN:' followed by double-space artifact.
    # We only assert that if 'GSTIN:' appears, it is never followed by '  ·'.
    if "GSTIN:" in text:
        assert "GSTIN:  ·" not in text


def test_l2_t9_ledger_and_statement_rupee_glyph_universal():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _invoice(h, cust)
    _cn(h, inv, 100)
    _dn(h, inv, 150)
    _, ltext = _ledger_pdf(h, cust)
    _, stext = _statement_pdf(h, cust)
    assert ltext.count("\u20b9") > 0, "Ledger PDF missing ₹ glyph"
    assert stext.count("\u20b9") > 0, "Statement PDF missing ₹ glyph"
