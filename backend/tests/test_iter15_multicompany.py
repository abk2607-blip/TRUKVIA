"""Iteration 15 backend tests: Multi-Company + HSN + RCM."""
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
TOKEN = "test_session_bitumen_2026"
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
    # Leave DB post-run for main agent debug; also clean
    _clean()


# ---------- Companies CRUD ----------
def test_01_fresh_user_auto_creates_default():
    r = requests.get(f"{API}/companies", headers=H)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 1
    assert data[0]["is_default"] is True
    pytest.C1 = data[0]["id"]


def test_02_create_second_company():
    payload = {"name": "BKA Logistics", "invoice_prefix": "BKA", "state": "Karnataka", "hsn_sac": "996791"}
    r = requests.post(f"{API}/companies", headers=H, json=payload)
    assert r.status_code == 200, r.text
    pytest.C2 = r.json()["id"]
    r2 = requests.get(f"{API}/companies", headers=H)
    assert len(r2.json()) == 2


def test_03_set_default_flip():
    r = requests.post(f"{API}/companies/{pytest.C2}/set-default", headers=H)
    assert r.status_code == 200
    docs = requests.get(f"{API}/companies", headers=H).json()
    d = {c["id"]: c["is_default"] for c in docs}
    assert d[pytest.C2] is True
    assert d[pytest.C1] is False
    # switch back
    requests.post(f"{API}/companies/{pytest.C1}/set-default", headers=H)


def test_04_update_c1_prefix_and_state():
    payload = {"name": "VBK Logistics", "invoice_prefix": "VBK", "state": "Tamil Nadu", "hsn_sac": "996791"}
    r = requests.put(f"{API}/companies/{pytest.C1}", headers=H, json=payload)
    assert r.status_code == 200
    assert r.json()["invoice_prefix"] == "VBK"


def test_05_delete_second_then_last_fails():
    # Create a temp third to safely delete
    r = requests.post(f"{API}/companies", headers=H, json={"name": "Temp", "invoice_prefix": "TMP"})
    tmp_id = r.json()["id"]
    d = requests.delete(f"{API}/companies/{tmp_id}", headers=H)
    assert d.status_code == 200
    # Now delete c2 as well (keep C1 for later tests)... actually keep both, we need C2 for scoping tests
    # But test spec: delete the only one should fail. Delete both then try last.
    d2 = requests.delete(f"{API}/companies/{pytest.C2}", headers=H)
    assert d2.status_code == 200
    d3 = requests.delete(f"{API}/companies/{pytest.C1}", headers=H)
    assert d3.status_code == 400
    # Recreate C2 for later tests
    r2 = requests.post(f"{API}/companies", headers=H,
                       json={"name": "BKA Logistics", "invoice_prefix": "BKA", "state": "Karnataka"})
    pytest.C2 = r2.json()["id"]


# ---------- Multi-company scoping ----------
def _create_customer(state="Tamil Nadu"):
    r = requests.post(f"{API}/customers", headers=H,
                      json={"name": "TEST_Cust", "state": state, "gstin": "33ABCDE1234F1Z5"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_trip(cid, customer_id, freight=24000):
    hdr = dict(H); hdr["X-Company-Id"] = cid
    payload = {
        "customer_id": customer_id,
        "date": "2026-01-15",
        "vehicle_number": "TN01AB1234",
        "vehicle_type": "own",
        "from_location": "Chennai",
        "to_location": "Bangalore",
        "product": "Bitumen",
        "loaded_qty": 20,
        "unloaded_qty": 20,
        "tons": 20,
        "freight_mode": "fixed",
        "rate_per_ton": 0,
        "fixed_amount": freight,
        "freight_rate": freight / 20,
        "freight_amount": freight,
    }
    r = requests.post(f"{API}/trips", headers=hdr, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_06_trip_scoping():
    cust = _create_customer()
    pytest.CUST = cust
    t1 = _create_trip(pytest.C1, cust)
    pytest.TRIP_C1 = t1["id"]
    assert t1["company_id"] == pytest.C1
    # GET with C1
    h1 = dict(H); h1["X-Company-Id"] = pytest.C1
    r1 = requests.get(f"{API}/trips", headers=h1).json()
    assert any(t["id"] == t1["id"] for t in r1)
    # GET with C2 should not include it
    h2 = dict(H); h2["X-Company-Id"] = pytest.C2
    r2 = requests.get(f"{API}/trips", headers=h2).json()
    assert not any(t["id"] == t1["id"] for t in r2)


def test_07_invoice_hsn_996511_and_scoping():
    h1 = dict(H); h1["X-Company-Id"] = pytest.C1
    payload = {"customer_id": pytest.CUST, "trip_ids": [pytest.TRIP_C1], "hsn_sac": "996511", "rcm": False}
    r = requests.post(f"{API}/invoices", headers=h1, json=payload)
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["hsn_sac"] == "996511"
    assert inv["company_id"] == pytest.C1
    pytest.INV1 = inv["id"]
    pytest.INV1_NUM = inv["invoice_number"]
    # Not visible under C2
    h2 = dict(H); h2["X-Company-Id"] = pytest.C2
    r2 = requests.get(f"{API}/invoices", headers=h2).json()
    assert not any(x["id"] == inv["id"] for x in r2)
    # Visible under C1
    r1 = requests.get(f"{API}/invoices", headers=h1).json()
    assert any(x["id"] == inv["id"] for x in r1)


def test_08_rcm_false_totals():
    # subtotal=24000, cust TN == company TN → cgst_sgst 5% = 1200 → gross 25200
    inv = requests.get(f"{API}/invoices/{pytest.INV1}", headers=H).json()
    assert inv["subtotal"] == 24000
    assert inv["gst_type"] == "cgst_sgst"
    assert inv["total_tax"] == 1200
    assert inv["total_amount"] == 25200
    assert inv["hsn_sac"] == "996511"


def test_09_pdf_contains_hsn():
    r = requests.get(f"{API}/invoices/{pytest.INV1}/pdf", headers=H)
    assert r.status_code == 200
    from io import BytesIO
    from pypdf import PdfReader
    text = "".join(p.extract_text() or "" for p in PdfReader(BytesIO(r.content)).pages)
    assert "996511" in text, f"HSN not in PDF text: {text[:500]}"


def test_10_second_invoice_996791_and_rcm_true():
    # Create another trip in C1 so we can bill again
    t = _create_trip(pytest.C1, pytest.CUST)
    h1 = dict(H); h1["X-Company-Id"] = pytest.C1
    payload = {"customer_id": pytest.CUST, "trip_ids": [t["id"]], "hsn_sac": "996791", "rcm": True}
    r = requests.post(f"{API}/invoices", headers=h1, json=payload)
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["hsn_sac"] == "996791"
    # RCM=True → total_amount == subtotal (no tax added), though tax fields still computed
    assert inv["subtotal"] == 24000
    assert inv["total_amount"] == 24000
    # verify PDF has 996791
    p = requests.get(f"{API}/invoices/{inv['id']}/pdf", headers=H)
    from io import BytesIO
    from pypdf import PdfReader
    text = "".join(pg.extract_text() or "" for pg in PdfReader(BytesIO(p.content)).pages)
    assert "996791" in text


def test_11_invoice_prefixes_per_company():
    # C1 first invoice already used → VBK/26-27/0001
    assert pytest.INV1_NUM.startswith("VBK/")
    assert pytest.INV1_NUM.endswith("/0001")
    # Create trip + invoice under C2 (Karnataka; customer TN → IGST)
    t = _create_trip(pytest.C2, pytest.CUST)
    h2 = dict(H); h2["X-Company-Id"] = pytest.C2
    r = requests.post(f"{API}/invoices", headers=h2,
                     json={"customer_id": pytest.CUST, "trip_ids": [t["id"]], "hsn_sac": "996511", "rcm": False})
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["invoice_number"].startswith("BKA/")
    assert inv["invoice_number"].endswith("/0001")
    assert inv["gst_type"] == "igst"
    assert inv["igst_amount"] == 1200


def test_12_legacy_company_put_scopes_active():
    # PUT /api/company with X-Company-Id=C2 should update C2 only
    h2 = dict(H); h2["X-Company-Id"] = pytest.C2
    r = requests.put(f"{API}/company", headers=h2,
                     json={"name": "BKA Logistics Renamed", "invoice_prefix": "BKA", "state": "Karnataka"})
    assert r.status_code == 200
    all_c = requests.get(f"{API}/companies", headers=H).json()
    m = {c["id"]: c for c in all_c}
    assert m[pytest.C2]["name"] == "BKA Logistics Renamed"
    assert m[pytest.C1]["name"] == "VBK Logistics"


def test_13_backfill_legacy_trip():
    # Insert a trip directly with no company_id
    legacy_id = "trip_legacy_test_001"
    _db.trips.insert_one({
        "id": legacy_id, "user_id": UID, "customer_id": pytest.CUST,
        "date": "2026-01-10", "vehicle_number": "LEG01", "vehicle_type": "own",
        "freight_amount": 5000, "status": "pending",
    })
    # Trigger backfill via GET /companies
    requests.get(f"{API}/companies", headers=H)
    doc = _db.trips.find_one({"id": legacy_id})
    assert doc.get("company_id"), "backfill did not set company_id"
    # Determine default company
    default = next(c for c in requests.get(f"{API}/companies", headers=H).json() if c["is_default"])
    hd = dict(H); hd["X-Company-Id"] = default["id"]
    trips = requests.get(f"{API}/trips", headers=hd).json()
    assert any(t["id"] == legacy_id for t in trips)


def test_14_auto_gst_state_match():
    # Cust TN, C1 TN → cgst_sgst (already validated in 08).
    # Different state: C2=Karnataka, cust TN → igst (validated in test_11)
    assert True


def test_15_reports_scoped_by_company():
    h1 = dict(H); h1["X-Company-Id"] = pytest.C1
    h2 = dict(H); h2["X-Company-Id"] = pytest.C2
    d1 = requests.get(f"{API}/dashboard", headers=h1)
    d2 = requests.get(f"{API}/dashboard", headers=h2)
    assert d1.status_code == 200 and d2.status_code == 200
    # C1 has 2 invoices, C2 has 1 → invoices count differs
    assert d1.json() != d2.json()
