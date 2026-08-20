"""Iter97 · Phase 2 — Central Freight Calculation Engine.

Verifies:
- Customer.default_freight_method snapshots into Trip.applied_freight_method
  at create-time (per Iter89) and drives the freight amount.
- All four approved methods produce the correct freight:
   • per_ton_loading      → tons × rate
   • per_ton_unloading    → unloaded_qty × rate
   • per_ton_higher_of    → max(tons, unloaded) × rate
   • fixed                → fixed_amount, qty ignored
- Trip-level `freight_amount_override` wins over the method calc.
- Editing Customer master AFTER trip create does NOT change the snapshot on
  existing trips (historical protection).
"""
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


def _make_trip(h, cust_id, prod_id, veh_num, tons, unloaded, rate, fixed_amt=0, extra=None):
    body = {
        "date": "2026-08-20",
        "vehicle_number": veh_num, "vehicle_type": "own",
        "customer_id": cust_id, "product_id": prod_id,
        "tons": tons, "loaded_qty": tons, "unloaded_qty": unloaded,
        "freight_mode": "fixed" if fixed_amt else "per_ton",
        "rate_per_ton": rate, "fixed_amount": fixed_amt,
    }
    if extra: body.update(extra)
    r = requests.post(f"{API}/api/trips", headers=h, json=body, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def test_phase2_freight_methods_and_snapshot_and_override():
    cid = _boot()
    h = _h(cid)
    tag = str(int(time.time()))[-6:]

    prod = requests.post(f"{API}/api/products", headers=h, json={"name": f"P97-{tag}"}).json()
    pid = prod["id"]

    # Four customers, one per method
    customers = {}
    for m in ("per_ton_loading", "per_ton_unloading", "per_ton_higher_of", "fixed"):
        r = requests.post(f"{API}/api/customers", headers=h, json={
            "name": f"C97-{m}-{tag}", "default_freight_method": m,
        })
        customers[m] = r.json()

    made = []
    try:
        # per_ton_loading  → 20 × 1000 = 20000
        t = _make_trip(h, customers["per_ton_loading"]["id"], pid, f"AP97L{tag[:3]}",
                       tons=20, unloaded=19.5, rate=1000)
        assert t["applied_freight_method"] == "per_ton_loading"
        assert round(t["freight_amount"], 2) == 20000.0
        assert round(t["freight_qty_used"], 3) == 20.0
        made.append(t["id"])

        # per_ton_unloading → 19.5 × 1000 = 19500
        t = _make_trip(h, customers["per_ton_unloading"]["id"], pid, f"AP97U{tag[:3]}",
                       tons=20, unloaded=19.5, rate=1000)
        assert t["applied_freight_method"] == "per_ton_unloading"
        assert round(t["freight_amount"], 2) == 19500.0
        assert round(t["freight_qty_used"], 3) == 19.5
        made.append(t["id"])

        # per_ton_higher_of → max(20, 19.5) × 1000 = 20000; then flip qtys → 20500
        t = _make_trip(h, customers["per_ton_higher_of"]["id"], pid, f"AP97H{tag[:3]}",
                       tons=20, unloaded=20.5, rate=1000)
        assert t["applied_freight_method"] == "per_ton_higher_of"
        assert round(t["freight_amount"], 2) == 20500.0
        made.append(t["id"])

        # fixed → 47250 regardless of tons/unload
        t = _make_trip(h, customers["fixed"]["id"], pid, f"AP97F{tag[:3]}",
                       tons=25, unloaded=25, rate=0, fixed_amt=47250)
        assert t["applied_freight_method"] == "fixed"
        assert round(t["freight_amount"], 2) == 47250.0
        assert round(t["freight_qty_used"], 3) == 0.0
        made.append(t["id"])

        # Trip-level override wins
        override_target = made[0]
        r = requests.put(f"{API}/api/trips/{override_target}", headers=h, json={
            **requests.get(f"{API}/api/trips/{override_target}", headers=h).json(),
            "freight_amount_override": 18500,
            "freight_override_reason": "Client agreed short-payment for damage",
        })
        assert r.status_code == 200, r.text
        got = r.json()
        assert round(got["freight_amount"], 2) == 18500.0

        # Historical protection — flip the customer's default method and confirm
        # the snapshot on existing trips is unchanged.
        cust0 = customers["per_ton_loading"]
        requests.put(f"{API}/api/customers/{cust0['id']}", headers=h, json={
            **cust0, "default_freight_method": "fixed",
        })
        got2 = requests.get(f"{API}/api/trips/{made[0]}", headers=h).json()
        assert got2["applied_freight_method"] == "per_ton_loading"
    finally:
        for tid in made:
            requests.delete(f"{API}/api/trips/{tid}?reason=cleanup", headers=h)
        for c in customers.values():
            requests.delete(f"{API}/api/customers/{c['id']}", headers=h)
        requests.delete(f"{API}/api/products/{pid}", headers=h)
