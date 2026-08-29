"""Iter73 · Supplier Freight auto-calc, LR Consignee resolution, Suppliers dashboard perf.

Locks in:
1. Trip create with vehicle_type='supplier' + per_ton mode auto-computes
   supplier_freight from supplier_rate_per_ton × supplier_quantity (fallback: tons).
2. Trip create with fixed mode: computes freight from KMs × rate/ton/km OR falls
   back to supplier_fixed_amount.
3. LR PDF `_resolve_consignee_site` — priority: manual override → Ship-To
   (site_name · address) → trip.to_location.
4. `/api/suppliers-dashboard` responds under 5 seconds even on the demo tenant
   (was 58 s). Locks in the bulk-aggregation rewrite.
"""
import os, uuid, time, httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}
UNIQUE = f"IT73_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=30).json()


def _cust(h):
    return httpx.post(f"{BASE}/api/customers", json={"name": f"{UNIQUE}_C_{uuid.uuid4().hex[:6]}"}, headers=h, timeout=15).json()


def _sup(h):
    return httpx.post(
        f"{BASE}/api/suppliers",
        json={"name": f"{UNIQUE}_Sup_{uuid.uuid4().hex[:5]}", "mobile": f"9{uuid.uuid4().int % 10**9:09d}", "state": "AP"},
        headers=h, timeout=15,
    ).json()


# ---------------------------------------------------------------------------
# 1. Supplier Freight — per_ton auto-compute
# ---------------------------------------------------------------------------
def test_supplier_freight_per_ton_auto_computes():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)
    trip = httpx.post(f"{BASE}/api/trips", headers=h, json={
        "customer_id": c["id"],
        "date": "2027-07-01",
        "vehicle_number": f"AP73{uuid.uuid4().hex[:5].upper()}",
        "vehicle_type": "supplier",
        "supplier_id": s["id"],
        "tons": 15.0,
        "freight_mode": "per_ton", "rate_per_ton": 1200,
        "supplier_freight_mode": "per_ton",
        "supplier_rate_per_ton": 900,
        # NOTE: intentionally NOT passing supplier_freight — server must compute
    }, timeout=30).json()
    assert trip.get("supplier_freight") == 15.0 * 900, f"expected {15*900}, got {trip.get('supplier_freight')}"
    # Net payable = freight (no other deductions)
    assert trip.get("supplier_net_payable") == 15.0 * 900


def test_supplier_freight_per_ton_uses_supplier_quantity_when_set():
    """Iter111 realignment · Server-derived supplier quantity (basis mirror).

    ORIGINAL Iter73 contract (retired): a user-supplied `supplier_quantity`
    took precedence over `tons` for supplier freight computation.

    APPROVED Iter111 contract (this test locks it in):
        Supplier Freight quantity MIRRORS the trip's `applied_freight_method`
        snapshot (per_ton_loading / per_ton_unloading / per_ton_higher_of /
        fixed). The server DERIVES `supplier_quantity` from that basis and
        ignores any user-supplied value on the payload — so supplier billing
        stays consistent with the customer-side freight computation. A stale
        `supplier_quantity` from an in-flight compute cannot leak forward.

    The test scenario here (default `applied_freight_method = per_ton_loading`,
    tons=15, no `unloaded_qty`) MUST resolve to a derived basis of 15.0 MT
    even when the payload asks for `supplier_quantity=12.5`.
    """
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)
    trip = httpx.post(f"{BASE}/api/trips", headers=h, json={
        "customer_id": c["id"], "date": "2027-07-02",
        "vehicle_number": f"AP73{uuid.uuid4().hex[:5].upper()}",
        "vehicle_type": "supplier", "supplier_id": s["id"],
        "tons": 15.0,
        "freight_mode": "per_ton", "rate_per_ton": 1200,
        "supplier_quantity": 12.5,          # user hint — Iter111 ignores it
        "supplier_freight_mode": "per_ton",
        "supplier_rate_per_ton": 900,
    }, timeout=30).json()
    # Iter111 · applied_freight_method defaults to per_ton_loading → basis=tons
    assert trip["supplier_quantity"] == 15.0, (
        f"Iter111: supplier_quantity must be server-derived from the applied "
        f"basis (per_ton_loading → loaded tons = 15.0), not the user's 12.5. "
        f"Got {trip['supplier_quantity']}"
    )
    assert trip["supplier_freight"] == 15.0 * 900, (
        f"Iter111: supplier_freight = derived basis × supplier_rate_per_ton "
        f"= 15.0 × 900. Got {trip['supplier_freight']}"
    )


def test_supplier_freight_fixed_mode():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)
    # Fixed with KMs × rate
    tr1 = httpx.post(f"{BASE}/api/trips", headers=h, json={
        "customer_id": c["id"], "date": "2027-07-03",
        "vehicle_number": f"AP73{uuid.uuid4().hex[:5].upper()}",
        "vehicle_type": "supplier", "supplier_id": s["id"],
        "tons": 10.0,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "supplier_freight_mode": "fixed",
        "supplier_round_trip_kms": 200,
        "supplier_rate_per_km_per_ton": 5,
    }, timeout=30).json()
    assert tr1["supplier_freight"] == 10.0 * 200 * 5

    # Fixed with just supplier_fixed_amount (no KMs)
    tr2 = httpx.post(f"{BASE}/api/trips", headers=h, json={
        "customer_id": c["id"], "date": "2027-07-04",
        "vehicle_number": f"AP73{uuid.uuid4().hex[:5].upper()}",
        "vehicle_type": "supplier", "supplier_id": s["id"],
        "tons": 10.0,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "supplier_freight_mode": "fixed",
        "supplier_fixed_amount": 12500,
    }, timeout=30).json()
    assert tr2["supplier_freight"] == 12500


# ---------------------------------------------------------------------------
# 3. LR Consignee resolver — unit test of the helper
# ---------------------------------------------------------------------------
def test_lr_consignee_resolver_priority():
    """Manual override > Ship-To > to_location. Import the helper directly."""
    import sys
    sys.path.insert(0, "/app/backend")
    from pdf.lr import _resolve_consignee_site

    customer = {
        "ship_sites": [
            {"id": "ss1", "site_name": "Vijayawada Plant", "address": "NH-16, Highway", "contact_person": "Ravi", "phone": "9998887771"},
        ],
    }

    # 1. Manual override wins
    trip1 = {"consignee_site_location": "MANUAL SITE", "consignee_site_contact": "9876543210",
             "ship_site_id": "ss1", "to_location": "Fallback City"}
    loc, ct = _resolve_consignee_site(trip1, customer)
    assert loc == "MANUAL SITE"
    assert ct == "9876543210"

    # 2. Ship-To wins when no manual override
    trip2 = {"consignee_site_location": "", "consignee_site_contact": "",
             "ship_site_id": "ss1", "to_location": "Fallback City"}
    loc, ct = _resolve_consignee_site(trip2, customer)
    assert "Vijayawada Plant" in loc
    assert "NH-16, Highway" in loc
    assert "Ravi" in ct

    # 3. to_location fallback when no ship_site and no manual override
    trip3 = {"consignee_site_location": "", "ship_site_id": "", "to_location": "Kurnool"}
    loc, ct = _resolve_consignee_site(trip3, customer)
    assert loc == "Kurnool"

    # 4. Ship-To id that doesn't exist on customer → still fallback to to_location
    trip4 = {"consignee_site_location": "", "ship_site_id": "does_not_exist", "to_location": "Kurnool"}
    loc, _ = _resolve_consignee_site(trip4, customer)
    assert loc == "Kurnool"


# ---------------------------------------------------------------------------
# 4. Suppliers dashboard performance
# ---------------------------------------------------------------------------
def test_suppliers_dashboard_completes_under_5s():
    """Iter73 · locks the bulk-aggregation rewrite. Was 58 s in iter72."""
    t0 = time.time()
    r = httpx.get(f"{BASE}/api/suppliers-dashboard", headers=HDR, timeout=30)
    elapsed = time.time() - t0
    assert r.status_code == 200
    assert elapsed < 5.0, f"suppliers-dashboard took {elapsed:.2f}s — regression from bulk aggregation"
    body = r.json()
    assert "totals" in body
    assert "suppliers" in body
    assert body["totals"]["total_suppliers"] >= 0
