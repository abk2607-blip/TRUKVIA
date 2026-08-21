"""Iter102 · Round-Trip KM freight now respects the frozen `applied_freight_method`.

Prior to the fix, `freight_mode="fixed"` + `round_trip_kms` + `rate_per_km_per_ton`
always used the LOADING quantity — the Customer's `default_freight_method`
snapshot (Unloading Qty / Higher-of / Loading) was silently ignored.

This locks the corrected behaviour so every future refactor keeps the
Customer's frozen policy honoured for round-trip billing too.
"""
import os, time, requests

API = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
TOKEN = "test_session_bitumen_2026"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _boot():
    requests.post(f"{API}/auth/demo-login", timeout=30)


def _make_customer(name, method):
    return requests.post(f"{API}/customers", headers=H, json={
        "name": name, "state": "AP", "default_freight_method": method,
    }, timeout=30).json()


def _make_round_trip(cust_id, veh_num, tons, unloaded, rt_kms, rate_per_km_per_ton, fixed_amt=0):
    body = {
        "customer_id": cust_id,
        "date": "2026-08-25",
        "vehicle_number": veh_num,
        "vehicle_type": "own",
        "tons": tons, "loaded_qty": tons, "unloaded_qty": unloaded,
        "freight_mode": "fixed",   # round-trip mode uses fixed branch
        "round_trip_kms": rt_kms,
        "rate_per_km_per_ton": rate_per_km_per_ton,
        "fixed_amount": fixed_amt,
    }
    r = requests.post(f"{API}/trips", headers=H, json=body, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def test_round_trip_km_respects_all_four_freight_methods():
    """Same tons/unloaded/rt_kms/rate — flip the Customer's default freight
    method and confirm freight_amount adjusts (Loading vs Unloading vs Higher).
    Fixed method ignores qty and uses fixed_amount only."""
    _boot()
    tag = str(int(time.time()))[-6:]

    # tons=20  unloaded=19.5  rt_kms=100  rate=5.00 /km/ton
    #   per_ton_loading    → 20   × 100 × 5 = 10 000
    #   per_ton_unloading  → 19.5 × 100 × 5 =  9 750
    #   per_ton_higher_of  → max(20,19.5) × 100 × 5 = 10 000
    #   per_ton_higher_of (flip) → tons=19.5 unl=20 → 20 × 100 × 5 = 10 000
    #   fixed              → rate & km ignored, fixed_amount used
    customers = {}
    trips = []
    try:
        for m in ("per_ton_loading", "per_ton_unloading", "per_ton_higher_of", "fixed"):
            customers[m] = _make_customer(f"IT102_{m}_{tag}", m)

        # ── Loading basis
        t1 = _make_round_trip(customers["per_ton_loading"]["id"], f"AP102L{tag[:3]}",
                              tons=20, unloaded=19.5, rt_kms=100, rate_per_km_per_ton=5)
        assert t1["applied_freight_method"] == "per_ton_loading"
        assert round(t1["freight_amount"], 2) == 10000.00, t1
        assert round(t1["freight_qty_used"], 3) == 20.0
        trips.append(t1["id"])

        # ── Unloading basis (previously the reported bug — silently ignored)
        t2 = _make_round_trip(customers["per_ton_unloading"]["id"], f"AP102U{tag[:3]}",
                              tons=20, unloaded=19.5, rt_kms=100, rate_per_km_per_ton=5)
        assert t2["applied_freight_method"] == "per_ton_unloading"
        assert round(t2["freight_amount"], 2) == 9750.00, t2
        assert round(t2["freight_qty_used"], 3) == 19.5
        trips.append(t2["id"])

        # ── Higher-of (tons > unloaded → picks tons)
        t3 = _make_round_trip(customers["per_ton_higher_of"]["id"], f"AP102H1{tag[:3]}",
                              tons=20, unloaded=19.5, rt_kms=100, rate_per_km_per_ton=5)
        assert t3["applied_freight_method"] == "per_ton_higher_of"
        assert round(t3["freight_amount"], 2) == 10000.00, t3
        trips.append(t3["id"])

        # ── Higher-of (unloaded > tons → picks unloaded)
        t4 = _make_round_trip(customers["per_ton_higher_of"]["id"], f"AP102H2{tag[:3]}",
                              tons=19.5, unloaded=20, rt_kms=100, rate_per_km_per_ton=5)
        assert t4["applied_freight_method"] == "per_ton_higher_of"
        assert round(t4["freight_amount"], 2) == 10000.00, t4
        assert round(t4["freight_qty_used"], 3) == 20.0
        trips.append(t4["id"])

        # ── Fixed → freight_amount comes from fixed_amount, qty ignored
        t5 = _make_round_trip(customers["fixed"]["id"], f"AP102F{tag[:3]}",
                              tons=20, unloaded=19.5, rt_kms=100, rate_per_km_per_ton=5,
                              fixed_amt=47250)
        assert t5["applied_freight_method"] == "fixed"
        assert round(t5["freight_amount"], 2) == 47250.00, t5
        assert round(t5["freight_qty_used"], 3) == 0.0
        trips.append(t5["id"])

        # ── Historical protection — flip Customer's default method AFTER trip
        # create; snapshot on t2 must not change.
        cust = customers["per_ton_unloading"]
        requests.put(f"{API}/customers/{cust['id']}", headers=H, json={
            **cust, "default_freight_method": "per_ton_loading",
        }, timeout=30)
        got = requests.get(f"{API}/trips/{t2['id']}", headers=H, timeout=30).json()
        assert got["applied_freight_method"] == "per_ton_unloading"
        assert round(got["freight_amount"], 2) == 9750.00
    finally:
        for tid in trips:
            requests.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=30)
        for c in customers.values():
            requests.delete(f"{API}/customers/{c['id']}", headers=H, timeout=30)


def test_round_trip_override_wins_over_method():
    """`freight_amount_override` still wins over the RT calc (Iter102)."""
    _boot()
    tag = str(int(time.time()))[-6:]
    c = _make_customer(f"IT102_OV_{tag}", "per_ton_unloading")
    tid = None
    try:
        t = _make_round_trip(c["id"], f"AP102OV{tag[:2]}",
                             tons=20, unloaded=19.5, rt_kms=100, rate_per_km_per_ton=5)
        tid = t["id"]
        assert round(t["freight_amount"], 2) == 9750.00
        # PUT with override
        r = requests.put(f"{API}/trips/{tid}", headers=H, json={
            **t, "freight_amount_override": 8500,
            "freight_override_reason": "Client agreed short-payment",
        }, timeout=30)
        assert r.status_code == 200, r.text
        assert round(r.json()["freight_amount"], 2) == 8500.00
    finally:
        if tid:
            requests.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=30)
        requests.delete(f"{API}/customers/{c['id']}", headers=H, timeout=30)
