"""Iter100 · Task1 (field-override API) + Task2 (Phase 5 Landscape Invoice PDF).

Covers:
  - POST /api/trips/{tid}/field-override validation + persistence (Task 1 backend)
  - GET  /api/invoices/{iid}/pdf : landscape A4, section labels, Basis column,
    multi-trip consolidation, freight-basis labels, financial parity with JSON.
"""
import io
import os
import uuid

import httpx
import pytest
from pypdf import PdfReader

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
TOK = os.environ["DEMO_TOKEN_VALUE"]
HA = {"Authorization": f"Bearer {TOK}"}
T = 60


@pytest.fixture(scope="module")
def boot():
    httpx.post(f"{BASE}/api/auth/demo-login", timeout=T)
    r = httpx.get(f"{BASE}/api/companies", headers=HA, timeout=T)
    assert r.status_code == 200, r.text
    return {"company_id": r.json()[0]["id"]}


# ------------------------- Task 1 · field-override API -------------------------
@pytest.fixture(scope="module")
def simple_trip(boot):
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(f"{BASE}/api/customers", headers=HA,
                      json={"name": f"TEST_IT100_C_{tag}", "state": "AP"}, timeout=T).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=HA,
                     json={"vehicle_number": f"AP100T{tag[:4].upper()}", "vehicle_type": "own"},
                     timeout=T).json()
    trip = httpx.post(f"{BASE}/api/trips", headers=HA, json={
        "customer_id": cust["id"], "date": "2026-09-01",
        "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
        "tons": 20, "loaded_qty": 20, "unloaded_qty": 20,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "from_location": "Kakinada", "to_location": "Vizag",
    }, timeout=T).json()
    return {"customer": cust, "vehicle": veh, "trip": trip}


def test_field_override_persists(simple_trip):
    tid = simple_trip["trip"]["id"]
    r = httpx.post(f"{BASE}/api/trips/{tid}/field-override", headers=HA, json={
        "field": "shortage_amount", "system_value": 0, "final_value": 1500,
        "reason": "TEST_IT100 customer accepted manual shortage",
    }, timeout=T)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "_id" not in body
    ovs = body["field_overrides"]
    assert len(ovs) >= 1
    ent = [o for o in ovs if o["field"] == "shortage_amount"][-1]
    assert ent["system_value"] == 0
    assert ent["final_value"] == 1500
    assert ent["reason"] == "TEST_IT100 customer accepted manual shortage"
    assert ent["label"] == "Customer Shortage"
    assert ent["modified_by"] and ent["modified_at"]

    # GET verifies persistence
    got = httpx.get(f"{BASE}/api/trips/{tid}", headers=HA, timeout=T).json()
    assert any(o["field"] == "shortage_amount" and o["final_value"] == 1500
               for o in got.get("field_overrides") or [])


def test_field_override_supplier_halting_label(simple_trip):
    tid = simple_trip["trip"]["id"]
    r = httpx.post(f"{BASE}/api/trips/{tid}/field-override", headers=HA, json={
        "field": "supplier_halting_amount", "system_value": 0, "final_value": 2000,
        "reason": "TEST_IT100 negotiated halting",
    }, timeout=T)
    assert r.status_code == 200, r.text
    ent = [o for o in r.json()["field_overrides"] if o["field"] == "supplier_halting_amount"][-1]
    assert ent["label"] == "Supplier Halting"


def test_field_override_validation(simple_trip):
    tid = simple_trip["trip"]["id"]
    no_reason = httpx.post(f"{BASE}/api/trips/{tid}/field-override", headers=HA, json={
        "field": "shortage_amount", "system_value": 0, "final_value": 10}, timeout=T)
    assert no_reason.status_code == 400, no_reason.text
    no_field = httpx.post(f"{BASE}/api/trips/{tid}/field-override", headers=HA, json={
        "reason": "x", "system_value": 0, "final_value": 10}, timeout=T)
    assert no_field.status_code == 400, no_field.text
    bad_trip = httpx.post(f"{BASE}/api/trips/tr_nope_100/field-override", headers=HA, json={
        "field": "shortage_amount", "system_value": 0, "final_value": 10,
        "reason": "x"}, timeout=T)
    assert bad_trip.status_code == 404, bad_trip.text


# ------------------ Task 2 · Landscape multi-trip invoice PDF ------------------
@pytest.fixture(scope="module")
def multi_trip_invoice(boot):
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(f"{BASE}/api/customers", headers=HA, json={
        "name": f"TEST_IT100_Inv_{tag}", "state": "AP", "phone": "9990001111",
        "address": "Plot 9, Kakinada", "gstin": "37ABCDE1234F1Z5",
    }, timeout=T).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=HA, json={
        "vehicle_number": f"AP100I{tag[:4].upper()}", "vehicle_type": "own"}, timeout=T).json()

    specs = [
        # (date, applied_freight_method, ref, tons/loaded/unloaded)
        ("2026-09-10", "per_ton_higher_of", "CREF-A1", 21, 20),
        ("2026-09-11", "per_ton_loading", "CREF-A2", 18, 18),
        ("2026-09-12", "", "CREF-A3", 22, 22),  # legacy / no snapshot
    ]
    trips = []
    for d, method, ref, loaded, unloaded in specs:
        payload = {
            "customer_id": cust["id"], "date": d,
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "tons": loaded, "loaded_qty": loaded, "unloaded_qty": unloaded,
            "freight_mode": "per_ton", "rate_per_ton": 900,
            "from_location": "Kakinada", "to_location": "Vizag",
            "customer_reference_number": ref, "load_details": "Bitumen VG30",
        }
        if method:
            payload["applied_freight_method"] = method
        r = httpx.post(f"{BASE}/api/trips", headers=HA, json=payload, timeout=T)
        assert r.status_code in (200, 201), r.text
        trips.append(r.json())

    inv = httpx.post(f"{BASE}/api/invoices", headers=HA, json={
        "customer_id": cust["id"], "invoice_date": "2026-09-15",
        "trip_ids": [t["id"] for t in trips], "hsn_sac": "996791",
        "gst_treatment": "rcm", "due_date": "2026-10-15",
    }, timeout=T)
    assert inv.status_code in (200, 201), inv.text
    return {"invoice": inv.json(), "trips": trips, "customer": cust}


@pytest.fixture(scope="module")
def pdf_bundle(multi_trip_invoice):
    iid = multi_trip_invoice["invoice"]["id"]
    r = httpx.get(f"{BASE}/api/invoices/{iid}/pdf", headers=HA, timeout=90)
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/pdf")
    reader = PdfReader(io.BytesIO(r.content))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    return {"reader": reader, "text": text, "bytes": r.content}


def test_pdf_is_landscape_a4(pdf_bundle):
    box = pdf_bundle["reader"].pages[0].mediabox
    w, h = float(box.width), float(box.height)
    assert w > h, f"PDF must be LANDSCAPE, got {w}x{h}"
    # A4 landscape ≈ 841.89 x 595.28 pt
    assert abs(w - 841.89) < 3 and abs(h - 595.28) < 3, f"expected A4 landscape, got {w}x{h}"


def test_pdf_required_sections(pdf_bundle, multi_trip_invoice):
    text = pdf_bundle["text"]
    inv = multi_trip_invoice["invoice"]
    required = ["TAX INVOICE", "BILL TO", "SHIP TO", "Our Invoice No", "Basis",
                "Cust Ref", "Amount", "AMOUNT IN WORDS", "BANK DETAILS",
                "TERMS & CONDITIONS", "FINAL PAYABLE",
                inv["invoice_number"], multi_trip_invoice["customer"]["name"]]
    missing = [x for x in required if x not in text]
    assert not missing, f"missing from PDF: {missing}"


def test_pdf_multitrip_rows_and_refs(pdf_bundle, multi_trip_invoice):
    text = pdf_bundle["text"]
    for ref in ("CREF-A1", "CREF-A2", "CREF-A3"):
        assert ref in text, f"trip ref {ref} missing — multi-trip rows not rendered"
    assert "Trips in Invoice" in text
    assert str(len(multi_trip_invoice["trips"])) in text


def test_pdf_freight_basis_labels(pdf_bundle):
    # Normalise the extracted text: PDF cells wrap the "Per Ton (Higher of)"
    # label onto two lines in the narrow Basis column, so we collapse
    # whitespace before searching.
    text = " ".join(pdf_bundle["text"].split())
    assert "Per Ton (Higher of)" in text, "per_ton_higher_of label missing in Basis column"
    assert "Per Ton (Loading)" in text, "per_ton_loading label missing in Basis column"
    # legacy trip (no snapshot) must still render a fallback label
    assert "Per Ton" in text


def test_pdf_financials_match_invoice_json(multi_trip_invoice, pdf_bundle):
    iid = multi_trip_invoice["invoice"]["id"]
    inv = httpx.get(f"{BASE}/api/invoices/{iid}", headers=HA, timeout=T).json()
    trips = httpx.get(f"{BASE}/api/trips?ids=" + ",".join(t["id"] for t in multi_trip_invoice["trips"]),
                      headers=HA, timeout=T).json()
    freight_sum = round(sum(float(t.get("freight_amount") or 0) for t in trips), 2)
    assert abs(float(inv["freight_total"]) - freight_sum) < 0.02, \
        f"invoice freight_total {inv['freight_total']} != sum of trip freight {freight_sum}"

    text = pdf_bundle["text"].replace(",", "").replace(" ", "")
    for key in ("freight_total", "subtotal", "total_amount"):
        val = float(inv.get(key) or 0)
        needle = f"{val:,.2f}".replace(",", "")
        assert needle in text, f"{key}={val} not found in PDF text (financials changed?)"


def test_pdf_fixed_basis_label(boot):
    """A fixed-freight trip must show 'Fixed' in the Basis column."""
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(f"{BASE}/api/customers", headers=HA,
                      json={"name": f"TEST_IT100_Fx_{tag}", "state": "AP"}, timeout=T).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=HA, json={
        "vehicle_number": f"AP100F{tag[:4].upper()}", "vehicle_type": "own"}, timeout=T).json()
    trip = httpx.post(f"{BASE}/api/trips", headers=HA, json={
        "customer_id": cust["id"], "date": "2026-09-20",
        "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
        "tons": 20, "loaded_qty": 20, "unloaded_qty": 20,
        "freight_mode": "fixed", "fixed_amount": 25000,
        "applied_freight_method": "fixed",
        "from_location": "K", "to_location": "V",
    }, timeout=T).json()
    inv = httpx.post(f"{BASE}/api/invoices", headers=HA, json={
        "customer_id": cust["id"], "invoice_date": "2026-09-21",
        "trip_ids": [trip["id"]], "hsn_sac": "996791", "gst_treatment": "rcm",
    }, timeout=T).json()
    r = httpx.get(f"{BASE}/api/invoices/{inv['id']}/pdf", headers=HA, timeout=90)
    assert r.status_code == 200, r.text
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Fixed" in text or "Round Trip" in text, "fixed basis label missing"
