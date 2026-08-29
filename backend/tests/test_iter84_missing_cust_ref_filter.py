"""Iter84 — `missing_cust_ref` server-side filter on GET /api/trips.

Locks: when the filter is on, only trips with EVERY Customer Ref alias
blank/missing come back. No new field is created — we reuse the existing
per-trip `customer_reference_number` with legacy fallbacks (`customer_invoice_no`,
`waybill_no`).
"""
import os, uuid, httpx
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
TOK = os.environ["DEMO_TOKEN_VALUE"]
HA = {"Authorization": f"Bearer {TOK}"}


@pytest.fixture(scope="module")
def two_trips():
    httpx.post(f"{BASE}/api/auth/demo-login", timeout=60)
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(
        f"{BASE}/api/customers", headers=HA,
        json={"name": f"IT84_Cust_{tag}", "phone": "9998887777", "state": "AP"},
        timeout=60,
    ).json()
    veh = httpx.post(
        f"{BASE}/api/vehicles", headers=HA,
        json={"vehicle_number": f"AP99IT84{tag[:4].upper()}", "vehicle_type": "own"},
        timeout=60,
    ).json()
    with_ref = httpx.post(
        f"{BASE}/api/trips", headers=HA,
        json={
            "customer_id": cust["id"], "date": "2026-09-01",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1000,
            "from_location": "K", "to_location": "V",
            "customer_reference_number": f"CINV-{tag}",
        },
        timeout=60,
    ).json()
    without_ref = httpx.post(
        f"{BASE}/api/trips", headers=HA,
        json={
            "customer_id": cust["id"], "date": "2026-09-02",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1000,
            "from_location": "K", "to_location": "V",
            # customer_reference_number intentionally omitted
        },
        timeout=60,
    ).json()
    return {"with_ref": with_ref, "without_ref": without_ref}


def test_missing_cust_ref_filter_excludes_trips_with_ref(two_trips):
    """Filter on → trip with a ref MUST NOT be returned."""
    r = httpx.get(
        f"{BASE}/api/trips?missing_cust_ref=true&customer_id={two_trips['with_ref']['customer_id']}",
        headers=HA, timeout=60,
    )
    assert r.status_code == 200
    ids = {t["id"] for t in r.json()}
    assert two_trips["with_ref"]["id"] not in ids, \
        "trip WITH customer_reference_number must be excluded when missing_cust_ref=true"
    assert two_trips["without_ref"]["id"] in ids, \
        "trip WITHOUT customer_reference_number must be included when missing_cust_ref=true"


def test_filter_off_returns_both(two_trips):
    """Filter off (default) → both trips are returned."""
    r = httpx.get(
        f"{BASE}/api/trips?customer_id={two_trips['with_ref']['customer_id']}",
        headers=HA, timeout=60,
    )
    assert r.status_code == 200
    ids = {t["id"] for t in r.json()}
    assert two_trips["with_ref"]["id"] in ids
    assert two_trips["without_ref"]["id"] in ids


def test_export_respects_missing_cust_ref(two_trips):
    """CSV export must honor the same filter so what the user sees is what
    they download."""
    r = httpx.get(
        f"{BASE}/api/trips/export?format=csv&missing_cust_ref=true&customer_id={two_trips['with_ref']['customer_id']}",
        headers=HA, timeout=60,
    )
    assert r.status_code == 200
    body = r.content.decode("utf-8", errors="ignore")
    # LR numbers are stable per-trip and appear in the export
    assert two_trips["without_ref"]["lr_number"] in body
    assert two_trips["with_ref"]["lr_number"] not in body, \
        "export must exclude trips with a ref when missing_cust_ref=true"
