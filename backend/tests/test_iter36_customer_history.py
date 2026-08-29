"""Iter36 — Customer Transaction History (unified ledger + statement PDF + WhatsApp)."""
import os
import uuid
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Iter127a — each pytest process gets its own fixture customer so the
# customer-name duplicate rule can't 409 across parallel workers.
_FIXTURE_NAME = f"TEST_Iter36_Hist_{uuid.uuid4().hex[:6]}"


def _get_or_create_customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c.get("name") == _FIXTURE_NAME:
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": _FIXTURE_NAME, "state": "Andhra Pradesh"}).json()["id"]


def test_customer_transactions_returns_summary_and_txns():
    cid = _get_or_create_customer()
    # Ensure at least one trip with all financial fields
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06",
        "vehicle_number": "AP99HIST01", "driver_name": "TestDrv",
        "from_location": "Chennai", "to_location": "Hyderabad",
        "load_details": "Bitumen", "tons": 20,
        "freight_mode": "per_ton", "rate_per_ton": 1500,
        "customer_diesel_received": 2000,
        "customer_advance_received": 5000,
        "halting_rate_per_day": 500,
    }).json()
    tid = t["id"]
    try:
        r = requests.get(f"{API}/customers/{cid}/transactions", headers=HEADERS)
        assert r.status_code == 200
        d = r.json()
        assert d["customer"]["id"] == cid
        s = d["summary"]
        assert s["trip_count"] >= 1
        assert s["total_qty"] >= 20
        assert s["total_freight"] >= 30000
        assert s["total_diesel_received"] >= 2000
        assert s["total_advances"] >= 5000
        # Unified transactions list contains our trip
        trips = [x for x in d["transactions"] if x["type"] == "trip" and x["id"] == tid]
        assert len(trips) == 1
        assert trips[0]["customer_diesel_received"] == 2000
        assert trips[0]["customer_advance_received"] == 5000
        assert trips[0]["vehicle_number"] == "AP99HIST01"
    finally:
        requests.delete(f"{API}/trips/{tid}", headers=HEADERS, params={"reason": "cleanup"})


def test_customer_transactions_filters():
    cid = _get_or_create_customer()
    t1 = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06", "vehicle_number": "AP99FLT_A",
        "from_location": "A", "to_location": "B", "tons": 5,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
    }).json()
    t2 = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-07", "vehicle_number": "AP99FLT_B",
        "from_location": "C", "to_location": "D", "tons": 6,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
    }).json()
    try:
        # Filter by vehicle
        r = requests.get(f"{API}/customers/{cid}/transactions",
                         headers=HEADERS, params={"vehicle_number": "AP99FLT_A"})
        d = r.json()
        trip_ids = [x["id"] for x in d["transactions"] if x["type"] == "trip"]
        assert t1["id"] in trip_ids
        assert t2["id"] not in trip_ids
        # Filter by date range
        r = requests.get(f"{API}/customers/{cid}/transactions",
                         headers=HEADERS, params={"date_from": "2026-02-07", "date_to": "2026-02-07"})
        d = r.json()
        trip_ids = [x["id"] for x in d["transactions"] if x["type"] == "trip"]
        assert t2["id"] in trip_ids
        assert t1["id"] not in trip_ids
    finally:
        requests.delete(f"{API}/trips/{t1['id']}", headers=HEADERS, params={"reason": "cleanup"})
        requests.delete(f"{API}/trips/{t2['id']}", headers=HEADERS, params={"reason": "cleanup"})


def test_customer_statement_pdf():
    cid = _get_or_create_customer()
    r = requests.get(f"{API}/customers/{cid}/statement.pdf", headers=HEADERS)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 500


def test_customer_share_statement_returns_whatsapp():
    cid = _get_or_create_customer()
    r = requests.post(f"{API}/customers/{cid}/share-statement", headers=HEADERS)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["whatsapp_url"].startswith("https://wa.me/?text=")
    assert d["public_url"].startswith("http")
    # Verify public URL actually returns the PDF
    public_r = requests.get(d["public_url"])
    assert public_r.status_code == 200
    assert public_r.content[:5] == b"%PDF-"


def test_customer_txn_history_txn_type_filter():
    cid = _get_or_create_customer()
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06", "vehicle_number": "AP99TYPE01",
        "from_location": "A", "to_location": "B", "tons": 5,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
    }).json()
    try:
        # only trips
        r = requests.get(f"{API}/customers/{cid}/transactions", headers=HEADERS, params={"txn_type": "trip"})
        d = r.json()
        assert all(x["type"] == "trip" for x in d["transactions"])
        # only invoices
        r = requests.get(f"{API}/customers/{cid}/transactions", headers=HEADERS, params={"txn_type": "invoice"})
        d = r.json()
        assert all(x["type"] == "invoice" for x in d["transactions"])
    finally:
        requests.delete(f"{API}/trips/{t['id']}", headers=HEADERS, params={"reason": "cleanup"})
