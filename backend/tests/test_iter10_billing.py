"""Iteration 10 backend tests: auth session schema, trip auto-calc
(loading/unloading, halting, product rate), invoice billable, PDF ₹
rendering, reports/pl new fields.
"""
import os
import io
import pytest
import requests
import fitz  # PyMuPDF

from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer_id():
    r = requests.post(
        f"{BASE_URL}/api/customers",
        json={"name": "TEST_iter10_Customer", "state": "Telangana", "gstin": "36ABCDE1234F1Z5"},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    yield cid
    # cleanup: delete customer + its trips + its invoices
    invs = requests.get(f"{BASE_URL}/api/invoices", headers=HEADERS).json()
    for i in invs:
        if i.get("customer_id") == cid:
            requests.delete(f"{BASE_URL}/api/invoices/{i['id']}", params={"reason": "cleanup"}, headers=HEADERS)
    trips = requests.get(f"{BASE_URL}/api/trips", headers=HEADERS, params={"customer_id": cid}).json()
    for t in trips:
        requests.delete(f"{BASE_URL}/api/trips/{t['id']}", params={"reason": "cleanup"}, headers=HEADERS)
    requests.delete(f"{BASE_URL}/api/customers/{cid}", headers=HEADERS)


# ---------------- AUTH SESSION ----------------

def test_auth_session_bad_id_still_returns_401_but_schema_documented():
    """POST /auth/session with fake session_id should NOT crash. The point is
    the endpoint exists and rejects unknown ids."""
    r = requests.post(f"{BASE_URL}/api/auth/session", json={"session_id": "fake_iter10_bogus"})
    assert r.status_code in (400, 401), r.text


def test_auth_me_with_bearer_token():
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("user_id") == "test-user-bitumen"


def test_auth_me_without_bearer_returns_401():
    r = requests.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 401


# ---------------- TRIP AUTO-CALC ----------------

def _mk_trip(**overrides):
    base = {
        "customer_id": overrides.pop("customer_id"),
        "date": "2026-02-05",
        "vehicle_number": "TS10TR001",
        "load_details": "Bitumen VG 40",
        "tons": 20,
        "freight_mode": "per_ton",
        "rate_per_ton": 1200,
    }
    base.update(overrides)
    return base


def test_trip_shortage_and_halting_auto(customer_id):
    payload = _mk_trip(
        customer_id=customer_id,
        loading_date="2026-02-05",
        unloading_date="2026-02-11",
        loaded_qty=20,
        unloaded_qty=19.5,
        product_rate_per_mt=50000,
        grace_days=4,
        halting_rate_per_day=2000,
    )
    r = requests.post(f"{BASE_URL}/api/trips", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["shortage_qty"] == 0.5
    assert d["excess_qty"] == 0
    assert d["shortage_amount"] == 25000
    assert d["excess_amount"] == 0
    assert d["total_halting_days"] == 6
    assert d["chargeable_halting_days"] == 2
    assert d["halting_amount"] == 4000
    assert d["freight_amount"] == 24000
    # profit = billable(freight+halting+excess-shortage) - expenses(=0)
    # = 24000 + 4000 + 0 - 25000 = 3000
    assert d["profit"] == 3000
    # cleanup
    requests.delete(f"{BASE_URL}/api/trips/{d['id']}", params={"reason": "cleanup"}, headers=HEADERS)


def test_trip_excess_case(customer_id):
    payload = _mk_trip(
        customer_id=customer_id,
        loaded_qty=15,
        unloaded_qty=15.3,
        product_rate_per_mt=40000,
        tons=15,
    )
    r = requests.post(f"{BASE_URL}/api/trips", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    d = r.json()
    assert abs(d["excess_qty"] - 0.3) < 1e-6
    assert d["shortage_qty"] == 0
    assert d["excess_amount"] == 12000
    assert d["shortage_amount"] == 0
    requests.delete(f"{BASE_URL}/api/trips/{d['id']}", params={"reason": "cleanup"}, headers=HEADERS)


def test_trip_manual_shortage_override(customer_id):
    payload = _mk_trip(
        customer_id=customer_id,
        loaded_qty=20,
        unloaded_qty=19,
        product_rate_per_mt=50000,
        shortage_amount_override=True,
        shortage_amount=500,
    )
    r = requests.post(f"{BASE_URL}/api/trips", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["shortage_qty"] == 1
    # override honoured
    assert d["shortage_amount"] == 500
    requests.delete(f"{BASE_URL}/api/trips/{d['id']}", params={"reason": "cleanup"}, headers=HEADERS)


def test_trip_manual_halting_override(customer_id):
    payload = _mk_trip(
        customer_id=customer_id,
        loading_date="2026-02-05",
        unloading_date="2026-02-11",
        loaded_qty=20,
        unloaded_qty=20,
        halting_rate_per_day=2000,
        grace_days=4,
        halting_amount_override=True,
        halting_amount=1500,
        chargeable_halting_days=2,
    )
    r = requests.post(f"{BASE_URL}/api/trips", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["halting_amount"] == 1500
    requests.delete(f"{BASE_URL}/api/trips/{d['id']}", params={"reason": "cleanup"}, headers=HEADERS)


# ---------------- INVOICE BILLABLE + PDF ----------------

@pytest.fixture(scope="module")
def shortage_trip_and_invoice(customer_id):
    payload = _mk_trip(
        customer_id=customer_id,
        loading_date="2026-02-05",
        unloading_date="2026-02-11",
        loaded_qty=20,
        unloaded_qty=19.5,
        product_rate_per_mt=50000,
        grace_days=4,
        halting_rate_per_day=2000,
    )
    r = requests.post(f"{BASE_URL}/api/trips", json=payload, headers=HEADERS)
    trip = r.json()

    inv = requests.post(
        f"{BASE_URL}/api/invoices",
        json={"customer_id": customer_id, "trip_ids": [trip["id"]], "gst_type": "cgst_sgst", "rcm": True},
        headers=HEADERS,
    ).json()

    yield trip, inv

    requests.delete(f"{BASE_URL}/api/invoices/{inv['id']}", params={"reason": "cleanup"}, headers=HEADERS)
    requests.delete(f"{BASE_URL}/api/trips/{trip['id']}", params={"reason": "cleanup"}, headers=HEADERS)


def test_invoice_billable_totals(shortage_trip_and_invoice):
    trip, inv = shortage_trip_and_invoice
    assert inv["freight_total"] == 24000
    assert inv["halting_total"] == 4000
    assert inv["shortage_total"] == 25000
    assert inv["excess_total"] == 0
    assert inv["subtotal"] == 3000
    # RCM=true → tax computed but total_amount = subtotal
    assert inv["rcm"] is True
    assert inv["total_amount"] == inv["subtotal"]


def test_invoice_pdf_has_rupee_and_labels(shortage_trip_and_invoice):
    trip, inv = shortage_trip_and_invoice
    r = requests.get(f"{BASE_URL}/api/invoices/{inv['id']}/pdf", headers=HEADERS)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    doc = fitz.open(stream=r.content, filetype="pdf")
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    assert "\u20b9" in text, "₹ (U+20B9) missing from invoice PDF"
    assert "Halting Charges" in text
    assert "Shortage Deduction" in text
    assert "Amount in Words" in text
    assert "TOTAL PAYABLE" in text


def test_invoice_recomputes_on_trip_edit(customer_id):
    # Build fresh trip + invoice to avoid interfering with module fixture
    payload = _mk_trip(
        customer_id=customer_id,
        loading_date="2026-02-05",
        unloading_date="2026-02-11",
        loaded_qty=20,
        unloaded_qty=19.5,
        product_rate_per_mt=50000,
        grace_days=4,
        halting_rate_per_day=2000,
    )
    trip = requests.post(f"{BASE_URL}/api/trips", json=payload, headers=HEADERS).json()
    inv = requests.post(
        f"{BASE_URL}/api/invoices",
        json={"customer_id": customer_id, "trip_ids": [trip["id"]], "gst_type": "cgst_sgst", "rcm": True},
        headers=HEADERS,
    ).json()
    assert inv["subtotal"] == 3000

    # Now edit trip: no shortage
    upd = dict(payload)
    upd["loaded_qty"] = 20
    upd["unloaded_qty"] = 20
    r = requests.put(f"{BASE_URL}/api/trips/{trip['id']}", json=upd, headers=HEADERS)
    assert r.status_code == 200, r.text
    inv2 = requests.get(f"{BASE_URL}/api/invoices/{inv['id']}", headers=HEADERS).json()
    assert inv2["shortage_total"] == 0
    assert inv2["subtotal"] == 28000  # 24000 + 4000
    assert inv2["freight_total"] == 24000
    assert inv2["halting_total"] == 4000
    # cleanup
    requests.delete(f"{BASE_URL}/api/invoices/{inv['id']}", params={"reason": "cleanup"}, headers=HEADERS)
    requests.delete(f"{BASE_URL}/api/trips/{trip['id']}", params={"reason": "cleanup"}, headers=HEADERS)


# ---------------- REPORTS ----------------

def test_reports_pl_has_new_fields():
    r = requests.get(f"{BASE_URL}/api/reports/pl", headers=HEADERS)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("freight_revenue", "halting_revenue", "excess_revenue", "shortage_deduction", "revenue"):
        assert k in d, f"missing {k}"
    # revenue formula sanity
    calc = round(d["freight_revenue"] + d["halting_revenue"] + d["excess_revenue"] - d["shortage_deduction"], 2)
    assert abs(calc - d["revenue"]) < 0.01
