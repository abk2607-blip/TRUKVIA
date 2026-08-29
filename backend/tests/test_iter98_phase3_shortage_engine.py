"""Iter98 · Phase 3 — Central Customer/Supplier Shortage Calc Engine."""
import os, time, requests

API = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]


def _boot():
    requests.post(f"{API}/api/auth/demo-login", timeout=30)
    cid = requests.get(f"{API}/api/companies",
                       headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30).json()[0]["id"]
    return cid


def _h(cid):
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
            "X-Company-Id": cid}


def _mktrip(h, cust_id, prod_id, sup_id, veh_id, veh_num, tons, unloaded, rate_mt=1000, prod_rate=50000):
    body = {
        "date": "2026-08-20",
        "vehicle_number": veh_num, "vehicle_type": "supplier",
        "supplier_id": sup_id, "vehicle_id": veh_id,
        "customer_id": cust_id, "product_id": prod_id,
        "tons": tons, "loaded_qty": tons, "unloaded_qty": unloaded,
        "freight_mode": "per_ton", "rate_per_ton": rate_mt,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 800,
        "product_rate_per_mt": prod_rate,
    }
    r = requests.post(f"{API}/api/trips", headers=h, json=body, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def test_phase3_customer_and_supplier_shortage_engine():
    cid = _boot()
    h = _h(cid)
    tag = str(int(time.time()))[-6:]

    prod = requests.post(f"{API}/api/products", headers=h, json={"name": f"P98-{tag}"}).json()
    pid = prod["id"]

    # Customer with 1% net_shortage limit
    c_net = requests.post(f"{API}/api/customers", headers=h, json={
        "name": f"C98-net-{tag}",
        "shortage_config": {"limit": 1.0, "limit_type": "pct", "method": "net_shortage"},
    }).json()
    # Customer with 1% full_after_limit
    c_full = requests.post(f"{API}/api/customers", headers=h, json={
        "name": f"C98-full-{tag}",
        "shortage_config": {"limit": 1.0, "limit_type": "pct", "method": "full_after_limit"},
    }).json()

    # Supplier with 100 KG limit
    sup = requests.post(f"{API}/api/suppliers", headers=h, json={
        "name": f"S98-{tag}", "shortage_limit_kg": 100,
    }).json()
    veh = requests.post(f"{API}/api/vehicles", headers=h, json={
        "vehicle_number": f"AP98IT{tag[:3]}", "vehicle_type": "supplier", "supplier_id": sup["id"],
    }).json()

    made = []
    try:
        # ── Case A: Within BOTH limits (shortage 50kg ≤ customer 200kg AND ≤ supplier 100kg).
        t = _mktrip(h, c_net["id"], pid, sup["id"], veh["id"], f"AP98A{tag[:3]}",
                    tons=20, unloaded=19.95)   # shortage 0.05 MT = 50 kg
        assert round(t["shortage_qty"], 3) == 0.05
        assert t["shortage_amount"] == 0.0, f"within customer limit → expected 0, got {t['shortage_amount']}"
        assert t["supplier_shortage_deduction"] == 0.0, f"supplier within 100kg → 0, got {t['supplier_shortage_deduction']}"
        made.append(t["id"])

        # ── Case B: Above limit, net_shortage. tons=20, allowed=0.2 MT, unloaded=19.5 → short 0.5 MT = 500kg
        #   Customer deduction = (0.5 - 0.2) × 50000 = 15000
        #   Supplier deduction = 0.5 × 50000 = 25000 (full because above 100kg)
        t = _mktrip(h, c_net["id"], pid, sup["id"], veh["id"], f"AP98B{tag[:3]}",
                    tons=20, unloaded=19.5)
        assert round(t["shortage_qty"], 3) == 0.5
        assert round(t["shortage_amount"], 2) == 15000.0, t["shortage_amount"]
        assert round(t["supplier_shortage_deduction"], 2) == 25000.0, t["supplier_shortage_deduction"]
        made.append(t["id"])

        # ── Case C: Above limit, full_after_limit. Same qtys → customer 25000, supplier 25000
        t = _mktrip(h, c_full["id"], pid, sup["id"], veh["id"], f"AP98C{tag[:3]}",
                    tons=20, unloaded=19.5)
        assert round(t["shortage_amount"], 2) == 25000.0, t["shortage_amount"]
        assert round(t["supplier_shortage_deduction"], 2) == 25000.0, t["supplier_shortage_deduction"]
        made.append(t["id"])

        # ── Case D: Supplier above limit but Customer within (mixed independence).
        # Set supplier limit low (50 kg) and customer limit high (5%).
        c_hi = requests.post(f"{API}/api/customers", headers=h, json={
            "name": f"C98-hi-{tag}",
            "shortage_config": {"limit": 5.0, "limit_type": "pct", "method": "net_shortage"},
        }).json()
        sup2 = requests.post(f"{API}/api/suppliers", headers=h, json={
            "name": f"S98lo-{tag}", "shortage_limit_kg": 50,
        }).json()
        veh2 = requests.post(f"{API}/api/vehicles", headers=h, json={
            "vehicle_number": f"AP98D{tag[:3]}", "vehicle_type": "supplier", "supplier_id": sup2["id"],
        }).json()
        # tons=20 short=0.1MT=100kg. Customer 5%=1MT (within → 0). Supplier 50kg (above → full 5000).
        t = _mktrip(h, c_hi["id"], pid, sup2["id"], veh2["id"], f"AP98D2{tag[:3]}",
                    tons=20, unloaded=19.9)
        assert round(t["shortage_qty"], 3) == 0.1
        assert t["shortage_amount"] == 0.0, f"customer within 5% → 0, got {t['shortage_amount']}"
        assert round(t["supplier_shortage_deduction"], 2) == 5000.0, t["supplier_shortage_deduction"]
        made.append(t["id"])

        # ── Case E: Historical protection. Change customer master's method AFTER creation.
        cust_ref = requests.get(f"{API}/api/customers/{c_net['id']}", headers=h).json()
        requests.put(f"{API}/api/customers/{c_net['id']}", headers=h, json={
            **cust_ref,
            "shortage_config": {"limit": 5.0, "limit_type": "pct", "method": "full_after_limit"},
        })
        got = requests.get(f"{API}/api/trips/{made[1]}", headers=h).json()
        assert got["applied_customer_shortage_limit"] == 1.0
        assert got["applied_customer_shortage_method"] == "net_shortage"
        assert round(got["shortage_amount"], 2) == 15000.0

        # Cleanup extra masters
        requests.delete(f"{API}/api/customers/{c_hi['id']}", headers=h)
        requests.delete(f"{API}/api/suppliers/{sup2['id']}", headers=h)
        requests.delete(f"{API}/api/vehicles/{veh2['id']}", headers=h)
    finally:
        for tid in made:
            requests.delete(f"{API}/api/trips/{tid}?reason=cleanup", headers=h)
        for c in (c_net, c_full):
            requests.delete(f"{API}/api/customers/{c['id']}", headers=h)
        requests.delete(f"{API}/api/suppliers/{sup['id']}", headers=h)
        requests.delete(f"{API}/api/vehicles/{veh['id']}", headers=h)
        requests.delete(f"{API}/api/products/{pid}", headers=h)
