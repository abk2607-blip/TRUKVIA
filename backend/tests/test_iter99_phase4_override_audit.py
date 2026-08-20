"""Iter99 · Phase 4 — Per-Field Override Audit Trail."""
import os, time, requests

API = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com")
TOKEN = "test_session_bitumen_2026"


def _boot():
    requests.post(f"{API}/api/auth/demo-login", timeout=30)
    cid = requests.get(f"{API}/api/companies",
                       headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30).json()[0]["id"]
    return cid


def _h(cid):
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
            "X-Company-Id": cid}


def test_phase4_field_override_audit_trail():
    cid = _boot()
    h = _h(cid)
    tag = str(int(time.time()))[-6:]

    prod = requests.post(f"{API}/api/products", headers=h, json={"name": f"P99-{tag}"}).json()
    cust = requests.post(f"{API}/api/customers", headers=h, json={"name": f"C99-{tag}"}).json()
    veh = requests.post(f"{API}/api/vehicles", headers=h,
                        json={"vehicle_number": f"AP99IT{tag[:3]}", "vehicle_type": "own"}).json()

    trip = requests.post(f"{API}/api/trips", headers=h, json={
        "date": "2026-08-20", "vehicle_number": veh["vehicle_number"], "vehicle_type": "own",
        "customer_id": cust["id"], "product_id": prod["id"],
        "tons": 20, "loaded_qty": 20, "unloaded_qty": 20,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
    }).json()
    tid = trip["id"]
    try:
        # Log Freight override
        r = requests.post(f"{API}/api/trips/{tid}/field-override", headers=h, json={
            "field": "freight_amount",
            "system_value": 20000, "final_value": 22500,
            "reason": "Customer agreed revised freight",
        })
        assert r.status_code == 200, r.text
        got = r.json()
        assert len(got["field_overrides"]) == 1
        ent = got["field_overrides"][0]
        assert ent["field"] == "freight_amount"
        assert ent["system_value"] == 20000
        assert ent["final_value"] == 22500
        assert ent["reason"] == "Customer agreed revised freight"
        assert ent["label"] == "Freight"
        assert ent["modified_by"] and ent["modified_at"]

        # Second override on shortage
        r2 = requests.post(f"{API}/api/trips/{tid}/field-override", headers=h, json={
            "field": "supplier_shortage_deduction",
            "system_value": 0, "final_value": 5000,
            "reason": "Manual mutual settlement",
        })
        assert r2.status_code == 200
        got2 = r2.json()
        assert len(got2["field_overrides"]) == 2
        assert got2["field_overrides"][1]["label"] == "Supplier Shortage"

        # Missing reason → 400
        r3 = requests.post(f"{API}/api/trips/{tid}/field-override", headers=h, json={
            "field": "freight_amount", "system_value": 1, "final_value": 2,
        })
        assert r3.status_code == 400

        # Missing field → 400
        r4 = requests.post(f"{API}/api/trips/{tid}/field-override", headers=h, json={
            "reason": "x", "system_value": 1, "final_value": 2,
        })
        assert r4.status_code == 400

        # Confirm log persists on subsequent GET
        got3 = requests.get(f"{API}/api/trips/{tid}", headers=h).json()
        assert len(got3["field_overrides"]) == 2

        # And that the calculation logic is UNCHANGED — freight_amount still 20000
        assert round(got3["freight_amount"], 2) == 20000.0, "Phase 4 must not mutate the calc"
    finally:
        requests.delete(f"{API}/api/trips/{tid}?reason=cleanup", headers=h)
        requests.delete(f"{API}/api/customers/{cust['id']}", headers=h)
        requests.delete(f"{API}/api/products/{prod['id']}", headers=h)
        requests.delete(f"{API}/api/vehicles/{veh['id']}", headers=h)
