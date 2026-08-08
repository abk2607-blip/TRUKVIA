"""Iter32 — Phase-2: supplier settlement expanded (diesel + shortage + other_income)."""
import os, uuid, requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _get_or_create_customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    assert r.status_code == 200
    for c in r.json():
        if c.get("name") == "TEST_Sup_Settle":
            return c["id"]
    c = requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Sup_Settle", "state": "Andhra Pradesh"}).json()
    return c["id"]


def _create_trip(**kw):
    payload = {"date": "2026-02-05", "load_details": "Bitumen", "from_location": "X", "to_location": "Y",
               "vehicle_number": kw.pop("vehicle_number", f"AP99SUP{uuid.uuid4().hex[:4].upper()}")}
    payload.update(kw)
    r = requests.post(f"{API}/trips", headers=HEADERS, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup(tid):
    requests.delete(f"{API}/trips/{tid}", headers=HEADERS)


def test_supplier_full_settlement_new_fields():
    """New fields: supplier_diesel, supplier_shortage_deduction, supplier_other_income."""
    cid = _get_or_create_customer()
    t = _create_trip(
        customer_id=cid,
        vehicle_type="supplier",
        supplier_name="TEST_Sup_Full",
        supplier_freight_mode="per_ton",
        supplier_rate_per_ton=1000,
        supplier_quantity=20,
        supplier_advance=5000,
        supplier_diesel=2000,
        supplier_shortage_deduction=800,
        supplier_other_recoveries=200,
        supplier_other_income=500,
        tons=20,
        freight_mode="per_ton",
        rate_per_ton=1500,
    )
    try:
        assert t["supplier_freight"] == 20000
        # Net = 20000 - 5000 - 2000 - 800 - 200 + 500 = 12500
        assert t["supplier_net_payable"] == 12500, t
        assert t["total_expense"] == 12500
        # freight = 20 * 1500 = 30000; profit = 30000 - 12500 = 17500
        assert t["freight_amount"] == 30000
        assert t["profit"] == 17500
    finally:
        _cleanup(t["id"])


def test_supplier_fields_default_zero_backward_compat():
    """Old trips without new fields still compute correctly (net_payable == freight - advance - other_recoveries)."""
    cid = _get_or_create_customer()
    t = _create_trip(
        customer_id=cid,
        vehicle_type="supplier",
        supplier_name="TEST_Sup_BC",
        supplier_freight_mode="per_ton",
        supplier_rate_per_ton=800,
        supplier_quantity=10,
        supplier_advance=1000,
        tons=10,
        freight_mode="per_ton",
        rate_per_ton=1000,
    )
    try:
        assert t["supplier_freight"] == 8000
        # No diesel/shortage/income → net = 8000 - 1000 = 7000
        assert t["supplier_net_payable"] == 7000, t
        assert t.get("supplier_diesel", 0) == 0
        assert t.get("supplier_shortage_deduction", 0) == 0
        assert t.get("supplier_other_income", 0) == 0
        assert t["total_expense"] == 7000
        assert t["profit"] == 3000
    finally:
        _cleanup(t["id"])
