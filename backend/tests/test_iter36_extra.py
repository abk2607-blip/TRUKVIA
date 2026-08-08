"""Iter36 supplementary — payment_status/invoice_status filters, PUT trip preservation, statement date-range, share pdf."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
HEADERS = {"Authorization": "Bearer test_session_bitumen_2026", "Content-Type": "application/json"}


def _cust():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c.get("name") == "TEST_Iter36Extra":
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Iter36Extra", "state": "Andhra Pradesh"}).json()["id"]


def test_trip_new_fields_roundtrip_post_get_put():
    cid = _cust()
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06", "vehicle_number": "AP99RT01",
        "from_location": "X", "to_location": "Y", "tons": 10,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "customer_diesel_received": 1500, "customer_advance_received": 3000,
    }).json()
    tid = t["id"]
    try:
        assert t.get("customer_diesel_received") == 1500
        assert t.get("customer_advance_received") == 3000
        # GET list
        lst = requests.get(f"{API}/trips", headers=HEADERS).json()
        found = [x for x in lst if x["id"] == tid][0]
        assert found["customer_diesel_received"] == 1500
        assert found["customer_advance_received"] == 3000
        # PUT preserves + updates
        upd = requests.put(f"{API}/trips/{tid}", headers=HEADERS, json={
            **found, "customer_diesel_received": 2500,
        }).json()
        assert upd.get("customer_diesel_received") == 2500
        assert upd.get("customer_advance_received") == 3000  # preserved
    finally:
        requests.delete(f"{API}/trips/{tid}", headers=HEADERS, params={"reason": "cleanup"})


def test_summary_keys_full_shape():
    cid = _cust()
    r = requests.get(f"{API}/customers/{cid}/transactions", headers=HEADERS)
    assert r.status_code == 200
    s = r.json()["summary"]
    for k in ["trip_count", "total_qty", "total_freight", "total_diesel_received",
              "total_advances", "total_shortage", "total_excess", "total_halting",
              "total_billed", "total_received", "outstanding", "total_pending_uninvoiced"]:
        assert k in s, f"missing summary key {k}"


def test_txn_row_shape():
    cid = _cust()
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06", "vehicle_number": "AP99ROW01",
        "from_location": "P", "to_location": "Q", "tons": 7,
        "freight_mode": "per_ton", "rate_per_ton": 900,
    }).json()
    try:
        d = requests.get(f"{API}/customers/{cid}/transactions", headers=HEADERS).json()
        trip_rows = [x for x in d["transactions"] if x["type"] == "trip"]
        assert trip_rows, "expected at least 1 trip row"
        row = trip_rows[0]
        for k in ["type", "date", "id", "amount"]:
            assert k in row
        # DESC sort by date
        dates = [x["date"] for x in d["transactions"]]
        assert dates == sorted(dates, reverse=True)
    finally:
        requests.delete(f"{API}/trips/{t['id']}", headers=HEADERS, params={"reason": "cleanup"})


def test_invoice_and_payment_status_filters():
    cid = _cust()
    for ps in ["all", "unpaid", "partial", "paid"]:
        r = requests.get(f"{API}/customers/{cid}/transactions", headers=HEADERS, params={"payment_status": ps})
        assert r.status_code == 200, f"payment_status={ps} failed: {r.text}"
    for isf in ["all", "pending", "invoiced"]:
        r = requests.get(f"{API}/customers/{cid}/transactions", headers=HEADERS, params={"invoice_status": isf})
        assert r.status_code == 200


def test_statement_pdf_with_date_range():
    cid = _cust()
    r = requests.get(f"{API}/customers/{cid}/statement.pdf", headers=HEADERS,
                     params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 500


def test_share_statement_shape_and_public_pdf():
    cid = _cust()
    r = requests.post(f"{API}/customers/{cid}/share-statement", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert d["whatsapp_url"].startswith("https://wa.me/?text=")
    assert "whatsapp_text" in d
    assert d["public_url"].startswith("http")
    assert "/api/files/public/" in d["public_url"]
    pr = requests.get(d["public_url"])  # no auth
    assert pr.status_code == 200
    assert pr.content[:5] == b"%PDF-"


def test_combined_filters():
    cid = _cust()
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06", "vehicle_number": "AP99COMB1",
        "from_location": "M", "to_location": "N", "tons": 3,
        "freight_mode": "per_ton", "rate_per_ton": 500,
    }).json()
    try:
        r = requests.get(f"{API}/customers/{cid}/transactions", headers=HEADERS, params={
            "txn_type": "trip", "vehicle_number": "AP99COMB1",
            "date_from": "2026-02-06", "date_to": "2026-02-06",
        })
        assert r.status_code == 200
        rows = r.json()["transactions"]
        assert all(x["type"] == "trip" for x in rows)
        assert any(x["id"] == t["id"] for x in rows)
    finally:
        requests.delete(f"{API}/trips/{t['id']}", headers=HEADERS, params={"reason": "cleanup"})
