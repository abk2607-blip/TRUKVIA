"""Iter39 — Customer Receipts list (multiple diesel/advance entries per trip)."""
import os
import uuid
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Iter127a — unique per pytest process to avoid the name-duplicate rule.
_FIXTURE_NAME = f"TEST_Iter39_{uuid.uuid4().hex[:6]}"


def _cust():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c["name"] == _FIXTURE_NAME:
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": _FIXTURE_NAME, "state": "Andhra Pradesh"}).json()["id"]


def test_customer_receipts_auto_compute_diesel_and_totals():
    cid = _cust()
    r = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-08-09",
        "vehicle_number": "AP99RCT_A", "tons": 10,
        "freight_mode": "per_ton", "rate_per_ton": 10000,
        "customer_receipts": [
            {"id": "r1", "date": "2026-08-09", "type": "diesel", "litres": 280, "rate": 104.24},
            {"id": "r2", "date": "2026-08-09", "type": "advance", "amount": 20000, "mode": "Cash"},
            {"id": "r3", "date": "2026-08-12", "type": "advance", "amount": 15000, "mode": "NEFT", "ref_no": "XYZ123"},
        ],
    })
    assert r.status_code == 200, r.text
    t = r.json()
    try:
        # Diesel amount auto = 280 * 104.24 = 29187.20
        diesel = next(x for x in t["customer_receipts"] if x["type"] == "diesel")
        assert diesel["amount"] == 29187.2, diesel
        assert t["customer_diesel_received"] == 29187.2
        assert t["customer_advance_received"] == 35000.0
        assert t["freight_amount"] == 100000.0
    finally:
        requests.delete(f"{API}/trips/{t['id']}", headers=HEADERS, params={"reason": "cleanup"})


def test_customer_diesel_deducts_from_supplier_net_payable():
    """For supplier vehicle trips, customer diesel is treated as supplier recovery."""
    cid = _cust()
    r = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-08-09",
        "vehicle_number": "AP99RCT_B",
        "vehicle_type": "supplier", "supplier_name": "TestSup",
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 10000,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 8000, "supplier_quantity": 10,
        "customer_receipts": [
            {"id": "r1", "date": "2026-08-09", "type": "diesel", "litres": 280, "rate": 104.24},
        ],
    })
    assert r.status_code == 200, r.text
    t = r.json()
    try:
        assert t["supplier_freight"] == 80000
        # Net = 80000 - 0(adv) - 0(sup_diesel) - 29187.20(customer_diesel) = 50812.80
        assert t["supplier_net_payable"] == 50812.8, t
        assert t["total_expense"] == 50812.8
        # Profit = freight(100000) - total_expense(50812.80) = 49187.20 (customer receipts do NOT reduce profit)
        assert t["profit"] == 49187.2
    finally:
        requests.delete(f"{API}/trips/{t['id']}", headers=HEADERS, params={"reason": "cleanup"})


def test_own_vehicle_receipts_do_not_affect_profit():
    """For own vehicle, customer receipts reduce the receivable but don't change P&L profit."""
    cid = _cust()
    r = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-08-09",
        "vehicle_number": "AP99RCT_C",
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 10000,
        "expenses": {"diesel": 5000, "toll": 500},
        "customer_receipts": [
            {"id": "r1", "date": "2026-08-09", "type": "advance", "amount": 30000, "mode": "UPI"},
        ],
    })
    assert r.status_code == 200
    t = r.json()
    try:
        assert t["customer_advance_received"] == 30000
        # Profit = 100000 - 5500 = 94500 (expenses only; advance is a collection, not a cost)
        assert t["profit"] == 94500.0, t
    finally:
        requests.delete(f"{API}/trips/{t['id']}", headers=HEADERS, params={"reason": "cleanup"})


def test_legacy_scalar_fields_still_work_when_no_receipts_list():
    """Backward compat: trips created with only customer_diesel_received (no list) still compute."""
    cid = _cust()
    r = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-08-09",
        "vehicle_number": "AP99RCT_D",
        "tons": 5, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "customer_diesel_received": 500,
        "customer_advance_received": 200,
    })
    assert r.status_code == 200
    t = r.json()
    try:
        assert t["customer_diesel_received"] == 500
        assert t["customer_advance_received"] == 200
    finally:
        requests.delete(f"{API}/trips/{t['id']}", headers=HEADERS, params={"reason": "cleanup"})
