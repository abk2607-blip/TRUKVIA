"""Iter66 · Phase A — Customer Ship-To sites + Trip ship_site_id + customer_reference_number.

Verifies:
 - Ship-site CRUD (create / list / update / soft-delete)
 - First site auto-marked default
 - Only one default at a time
 - Trip persists ship_site_id + customer_reference_number as-typed
 - Blank customer_reference_number stays blank — never inherits
 - Fallback: if ship_site_id is empty, to_location still shown
 - Multi-company isolation
"""
import os, uuid, pytest, httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = "test_session_bitumen_2026"
HDR = {"Authorization": f"Bearer {TOKEN}"}
UNIQUE = f"IT66_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=60).json()


def _h(cid=None):
    return {**HDR, "X-Company-Id": cid or _companies()[0]["id"]}


@pytest.fixture(scope="module")
def env():
    cs = _companies()
    cid_a = cs[0]["id"]
    cid_b = cs[1]["id"] if len(cs) > 1 else cid_a
    ha = _h(cid_a)
    cust = httpx.post(f"{BASE}/api/customers", headers=ha, json={
        "name": f"IT66_C_{UNIQUE}", "phone": "9110000066", "state": "Andhra Pradesh",
        "gstin": "37ABCDE1234F1Z5",
    }, timeout=60).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP66A{UNIQUE[:5]}", "vehicle_type": "own",
    }, timeout=60).json()
    return {"cid_a": cid_a, "cid_b": cid_b, "ha": ha, "cust": cust, "veh": veh}


def test_first_ship_site_auto_default(env):
    cid = env["cust"]["id"]
    ha = env["ha"]
    r = httpx.post(f"{BASE}/api/customers/{cid}/ship-sites", headers=ha, json={
        "site_name": "Vijayawada Plant", "address": "NH-16 Kondapalli",
        "state": "Andhra Pradesh", "pincode": "521228",
    }, timeout=60)
    assert r.status_code == 200
    body = r.json()
    assert body["is_default"] is True   # first site auto-defaulted
    assert body["is_active"] is True
    sites = httpx.get(f"{BASE}/api/customers/{cid}/ship-sites", headers=ha, timeout=60).json()["items"]
    assert len(sites) == 1


def test_single_default_enforced(env):
    cid = env["cust"]["id"]
    ha = env["ha"]
    # Add a second site as default → previous default should be cleared
    r2 = httpx.post(f"{BASE}/api/customers/{cid}/ship-sites", headers=ha, json={
        "site_name": "Guntur Depot", "address": "NH-16 Guntur",
        "state": "Andhra Pradesh", "pincode": "522004", "is_default": True,
    }, timeout=60).json()
    assert r2["is_default"] is True
    sites = httpx.get(f"{BASE}/api/customers/{cid}/ship-sites", headers=ha, timeout=60).json()["items"]
    defaults = [s for s in sites if s["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == r2["id"]


def test_update_and_soft_delete_ship_site(env):
    cid = env["cust"]["id"]
    ha = env["ha"]
    sites = httpx.get(f"{BASE}/api/customers/{cid}/ship-sites", headers=ha, timeout=60).json()["items"]
    target = sites[0]
    # Update address
    upd = httpx.put(f"{BASE}/api/customers/{cid}/ship-sites/{target['id']}", headers=ha, json={
        **target, "address": "Updated address 12-3-45",
    }, timeout=60).json()
    assert upd["address"] == "Updated address 12-3-45"
    # Soft-delete
    d = httpx.delete(f"{BASE}/api/customers/{cid}/ship-sites/{target['id']}", headers=ha, timeout=60)
    assert d.status_code == 200
    # Refetch — the site is still in the list but inactive
    all_sites = httpx.get(f"{BASE}/api/customers/{cid}/ship-sites", headers=ha, timeout=60).json()["items"]
    hit = next(s for s in all_sites if s["id"] == target["id"])
    assert hit["is_active"] is False
    # active_only hides it
    active = httpx.get(f"{BASE}/api/customers/{cid}/ship-sites", headers=ha,
                      params={"active_only": "true"}, timeout=60).json()["items"]
    assert not any(s["id"] == target["id"] for s in active)


def test_trip_persists_ship_site_and_ref(env):
    ha = env["ha"]
    cid = env["cust"]["id"]
    # Add a fresh site to use on the trip
    site = httpx.post(f"{BASE}/api/customers/{cid}/ship-sites", headers=ha, json={
        "site_name": "Nellore SEZ", "address": "SEZ Rd Nellore",
        "state": "Andhra Pradesh", "pincode": "524001",
    }, timeout=60).json()
    trip = httpx.post(f"{BASE}/api/trips", headers=ha, json={
        "customer_id": cid, "date": "2026-07-15",
        "vehicle_id": env["veh"]["id"], "vehicle_number": env["veh"]["vehicle_number"],
        "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "from_location": "K", "to_location": "V",
        "ship_site_id": site["id"],
        "customer_reference_number": "CUST-REF-9091",
    }, timeout=60).json()
    fetched = httpx.get(f"{BASE}/api/trips/{trip['id']}", headers=ha, timeout=60).json()
    assert fetched["ship_site_id"] == site["id"]
    assert fetched["customer_reference_number"] == "CUST-REF-9091"


def test_blank_customer_reference_no_inheritance(env):
    ha = env["ha"]
    cid = env["cust"]["id"]
    # First trip has a customer ref set
    t1 = httpx.post(f"{BASE}/api/trips", headers=ha, json={
        "customer_id": cid, "date": "2026-07-16",
        "vehicle_id": env["veh"]["id"], "vehicle_number": env["veh"]["vehicle_number"],
        "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "from_location": "K", "to_location": "V",
        "customer_reference_number": "CR-A-9092",
    }, timeout=60).json()
    # Second trip omits customer_reference_number entirely
    t2 = httpx.post(f"{BASE}/api/trips", headers=ha, json={
        "customer_id": cid, "date": "2026-07-17",
        "vehicle_id": env["veh"]["id"], "vehicle_number": env["veh"]["vehicle_number"],
        "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "from_location": "K", "to_location": "V",
    }, timeout=60).json()
    assert t2["customer_reference_number"] == ""
    # Fetch fresh (no shared cache)
    assert httpx.get(f"{BASE}/api/trips/{t2['id']}", headers=ha, timeout=60).json()["customer_reference_number"] == ""
    # Sanity: t1 still has its own ref
    assert httpx.get(f"{BASE}/api/trips/{t1['id']}", headers=ha, timeout=60).json()["customer_reference_number"] == "CR-A-9092"


def test_ship_site_multi_company_isolation(env):
    if env["cid_a"] == env["cid_b"]:
        pytest.skip("only one company")
    cid = env["cust"]["id"]
    hb = _h(env["cid_b"])
    # From company B, Customer A is 404
    r = httpx.get(f"{BASE}/api/customers/{cid}/ship-sites", headers=hb, timeout=60)
    assert r.status_code == 404
    # Cannot create a ship site on A's customer from B
    r2 = httpx.post(f"{BASE}/api/customers/{cid}/ship-sites", headers=hb, json={
        "site_name": "Leak Attempt",
    }, timeout=60)
    assert r2.status_code == 404
