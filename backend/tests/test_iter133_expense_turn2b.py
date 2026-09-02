"""Iter133 · Turn 2B · Vehicle Cost + Vehicle Repair History tests.

FROZEN source-of-truth map (see PRD):
  Vehicle Cost         ← canonical Expense (+ legacy Trip fallback ONLY for
                          trips where has_canonical_expenses=false)
  Vehicle Repair Cost  ← DERIVED Σ Expense where repair_event_id != ""
  Vendor/Mechanic payable ← Bill/WO + Payment (independent)

CRITICAL invariant: repair of ₹18k parts + ₹7k labour = ₹25k vehicle repair
cost — never ₹36k / ₹50k / ₹43k.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]

TAG = f"IT133T2B-{uuid.uuid4().hex[:6].upper()}"


def _hdr(key=None, company_id=None):
    h = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}
    if key:
        h["Idempotency-Key"] = key
    if company_id:
        h["X-Company-Id"] = company_id
    return h


def _idem():
    return f"iter133t2b-{uuid.uuid4().hex[:24]}"


def _first_customer():
    r = requests.get(f"{API}/customers", headers=_hdr(), timeout=10)
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    return items[0]["id"]


def _mk_vehicle():
    r = requests.post(f"{API}/vehicles", headers=_hdr(_idem()), json={
        "vehicle_number": f"AP99IT2B{uuid.uuid4().hex[:4].upper()}",
        "vehicle_type": "own",
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_trip(vehicle, **kw):
    base = {
        "customer_id": _first_customer(),
        "date": kw.get("date", "2029-08-31"),
        "vehicle_number": vehicle["vehicle_number"],
        "vehicle_id": vehicle["id"],
        "vehicle_type": "own",
        "tons": 15,
        "loaded_qty": 15,
        "unloaded_qty": 15,
        "freight_mode": "per_ton",
        "rate_per_ton": 850,
        "product_rate_per_mt": 40000,
        "from_location": "A",
        "to_location": "B",
        "driver_name": f"{TAG} Driver",
        "expenses": kw.get("expenses", {}),
        "other_expenditures": kw.get("other_expenditures", []),
    }
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=base, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


def _cost(vid, **params):
    r = requests.get(f"{API}/vehicles/{vid}/cost-summary", headers=_hdr(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _history(vid, **params):
    r = requests.get(f"{API}/vehicles/{vid}/repair-history", headers=_hdr(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# T2B.1 — Vehicle Cost for one vehicle (canonical path via trip).             #
# --------------------------------------------------------------------------- #
def test_t2b1_vehicle_cost_one_vehicle_from_trip_toll():
    v = _mk_vehicle()
    _mk_trip(v, expenses={"toll": 1000})
    r = _cost(v["id"])
    assert r["total_cost"] == 1000
    assert r["expense_count"] == 1
    assert r["by_category"][0] == {"category": "Toll", "amount": 1000}


# T2B.2 date filter
def test_t2b2_date_filtering():
    v = _mk_vehicle()
    _mk_trip(v, expenses={"toll": 500}, date="2029-01-15")
    _mk_trip(v, expenses={"toll": 700}, date="2029-05-20")
    r = _cost(v["id"], **{"from": "2029-05-01", "to": "2029-05-31"})
    assert r["total_cost"] == 700


# T2B.3 category filter
def test_t2b3_category_filtering():
    v = _mk_vehicle()
    _mk_trip(v, expenses={"toll": 500, "repair": 300})
    r = _cost(v["id"], category="Toll")
    assert r["total_cost"] == 500
    assert r["expense_count"] == 1


# T2B.4 trip-linked filter
def test_t2b4_trip_linked_filter():
    v = _mk_vehicle()
    t = _mk_trip(v, expenses={"toll": 500})
    # Also a standalone expense (no trip)
    e = requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Parking", "amount": 200,
        "vehicle_id": v["id"],
    }, timeout=10)
    assert e.status_code == 200, e.text
    r_all = _cost(v["id"])
    assert r_all["total_cost"] == 700
    r_trip = _cost(v["id"], trip_linked="yes")
    assert r_trip["total_cost"] == 500
    r_nontrip = _cost(v["id"], trip_linked="no")
    assert r_nontrip["total_cost"] == 200


# T2B.5 non-trip expense on vehicle
def test_t2b5_non_trip_expense_on_vehicle():
    v = _mk_vehicle()
    e = requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Insurance", "amount": 12000,
        "vehicle_id": v["id"],
    }, timeout=10).json()
    r = _cost(v["id"])
    assert r["total_cost"] == 12000
    assert r["non_trip_total"] == 12000
    assert r["trip_linked_total"] == 0


# T2B.6 legacy Trip fallback (has_canonical_expenses=False path)
def test_t2b6_legacy_trip_fallback_via_direct_db():
    """Simulate a legacy trip by inserting directly (bypassing sync) then
    force-flip has_canonical_expenses=False."""
    import motor.motor_asyncio, asyncio, pymongo, os
    from urllib.parse import urlparse
    # Use pymongo synchronously — same DB as backend.
    mc = pymongo.MongoClient(os.environ["MONGO_URL"])
    dbm = mc[os.environ["DB_NAME"]]
    v = _mk_vehicle()
    # Find demo user_id + active company_id from a real trip we create
    t = _mk_trip(v, expenses={})
    uid = dbm.trips.find_one({"id": t["id"]})["user_id"]
    cid = dbm.trips.find_one({"id": t["id"]})["company_id"]
    legacy_id = f"trip_{uuid.uuid4().hex[:16]}"
    dbm.trips.insert_one({
        "id": legacy_id, "user_id": uid, "company_id": cid,
        "vehicle_id": v["id"], "vehicle_number": v["vehicle_number"],
        "date": "2029-08-31", "customer_id": t["customer_id"],
        "vehicle_type": "own", "tons": 10, "loaded_qty": 10, "unloaded_qty": 10,
        "freight_mode": "per_ton", "rate_per_ton": 800,
        "expenses": {"toll": 900, "repair": 400},
        "other_expenditures": [],
        "has_canonical_expenses": False,  # explicit legacy marker
    })
    try:
        r = _cost(v["id"])
        # Should include the 1300 legacy total
        assert r["total_cost"] == 1300, r
    finally:
        dbm.trips.delete_one({"id": legacy_id})


# T2B.7 canonical XOR legacy — no double count
def test_t2b7_canonical_vs_legacy_xor_no_double_count():
    v = _mk_vehicle()
    # Modern trip via API — auto-materialises
    _mk_trip(v, expenses={"toll": 1000})
    r = _cost(v["id"])
    # Exactly 1000 — no legacy-side double add.
    assert r["total_cost"] == 1000
    assert r["expense_count"] == 1


# T2B.8 same trip re-saved does not double vehicle cost
def test_t2b8_no_duplicate_cost_on_resave():
    v = _mk_vehicle()
    t = _mk_trip(v, expenses={"toll": 1000})
    latest = requests.get(f"{API}/trips/{t['id']}", headers=_hdr(), timeout=10).json()
    requests.put(f"{API}/trips/{t['id']}", headers=_hdr(), json=latest, timeout=15)
    r = _cost(v["id"])
    assert r["total_cost"] == 1000


# T2B.9 – T2B.14 — Repair 18k + 7k end-to-end
@pytest.fixture(scope="module")
def repair_fixture():
    v = _mk_vehicle()
    vendor = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                           json={"name": f"{TAG} R-Vendor"}, timeout=15).json()
    mech = requests.post(f"{API}/mechanics", headers=_hdr(_idem()),
                         json={"name": f"{TAG} R-Mech"}, timeout=15).json()
    rev = requests.post(f"{API}/repair-events", headers=_hdr(_idem()),
                        json={"event_date": "2029-08-31",
                              "vehicle_id": v["id"],
                              "workshop_name": f"{TAG} WS"}, timeout=15).json()
    bill = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
        "vendor_id": vendor["id"], "bill_number": f"{TAG}-B",
        "bill_date": "2029-08-31", "bill_amount": 18000,
        "vehicle_id": v["id"], "repair_event_id": rev["id"],
    }, timeout=15).json()
    # Twin Expense (parts)
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Parts", "amount": 18000,
        "party_type": "vendor", "party_id": vendor["id"],
        "vendor_bill_id": bill["id"],
        "vehicle_id": v["id"], "repair_event_id": rev["id"],
    }, timeout=15)
    wo = requests.post(f"{API}/mechanic-work-orders", headers=_hdr(_idem()), json={
        "mechanic_id": mech["id"], "work_date": "2029-08-31", "amount": 7000,
        "vehicle_id": v["id"], "repair_event_id": rev["id"],
    }, timeout=15).json()
    # Twin Expense (labour)
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Labour", "amount": 7000,
        "party_type": "mechanic", "party_id": mech["id"],
        "mechanic_work_order_id": wo["id"],
        "vehicle_id": v["id"], "repair_event_id": rev["id"],
    }, timeout=15)
    return {"vehicle": v, "vendor": vendor, "mechanic": mech,
            "repair_event": rev, "bill": bill, "wo": wo}


def test_t2b9_repair_history_one_event(repair_fixture):
    r = _history(repair_fixture["vehicle"]["id"])
    assert r["count"] == 1
    ev = r["events"][0]
    assert ev["id"] == repair_fixture["repair_event"]["id"]


def test_t2b10_repair_event_derived_total_25k(repair_fixture):
    r = _history(repair_fixture["vehicle"]["id"])
    ev = r["events"][0]
    assert ev["total_repair_cost"] == 25000.0
    assert ev["parts_cost"] == 18000.0
    assert ev["labour_cost"] == 7000.0
    # And vehicle cost report agrees
    cs = _cost(repair_fixture["vehicle"]["id"])
    assert cs["repair_total"] == 25000.0


def test_t2b11_repair_25k_not_50k_not_43k(repair_fixture):
    """CRITICAL: Vehicle Repair Cost MUST equal 25000 — never 50000 (Bill+Expense
    doubled) or 43000 (Bill+WO+labour Expense mixed)."""
    r = _history(repair_fixture["vehicle"]["id"])
    ev = r["events"][0]
    assert ev["total_repair_cost"] == 25000.0
    assert ev["total_repair_cost"] not in (50000.0, 43000.0, 36000.0)
    # Report-level total matches
    assert r["total_repair_cost"] == 25000.0


def test_t2b12_vendor_payable_18k(repair_fixture):
    r = _history(repair_fixture["vehicle"]["id"])
    ev = r["events"][0]
    assert ev["vendor_payable"] == 18000.0


def test_t2b13_mechanic_payable_7k(repair_fixture):
    r = _history(repair_fixture["vehicle"]["id"])
    ev = r["events"][0]
    assert ev["mechanic_payable"] == 7000.0


def test_t2b14_payment_does_not_increase_vehicle_cost(repair_fixture):
    v = repair_fixture["vehicle"]
    ven = repair_fixture["vendor"]
    bill = repair_fixture["bill"]
    cost_before = _cost(v["id"])["total_cost"]
    requests.post(f"{API}/vendors/{ven['id']}/payments", headers=_hdr(_idem()),
                  json={"vendor_id": ven["id"], "date": "2029-09-05",
                        "amount": 10000, "against": "bill",
                        "vendor_bill_id": bill["id"]}, timeout=15)
    cost_after = _cost(v["id"])["total_cost"]
    assert cost_before == cost_after
    # Also outstanding shifts, not payable
    r = _history(v["id"])
    ev = r["events"][0]
    assert ev["vendor_payable"] == 18000.0
    assert ev["vendor_paid"] == 10000.0
    assert ev["vendor_outstanding"] == 8000.0


def test_t2b15_vehicle_cost_ignores_bill_wo_duplicates(repair_fixture):
    """Vehicle Cost reads Expense only, so Bill+WO amounts never inflate the
    cost figure — asserted by grand total staying at 25000."""
    r = _cost(repair_fixture["vehicle"]["id"])
    assert r["repair_total"] == 25000.0
    assert r["total_cost"] == 25000.0


def test_t2b16_repair_drilldown_linkage(repair_fixture):
    r = _history(repair_fixture["vehicle"]["id"])
    ev = r["events"][0]
    assert len(ev["expenses"]) == 2
    assert len(ev["vendor_bills"]) == 1
    assert len(ev["mechanic_work_orders"]) == 1
    exp_bill = next(x for x in ev["expenses"] if x.get("vendor_bill_id"))
    assert exp_bill["vendor_bill_id"] == repair_fixture["bill"]["id"]


# T2B.17 attachment visibility
def test_t2b17_attachments_flow_through_drilldown():
    r = _history  # no-op guard
    v = _mk_vehicle()
    ven = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                        json={"name": f"{TAG} T2B17 V"}, timeout=15).json()
    rev = requests.post(f"{API}/repair-events", headers=_hdr(_idem()), json={
        "event_date": "2029-08-31", "vehicle_id": v["id"], "workshop_name": "WS",
    }, timeout=15).json()
    bill = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
        "vendor_id": ven["id"], "bill_number": f"{TAG}-T2B17",
        "bill_date": "2029-08-31", "bill_amount": 500,
        "vehicle_id": v["id"], "repair_event_id": rev["id"],
        # Note: no real file upload; just prove field surfaces cleanly (empty list).
        "file_ids": [],
    }, timeout=15).json()
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Parts", "amount": 500,
        "party_type": "vendor", "party_id": ven["id"],
        "vendor_bill_id": bill["id"], "vehicle_id": v["id"],
        "repair_event_id": rev["id"], "file_ids": [],
    }, timeout=15)
    resp = _history(v["id"])
    ev = resp["events"][0]
    assert "file_ids" in ev  # RepairEvent has file_ids surfaced
    assert isinstance(ev["vendor_bills"][0].get("file_ids", []), list)


# T2B.18 tenant isolation
def test_t2b18_tenant_isolation():
    companies = requests.get(f"{API}/companies", headers=_hdr(), timeout=10).json()
    if len(companies) < 2:
        r = requests.post(f"{API}/companies", headers=_hdr(_idem()),
                          json={"name": f"{TAG} Co2"}, timeout=10)
        if r.status_code != 200:
            pytest.skip("cannot create 2nd company")
        companies = requests.get(f"{API}/companies", headers=_hdr(), timeout=10).json()
        if len(companies) < 2:
            pytest.skip()
    a, b = companies[0]["id"], companies[1]["id"]
    r = requests.post(f"{API}/vehicles", headers=_hdr(_idem(), company_id=a), json={
        "vehicle_number": f"AP99T2B18{uuid.uuid4().hex[:4].upper()}",
        "vehicle_type": "own",
    }, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"cannot create vehicle in company A: {r.text[:200]}")
    va = r.json()
    # Fetch from company B should 404
    r = requests.get(f"{API}/vehicles/{va['id']}/cost-summary",
                     headers=_hdr(company_id=b), timeout=10)
    assert r.status_code == 404


# T2B.19 RBAC — read is permitted for authenticated user; verify 401 without token
def test_t2b19_rbac_unauthenticated_blocked():
    v = _mk_vehicle()
    r = requests.get(f"{API}/vehicles/{v['id']}/cost-summary", timeout=10)
    assert r.status_code == 401


# T2B.20 pagination / full-result totals — totals cover the ENTIRE filtered set
def test_t2b20_totals_cover_full_result_set():
    v = _mk_vehicle()
    # Trip with many expenditure rows
    rows = [{"id": f"oe_{i}_{uuid.uuid4().hex[:6]}", "date": "2029-08-31",
             "type": "Parking", "amount": 10 + i, "remarks": ""}
            for i in range(50)]
    _mk_trip(v, other_expenditures=rows)
    expected_total = sum(10 + i for i in range(50))
    r = _cost(v["id"])
    assert r["total_cost"] == expected_total
    assert r["expense_count"] == 50


# T2B.21 high-volume repair history without truncation
def test_t2b21_high_volume_history_no_truncation():
    v = _mk_vehicle()
    ven = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                        json={"name": f"{TAG} T2B21 V"}, timeout=15).json()
    N = 30
    for i in range(N):
        rev = requests.post(f"{API}/repair-events", headers=_hdr(_idem()), json={
            "event_date": "2029-08-31", "vehicle_id": v["id"],
            "workshop_name": f"WS-{i}",
        }, timeout=15).json()
        bill = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
            "vendor_id": ven["id"], "bill_number": f"{TAG}-T2B21-{i}",
            "bill_date": "2029-08-31", "bill_amount": 100 + i,
            "vehicle_id": v["id"], "repair_event_id": rev["id"],
        }, timeout=15).json()
        requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
            "date": "2029-08-31", "category": "Repair-Parts",
            "amount": 100 + i,
            "party_type": "vendor", "party_id": ven["id"],
            "vendor_bill_id": bill["id"], "vehicle_id": v["id"],
            "repair_event_id": rev["id"],
        }, timeout=15)
    r = _history(v["id"])
    assert r["count"] == N
    expected_total = sum(100 + i for i in range(N))
    assert r["total_repair_cost"] == expected_total


# T2B.22 supplier-owned vehicle: company_borne AND supplier_settlement_adjustment
def test_t2b22_supplier_owned_vehicle_modes_appear_in_cost():
    v = _mk_vehicle()
    # company_borne
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Parts", "amount": 300,
        "vehicle_id": v["id"],
        "supplier_owned_vehicle": True, "supplier_settlement_mode": "company_borne",
    }, timeout=10)
    # supplier_settlement_adjustment
    requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
        "date": "2029-08-31", "category": "Repair-Parts", "amount": 200,
        "vehicle_id": v["id"],
        "supplier_owned_vehicle": True, "supplier_settlement_mode": "supplier_settlement_adjustment",
    }, timeout=10)
    r = _cost(v["id"])
    assert r["total_cost"] == 500  # both appear on the vehicle
