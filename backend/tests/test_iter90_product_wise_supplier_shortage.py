"""Iter90 — Product-wise Supplier Shortage KG limits.

Verifies:
1. Supplier.product_shortage_limits accepts a list of {product_id, product_name, limit_kg}.
2. When a Trip is created, applied_supplier_shortage_limit_kg is snapshotted
   from the matching product row (preferred).
3. Trips for products NOT in the list fall back to the legacy
   supplier.shortage_limit_kg field.
4. Existing trips remain untouched when supplier config changes (historical
   protection — already covered by iter89, spot-checked here).
"""
import os
import time
import requests

API = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com")
H = {
    "Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}",
    "Content-Type": "application/json",
}


def _boot():
    requests.post(f"{API}/api/auth/demo-login", timeout=15)
    cid = requests.get(f"{API}/api/companies", headers=H, timeout=15).json()[0]["id"]
    H["X-Company-Id"] = cid
    return cid


def test_product_wise_supplier_shortage_snapshot():
    _boot()
    tag = str(int(time.time()))[-6:]

    p_bit = requests.post(
        f"{API}/api/products", headers=H,
        json={"name": f"I90B-{tag}", "default_shortage_allowance_pct": 0.5},
    ).json()["id"]
    p_crmb = requests.post(
        f"{API}/api/products", headers=H,
        json={"name": f"I90C-{tag}", "default_shortage_allowance_pct": 0.5},
    ).json()["id"]
    p_unlisted = requests.post(
        f"{API}/api/products", headers=H,
        json={"name": f"I90U-{tag}"},
    ).json()["id"]

    sup = requests.post(
        f"{API}/api/suppliers", headers=H,
        json={
            "name": f"I90Sup-{tag}",
            "shortage_limit_kg": 50,   # legacy fallback
            "product_shortage_limits": [
                {"product_id": p_bit,  "product_name": f"I90B-{tag}",  "limit_kg": 100},
                {"product_id": p_crmb, "product_name": f"I90C-{tag}",  "limit_kg": 150},
            ],
        },
    ).json()
    sid = sup["id"]
    assert len(sup["product_shortage_limits"]) == 2
    assert sup["product_shortage_limits"][0]["limit_kg"] == 100
    assert sup["product_shortage_limits"][1]["limit_kg"] == 150

    veh = requests.post(
        f"{API}/api/vehicles", headers=H,
        json={"vehicle_number": f"AP99XX{tag[:4]}", "vehicle_type": "supplier", "supplier_id": sid},
    ).json()
    vid = veh["id"]

    cust = requests.get(f"{API}/api/customers?limit=1", headers=H).json()["items"][0]["id"]

    base = {
        "date": "2026-08-20",
        "vehicle_number": f"AP99XX{tag[:4]}",
        "vehicle_type": "supplier",
        "supplier_id": sid,
        "vehicle_id": vid,
        "customer_id": cust,
        "tons": 20, "loaded_qty": 20000,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
    }

    def mktrip(pid):
        r = requests.post(f"{API}/api/trips", headers=H, json={**base, "product_id": pid})
        assert r.status_code == 200, r.text
        return r.json()

    created = []
    try:
        t_bit = mktrip(p_bit)
        t_crmb = mktrip(p_crmb)
        t_unl = mktrip(p_unlisted)
        created = [t_bit["id"], t_crmb["id"], t_unl["id"]]

        assert t_bit["applied_supplier_shortage_limit_kg"] == 100.0
        assert t_crmb["applied_supplier_shortage_limit_kg"] == 150.0
        assert t_unl["applied_supplier_shortage_limit_kg"] == 50.0
        # policy snapshot timestamp set on all
        for t in (t_bit, t_crmb, t_unl):
            assert t.get("policy_snapshot_at")

        # Historical protection: bump supplier's Bitumen limit → existing
        # Bitumen trip snapshot must NOT change.
        requests.put(
            f"{API}/api/suppliers/{sid}", headers=H,
            json={**sup,
                  "product_shortage_limits": [
                      {"product_id": p_bit,  "product_name": f"I90B-{tag}",  "limit_kg": 999},
                      {"product_id": p_crmb, "product_name": f"I90C-{tag}",  "limit_kg": 150},
                  ]},
        )
        got = requests.get(f"{API}/api/trips/{t_bit['id']}", headers=H).json()
        assert got["applied_supplier_shortage_limit_kg"] == 100.0, \
            "historical protection violated: existing trip snapshot mutated"
    finally:
        for tid in created:
            requests.delete(f"{API}/api/trips/{tid}", headers=H)
        requests.delete(f"{API}/api/suppliers/{sid}", headers=H)
        for pid in (p_bit, p_crmb, p_unlisted):
            requests.delete(f"{API}/api/products/{pid}", headers=H)
        requests.delete(f"{API}/api/vehicles/{vid}", headers=H)
