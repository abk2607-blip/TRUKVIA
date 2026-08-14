"""Iter72 · Ship-To / Vehicle / Supplier Sync — root-cause tests

Locks in three behaviours the UI depends on:
1. POST /api/customers/{cid}/ship-sites is idempotent on site_name (case-fold)
   and returns the EXISTING site instead of a duplicate.
2. POST /api/vehicles is idempotent on vehicle_number (upper-cased) and
   returns the existing row for the same company.
3. POST /api/vehicles with vehicle_type='supplier' HYDRATES supplier_name /
   mobile / gstin / state / contact_person from the supplier master — any
   value passed by the client is overwritten with the master's canonical
   value. Missing supplier_id → 400.
"""
import os, uuid, httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
HDR = {"Authorization": "Bearer test_session_bitumen_2026"}
UNIQUE = f"IT72_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=30).json()


def _new_customer(h):
    return httpx.post(f"{BASE}/api/customers", json={"name": f"{UNIQUE}_Cust"}, headers=h, timeout=15).json()


def _new_supplier(h):
    return httpx.post(
        f"{BASE}/api/suppliers",
        json={"name": f"{UNIQUE}_Sup", "mobile": "9990001111", "gst_in": "37XX1234A1Z5", "state": "Andhra Pradesh"},
        headers=h, timeout=15,
    ).json()


def test_ship_site_dedup_and_first_becomes_default():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _new_customer(h)
    s1 = httpx.post(
        f"{BASE}/api/customers/{c['id']}/ship-sites",
        json={"site_name": "Vijayawada Plant", "address": "A"},
        headers=h, timeout=15,
    ).json()
    assert s1["is_default"] is True, "first site must auto-default"
    # Duplicate — same name (case-insensitive), different address
    s2 = httpx.post(
        f"{BASE}/api/customers/{c['id']}/ship-sites",
        json={"site_name": "vijayawada PLANT", "address": "different"},
        headers=h, timeout=15,
    ).json()
    assert s2["id"] == s1["id"], "duplicate site_name must return existing id"
    listing = httpx.get(f"{BASE}/api/customers/{c['id']}/ship-sites", headers=h, timeout=15).json()
    assert listing["total"] == 1, f"expected 1 site after dedup, got {listing['total']}"


def test_ship_site_blank_name_rejected():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _new_customer(h)
    r = httpx.post(f"{BASE}/api/customers/{c['id']}/ship-sites",
                   json={"site_name": "   "}, headers=h, timeout=15)
    assert r.status_code == 400


def test_vehicle_dedup_by_number_within_company():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    vn = f"AP{uuid.uuid4().hex[:8].upper()}"
    v1 = httpx.post(f"{BASE}/api/vehicles", json={"vehicle_number": vn, "vehicle_type": "own"}, headers=h, timeout=15).json()
    v2 = httpx.post(f"{BASE}/api/vehicles", json={"vehicle_number": vn.lower(), "vehicle_type": "own"}, headers=h, timeout=15).json()
    assert v1["id"] == v2["id"], "duplicate vehicle_number must return existing id"
    assert v2["vehicle_number"] == vn, "vehicle_number must be normalised to upper-case"


def test_vehicle_supplier_id_required_for_supplier_type():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    r = httpx.post(f"{BASE}/api/vehicles", json={"vehicle_number": f"AP{uuid.uuid4().hex[:8].upper()}", "vehicle_type": "supplier"}, headers=h, timeout=15)
    assert r.status_code == 400
    assert "supplier" in r.json()["detail"].lower()


def test_vehicle_supplier_hydrates_from_master_and_ignores_client_text():
    """The vehicle row is the source of truth for supplier text — client
    can't accidentally save a stale name. Master values always win."""
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    sup = _new_supplier(h)
    vn = f"AP{uuid.uuid4().hex[:8].upper()}"
    v = httpx.post(f"{BASE}/api/vehicles", json={
        "vehicle_number": vn,
        "vehicle_type": "supplier",
        "supplier_id": sup["id"],
        # Deliberate wrong text — server must overwrite these from master:
        "supplier_name": "STALE NAME",
        "supplier_mobile": "0000000000",
        "supplier_state": "Wrong State",
        "supplier_gstin": "BADGSTIN",
    }, headers=h, timeout=15).json()
    assert v["supplier_id"] == sup["id"]
    assert v["supplier_name"] == sup["name"]
    assert v["supplier_mobile"] == sup["mobile"]
    assert v["supplier_state"] == sup["state"]
    assert v["supplier_gstin"] == sup["gst_in"]


def test_vehicle_own_never_carries_supplier_text():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    vn = f"AP{uuid.uuid4().hex[:8].upper()}"
    v = httpx.post(f"{BASE}/api/vehicles", json={
        "vehicle_number": vn,
        "vehicle_type": "own",
        # Client passes supplier fields by mistake — server must strip them
        "supplier_id": "sup_bogus",
        "supplier_name": "SHOULD NOT SURVIVE",
        "supplier_mobile": "9999999999",
    }, headers=h, timeout=15).json()
    assert v["supplier_id"] == ""
    assert v["supplier_name"] == ""
    assert v["supplier_mobile"] == ""


def test_vehicle_supplier_cross_tenant_rejected():
    """Supplier from Company A cannot be attached to a vehicle in Company B."""
    cs = _companies()
    if len(cs) < 2:
        httpx.post(f"{BASE}/api/companies", json={"name": f"IsoCoB {UNIQUE}"}, headers=HDR, timeout=15)
        cs = _companies()
    ha = {**HDR, "X-Company-Id": cs[0]["id"]}
    hb = {**HDR, "X-Company-Id": cs[1]["id"]}
    sup_a = _new_supplier(ha)
    if "id" not in sup_a:
        # If supplier creation failed for any reason (mobile dedup, etc.),
        # find any existing supplier in cs[0].
        sups = httpx.get(f"{BASE}/api/suppliers", headers=ha, timeout=15).json()
        sup_a = sups[0] if sups else None
    assert sup_a and sup_a.get("id"), "test setup — need at least one supplier in company A"
    r = httpx.post(f"{BASE}/api/vehicles", json={
        "vehicle_number": f"AP{uuid.uuid4().hex[:8].upper()}",
        "vehicle_type": "supplier",
        "supplier_id": sup_a["id"],
    }, headers=hb, timeout=15)
    assert r.status_code == 400, "cross-tenant supplier reference must fail"
