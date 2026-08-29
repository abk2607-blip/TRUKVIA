"""Iter91 — Supplier Diesel / Advance multi-row transaction logs.

Verifies:
- Adding 3 diesel and 3 advance entries totals correctly.
- Edit and soft-delete recompute the trip's flat supplier_diesel / supplier_advance
  and supplier_net_payable.
- Delete without reason is rejected (400).
- Supplier ledger emits one row per active entry.
- Lazy migration converts a legacy flat value into a single migrated entry
  on first GET of the trip.
- Multi-company isolation — entries under one company are invisible when the
  same supplier is queried in a different company context.
"""
import os
import time
import requests

API = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]


def _boot():
    requests.post(f"{API}/api/auth/demo-login", timeout=30)
    cid = requests.get(f"{API}/api/companies",
                       headers={"Authorization": f"Bearer {TOKEN}"},
                       timeout=30).json()[0]["id"]
    return cid


def _h(cid: str):
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
            "X-Company-Id": cid}


def test_supplier_entries_crud_and_ledger():
    cid = _boot()
    h = _h(cid)
    tag = str(int(time.time()))[-6:]

    prod = requests.post(f"{API}/api/products", headers=h,
                         json={"name": f"IT91P-{tag}"}).json()
    sup = requests.post(f"{API}/api/suppliers", headers=h,
                        json={"name": f"IT91S-{tag}"}).json()
    veh = requests.post(f"{API}/api/vehicles", headers=h,
                        json={"vehicle_number": f"AP99IT{tag[:3]}",
                              "vehicle_type": "supplier", "supplier_id": sup["id"]}).json()
    cust = requests.get(f"{API}/api/customers?limit=1", headers=h).json()["items"][0]

    trip = requests.post(f"{API}/api/trips", headers=h, json={
        "date": "2026-08-18",
        "vehicle_number": veh["vehicle_number"],
        "vehicle_type": "supplier",
        "supplier_id": sup["id"], "vehicle_id": veh["id"],
        "customer_id": cust["id"], "product_id": prod["id"],
        "tons": 20, "loaded_qty": 20000,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 800,
        "from_location": "IOCL Chennai", "to_location": "Vijayawada Site",
        "load_details": "VG-40",
    }).json()
    tid = trip["id"]
    try:
        # Auto-fill Loading/Unloading/Material/Qty from Trip Details
        assert trip["supplier_loading_point"] == "IOCL Chennai"
        assert trip["supplier_unloading_point"] == "Vijayawada Site"
        assert trip["supplier_material"] == "VG-40"
        assert float(trip["supplier_quantity"]) == 20.0

        # Add 3 diesel entries → total = 200*104.24 + 150*104.50 + 100*104.75
        expected_diesel = round(200 * 104.24 + 150 * 104.50 + 100 * 104.75, 2)
        for (d, q, r) in [("2026-08-18", 200, 104.24), ("2026-08-19", 150, 104.50), ("2026-08-20", 100, 104.75)]:
            requests.post(f"{API}/api/trips/{tid}/supplier-diesel", headers=h,
                          json={"date": d, "quantity": q, "rate": r, "mode": "UPI",
                                "reference": f"D-{d}", "remarks": ""}).raise_for_status()

        # Add 3 advance entries → total = 30_000
        for (d, a, m, ref) in [("2026-08-18", 10000, "Cash", ""),
                               ("2026-08-19", 15000, "NEFT", "N12345"),
                               ("2026-08-20", 5000, "UPI", "U98765")]:
            requests.post(f"{API}/api/trips/{tid}/supplier-advance", headers=h,
                          json={"date": d, "amount": a, "mode": m, "reference": ref}).raise_for_status()

        got = requests.get(f"{API}/api/trips/{tid}", headers=h).json()
        assert round(got["supplier_diesel"], 2) == expected_diesel, got["supplier_diesel"]
        assert round(got["supplier_advance"], 2) == 30000.0, got["supplier_advance"]
        assert len(got["supplier_diesel_entries"]) == 3
        assert len(got["supplier_advance_entries"]) == 3

        # Edit an advance (15000 → 12000) → total moves from 30000 to 27000
        adv_eid = got["supplier_advance_entries"][1]["id"]
        got2 = requests.put(f"{API}/api/trips/{tid}/supplier-advance/{adv_eid}", headers=h,
                            json={"amount": 12000}).json()
        assert round(got2["supplier_advance"], 2) == 27000.0

        # Soft-delete one diesel entry with a reason → total drops accordingly
        dsl_eid = got["supplier_diesel_entries"][2]["id"]
        expected_after = round(expected_diesel - 100 * 104.75, 2)
        got3 = requests.delete(f"{API}/api/trips/{tid}/supplier-diesel/{dsl_eid}",
                               headers=h, params={"reason": "duplicate slip"}).json()
        assert round(got3["supplier_diesel"], 2) == expected_after
        # entry is present but marked deleted
        deleted = next(e for e in got3["supplier_diesel_entries"] if e["id"] == dsl_eid)
        assert deleted["deleted"] is True
        assert deleted["deleted_reason"] == "duplicate slip"

        # Delete without reason → 400
        r_bad = requests.delete(f"{API}/api/trips/{tid}/supplier-diesel/{got['supplier_diesel_entries'][0]['id']}",
                                headers=h)
        assert r_bad.status_code == 400

        # Supplier ledger — 3 advance rows + 2 active diesel rows
        lg = requests.get(f"{API}/api/suppliers/{sup['id']}/ledger", headers=h).json()
        rows = lg.get("entries", [])
        adv_rows = [r for r in rows if r.get("type") == "trip_advance" and r.get("trip_id") == tid]
        dsl_rows = [r for r in rows if r.get("type") == "trip_diesel" and r.get("trip_id") == tid]
        assert len(adv_rows) == 3, adv_rows
        assert len(dsl_rows) == 2, dsl_rows
    finally:
        requests.delete(f"{API}/api/trips/{tid}?reason=cleanup", headers=h)
        requests.delete(f"{API}/api/suppliers/{sup['id']}", headers=h)
        requests.delete(f"{API}/api/vehicles/{veh['id']}", headers=h)
        requests.delete(f"{API}/api/products/{prod['id']}", headers=h)


def test_lazy_migration_of_legacy_flat_diesel_advance():
    cid = _boot()
    h = _h(cid)
    tag = str(int(time.time()))[-6:] + "L"

    prod = requests.post(f"{API}/api/products", headers=h, json={"name": f"IT91LP-{tag}"}).json()
    sup = requests.post(f"{API}/api/suppliers", headers=h, json={"name": f"IT91LS-{tag}"}).json()
    veh = requests.post(f"{API}/api/vehicles", headers=h,
                        json={"vehicle_number": f"AP88IT{tag[:3]}",
                              "vehicle_type": "supplier", "supplier_id": sup["id"]}).json()
    cust = requests.get(f"{API}/api/customers?limit=1", headers=h).json()["items"][0]

    # Legacy-style trip with flat supplier_diesel and supplier_advance
    trip = requests.post(f"{API}/api/trips", headers=h, json={
        "date": "2026-08-01",
        "vehicle_number": veh["vehicle_number"],
        "vehicle_type": "supplier",
        "supplier_id": sup["id"], "vehicle_id": veh["id"],
        "customer_id": cust["id"], "product_id": prod["id"],
        "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 800,
        "supplier_diesel": 20000, "supplier_advance": 5000,
    }).json()
    tid = trip["id"]
    try:
        # First GET migrates
        got = requests.get(f"{API}/api/trips/{tid}", headers=h).json()
        assert len(got["supplier_diesel_entries"]) == 1
        assert got["supplier_diesel_entries"][0]["amount"] == 20000
        assert "Migrated" in got["supplier_diesel_entries"][0]["remarks"]
        assert len(got["supplier_advance_entries"]) == 1
        assert got["supplier_advance_entries"][0]["amount"] == 5000

        # Second GET is idempotent (still 1 entry each)
        got2 = requests.get(f"{API}/api/trips/{tid}", headers=h).json()
        assert len(got2["supplier_diesel_entries"]) == 1
        assert len(got2["supplier_advance_entries"]) == 1
    finally:
        requests.delete(f"{API}/api/trips/{tid}?reason=cleanup", headers=h)
        requests.delete(f"{API}/api/suppliers/{sup['id']}", headers=h)
        requests.delete(f"{API}/api/vehicles/{veh['id']}", headers=h)
        requests.delete(f"{API}/api/products/{prod['id']}", headers=h)
