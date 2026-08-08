"""Iter35 — Trip Log chronological sort (date DESC, then created_at DESC)."""
import os
import requests
import time
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _get_or_create_customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c.get("name") == "TEST_Iter35_Sort":
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Iter35_Sort", "state": "Andhra Pradesh"}).json()["id"]


def _create(cust, **kw):
    payload = {"customer_id": cust, "vehicle_number": "AP99SORT01",
               "from_location": "A", "to_location": "B", "load_details": "Bitumen",
               "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1000}
    payload.update(kw)
    return requests.post(f"{API}/trips", headers=HEADERS, json=payload).json()


def test_trips_sorted_by_date_desc_then_created_at_desc():
    """When two trips share the same date, the one created later must appear first."""
    cust = _get_or_create_customer()
    today = datetime.now(timezone.utc).date().isoformat()
    # Create trip A first, then B on the same date — B should be listed before A.
    a = _create(cust, date=today, vehicle_number="AP99SORT_A")
    time.sleep(1.2)
    b = _create(cust, date=today, vehicle_number="AP99SORT_B")

    try:
        r = requests.get(f"{API}/trips", headers=HEADERS)
        assert r.status_code == 200
        trips = r.json()
        # Filter to our two test trips (there may be others)
        ours = [t for t in trips if t.get("id") in (a["id"], b["id"])]
        assert len(ours) == 2, f"expected 2 test trips, got {ours}"
        # The one that was created later (b) must come first in the list
        assert ours[0]["id"] == b["id"], f"expected {b['id']} first, got {ours[0]['id']}"
        assert ours[1]["id"] == a["id"]
    finally:
        requests.delete(f"{API}/trips/{a['id']}", headers=HEADERS, params={"reason": "cleanup"})
        requests.delete(f"{API}/trips/{b['id']}", headers=HEADERS, params={"reason": "cleanup"})


def test_older_date_after_newer_date():
    cust = _get_or_create_customer()
    old = _create(cust, date="2026-01-10", vehicle_number="AP99SORT_OLD")
    new = _create(cust, date="2026-06-15", vehicle_number="AP99SORT_NEW")
    try:
        r = requests.get(f"{API}/trips", headers=HEADERS)
        ours = [t for t in r.json() if t.get("id") in (old["id"], new["id"])]
        assert len(ours) == 2
        assert ours[0]["id"] == new["id"], "newer date must come first"
        assert ours[1]["id"] == old["id"]
    finally:
        requests.delete(f"{API}/trips/{old['id']}", headers=HEADERS, params={"reason": "cleanup"})
        requests.delete(f"{API}/trips/{new['id']}", headers=HEADERS, params={"reason": "cleanup"})
