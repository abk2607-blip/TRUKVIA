"""Iter83 — Cust Ref column in main Trips list.

Locks the contract that `/api/trips` returns the per-trip
`customer_reference_number` field so the Trips list can render it. No new
DB field, no duplicate — just reusing the value stored since iter66.
"""
import os, uuid, httpx
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
TOK = os.environ["DEMO_TOKEN_VALUE"]
HA = {"Authorization": f"Bearer {TOK}"}


@pytest.fixture(scope="module")
def sample_trips():
    httpx.post(f"{BASE}/api/auth/demo-login", timeout=60)
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(
        f"{BASE}/api/customers", headers=HA,
        json={"name": f"IT83_Cust_{tag}", "phone": "9998887777", "state": "AP"},
        timeout=60,
    ).json()
    veh = httpx.post(
        f"{BASE}/api/vehicles", headers=HA,
        json={"vehicle_number": f"AP99IT83{tag[:4].upper()}", "vehicle_type": "own"},
        timeout=60,
    ).json()
    trip_a = httpx.post(
        f"{BASE}/api/trips", headers=HA,
        json={
            "customer_id": cust["id"], "date": "2026-08-10",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1000,
            "from_location": "K", "to_location": "V",
            "customer_reference_number": "CINV-A1",
        },
        timeout=60,
    ).json()
    trip_b = httpx.post(
        f"{BASE}/api/trips", headers=HA,
        json={
            "customer_id": cust["id"], "date": "2026-08-11",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1000,
            "from_location": "K", "to_location": "V",
            # no customer_reference_number
        },
        timeout=60,
    ).json()
    return {"with_ref": trip_a, "without_ref": trip_b}


def test_trips_list_returns_customer_reference_number(sample_trips):
    """The /api/trips list must return `customer_reference_number` per row so
    the Trips page can display the Cust Ref column."""
    r = httpx.get(
        f"{BASE}/api/trips?ids={sample_trips['with_ref']['id']},{sample_trips['without_ref']['id']}",
        headers=HA, timeout=30,
    )
    assert r.status_code == 200
    trips = r.json()
    by_id = {t["id"]: t for t in trips}
    assert by_id[sample_trips["with_ref"]["id"]]["customer_reference_number"] == "CINV-A1"
    assert by_id[sample_trips["without_ref"]["id"]]["customer_reference_number"] == ""


def test_no_cross_trip_ref_leak(sample_trips):
    """Trip without a ref must NEVER inherit the ref from another trip."""
    r = httpx.get(
        f"{BASE}/api/trips/{sample_trips['without_ref']['id']}",
        headers=HA, timeout=30,
    )
    assert r.status_code == 200
    assert r.json()["customer_reference_number"] == ""
