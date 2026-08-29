"""Iter56 — Trip Log Search/Filter/Pagination (server-side).

Coverage:
 1. GET /api/trips returns array + X-Total-Count + X-Has-More headers
 2. limit + offset paginate correctly
 3. customer_id filter narrows results
 4. vehicle_id filter narrows results
 5. supplier_id filter narrows results (Iter55 supplier vehicle)
 6. date single filter
 7. date_from/date_to range filter
 8. q free-text matches LR number
 9. q free-text matches vehicle number
10. q free-text matches customer NAME (via customer_id join)
11. q free-text matches from_location / to_location
12. halting_only=true filters to trips with halting_amount>0
13. Combined filters (date+customer+vehicle) apply AND semantics
14. Multi-company isolation: filters only match trips in active company
15. Sort is by (date desc, created_at desc) — latest first
16. Frontend Trips.jsx exposes the required testids
"""
import os
import time
import uuid
import pytest
import httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}


def _cid():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=30).json()[0]["id"]


def _h():
    return {**HDR, "X-Company-Id": _cid()}


UNIQUE = f"IT56_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def seed():
    """Create 3 known trips we can filter by."""
    h = _h()
    T = 30  # longer timeout — CI env may be slow with heavy data
    # Create a dedicated customer
    cust = httpx.post(f"{BASE}/api/customers", headers=h, json={
        "name": f"CUST_{UNIQUE}", "phone": "9999999999", "state": "AP",
    }, timeout=T).json()
    # Create own + supplier vehicles for filter tests
    sup = httpx.post(f"{BASE}/api/suppliers", headers=h, json={
        "name": f"SUP_{UNIQUE}", "opening_balance": 0, "opening_balance_type": "payable",
    }, timeout=T).json()
    veh_own = httpx.post(f"{BASE}/api/vehicles", headers=h, json={
        "vehicle_number": f"AP99{UNIQUE[:4]}",
        "vehicle_type": "own",
    }, timeout=T).json()
    veh_sup = httpx.post(f"{BASE}/api/vehicles", headers=h, json={
        "vehicle_number": f"AP66{UNIQUE[:4]}",
        "vehicle_type": "supplier",
        "supplier_id": sup["id"],
        "supplier_name": sup["name"],
    }, timeout=T).json()
    trips = []
    for i, (date, veh_id, veh_number, from_loc, halting) in enumerate([
        ("2026-08-01", veh_own["id"], veh_own["vehicle_number"], "Kondapalli", 0),
        ("2026-08-05", veh_sup["id"], veh_sup["vehicle_number"], "Vizag", 3000),
        ("2026-08-10", veh_own["id"], veh_own["vehicle_number"], "Kondapalli", 0),
    ]):
        payload = {
            "customer_id": cust["id"], "date": date,
            "vehicle_id": veh_id, "vehicle_number": veh_number,
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1500,
            "from_location": from_loc, "to_location": "Vijayawada",
            "load_details": f"Bitumen VG 40 - {UNIQUE}", "halting_amount": halting,
            "halting_amount_override": halting > 0,
        }
        if veh_id == veh_sup["id"]:
            payload["supplier_id"] = sup["id"]
            payload["supplier_name"] = sup["name"]
        r = httpx.post(f"{BASE}/api/trips", headers=h, json=payload, timeout=T)
        assert r.status_code == 200, f"create trip {i} failed: {r.text}"
        trips.append(r.json())
    return {"cust": cust, "sup": sup, "veh_own": veh_own, "veh_sup": veh_sup, "trips": trips}


def test_list_returns_pagination_headers():
    r = httpx.get(f"{BASE}/api/trips", headers=_h(), params={"limit": 5}, timeout=30)
    assert r.status_code == 200
    assert "x-total-count" in {k.lower() for k in r.headers.keys()}, "X-Total-Count header missing"
    assert "x-has-more" in {k.lower() for k in r.headers.keys()}, "X-Has-More header missing"
    items = r.json()
    assert isinstance(items, list)
    assert len(items) <= 5


def test_pagination_limit_offset(seed):
    r1 = httpx.get(f"{BASE}/api/trips", headers=_h(), params={"limit": 2, "offset": 0}, timeout=30)
    r2 = httpx.get(f"{BASE}/api/trips", headers=_h(), params={"limit": 2, "offset": 2}, timeout=30)
    assert r1.status_code == 200 and r2.status_code == 200
    ids1 = [t["id"] for t in r1.json()]
    ids2 = [t["id"] for t in r2.json()]
    # No overlap between page 1 and page 2
    assert set(ids1).isdisjoint(set(ids2)), f"pages overlap: {ids1} vs {ids2}"


def test_customer_id_filter(seed):
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"customer_id": seed["cust"]["id"], "limit": 50}, timeout=30)
    trips = r.json()
    assert len(trips) >= 3
    assert all(t["customer_id"] == seed["cust"]["id"] for t in trips)


def test_vehicle_id_filter(seed):
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"vehicle_id": seed["veh_own"]["id"], "limit": 50}, timeout=30)
    trips = r.json()
    assert len(trips) >= 2
    assert all(t["vehicle_id"] == seed["veh_own"]["id"] for t in trips)


def test_supplier_id_filter(seed):
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"supplier_id": seed["sup"]["id"], "limit": 50}, timeout=30)
    trips = r.json()
    assert len(trips) == 1, f"expected 1 supplier trip, got {len(trips)}"
    assert trips[0]["supplier_id"] == seed["sup"]["id"]


def test_single_date_filter(seed):
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"date": "2026-08-05", "customer_id": seed["cust"]["id"], "limit": 50}, timeout=30)
    trips = r.json()
    assert len(trips) == 1
    assert trips[0]["date"] == "2026-08-05"


def test_date_range_filter(seed):
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"date_from": "2026-08-01", "date_to": "2026-08-05",
                          "customer_id": seed["cust"]["id"], "limit": 50}, timeout=30)
    trips = r.json()
    assert len(trips) == 2
    dates = sorted(t["date"] for t in trips)
    assert dates == ["2026-08-01", "2026-08-05"]


def test_q_matches_lr_number(seed):
    lr = seed["trips"][0].get("lr_number")
    if not lr:
        pytest.skip("no LR number auto-assigned")
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"q": lr, "limit": 10}, timeout=30)
    trips = r.json()
    assert any(t["id"] == seed["trips"][0]["id"] for t in trips), "trip not found by LR search"


def test_q_matches_vehicle_number(seed):
    # Use full vehicle number to avoid noisy prefix matches from seed data
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"q": seed["veh_own"]["vehicle_number"],
                          "customer_id": seed["cust"]["id"], "limit": 10}, timeout=30)
    trips = r.json()
    assert any(t["vehicle_id"] == seed["veh_own"]["id"] for t in trips), \
        f"trip not found by vehicle_number search: got {[t.get('vehicle_number') for t in trips]}"


def test_q_matches_customer_name(seed):
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"q": f"CUST_{UNIQUE}", "limit": 10}, timeout=30)
    trips = r.json()
    assert any(t["customer_id"] == seed["cust"]["id"] for t in trips), \
        "trip not found by customer name search"


def test_q_matches_from_location(seed):
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"q": "Vizag", "customer_id": seed["cust"]["id"], "limit": 10}, timeout=30)
    trips = r.json()
    assert len(trips) == 1
    assert trips[0]["from_location"] == "Vizag"


def test_halting_only_filter(seed):
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"halting_only": "true", "customer_id": seed["cust"]["id"], "limit": 10}, timeout=30)
    trips = r.json()
    assert len(trips) == 1
    assert trips[0]["halting_amount"] > 0


def test_combined_filters_apply_AND(seed):
    """User's example: date range + customer + vehicle should intersect."""
    r = httpx.get(f"{BASE}/api/trips", headers=_h(), params={
        "date_from": "2026-08-01", "date_to": "2026-08-10",
        "customer_id": seed["cust"]["id"],
        "vehicle_id": seed["veh_own"]["id"],
        "limit": 50,
    }, timeout=30)
    trips = r.json()
    assert len(trips) == 2, f"expected 2 combined-filter matches, got {len(trips)}"
    for t in trips:
        assert t["customer_id"] == seed["cust"]["id"]
        assert t["vehicle_id"] == seed["veh_own"]["id"]
        assert "2026-08-01" <= t["date"] <= "2026-08-10"


def test_results_sorted_latest_first(seed):
    r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                  params={"customer_id": seed["cust"]["id"], "limit": 10}, timeout=30)
    trips = r.json()
    dates = [t["date"] for t in trips]
    assert dates == sorted(dates, reverse=True), f"not sorted latest-first: {dates}"


def test_multi_company_isolation():
    """Trips filtered from Company A must never appear when active company is B."""
    comps = httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=30).json()
    if len(comps) < 2:
        pytest.skip("need 2+ companies")
    cid_a = comps[0]["id"]
    cid_b = comps[1]["id"]
    # List trips in A and B — no ID overlap
    ids_a = {t["id"] for t in httpx.get(f"{BASE}/api/trips", headers={**HDR, "X-Company-Id": cid_a}, params={"limit": 200}, timeout=30).json()}
    ids_b = {t["id"] for t in httpx.get(f"{BASE}/api/trips", headers={**HDR, "X-Company-Id": cid_b}, params={"limit": 200}, timeout=30).json()}
    assert ids_a.isdisjoint(ids_b), "cross-company trip leak"


def test_frontend_exposes_required_testids():
    with open("/app/frontend/src/pages/Trips.jsx") as f:
        content = f.read()
    for tid in ("trips-filter-bar", "trips-search-input", "trips-filter-date-from",
                "trips-filter-date-to", "trips-filter-customer", "trips-filter-vehicle",
                "trips-filter-supplier", "trips-clear-filters", "trips-pagination",
                "pagination-prev", "pagination-next", "trip-count-total",
                "preset-7d", "preset-30d", "preset-90d"):
        assert tid in content, f"testid {tid!r} missing from Trips.jsx"
