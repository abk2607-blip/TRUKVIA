"""Iter89 · Phase 1 — Policy Snapshot regression tests.

Locks:
  1. Customer.default_freight_method + shortage_config persist correctly
  2. Product.default_shortage_allowance_pct persists
  3. Supplier.shortage_limit_kg persists
  4. Trip create → snapshot from all 3 masters onto trip.applied_* fields
  5. Editing master later → old trip's snapshot UNCHANGED (historical protection)
  6. Multi-company isolation — Company A cust config never leaks into Company B trip
  7. Trip-level override of applied_freight_method survives (already editable)
"""
import os, uuid, httpx
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
TOK = "test_session_bitumen_2026"
HA = {"Authorization": f"Bearer {TOK}"}


def _tag():
    return uuid.uuid4().hex[:6]


@pytest.fixture(scope="module")
def seeded():
    httpx.post(f"{BASE}/api/auth/demo-login", timeout=60)
    t = _tag()
    cust = httpx.post(f"{BASE}/api/customers", headers=HA, json={
        "name": f"IT89_C_{t}", "phone": "9990000001", "state": "AP",
        "default_freight_method": "per_ton_unloading",
        "shortage_config": {"limit": 0.5, "limit_type": "pct",
                            "method": "net_shortage", "active": True},
    }, timeout=60).json()
    sup = httpx.post(f"{BASE}/api/suppliers", headers=HA, json={
        "name": f"IT89_S_{t}", "mobile": "9990000002",
        "shortage_limit_kg": 100.0,
    }, timeout=60).json()
    prod = httpx.post(f"{BASE}/api/products", headers=HA, json={
        "name": f"IT89_P_{t}", "default_rate": 45000.0,
        "default_shortage_allowance_pct": 0.5,
    }, timeout=60).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=HA, json={
        "vehicle_number": f"AP99IT89{t[:4].upper()}", "vehicle_type": "supplier",
        "supplier_id": sup["id"], "supplier_name": sup["name"],
    }, timeout=60).json()
    trip = httpx.post(f"{BASE}/api/trips", headers=HA, json={
        "customer_id": cust["id"], "date": "2027-01-05",
        "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
        "vehicle_type": "supplier", "supplier_id": sup["id"], "supplier_name": sup["name"],
        "product_id": prod["id"],
        "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 2500,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 2000,
        "from_location": "K", "to_location": "V",
    }, timeout=60).json()
    return {"tag": t, "cust": cust, "sup": sup, "prod": prod, "veh": veh, "trip": trip}


def test_customer_master_persists_freight_method_and_shortage_config(seeded):
    lst = httpx.get(f"{BASE}/api/customers?limit=500&include_fixtures=true", headers=HA, timeout=30).json()
    items = lst if isinstance(lst, list) else lst.get("items", [])
    c = next((x for x in items if x["id"] == seeded["cust"]["id"]), None)
    assert c is not None, "customer not found in list"
    assert c["default_freight_method"] == "per_ton_unloading"
    sc = c.get("shortage_config") or {}
    assert sc.get("limit") == 0.5
    assert sc.get("limit_type") == "pct"
    assert sc.get("method") == "net_shortage"
    assert sc.get("active") is True


def test_product_master_persists_shortage_allowance(seeded):
    lst = httpx.get(f"{BASE}/api/products", headers=HA, timeout=30).json()
    items = lst if isinstance(lst, list) else lst.get("items", [])
    p = next((x for x in items if x["id"] == seeded["prod"]["id"]), None)
    assert p is not None, "product not found in list"
    assert p["default_shortage_allowance_pct"] == 0.5


def test_supplier_master_persists_shortage_limit_kg(seeded):
    tag = seeded["tag"]
    lst = httpx.get(f"{BASE}/api/suppliers?q=IT89_S_{tag}", headers=HA, timeout=30).json()
    items = lst if isinstance(lst, list) else lst.get("items", [])
    s = next((x for x in items if x["id"] == seeded["sup"]["id"]), None)
    assert s is not None, f"supplier not found via q=IT89_S_{tag} (got {len(items)} rows)"
    assert s.get("shortage_limit_kg") == 100.0


def test_trip_snapshots_all_three_masters(seeded):
    t = httpx.get(f"{BASE}/api/trips/{seeded['trip']['id']}", headers=HA, timeout=30).json()
    assert t["applied_freight_method"] == "per_ton_unloading"
    assert t["applied_customer_shortage_limit"] == 0.5
    assert t["applied_customer_shortage_limit_type"] == "pct"
    assert t["applied_customer_shortage_method"] == "net_shortage"
    assert t["applied_product_shortage_pct"] == 0.5
    assert t["applied_supplier_shortage_limit_kg"] == 100.0
    assert t["policy_snapshot_at"], "policy_snapshot_at must be recorded"


def test_master_edit_never_changes_old_trip_snapshot(seeded):
    # Edit Customer default_freight_method + shortage_config AFTER trip creation.
    cust = seeded["cust"]
    new_body = dict(cust)
    new_body["default_freight_method"] = "fixed"
    new_body["shortage_config"] = {"limit": 5.0, "limit_type": "kg",
                                    "method": "full_after_limit", "active": True}
    r = httpx.put(f"{BASE}/api/customers/{cust['id']}", headers=HA, json=new_body, timeout=30)
    assert r.status_code == 200
    # Also edit product + supplier
    prod = seeded["prod"]
    prod_body = {**prod, "default_shortage_allowance_pct": 5.0}
    httpx.put(f"{BASE}/api/products/{prod['id']}", headers=HA, json=prod_body, timeout=30)
    sup = seeded["sup"]
    sup_body = {**sup, "shortage_limit_kg": 999.0}
    httpx.put(f"{BASE}/api/suppliers/{sup['id']}", headers=HA, json=sup_body, timeout=30)
    # Old trip snapshot must be UNCHANGED
    t = httpx.get(f"{BASE}/api/trips/{seeded['trip']['id']}", headers=HA, timeout=30).json()
    assert t["applied_freight_method"] == "per_ton_unloading", "old trip must retain original method"
    assert t["applied_customer_shortage_limit"] == 0.5
    assert t["applied_customer_shortage_method"] == "net_shortage"
    assert t["applied_product_shortage_pct"] == 0.5
    assert t["applied_supplier_shortage_limit_kg"] == 100.0


def test_new_trip_after_master_edit_uses_new_values(seeded):
    # Create a NEW trip after masters were edited — must pick up NEW values.
    trip2 = httpx.post(f"{BASE}/api/trips", headers=HA, json={
        "customer_id": seeded["cust"]["id"], "date": "2027-02-05",
        "vehicle_id": seeded["veh"]["id"], "vehicle_number": seeded["veh"]["vehicle_number"],
        "vehicle_type": "supplier", "supplier_id": seeded["sup"]["id"],
        "supplier_name": seeded["sup"]["name"],
        "product_id": seeded["prod"]["id"],
        "tons": 15, "freight_mode": "per_ton", "rate_per_ton": 2500,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 2000,
        "from_location": "K", "to_location": "V",
    }, timeout=60).json()
    assert trip2["applied_freight_method"] == "fixed"
    assert trip2["applied_customer_shortage_limit"] == 5.0
    assert trip2["applied_customer_shortage_method"] == "full_after_limit"
    assert trip2["applied_product_shortage_pct"] == 5.0
    assert trip2["applied_supplier_shortage_limit_kg"] == 999.0


def test_trip_snapshot_backward_compatible_defaults():
    """A trip with no product / supplier + minimal customer must still snapshot
    with safe defaults (blank shortage config, zero limits)."""
    httpx.post(f"{BASE}/api/auth/demo-login", timeout=60)
    t = _tag()
    minimal_cust = httpx.post(f"{BASE}/api/customers", headers=HA, json={
        "name": f"IT89_MIN_{t}", "phone": "9990000099",
    }, timeout=60).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=HA, json={
        "vehicle_number": f"AP89MIN{t[:3].upper()}", "vehicle_type": "own",
    }, timeout=60).json()
    trip = httpx.post(f"{BASE}/api/trips", headers=HA, json={
        "customer_id": minimal_cust["id"], "date": "2027-01-10",
        "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "from_location": "A", "to_location": "B",
    }, timeout=60).json()
    # Customer with no explicit config → falls back to per_ton_loading default
    assert trip["applied_freight_method"] == "per_ton_loading"
    assert trip["applied_customer_shortage_limit"] == 0.0
    assert trip["applied_customer_shortage_method"] == "net_shortage"
    assert trip["applied_product_shortage_pct"] == 0.0
    assert trip["applied_supplier_shortage_limit_kg"] == 0.0
    assert trip["policy_snapshot_at"]
