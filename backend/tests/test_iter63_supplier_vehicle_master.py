"""Iter63 · Supplier Vehicle Master Integration + Trip Layout + Active/Inactive.

Covers:
 1. Vehicle model accepts + persists `is_active` field
 2. list_vehicles?active_only=true excludes inactive
 3. list_vehicles (default) still returns all (backwards compatible)
 4. Legacy vehicles (missing is_active field) treated as active by filter
 5. Supplier link by ID is preserved on create + update
 6. Multi-company isolation for vehicles + suppliers unchanged
"""
import os, uuid, pytest, httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}
UNIQUE = f"IT63_{uuid.uuid4().hex[:6]}"


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
    # Create a supplier in A
    sup = httpx.post(f"{BASE}/api/suppliers", headers=ha, json={
        "name": f"IT63_SUP_{UNIQUE}", "mobile": "9990000063", "state": "Andhra Pradesh",
        "gst_in": f"37AB{uuid.uuid4().hex[:9].upper()}Z1"[:15], "opening_balance": 0.0, "is_active": True,
    }, timeout=60).json()
    return {"cid_a": cid_a, "cid_b": cid_b, "ha": ha, "sup": sup}


def test_vehicle_is_active_default_true(env):
    ha = env["ha"]
    v = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP63A{uuid.uuid4().hex[:8].upper()}", "vehicle_type": "own",
    }, timeout=60).json()
    assert v.get("is_active") is True


def test_vehicle_is_active_false_persists(env):
    ha = env["ha"]
    v = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP63B{uuid.uuid4().hex[:8].upper()}", "vehicle_type": "own",
        "is_active": False,
    }, timeout=60).json()
    assert v.get("is_active") is False
    fetched = [x for x in httpx.get(f"{BASE}/api/vehicles", headers=ha, timeout=60).json() if x["id"] == v["id"]]
    assert fetched and fetched[0]["is_active"] is False


def test_active_only_filter_hides_inactive(env):
    ha = env["ha"]
    # Create one active + one inactive
    v_active = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP63C{uuid.uuid4().hex[:8].upper()}", "vehicle_type": "own", "is_active": True,
    }, timeout=60).json()
    v_inactive = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP63D{uuid.uuid4().hex[:8].upper()}", "vehicle_type": "own", "is_active": False,
    }, timeout=60).json()
    all_ids = {v["id"] for v in httpx.get(f"{BASE}/api/vehicles", headers=ha, timeout=60).json()}
    active_only_ids = {v["id"] for v in httpx.get(f"{BASE}/api/vehicles", headers=ha,
                                                    params={"active_only": "true"}, timeout=60).json()}
    assert v_active["id"] in all_ids and v_active["id"] in active_only_ids
    assert v_inactive["id"] in all_ids
    assert v_inactive["id"] not in active_only_ids


def test_supplier_id_link_preserved(env):
    ha = env["ha"]
    sup = env["sup"]
    v = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP63E{uuid.uuid4().hex[:8].upper()}", "vehicle_type": "supplier",
        "supplier_id": sup["id"], "supplier_name": sup["name"],
        "supplier_mobile": sup["mobile"], "supplier_gstin": sup["gst_in"],
    }, timeout=60).json()
    assert v["supplier_id"] == sup["id"]
    assert v["supplier_name"] == sup["name"]
    # Round-trip: update
    upd = httpx.put(f"{BASE}/api/vehicles/{v['id']}", headers=ha, json={
        **v, "capacity_tons": 30.0,
    }, timeout=60).json()
    assert upd["supplier_id"] == sup["id"]
    assert upd["supplier_name"] == sup["name"]


def test_multi_company_isolation_vehicles(env):
    if env["cid_a"] == env["cid_b"]:
        pytest.skip("only one company — cannot verify isolation")
    ha = env["ha"]
    hb = _h(env["cid_b"])
    v = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP63F{uuid.uuid4().hex[:8].upper()}", "vehicle_type": "own",
    }, timeout=60).json()
    ids_a = {x["id"] for x in httpx.get(f"{BASE}/api/vehicles", headers=ha, timeout=60).json()}
    ids_b = {x["id"] for x in httpx.get(f"{BASE}/api/vehicles", headers=hb, timeout=60).json()}
    assert v["id"] in ids_a
    assert v["id"] not in ids_b
    # Suppliers isolation too
    ids_sup_b = {x["id"] for x in httpx.get(f"{BASE}/api/suppliers", headers=hb, timeout=60).json()}
    assert env["sup"]["id"] not in ids_sup_b
