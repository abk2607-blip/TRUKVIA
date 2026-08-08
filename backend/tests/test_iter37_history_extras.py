"""Iter37 — Customer History extras: with_balance list, aging buckets, bulk reminders, monthly balances, add-payment."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _cust():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c["name"] == "TEST_Iter37":
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Iter37", "state": "Andhra Pradesh", "phone": "9998887770"}).json()["id"]


def test_customers_with_balance_flag():
    r = requests.get(f"{API}/customers", headers=HEADERS, params={"with_balance": True})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if data:
        assert "outstanding_balance" in data[0]
    # Without flag → no field
    r2 = requests.get(f"{API}/customers", headers=HEADERS)
    if r2.json():
        assert "outstanding_balance" not in r2.json()[0]


def test_aging_buckets_present_in_summary():
    cid = _cust()
    r = requests.get(f"{API}/customers/{cid}/transactions", headers=HEADERS)
    assert r.status_code == 200
    s = r.json()["summary"]
    assert "aging" in s
    for k in ("0_30", "31_60", "61_90", "90_plus"):
        assert k in s["aging"]


def test_bulk_reminder_returns_whatsapp_urls():
    r = requests.get(f"{API}/customers/bulk-reminder", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert "reminders" in d and isinstance(d["reminders"], list)
    assert "total_customers" in d
    assert "total_outstanding" in d


def test_monthly_balances_endpoint():
    cid = _cust()
    r = requests.get(f"{API}/customers/{cid}/monthly-balances", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert "months" in d and isinstance(d["months"], list)
    if d["months"]:
        m0 = d["months"][0]
        for k in ("month", "trip_count", "quantity", "freight", "billed", "received", "balance"):
            assert k in m0


def test_add_payment_creates_and_allocates():
    cid = _cust()
    # Create a trip + invoice
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06", "vehicle_number": "AP99PAY01",
        "from_location": "A", "to_location": "B", "tons": 10,
        "freight_mode": "per_ton", "rate_per_ton": 1500,
    }).json()
    inv = requests.post(f"{API}/invoices", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06", "trip_ids": [t["id"]],
    }).json()
    try:
        # Add a partial payment of 5000 via UPI
        r = requests.post(f"{API}/customers/{cid}/add-payment", headers=HEADERS, json={
            "amount": 5000, "mode": "UPI", "date": "2026-02-07"
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["applied"], "expected at least one applied allocation"
        assert d["applied"][0]["amount"] == 5000
        # Verify invoice updated
        inv2 = requests.get(f"{API}/invoices/{inv['id']}", headers=HEADERS).json()
        assert inv2["amount_paid"] == 5000
        assert inv2["payment_status"] in ("partial", "paid")
    finally:
        requests.delete(f"{API}/invoices/{inv['id']}", headers=HEADERS)
        requests.delete(f"{API}/trips/{t['id']}", headers=HEADERS, params={"reason": "cleanup"})
