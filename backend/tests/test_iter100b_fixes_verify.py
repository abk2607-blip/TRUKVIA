"""Iter100 re-test: (a) Basis column must show 'Fixed' when freight_mode='fixed'
even if applied_freight_method snapshot says per_ton_loading; (b) a single-trip
invoice must fit ONE landscape A4 page.
"""
import io
import os
import uuid

import fitz  # PyMuPDF
import httpx
import pytest
from pypdf import PdfReader

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
HA = {"Authorization": "Bearer test_session_bitumen_2026"}
T = 90


@pytest.fixture(scope="module")
def boot():
    httpx.post(f"{BASE}/api/auth/demo-login", timeout=T)
    r = httpx.get(f"{BASE}/api/companies", headers=HA, timeout=T)
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


def _make_invoice(freight_payload, extra_trip=None):
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(f"{BASE}/api/customers", headers=HA, json={
        "name": f"TEST_IT100B_{tag}", "state": "AP", "phone": "9998887777",
        "address": "Plot 11, Kakinada", "gstin": "37ABCDE1234F1Z5"}, timeout=T).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=HA, json={
        "vehicle_number": f"AP100B{tag[:4].upper()}", "vehicle_type": "own"}, timeout=T).json()
    base = {
        "customer_id": cust["id"], "date": "2026-09-25",
        "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
        "tons": 20, "loaded_qty": 20, "unloaded_qty": 19.5,
        "from_location": "Kakinada", "to_location": "Vizag",
        "customer_reference_number": "CREF-B1", "load_details": "Bitumen VG30",
        "product_rate": 40000, "diesel_amount": 3000, "advance_amount": 2000,
    }
    base.update(freight_payload)
    tr = httpx.post(f"{BASE}/api/trips", headers=HA, json=base, timeout=T)
    assert tr.status_code in (200, 201), tr.text
    trip = tr.json()
    inv = httpx.post(f"{BASE}/api/invoices", headers=HA, json={
        "customer_id": cust["id"], "invoice_date": "2026-09-26",
        "trip_ids": [trip["id"]], "hsn_sac": "996791", "gst_treatment": "rcm",
        "due_date": "2026-10-26"}, timeout=T)
    assert inv.status_code in (200, 201), inv.text
    pdf = httpx.get(f"{BASE}/api/invoices/{inv.json()['id']}/pdf", headers=HA, timeout=T)
    assert pdf.status_code == 200, pdf.text
    return trip, inv.json(), pdf.content


def test_fixed_mode_overrides_snapshot_basis(boot):
    """P1: freight_mode='fixed' + applied_freight_method='per_ton_loading' -> 'Fixed'."""
    trip, inv, content = _make_invoice({
        "freight_mode": "fixed", "fixed_amount": 5000,
        "applied_freight_method": "per_ton_loading", "rate_per_ton": 900,
    })
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(content)).pages)
    assert "Fixed" in text, "Basis column must show 'Fixed' for freight_mode=fixed"
    assert "Per Ton (Loading)" not in text, \
        "stale snapshot label 'Per Ton (Loading)' still rendered for a fixed-mode trip"
    assert float(trip.get("freight_amount") or 0) == 5000.0, trip.get("freight_amount")


def test_single_trip_invoice_fits_one_landscape_page(boot):
    """P1: single-trip invoice must render on exactly one landscape A4 page."""
    trip, inv, content = _make_invoice({
        "freight_mode": "per_ton", "rate_per_ton": 950,
    })
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        rect = doc[0].rect
        assert rect.width > rect.height, f"not landscape: {rect.width}x{rect.height}"
        assert abs(rect.width - 841.89) < 3 and abs(rect.height - 595.28) < 3, \
            f"not A4 landscape: {rect.width}x{rect.height}"
        assert doc.page_count == 1, f"single-trip invoice spilled to {doc.page_count} pages"
        page_text = doc[0].get_text()
    finally:
        doc.close()
    for need in ("TAX INVOICE", "AMOUNT IN WORDS", "BANK DETAILS",
                 "TERMS & CONDITIONS", "FINAL PAYABLE", "Basis", "Cust Ref"):
        assert need in page_text, f"'{need}' missing from page 1"
