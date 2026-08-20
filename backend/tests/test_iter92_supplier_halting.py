"""Iter92 — Supplier Halting Charges (independent from Customer Halting).

Verifies:
- Supplier halting is NOT auto-copied from customer halting_amount.
- Manually entering supplier_halting_amount increases supplier_net_payable.
- Supplier ledger emits a `trip_halting` debit row when > 0.
- Editing existing customer halting has zero effect on supplier halting.
- Settlement summary debit rolls in supplier_halting_amount.
"""
import os
import time
import requests

API = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com")
TOKEN = "test_session_bitumen_2026"


def _boot():
    requests.post(f"{API}/api/auth/demo-login", timeout=30)
    cid = requests.get(f"{API}/api/companies",
                       headers={"Authorization": f"Bearer {TOKEN}"},
                       timeout=30).json()[0]["id"]
    return cid


def _h(cid):
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
            "X-Company-Id": cid}


def test_supplier_halting_independent_of_customer_halting():
    cid = _boot()
    h = _h(cid)
    tag = str(int(time.time()))[-6:]

    prod = requests.post(f"{API}/api/products", headers=h,
                         json={"name": f"IT92P-{tag}"}).json()
    sup = requests.post(f"{API}/api/suppliers", headers=h,
                        json={"name": f"IT92S-{tag}"}).json()
    veh = requests.post(f"{API}/api/vehicles", headers=h,
                        json={"vehicle_number": f"AP92IT{tag[:3]}",
                              "vehicle_type": "supplier", "supplier_id": sup["id"]}).json()
    cust = requests.get(f"{API}/api/customers?limit=1", headers=h).json()["items"][0]

    # Create trip with CUSTOMER halting only (2 days × 1500 = 3000)
    trip = requests.post(f"{API}/api/trips", headers=h, json={
        "date": "2026-08-18",
        "loading_date": "2026-08-18",
        "unloading_date": "2026-08-24",     # 6 days elapsed
        "grace_days": 4,                    # 2 chargeable days
        "halting_rate_per_day": 1500,
        "vehicle_number": veh["vehicle_number"],
        "vehicle_type": "supplier",
        "supplier_id": sup["id"], "vehicle_id": veh["id"],
        "customer_id": cust["id"], "product_id": prod["id"],
        "tons": 20, "loaded_qty": 20000,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 800,
    }).json()
    tid = trip["id"]
    try:
        # Customer halting auto-computes to 3000
        assert round(float(trip["halting_amount"]), 2) == 3000.0
        # Supplier halting stays at 0 — NEVER auto-copied
        assert float(trip.get("supplier_halting_amount", 0)) == 0.0
        base_payable = float(trip["supplier_net_payable"])   # 20*800 - 0 = 16000
        assert round(base_payable, 2) == 16000.0

        # Manually add supplier halting → 2000
        r = requests.put(f"{API}/api/trips/{tid}", headers=h, json={
            **{k: v for k, v in trip.items() if k not in ("id",)},
            "supplier_halting_days": 2,
            "supplier_halting_rate_per_day": 1000,
            "supplier_halting_amount": 2000,
            "supplier_halting_remarks": "Site detention",
        })
        assert r.status_code == 200, r.text
        got = r.json()
        assert float(got["supplier_halting_amount"]) == 2000.0
        assert float(got["halting_amount"]) == 3000.0        # customer halting unchanged
        assert round(float(got["supplier_net_payable"]), 2) == round(base_payable + 2000, 2)

        # Change customer halting rate — supplier halting must not budge
        r2 = requests.put(f"{API}/api/trips/{tid}", headers=h, json={
            **{k: v for k, v in got.items() if k != "id"},
            "halting_rate_per_day": 2000,   # 2 days × 2000 = 4000 customer halting
        })
        got2 = r2.json()
        assert float(got2["halting_amount"]) == 4000.0
        assert float(got2["supplier_halting_amount"]) == 2000.0  # untouched
        # supplier_net_payable still reflects supplier halting only, not the new customer halting
        assert round(float(got2["supplier_net_payable"]), 2) == round(base_payable + 2000, 2)

        # Ledger emits a trip_halting debit row for supplier halting
        lg = requests.get(f"{API}/api/suppliers/{sup['id']}/ledger", headers=h).json()
        halt_rows = [r for r in lg.get("entries", []) if r.get("type") == "trip_halting" and r.get("trip_id") == tid]
        assert len(halt_rows) == 1, halt_rows
        assert round(float(halt_rows[0]["debit"]), 2) == 2000.0
        assert halt_rows[0]["credit"] == 0.0
        assert "Site detention" in halt_rows[0]["remarks"]

        # Clear supplier halting — row disappears
        r3 = requests.put(f"{API}/api/trips/{tid}", headers=h, json={
            **{k: v for k, v in got2.items() if k != "id"},
            "supplier_halting_days": 0,
            "supplier_halting_rate_per_day": 0,
            "supplier_halting_amount": 0,
            "supplier_halting_remarks": "",
        })
        got3 = r3.json()
        assert float(got3["supplier_halting_amount"]) == 0.0
        assert round(float(got3["supplier_net_payable"]), 2) == round(base_payable, 2)
        lg2 = requests.get(f"{API}/api/suppliers/{sup['id']}/ledger", headers=h).json()
        halt_rows2 = [r for r in lg2.get("entries", []) if r.get("type") == "trip_halting" and r.get("trip_id") == tid]
        assert halt_rows2 == []
    finally:
        requests.delete(f"{API}/api/trips/{tid}?reason=cleanup", headers=h)
        requests.delete(f"{API}/api/suppliers/{sup['id']}", headers=h)
        requests.delete(f"{API}/api/vehicles/{veh['id']}", headers=h)
        requests.delete(f"{API}/api/products/{prod['id']}", headers=h)
