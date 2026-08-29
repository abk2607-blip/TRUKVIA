"""Iteration 17 backend tests — Trip-wise Diesel-from-Customer & Cash Advance
deductions on Invoice (subtotal / diesel_deduction_total / advance_deduction_total)
and PDF label rendering."""
import os
import pytest
import requests
from pymongo import MongoClient

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
UID = "test-user-bitumen"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
_client = MongoClient(MONGO_URL)
_db = _client[os.environ.get("DB_NAME", "test_database")]


def _clean():
    for c in ("trips", "invoices", "customers", "companies", "audit_logs", "files"):
        _db[c].delete_many({"user_id": UID})


@pytest.fixture(scope="module", autouse=True)
def clean_once():
    _clean()
    yield
    _clean()


# ---------- helpers ----------
def _companies():
    r = requests.get(f"{API}/companies", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _create_company(name, prefix, state="Tamil Nadu"):
    r = requests.post(f"{API}/companies", headers=H,
                      json={"name": name, "invoice_prefix": prefix, "state": state, "hsn_sac": "996791"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_customer(name="TEST_Cust", state="Tamil Nadu", cid=None):
    hdr = dict(H)
    if cid:
        hdr["X-Company-Id"] = cid
    r = requests.post(f"{API}/customers", headers=hdr,
                      json={"name": name, "state": state, "gstin": "33ABCDE1234F1Z5"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_trip(cid, customer_id, *, tons=20, rate=1500,
                 diesel_qty=0.0, diesel_rate=0.0, advance=0.0):
    hdr = dict(H); hdr["X-Company-Id"] = cid
    freight = tons * rate
    payload = {
        "customer_id": customer_id,
        "date": "2026-01-15",
        "vehicle_number": "TN01AB1234",
        "vehicle_type": "own",
        "from_location": "Chennai",
        "to_location": "Bangalore",
        "loaded_qty": tons, "unloaded_qty": tons, "tons": tons,
        "freight_mode": "per_ton",
        "rate_per_ton": rate,
        "fixed_amount": 0,
        "freight_amount": freight,
        "expenses": {
            "diesel_from_customer_qty": diesel_qty,
            "diesel_from_customer_rate": diesel_rate,
            "cash_advance_received": advance,
        },
    }
    r = requests.post(f"{API}/trips", headers=hdr, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Test 1: single-trip end-to-end ----------
def test_01_single_trip_deductions_and_invoice_totals():
    comps = _companies()
    pytest.C1 = comps[0]["id"]
    cust = _create_customer(cid=pytest.C1)
    pytest.CUST = cust

    trip = _create_trip(pytest.C1, cust, tons=20, rate=1500,
                        diesel_qty=100, diesel_rate=90, advance=5000)
    # Diesel auto-computed
    assert trip["expenses"]["diesel_from_customer_amount"] == 9000, trip["expenses"]
    assert trip["expenses"]["cash_advance_received"] == 5000
    assert trip["freight_amount"] == 30000
    pytest.TRIP1 = trip["id"]

    hdr = dict(H); hdr["X-Company-Id"] = pytest.C1
    r = requests.post(f"{API}/invoices", headers=hdr, json={
        "customer_id": cust, "trip_ids": [trip["id"]], "rcm": True,
    })
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["diesel_deduction_total"] == 9000, inv
    assert inv["advance_deduction_total"] == 5000, inv
    # 30000 - 9000 - 5000 = 16000
    assert inv["subtotal"] == 16000, inv
    # RCM → tax not added
    assert inv["total_amount"] == 16000, inv
    assert inv["round_off"] == 0, inv
    pytest.INV1 = inv["id"]


# ---------- Test 2: multi-trip aggregation ----------
def test_02_multi_trip_aggregation():
    # Fresh customer to avoid using trip1 already invoiced
    cust = _create_customer(name="TEST_CustMulti", cid=pytest.C1)

    # trip A: diesel 3000 (30L * 100) + advance 2000
    tA = _create_trip(pytest.C1, cust, tons=10, rate=1000,
                      diesel_qty=30, diesel_rate=100, advance=2000)
    assert tA["expenses"]["diesel_from_customer_amount"] == 3000
    # trip B: diesel 4000 (40L * 100), no advance
    tB = _create_trip(pytest.C1, cust, tons=10, rate=1000,
                      diesel_qty=40, diesel_rate=100, advance=0)
    assert tB["expenses"]["diesel_from_customer_amount"] == 4000

    hdr = dict(H); hdr["X-Company-Id"] = pytest.C1
    r = requests.post(f"{API}/invoices", headers=hdr, json={
        "customer_id": cust, "trip_ids": [tA["id"], tB["id"]], "rcm": True,
    })
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["diesel_deduction_total"] == 7000, inv
    assert inv["advance_deduction_total"] == 2000, inv
    # freight 10000 + 10000 = 20000; -7000 -2000 = 11000
    assert inv["subtotal"] == 11000, inv
    pytest.INV2 = inv["id"]
    pytest.TRIP_A = tA["id"]
    pytest.TRIP_A_DOC = tA


# ---------- Test 3: edit trip → invoice recomputes ----------
def test_03_edit_trip_recomputes_invoice():
    # PUT requires full body — reuse the doc returned by create-trip, mutate expenses
    hdr = dict(H); hdr["X-Company-Id"] = pytest.C1
    existing = dict(pytest.TRIP_A_DOC)
    existing["expenses"] = {
        **(existing.get("expenses") or {}),
        "diesel_from_customer_qty": 50,
        "diesel_from_customer_rate": 100,
        "diesel_from_customer_amount": 0,  # let backend recompute
        "cash_advance_received": 3500,
    }
    for k in ("user_id", "created_at", "invoice_id", "status",
              "total_expense", "profit", "net_settlement", "company_id"):
        existing.pop(k, None)
    r = requests.put(f"{API}/trips/{pytest.TRIP_A}", headers=hdr, json=existing)
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["expenses"]["diesel_from_customer_amount"] == 5000, t["expenses"]

    inv = requests.get(f"{API}/invoices/{pytest.INV2}", headers=hdr).json()
    # tA diesel: 5000, tB diesel: 4000 → total 9000
    assert inv["diesel_deduction_total"] == 9000, inv
    # advances: 3500 (tA) + 0 = 3500
    assert inv["advance_deduction_total"] == 3500, inv
    # freight 20000 - 9000 - 3500 = 7500
    assert inv["subtotal"] == 7500, inv


# ---------- Test 4: PDF contains new labels ----------
def test_04_pdf_labels():
    r = requests.get(f"{API}/invoices/{pytest.INV1}/pdf", headers=H)
    assert r.status_code == 200, r.status_code
    assert r.headers.get("content-type", "").startswith("application/pdf"), r.headers
    body = r.content
    assert len(body) > 500
    # Extract text via pypdf (reportlab uses Flate compression)
    import io, pypdf
    reader = pypdf.PdfReader(io.BytesIO(body))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    for needle in ("Diesel from Customer",
                   "Customer Advance",
                   "Net Freight"):
        assert needle in text, f"PDF missing text: {needle!r}\n--- extracted ---\n{text}"


# ---------- Test 5: Regression — no reduction when nothing set ----------
def test_05_regression_no_reduction():
    cust = _create_customer(name="TEST_Plain", cid=pytest.C1)
    t = _create_trip(pytest.C1, cust, tons=10, rate=1000)  # freight 10000, no diesel/adv
    hdr = dict(H); hdr["X-Company-Id"] = pytest.C1
    r = requests.post(f"{API}/invoices", headers=hdr, json={
        "customer_id": cust, "trip_ids": [t["id"]], "rcm": True,
    })
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["diesel_deduction_total"] == 0
    assert inv["advance_deduction_total"] == 0
    assert inv["subtotal"] == 10000


# ---------- Test 6: Multi-company scoping (regression) ----------
def test_06_multi_company_scoping():
    C2 = _create_company("BKA Logistics 17", "BKA17", state="Karnataka")
    pytest.C2 = C2
    # Customer in C1 has trips with diesel; C2 preview shouldn't include them
    hdr2 = dict(H); hdr2["X-Company-Id"] = C2
    trips_c2 = requests.get(f"{API}/trips", headers=hdr2).json()
    assert all(t.get("company_id") == C2 for t in trips_c2)
    assert not any(t["id"] == pytest.TRIP1 for t in trips_c2)

    # Trying to invoice C1 trip under C2 should fail
    r = requests.post(f"{API}/invoices", headers=hdr2, json={
        "customer_id": pytest.CUST, "trip_ids": [pytest.TRIP1], "rcm": True,
    })
    assert r.status_code in (400, 404), r.text
