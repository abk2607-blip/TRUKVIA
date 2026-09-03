"""Iter133 · Turn 2D · Final integration tests.

Covers Turn-2D matrix (T2D.1 – T2D.22) plus the 5 approved
cross-module reconciliation scenarios A – E.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]
TAG = f"IT133T2D-{uuid.uuid4().hex[:6].upper()}"


def _hdr(key=None, cid=None):
    h = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}
    if key: h["Idempotency-Key"] = key
    if cid: h["X-Company-Id"] = cid
    return h


def _idem(): return f"iter133t2d-{uuid.uuid4().hex[:24]}"


def _first_customer():
    r = requests.get(f"{API}/customers", headers=_hdr(), timeout=10).json()
    items = r.get("items", r) if isinstance(r, dict) else r
    return items[0]["id"]


def _mk_vehicle(vehicle_type="own", supplier_id=""):
    payload = {"vehicle_number": f"AP99T2D{uuid.uuid4().hex[:4].upper()}",
               "vehicle_type": vehicle_type}
    if supplier_id:
        payload["supplier_id"] = supplier_id
    return requests.post(f"{API}/vehicles", headers=_hdr(_idem()), json=payload, timeout=15).json()


def _mk_supplier():
    return requests.post(f"{API}/suppliers", headers=_hdr(_idem()),
                         json={"name": f"{TAG} Sup", "mobile": "9990001111"}, timeout=15).json()


def _cost(vid, **params):
    return requests.get(f"{API}/vehicles/{vid}/cost-summary", headers=_hdr(),
                        params=params, timeout=15).json()


def _repair(vid, **params):
    return requests.get(f"{API}/vehicles/{vid}/repair-history", headers=_hdr(),
                        params=params, timeout=15).json()


# ------------------------- SCENARIO A -------------------------

def test_scenario_a_trip_toll_reconciles_end_to_end():
    v = _mk_vehicle()
    trip = {
        "customer_id": _first_customer(), "date": "2029-08-31",
        "vehicle_number": v["vehicle_number"], "vehicle_id": v["id"], "vehicle_type": "own",
        "tons": 15, "loaded_qty": 15, "unloaded_qty": 15,
        "freight_mode": "per_ton", "rate_per_ton": 850, "product_rate_per_mt": 40000,
        "from_location": "A", "to_location": "B", "driver_name": f"{TAG} Drv",
        "expenses": {"toll": 1000}, "other_expenditures": [],
    }
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=20)
    tid = r.json()["id"]
    # Expense = 1000
    exp = requests.get(f"{API}/expenses", headers=_hdr(),
                       params={"trip_id": tid}, timeout=10).json()
    assert sum(x["amount"] for x in exp) == 1000
    # Trip Cost (via canonical expenses filtered by trip)
    assert len(exp) == 1
    # Vehicle Cost = 1000
    assert _cost(v["id"])["total_cost"] == 1000
    # Register (list without filter for this trip)
    reg = requests.get(f"{API}/expenses", headers=_hdr(),
                       params={"trip_id": tid}, timeout=10).json()
    assert sum(x["amount"] for x in reg) == 1000


# ------------------------- SCENARIO B + C -------------------------

@pytest.fixture(scope="module")
def repair_scen():
    v = _mk_vehicle()
    vendor = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                           json={"name": f"{TAG} V"}, timeout=15).json()
    mech = requests.post(f"{API}/mechanics", headers=_hdr(_idem()),
                         json={"name": f"{TAG} M"}, timeout=15).json()
    rev = requests.post(f"{API}/repair-events", headers=_hdr(_idem()), json={
        "event_date": "2029-08-31", "vehicle_id": v["id"],
        "workshop_name": f"{TAG} WS"}, timeout=15).json()
    bill = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
        "vendor_id": vendor["id"], "bill_number": f"{TAG}-B",
        "bill_date": "2029-08-31", "bill_amount": 18000,
        "vehicle_id": v["id"], "repair_event_id": rev["id"]}, timeout=15).json()
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Parts", "amount": 18000,
        "party_type": "vendor", "party_id": vendor["id"],
        "vendor_bill_id": bill["id"], "vehicle_id": v["id"],
        "repair_event_id": rev["id"]}, timeout=15)
    wo = requests.post(f"{API}/mechanic-work-orders", headers=_hdr(_idem()), json={
        "mechanic_id": mech["id"], "work_date": "2029-08-31", "amount": 7000,
        "vehicle_id": v["id"], "repair_event_id": rev["id"]}, timeout=15).json()
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Labour", "amount": 7000,
        "party_type": "mechanic", "party_id": mech["id"],
        "mechanic_work_order_id": wo["id"], "vehicle_id": v["id"],
        "repair_event_id": rev["id"]}, timeout=15)
    return {"v": v, "vendor": vendor, "mech": mech, "bill": bill, "wo": wo}


def test_scenario_b_repair_25k_no_double_count(repair_scen):
    v = repair_scen["v"]
    h = _repair(v["id"])
    ev = h["events"][0]
    assert ev["total_repair_cost"] == 25000.0
    assert ev["vendor_payable"] == 18000.0
    assert ev["mechanic_payable"] == 7000.0
    # Vendor ledger sees 18k debit; mechanic sees 7k
    vl = requests.get(f"{API}/vendors/{repair_scen['vendor']['id']}/ledger",
                      headers=_hdr(), timeout=15).json()
    ml = requests.get(f"{API}/mechanics/{repair_scen['mech']['id']}/ledger",
                      headers=_hdr(), timeout=15).json()
    assert any(e["kind"] == "bill" and e["debit"] == 18000 for e in vl["entries"])
    assert any(e["kind"] == "work_order" and e["debit"] == 7000 for e in ml["entries"])


def test_scenario_c_partial_vendor_payment_reduces_payable_not_cost(repair_scen):
    v = repair_scen["v"]; ven = repair_scen["vendor"]; bill = repair_scen["bill"]
    requests.post(f"{API}/vendors/{ven['id']}/payments", headers=_hdr(_idem()), json={
        "vendor_id": ven["id"], "date": "2029-09-05", "amount": 10000,
        "against": "bill", "vendor_bill_id": bill["id"]}, timeout=15)
    h = _repair(v["id"])
    ev = h["events"][0]
    assert ev["vendor_paid"] == 10000
    assert ev["vendor_outstanding"] == 8000
    assert ev["total_repair_cost"] == 25000  # cost unchanged
    assert _cost(v["id"])["total_cost"] == 25000


# ------------------------- SCENARIO D (settlement) & E (company_borne) -------------------------

def test_scenario_d_and_e_supplier_settlement_projection():
    sup = _mk_supplier()
    v = _mk_vehicle(vehicle_type="supplier", supplier_id=sup["id"])
    # D · adjustment
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Parts", "amount": 3000,
        "vehicle_id": v["id"],
        "supplier_owned_vehicle": True,
        "supplier_settlement_mode": "supplier_settlement_adjustment"}, timeout=15)
    # E · company_borne
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Labour", "amount": 3000,
        "vehicle_id": v["id"],
        "supplier_owned_vehicle": True,
        "supplier_settlement_mode": "company_borne"}, timeout=15)
    # Vehicle Cost sees BOTH
    c = _cost(v["id"])
    assert c["total_cost"] == 6000
    # Supplier settlement projection sees ONLY the adjustment one
    r = requests.get(f"{API}/suppliers/{sup['id']}/settlement-adjustments",
                     headers=_hdr(), timeout=15)
    assert r.status_code == 200, r.text
    proj = r.json()
    assert proj["count"] == 1
    assert proj["total_credit"] == 3000
    # No SupplierPayment(payment_out) auto-created for adjustment
    sp = requests.get(f"{API}/suppliers/{sup['id']}/payments",
                      headers=_hdr(), timeout=15)
    if sp.status_code == 200:
        pays = sp.json()
        adjustments_as_payment = [p for p in pays
                                  if p.get("remarks", "") == "supplier_settlement_adjustment"]
        assert adjustments_as_payment == []


# ------------------------- Date semantics -------------------------

def test_cost_date_vs_payment_date_split():
    v = _mk_vehicle()
    vendor = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                           json={"name": f"{TAG} DateV"}, timeout=15).json()
    bill = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
        "vendor_id": vendor["id"], "bill_number": f"{TAG}-DT",
        "bill_date": "2029-08-31", "bill_amount": 25000,
        "vehicle_id": v["id"]}, timeout=15).json()
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Parts", "amount": 25000,
        "party_type": "vendor", "party_id": vendor["id"],
        "vendor_bill_id": bill["id"], "vehicle_id": v["id"]}, timeout=15)
    # Vehicle Cost by COST DATE — Aug range picks up ₹25k
    aug = _cost(v["id"], **{"from": "2029-08-01", "to": "2029-08-31"})
    sep = _cost(v["id"], **{"from": "2029-09-01", "to": "2029-09-30"})
    assert aug["total_cost"] == 25000
    assert sep["total_cost"] == 0
    # Pay in Sep
    requests.post(f"{API}/vendors/{vendor['id']}/payments", headers=_hdr(_idem()), json={
        "vendor_id": vendor["id"], "date": "2029-09-05", "amount": 25000,
        "against": "bill", "vendor_bill_id": bill["id"]}, timeout=15)
    # Vehicle cost unchanged
    assert _cost(v["id"], **{"from": "2029-08-01", "to": "2029-08-31"})["total_cost"] == 25000
    # Payment cashbook by PAYMENT DATE — Sep picks it up
    cb_aug = requests.get(f"{API}/payment-cashbook", headers=_hdr(),
                          params={"party_type": "vendor",
                                  "from": "2029-08-01", "to": "2029-08-31"}, timeout=15).json()
    cb_sep = requests.get(f"{API}/payment-cashbook", headers=_hdr(),
                          params={"party_type": "vendor",
                                  "from": "2029-09-01", "to": "2029-09-30"}, timeout=15).json()
    assert cb_aug["net_out"] == 0
    assert cb_sep["net_out"] >= 25000  # includes our payment (+ any pre-existing in tenant)
    assert cb_sep["date_basis"] == "payment_date"
    # Outstanding-as-of
    o_aug = requests.get(f"{API}/vendors/{vendor['id']}/outstanding-as-of",
                         headers=_hdr(), params={"as_of": "2029-08-31"}, timeout=15).json()
    o_sep = requests.get(f"{API}/vendors/{vendor['id']}/outstanding-as-of",
                         headers=_hdr(), params={"as_of": "2029-09-30"}, timeout=15).json()
    assert o_aug["outstanding"] >= 25000
    assert o_sep["outstanding"] == max(0, o_aug["outstanding"] - 25000)


# ------------------------- RBAC / cross-tenant -------------------------

def test_cashbook_requires_auth():
    r = requests.get(f"{API}/payment-cashbook", params={"party_type": "vendor"}, timeout=10)
    assert r.status_code == 401


def test_outstanding_as_of_cross_tenant_blocked():
    companies = requests.get(f"{API}/companies", headers=_hdr(), timeout=15).json()
    if len(companies) < 2:
        pytest.skip("need ≥2 companies")
    a, b = companies[0]["id"], companies[1]["id"]
    v = requests.post(f"{API}/vendors", headers=_hdr(_idem(), cid=a),
                      json={"name": f"{TAG} Iso"}, timeout=15).json()
    r = requests.get(f"{API}/vendors/{v['id']}/outstanding-as-of",
                     headers=_hdr(cid=b), params={"as_of": "2029-08-31"}, timeout=15)
    assert r.status_code == 404


# ------------------------- High-volume sanity -------------------------

def test_high_volume_expenses_1000_no_truncation():
    """1000 expenses on one vehicle — full aggregation, no cap, right totals."""
    v = _mk_vehicle()
    expected = 0
    # Chunked bulk-create — 1000 rows
    for i in range(1000):
        amt = 10 + (i % 90)
        expected += amt
        # Only one request pattern; server should stream fine
        r = requests.post(f"{API}/expenses", headers=_hdr(_idem()),
                          json={"date": "2029-08-31", "category": "Toll",
                                "amount": amt, "vehicle_id": v["id"]}, timeout=10)
        assert r.status_code == 200
        if i > 0 and i % 200 == 0:
            pass  # progress checkpoint (no assertion)
    s = _cost(v["id"])
    assert s["expense_count"] == 1000
    assert s["total_cost"] == expected
    # Filtered totals correct — Toll only
    s_toll = _cost(v["id"], category="Toll")
    assert s_toll["total_cost"] == expected
