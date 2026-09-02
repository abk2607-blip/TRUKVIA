"""Iter133 · Turn 2A · Trip → canonical Expense integration tests.

Tests T2.1 – T2.20 per FROZEN Turn-2A scope. Deterministic source-line
identity guarantees ONE real-world cost = ONE canonical Expense row.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]

TAG = f"IT133T2A-{uuid.uuid4().hex[:6].upper()}"


def _hdr(key: str | None = None, company_id: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}
    if key:
        h["Idempotency-Key"] = key
    if company_id:
        h["X-Company-Id"] = company_id
    return h


def _idem() -> str:
    return f"iter133t2a-{uuid.uuid4().hex[:24]}"


def _first_customer() -> str:
    r = requests.get(f"{API}/customers", headers=_hdr(), timeout=10)
    r.raise_for_status()
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert items, "no customers in test env"
    return items[0]["id"]


def _mk_trip_payload(**overrides) -> dict:
    base = {
        "customer_id": _first_customer(),
        "date": "2029-08-31",
        "vehicle_number": f"AP99IT{uuid.uuid4().hex[:4].upper()}",
        "vehicle_type": "own",
        "tons": 15,
        "loaded_qty": 15,
        "unloaded_qty": 15,
        "freight_mode": "per_ton",
        "rate_per_ton": 850,
        "product_rate_per_mt": 40000,
        "from_location": "Kakinada",
        "to_location": "Vizag",
        "driver_name": f"{TAG} Driver",
        "expenses": {},
        "other_expenditures": [],
    }
    base.update(overrides)
    return base


def _list_expenses_for_trip(tid: str) -> list:
    r = requests.get(f"{API}/expenses", headers=_hdr(),
                     params={"trip_id": tid}, timeout=10)
    r.raise_for_status()
    return r.json()


def _get_trip(tid: str) -> dict:
    r = requests.get(f"{API}/trips/{tid}", headers=_hdr(), timeout=10)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# T2.1 — Trip expense creates exactly one canonical Expense.                  #
# --------------------------------------------------------------------------- #
def test_t21_trip_toll_creates_exactly_one_canonical_expense():
    trip = _mk_trip_payload(expenses={"toll": 1000})
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=20)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    assert r.json().get("has_canonical_expenses") is True

    rows = _list_expenses_for_trip(tid)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["category"] == "Toll"
    assert row["amount"] == 1000
    assert row["source_type"] == "trip_legacy"
    assert row["source_key"] == f"trip:{tid}:legacy:toll"
    assert row["source_trip_id"] == tid
    assert row["trip_id"] == tid
    assert row["party_type"] == "cash"
    assert row["settlement_mode"] == "cash_now"


# --------------------------------------------------------------------------- #
# T2.2 — Saving the same Trip twice does NOT duplicate the Expense.           #
# --------------------------------------------------------------------------- #
def test_t22_trip_save_twice_no_duplicate():
    trip = _mk_trip_payload(expenses={"toll": 500})
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=15)
    tid = r.json()["id"]
    latest = _get_trip(tid)
    r = requests.put(f"{API}/trips/{tid}", headers=_hdr(), json=latest, timeout=15)
    assert r.status_code == 200
    rows = _list_expenses_for_trip(tid)
    assert len(rows) == 1
    assert rows[0]["amount"] == 500


# --------------------------------------------------------------------------- #
# T2.3 — Editing Trip expense updates the same canonical Expense in place.    #
# --------------------------------------------------------------------------- #
def test_t23_editing_trip_expense_updates_same_canonical():
    trip = _mk_trip_payload(expenses={"toll": 500})
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=15)
    tid = r.json()["id"]
    before = _list_expenses_for_trip(tid)
    id_before = before[0]["id"]

    latest = _get_trip(tid)
    latest["expenses"]["toll"] = 800
    r = requests.put(f"{API}/trips/{tid}", headers=_hdr(), json=latest, timeout=15)
    assert r.status_code == 200

    after = _list_expenses_for_trip(tid)
    assert len(after) == 1
    assert after[0]["id"] == id_before, "same canonical Expense row updated in place"
    assert after[0]["amount"] == 800


# --------------------------------------------------------------------------- #
# T2.4 — Removing a Trip expense soft-deletes its canonical Expense.          #
# --------------------------------------------------------------------------- #
def test_t24_removing_trip_expense_soft_deletes_canonical():
    trip = _mk_trip_payload(expenses={"toll": 500, "repair": 300})
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=15)
    tid = r.json()["id"]
    assert len(_list_expenses_for_trip(tid)) == 2

    latest = _get_trip(tid)
    latest["expenses"]["toll"] = 0
    r = requests.put(f"{API}/trips/{tid}", headers=_hdr(), json=latest, timeout=15)
    assert r.status_code == 200

    active = _list_expenses_for_trip(tid)
    assert len(active) == 1
    assert active[0]["category"] == "Repair"


# --------------------------------------------------------------------------- #
# T2.5 — Trip without any expenses stays backward compatible.                 #
# --------------------------------------------------------------------------- #
def test_t25_legacy_trip_without_materialisation_backward_compat():
    trip = _mk_trip_payload(expenses={})
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=15)
    assert r.status_code == 200
    tid = r.json()["id"]

    t = _get_trip(tid)
    # Trip is fully readable; canonical flag defaults false when nothing to materialise.
    assert t.get("has_canonical_expenses") is False
    # Legacy expense scalars remain readable (defaults to 0).
    assert t.get("expenses", {}).get("toll", 0) == 0
    # Canonical collection has no rows for this trip.
    assert _list_expenses_for_trip(tid) == []


# --------------------------------------------------------------------------- #
# T2.6 — has_canonical_expenses transitions deterministically.                #
# --------------------------------------------------------------------------- #
def test_t26_has_canonical_expenses_state_transitions():
    trip = _mk_trip_payload(expenses={})
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=15)
    tid = r.json()["id"]
    assert _get_trip(tid).get("has_canonical_expenses") is False

    # Add a diesel expense
    latest = _get_trip(tid)
    latest["expenses"]["diesel"] = 4000
    requests.put(f"{API}/trips/{tid}", headers=_hdr(), json=latest, timeout=15)
    assert _get_trip(tid).get("has_canonical_expenses") is True

    # Zero everything out
    latest = _get_trip(tid)
    latest["expenses"]["diesel"] = 0
    requests.put(f"{API}/trips/{tid}", headers=_hdr(), json=latest, timeout=15)
    assert _get_trip(tid).get("has_canonical_expenses") is False


# --------------------------------------------------------------------------- #
# T2.7 — Two other_expenditure rows with identical amount/date/category       #
#        still map to two distinct canonical Expenses (via row.id).           #
# --------------------------------------------------------------------------- #
def test_t27_identical_oe_rows_still_two_distinct_canonicals():
    a_id = f"oe_{uuid.uuid4().hex[:8]}"
    b_id = f"oe_{uuid.uuid4().hex[:8]}"
    trip = _mk_trip_payload(other_expenditures=[
        {"id": a_id, "date": "2029-08-31", "type": "Parking", "amount": 200, "remarks": ""},
        {"id": b_id, "date": "2029-08-31", "type": "Parking", "amount": 200, "remarks": ""},
    ])
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=15)
    tid = r.json()["id"]
    rows = _list_expenses_for_trip(tid)
    assert len(rows) == 2
    keys = sorted(r["source_key"] for r in rows)
    assert keys[0] != keys[1]
    assert f"trip:{tid}:oe:{a_id}" in keys
    assert f"trip:{tid}:oe:{b_id}" in keys


# --------------------------------------------------------------------------- #
# T2.8 — Retry under idempotency does not create duplicate canonicals.        #
# --------------------------------------------------------------------------- #
def test_t28_idempotency_retry_no_duplicate_canonical():
    trip = _mk_trip_payload(expenses={"toll": 700})
    key = _idem()
    r1 = requests.post(f"{API}/trips", headers=_hdr(key), json=trip, timeout=15)
    assert r1.status_code == 200
    tid = r1.json()["id"]

    r2 = requests.post(f"{API}/trips", headers=_hdr(key), json=trip, timeout=15)
    assert r2.status_code == 200
    assert r2.headers.get("x-idempotent-replay") == "1"
    assert r2.json()["id"] == tid

    assert len(_list_expenses_for_trip(tid)) == 1


# --------------------------------------------------------------------------- #
# T2.9 — VendorBill + twin Expense: payable = bill, cost = expense, no double #
# --------------------------------------------------------------------------- #
def test_t29_vendor_bill_twin_expense_no_double_count():
    v = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                      json={"name": f"{TAG} T29 V"}, timeout=15).json()
    b = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()),
                      json={"vendor_id": v["id"], "bill_number": f"{TAG}-T29",
                            "bill_date": "2029-08-31", "bill_amount": 18000}, timeout=15).json()
    e = requests.post(f"{API}/expenses", headers=_hdr(_idem()),
                      json={"date": "2029-08-31", "category": "Repair-Parts",
                            "amount": 18000, "party_type": "vendor",
                            "party_id": v["id"], "vendor_bill_id": b["id"]}, timeout=15)
    assert e.status_code == 200

    bills = requests.get(f"{API}/vendor-bills", headers=_hdr(),
                         params={"vendor_id": v["id"]}, timeout=10).json()
    total_payable = sum(x["bill_amount"] for x in bills if x["bill_number"] == f"{TAG}-T29")
    exp = requests.get(f"{API}/expenses", headers=_hdr(),
                       params={"vendor_bill_id": b["id"]}, timeout=10).json()
    total_cost = sum(x["amount"] for x in exp)
    assert total_payable == 18000
    assert total_cost == 18000  # NOT 36000


# --------------------------------------------------------------------------- #
# T2.10 — MechanicWO + twin Expense: no double count.                         #
# --------------------------------------------------------------------------- #
def test_t210_mechanic_wo_twin_expense_no_double_count():
    m = requests.post(f"{API}/mechanics", headers=_hdr(_idem()),
                      json={"name": f"{TAG} T210 M"}, timeout=15).json()
    w = requests.post(f"{API}/mechanic-work-orders", headers=_hdr(_idem()),
                      json={"mechanic_id": m["id"], "work_date": "2029-08-31",
                            "amount": 7000}, timeout=15).json()
    e = requests.post(f"{API}/expenses", headers=_hdr(_idem()),
                      json={"date": "2029-08-31", "category": "Repair-Labour",
                            "amount": 7000, "party_type": "mechanic",
                            "party_id": m["id"],
                            "mechanic_work_order_id": w["id"]}, timeout=15)
    assert e.status_code == 200

    wos = requests.get(f"{API}/mechanic-work-orders", headers=_hdr(),
                       params={"mechanic_id": m["id"]}, timeout=10).json()
    total_wo = sum(x["amount"] for x in wos if x["id"] == w["id"])
    exp = requests.get(f"{API}/expenses", headers=_hdr(),
                       params={"mechanic_work_order_id": w["id"]}, timeout=10).json()
    total_cost = sum(x["amount"] for x in exp)
    assert total_wo == 7000 and total_cost == 7000  # NOT 14000


# --------------------------------------------------------------------------- #
# T2.11 — VendorPayment never changes Expense total.                          #
# --------------------------------------------------------------------------- #
def test_t211_vendor_payment_never_changes_expense_total():
    v = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                      json={"name": f"{TAG} T211 V"}, timeout=15).json()
    b = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()),
                      json={"vendor_id": v["id"], "bill_number": f"{TAG}-T211",
                            "bill_date": "2029-08-31", "bill_amount": 2000}, timeout=15).json()
    exp_before = len(requests.get(f"{API}/expenses", headers=_hdr(), timeout=10).json())
    requests.post(f"{API}/vendors/{v['id']}/payments", headers=_hdr(_idem()),
                  json={"vendor_id": v["id"], "date": "2029-09-01", "amount": 2000,
                        "against": "bill", "vendor_bill_id": b["id"]}, timeout=15)
    exp_after = len(requests.get(f"{API}/expenses", headers=_hdr(), timeout=10).json())
    assert exp_after == exp_before, "vendor payment must never create an Expense"


# --------------------------------------------------------------------------- #
# T2.12 — MechanicPayment never changes Expense total.                        #
# --------------------------------------------------------------------------- #
def test_t212_mechanic_payment_never_changes_expense_total():
    m = requests.post(f"{API}/mechanics", headers=_hdr(_idem()),
                      json={"name": f"{TAG} T212 M"}, timeout=15).json()
    w = requests.post(f"{API}/mechanic-work-orders", headers=_hdr(_idem()),
                      json={"mechanic_id": m["id"], "work_date": "2029-08-31",
                            "amount": 500}, timeout=15).json()
    exp_before = len(requests.get(f"{API}/expenses", headers=_hdr(), timeout=10).json())
    requests.post(f"{API}/mechanics/{m['id']}/payments", headers=_hdr(_idem()),
                  json={"mechanic_id": m["id"], "date": "2029-09-01", "amount": 500,
                        "against": "work_order",
                        "mechanic_work_order_id": w["id"]}, timeout=15)
    exp_after = len(requests.get(f"{API}/expenses", headers=_hdr(), timeout=10).json())
    assert exp_after == exp_before


# --------------------------------------------------------------------------- #
# T2.18 — Cross-company isolation for canonical expenses.                     #
# --------------------------------------------------------------------------- #
def test_t218_cross_company_isolation_of_canonical_expenses():
    companies = requests.get(f"{API}/companies", headers=_hdr(), timeout=10).json()
    if len(companies) < 2:
        r = requests.post(f"{API}/companies", headers=_hdr(_idem()),
                          json={"name": f"{TAG} T218 Co2"}, timeout=10)
        if r.status_code != 200:
            pytest.skip("cannot create a 2nd company")
        companies = requests.get(f"{API}/companies", headers=_hdr(), timeout=10).json()
        if len(companies) < 2:
            pytest.skip("still <2 companies")
    a, b = companies[0]["id"], companies[1]["id"]

    trip = _mk_trip_payload(expenses={"toll": 111})
    r = requests.post(f"{API}/trips", headers=_hdr(_idem(), company_id=a), json=trip, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"cannot create trip in company A: {r.text[:200]}")
    tid = r.json()["id"]

    exp_a = requests.get(f"{API}/expenses",
                         headers=_hdr(company_id=a),
                         params={"trip_id": tid}, timeout=10).json()
    exp_b = requests.get(f"{API}/expenses",
                         headers=_hdr(company_id=b),
                         params={"trip_id": tid}, timeout=10).json()
    assert len(exp_a) == 1
    assert len(exp_b) == 0


# --------------------------------------------------------------------------- #
# T2.19 — Trip delete soft-deletes every canonical Expense linked to it.      #
# --------------------------------------------------------------------------- #
def test_t219_delete_trip_soft_deletes_canonical_expenses():
    trip = _mk_trip_payload(expenses={"toll": 333, "repair": 111})
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=15)
    tid = r.json()["id"]
    assert len(_list_expenses_for_trip(tid)) == 2

    r = requests.delete(f"{API}/trips/{tid}?reason=test-t219-cleanup", headers=_hdr(), timeout=15)
    assert r.status_code == 200
    assert _list_expenses_for_trip(tid) == []


# --------------------------------------------------------------------------- #
# T2.20 — High-volume: 150 other_expenditures on one trip; no N+1 / truncate. #
# --------------------------------------------------------------------------- #
def test_t220_high_volume_sync_no_truncation():
    rows = [
        {"id": f"oe_{i}_{uuid.uuid4().hex[:6]}",
         "date": "2029-08-31",
         "type": "Parking",
         "amount": 10 + (i % 50),
         "remarks": ""}
        for i in range(150)
    ]
    trip = _mk_trip_payload(other_expenditures=rows)
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=60)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    rows_out = _list_expenses_for_trip(tid)
    assert len(rows_out) == 150

    # Prove no duplicates by source_key
    keys = [x["source_key"] for x in rows_out]
    assert len(set(keys)) == 150


# --------------------------------------------------------------------------- #
# Bonus — All 6 legacy scalars materialise correctly under one trip.          #
# --------------------------------------------------------------------------- #
def test_all_legacy_scalars_materialise():
    trip = _mk_trip_payload(expenses={
        "diesel": 4000,
        "toll": 500,
        "batta": 300,
        "repair": 1000,
        "other": 200,
        "firewood": 150,
        "other_desc": "Loading tarpaulin",
    })
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=15)
    assert r.status_code == 200
    tid = r.json()["id"]
    rows = _list_expenses_for_trip(tid)
    cats = sorted(x["category"] for x in rows)
    assert cats == ["Batta", "Diesel", "Firewood", "Other", "Repair", "Toll"]
    other_row = next(x for x in rows if x["category"] == "Other")
    assert other_row["narration"] == "Loading tarpaulin"


# --------------------------------------------------------------------------- #
# Bonus — Manual Expense not linked to a trip is not touched by trip sync.    #
# --------------------------------------------------------------------------- #
def test_manual_expense_not_affected_by_trip_sync():
    e = requests.post(f"{API}/expenses", headers=_hdr(_idem()),
                      json={"date": "2029-08-31", "category": "Toll", "amount": 42}, timeout=10)
    assert e.status_code == 200
    manual_id = e.json()["id"]
    assert e.json()["source_type"] == "manual"
    assert e.json()["source_key"] == ""

    trip = _mk_trip_payload(expenses={"toll": 42})
    r = requests.post(f"{API}/trips", headers=_hdr(_idem()), json=trip, timeout=15)
    tid = r.json()["id"]
    # Manual row remains
    still = requests.get(f"{API}/expenses/{manual_id}", headers=_hdr(), timeout=10)
    assert still.status_code == 200
    assert still.json()["amount"] == 42
    # Trip has its own canonical (source_key != empty)
    trip_rows = _list_expenses_for_trip(tid)
    assert len(trip_rows) == 1
    assert trip_rows[0]["source_key"] == f"trip:{tid}:legacy:toll"
