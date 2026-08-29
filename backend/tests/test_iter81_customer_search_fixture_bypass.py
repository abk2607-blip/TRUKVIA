"""Iter81 — Customer search must find fixture-named customers when the user
explicitly types their name. Fixture-hide filter only applies to unfiltered browse.

Real trips can reference customers whose names happen to match the fixture
regex (e.g. imported with prefixes like `CUST_IT56_…`). The fixture-purge
keeps them alive because trips are attached, so search must be able to find
them or the user cannot invoice their own trip (bug reported by user with a
screenshot showing "No matches" for `CUST_IT56_dfbacb`).
"""
import os, uuid, httpx
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
TOK = os.environ["DEMO_TOKEN_VALUE"]
HA = {"Authorization": f"Bearer {TOK}"}


@pytest.fixture(scope="module")
def fx_customer():
    """Seed a fixture-named customer with a trip so the purge preserves it."""
    httpx.post(f"{BASE}/api/auth/demo-login", timeout=30)
    unique = uuid.uuid4().hex[:6]
    name = f"CUST_IT81_search_{unique}"
    cust = httpx.post(
        f"{BASE}/api/customers", headers=HA,
        json={"name": name, "phone": "9998887777", "state": "AP"},
        timeout=30,
    ).json()
    veh = httpx.post(
        f"{BASE}/api/vehicles", headers=HA,
        json={"vehicle_number": f"AP99IT81{unique[:4].upper()}", "vehicle_type": "own"},
        timeout=30,
    ).json()
    httpx.post(
        f"{BASE}/api/trips", headers=HA,
        json={
            "customer_id": cust["id"], "date": "2026-08-01",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1000,
            "from_location": "K", "to_location": "V",
        },
        timeout=30,
    )
    return {"id": cust["id"], "name": name}


def test_search_finds_fixture_named_customer(fx_customer):
    """Typing the fixture-named customer's name MUST return it."""
    r = httpx.get(f"{BASE}/api/customers?q={fx_customer['name']}", headers=HA, timeout=30)
    assert r.status_code == 200
    body = r.json()
    names = [c["name"] for c in body["items"]]
    assert fx_customer["name"] in names, f"expected {fx_customer['name']} in {names}"


def test_search_partial_fixture_prefix(fx_customer):
    """Partial match on the fixture prefix must also work."""
    r = httpx.get(f"{BASE}/api/customers?q=CUST_IT81_search", headers=HA, timeout=30)
    assert r.status_code == 200
    body = r.json()
    names = [c["name"] for c in body["items"]]
    assert fx_customer["name"] in names


def test_browse_no_q_still_hides_fixtures(fx_customer):
    """Browse mode (no q) MUST continue to hide fixture-named customers."""
    r = httpx.get(f"{BASE}/api/customers?limit=200", headers=HA, timeout=30)
    assert r.status_code == 200
    body = r.json()
    names = [c["name"] for c in body["items"]]
    assert fx_customer["name"] not in names, "fixture-named customer must be hidden in unfiltered browse"
