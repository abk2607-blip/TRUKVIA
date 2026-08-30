"""Iter132c C2 · CN/DN PDF endpoint regression.

Verifies the two additive read-only GET endpoints:
  GET /api/credit-notes/{nid}/pdf
  GET /api/debit-notes/{nid}/pdf

Boundaries: reuses existing pdf/credit_note.py + pdf/debit_note.py builders
(both Iter132a/b LOCKED). Zero business-logic change. Feature-flag-gated.
"""
import os
import uuid
import httpx
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


def _company_header():
    companies = httpx.get(f"{API}/companies", headers=HDR, timeout=15).json()
    cid = companies[0]["id"]
    return cid, {**HDR, "X-Company-Id": cid}


def _fresh_customer(h):
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(f"{API}/customers", headers=h, json={
        "name": f"C2-PDF-{tag}", "phone": f"9{tag[:9]}",
        "email": f"{tag}@iter132c-c2.test", "state": "Andhra Pradesh",
    }, timeout=15)
    assert r.status_code == 200
    return r.json()["id"]


def _create_invoice_with_trip(h, cust_id):
    tag = uuid.uuid4().hex[:6]
    tr = httpx.post(f"{API}/trips", headers=h, json={
        "customer_id": cust_id, "date": "2026-06-01",
        "vehicle_number": f"C2{tag[:4].upper()}",
        "tons": 20, "loaded_qty": 20, "unloaded_qty": 20,
        "freight_mode": "per_ton", "rate_per_ton": 900,
        "product_rate_per_mt": 40000,
        "from_location": "A", "to_location": "B",
        "loading_date": "2026-06-01", "unloading_date": "2026-06-02",
    }, timeout=15)
    assert tr.status_code == 200
    inv = httpx.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust_id, "trip_ids": [tr.json()["id"]],
        "invoice_date": "2026-06-15", "rcm": True,
    }, timeout=15)
    assert inv.status_code == 200
    return inv.json()


def _issue_cn(inv, h, amount=1500.0):
    r = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "quality_claim",
        "reason_text": "C2 PDF test — CN",
        "lines": [{"description": "cn-line", "quantity": 1, "rate": amount}],
    }, timeout=15)
    assert r.status_code == 200
    return r.json()


def _issue_dn(inv, h, amount=1200.0):
    r = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "freight_escalation",
        "reason_text": "C2 PDF test — DN",
        "lines": [{"description": "dn-line", "quantity": 1, "rate": amount}],
    }, timeout=15)
    assert r.status_code == 200
    return r.json()


def test_credit_note_pdf_200_content_type_size():
    _cid, h = _company_header()
    inv = _create_invoice_with_trip(h, _fresh_customer(h))
    cn = _issue_cn(inv, h)
    r = httpx.get(f"{API}/credit-notes/{cn['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200, r.text[:200]
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert len(r.content) > 2000, f"PDF suspiciously small: {len(r.content)} bytes"
    # PDF magic bytes
    assert r.content[:4] == b"%PDF"


def test_debit_note_pdf_200_content_type_size():
    _cid, h = _company_header()
    inv = _create_invoice_with_trip(h, _fresh_customer(h))
    dn = _issue_dn(inv, h)
    r = httpx.get(f"{API}/debit-notes/{dn['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert len(r.content) > 2000
    assert r.content[:4] == b"%PDF"


def test_credit_note_pdf_unknown_nid_returns_404():
    _cid, h = _company_header()
    r = httpx.get(f"{API}/credit-notes/does_not_exist/pdf", headers=h, timeout=15)
    assert r.status_code == 404


def test_debit_note_pdf_unknown_nid_returns_404():
    _cid, h = _company_header()
    r = httpx.get(f"{API}/debit-notes/does_not_exist/pdf", headers=h, timeout=15)
    assert r.status_code == 404


def test_credit_note_pdf_wrong_kind_returns_404():
    """A DN nid must NOT be reachable via the credit-note PDF endpoint (kind filter)."""
    _cid, h = _company_header()
    inv = _create_invoice_with_trip(h, _fresh_customer(h))
    dn = _issue_dn(inv, h)
    r = httpx.get(f"{API}/credit-notes/{dn['id']}/pdf", headers=h, timeout=15)
    assert r.status_code == 404, f"CN PDF endpoint leaked a DN: {r.status_code}"


def test_cancelled_note_still_returns_pdf():
    """PDF is a read-only rendering — must remain available after cancel."""
    _cid, h = _company_header()
    inv = _create_invoice_with_trip(h, _fresh_customer(h))
    cn = _issue_cn(inv, h)
    c = httpx.post(f"{API}/credit-notes/{cn['id']}/cancel", headers=h,
                   json={"reason": "C2 PDF cancel test — must still render"}, timeout=15)
    assert c.status_code == 200
    r = httpx.get(f"{API}/credit-notes/{cn['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
