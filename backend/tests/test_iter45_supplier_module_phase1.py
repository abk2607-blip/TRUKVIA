"""Iter45 Phase 1 — Supplier Management Module (master + payments + ledger)."""
import os
import uuid
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _uniq_name(prefix):
    return f"{prefix} {os.urandom(3).hex().upper()}"


def _customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    return r.json()[0]["id"]


def test_supplier_crud_end_to_end():
    name = _uniq_name("PYTEST Supplier")
    # Create
    r = requests.post(f"{API}/suppliers", headers=HEADERS, json={
        "name": name, "contact_person": "Test Person", "mobile": "9999900001",
        "gst_in": f"37AAB{uuid.uuid4().hex[:8].upper()}A1Z"[:15], "pan": "ABCPD1234E",
        "opening_balance": 5000, "opening_balance_type": "payable",
    })
    assert r.status_code == 200
    s = r.json()
    sid = s["id"]
    # Duplicate rejected
    r2 = requests.post(f"{API}/suppliers", headers=HEADERS, json={"name": name})
    assert r2.status_code == 409
    # Get
    r3 = requests.get(f"{API}/suppliers/{sid}", headers=HEADERS)
    assert r3.status_code == 200
    assert r3.json()["name"] == name
    # Update
    r4 = requests.put(f"{API}/suppliers/{sid}", headers=HEADERS, json={
        **s, "contact_person": "Updated Person",
    })
    assert r4.status_code == 200
    assert r4.json()["contact_person"] == "Updated Person"
    # Soft-delete → mark inactive
    r5 = requests.delete(f"{API}/suppliers/{sid}", headers=HEADERS)
    assert r5.status_code == 200
    r6 = requests.get(f"{API}/suppliers/{sid}", headers=HEADERS)
    assert r6.status_code == 200
    assert r6.json()["is_active"] is False


def test_supplier_payments_crud_and_deletion_reason_required():
    sup = requests.post(f"{API}/suppliers", headers=HEADERS, json={"name": _uniq_name("PYTEST Pay")}).json()
    sid = sup["id"]
    # Create
    p = requests.post(f"{API}/suppliers/{sid}/payments", headers=HEADERS, json={
        "supplier_id": sid, "date": "2028-03-01", "amount": 12500,
        "mode": "NEFT", "ref_no": "NEFT-777", "against": "outstanding", "remarks": "March settlement",
    }).json()
    pid = p["id"]
    assert p["amount"] == 12500
    assert p["type"] == "payment_out"
    # List
    lst = requests.get(f"{API}/suppliers/{sid}/payments", headers=HEADERS).json()
    assert any(x["id"] == pid for x in lst)
    # Update
    p2 = requests.put(f"{API}/suppliers/{sid}/payments/{pid}", headers=HEADERS, json={
        **p, "remarks": "Updated remark",
    }).json()
    assert p2["remarks"] == "Updated remark"
    # Delete without reason → 422
    r = requests.delete(f"{API}/suppliers/{sid}/payments/{pid}", headers=HEADERS)
    assert r.status_code == 422
    # Delete with reason
    r = requests.delete(f"{API}/suppliers/{sid}/payments/{pid}", headers=HEADERS,
                        params={"reason": "Bank reversed the txn"})
    assert r.status_code == 200
    # List excludes deleted
    lst = requests.get(f"{API}/suppliers/{sid}/payments", headers=HEADERS).json()
    assert not any(x["id"] == pid for x in lst)


def test_supplier_ledger_reflects_opening_trip_and_payment():
    """Opening ₹5,000 Dr → +Trip freight ₹20,000 → +Trip advance ₹3,000 Cr → +Payment ₹10,000 Cr → closing ₹12,000 Dr."""
    cid = _customer()
    sup = requests.post(f"{API}/suppliers", headers=HEADERS, json={
        "name": _uniq_name("PYTEST Ledger"), "opening_balance": 5000, "opening_balance_type": "payable",
    }).json()
    sid = sup["id"]
    # Supplier trip
    requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2028-04-05",
        "vehicle_number": "AP99IT45L", "vehicle_type": "supplier",
        "supplier_id": sid, "supplier_name": sup["name"],
        "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 1000,
        "supplier_advance": 3000,
    })
    # Payment
    requests.post(f"{API}/suppliers/{sid}/payments", headers=HEADERS, json={
        "supplier_id": sid, "date": "2028-04-15", "amount": 10000, "mode": "NEFT", "against": "outstanding",
    })
    led = requests.get(f"{API}/suppliers/{sid}/ledger", headers=HEADERS).json()
    types = [e["type"] for e in led["entries"]]
    assert "opening" in types
    assert "trip_freight" in types
    assert "trip_advance" in types
    assert "payment_out" in types
    # Closing balance: +5000 (open Dr) +20000 (freight Dr) -3000 (adv) -10000 (pay) = 12000 Dr
    assert led["totals"]["closing_balance"] == 12000.0
    assert led["totals"]["closing_type"] == "payable"


def test_suppliers_dashboard_shape():
    r = requests.get(f"{API}/suppliers-dashboard", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    for k in ("total_suppliers", "active_suppliers", "active_vehicles",
              "total_freight", "total_advances", "total_payments", "total_outstanding"):
        assert k in d["totals"]
    assert isinstance(d["suppliers"], list)


def test_supplier_vehicles_endpoint():
    sup = requests.post(f"{API}/suppliers", headers=HEADERS, json={"name": _uniq_name("PYTEST Veh")}).json()
    r = requests.get(f"{API}/suppliers/{sup['id']}/vehicles", headers=HEADERS)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_outstanding_endpoint():
    sup = requests.post(f"{API}/suppliers", headers=HEADERS, json={
        "name": _uniq_name("PYTEST Out"), "opening_balance": 7500, "opening_balance_type": "payable",
    }).json()
    r = requests.get(f"{API}/suppliers/{sup['id']}/outstanding", headers=HEADERS).json()
    assert r["closing_balance"] == 7500.0
    assert r["outstanding_payable"] == 7500.0
    assert r["outstanding_advance"] == 0.0
