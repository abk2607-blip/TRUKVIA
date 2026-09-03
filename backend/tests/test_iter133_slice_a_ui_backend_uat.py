"""Iter133 · Turn 3 · Slice A — backend source-of-truth verification for the
operator UI flow (twin-write: VendorBill + Expense, MechanicWO + Expense,
Payments do not change Vehicle Cost).

Mirrors the exact API calls the new frontend pages issue.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_fe = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = f"{BASE_URL}/api"
DEMO_TOKEN = os.environ.get("DEMO_TOKEN_VALUE") or dotenv_values("/app/backend/.env").get("DEMO_TOKEN_VALUE")
TAG = f"SLICEA-{uuid.uuid4().hex[:6].upper()}"
EVIDENCE = {"tag": TAG, "scenarios": {}}


def _hdr(key=None):
    h = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}
    if key:
        h["Idempotency-Key"] = key
    return h


def _idem():
    return f"slicea-{uuid.uuid4().hex[:24]}"


@pytest.fixture(scope="module")
def ctx():
    assert DEMO_TOKEN, "DEMO_TOKEN_VALUE not available"
    c = {}
    # Vendor master create
    v = requests.post(f"{API}/vendors", headers=_hdr(),
                      json={"name": f"{TAG} Vendor", "mobile": "9998887777", "city": "Hyderabad"},
                      timeout=20)
    assert v.status_code == 200, v.text
    c["vendor"] = v.json()
    # Mechanic master create
    m = requests.post(f"{API}/mechanics", headers=_hdr(),
                      json={"name": f"{TAG} Mechanic", "skill": "Diesel Fitter", "mobile": "7776665555"},
                      timeout=20)
    assert m.status_code == 200, m.text
    c["mechanic"] = m.json()
    # Isolated OWN vehicle
    veh = requests.post(f"{API}/vehicles", headers=_hdr(_idem()),
                        json={"vehicle_number": f"AP99SA{uuid.uuid4().hex[:4].upper()}", "vehicle_type": "own"},
                        timeout=20)
    assert veh.status_code == 200, veh.text
    c["vehicle"] = veh.json()
    EVIDENCE["vendor_id"] = c["vendor"]["id"]
    EVIDENCE["mechanic_id"] = c["mechanic"]["id"]
    EVIDENCE["vehicle_id"] = c["vehicle"]["id"]
    yield c


# ---------------- masters ----------------

class TestMasters:
    def test_vendor_create_and_persist(self, ctx):
        vid = ctx["vendor"]["id"]
        g = requests.get(f"{API}/vendors/{vid}", headers=_hdr(), timeout=15)
        assert g.status_code == 200, g.text
        d = g.json()
        assert d["name"] == f"{TAG} Vendor"
        assert d["mobile"] == "9998887777"
        assert d.get("is_active") is True
        assert "_id" not in d

    def test_vendor_update(self, ctx):
        vid = ctx["vendor"]["id"]
        cur = requests.get(f"{API}/vendors/{vid}", headers=_hdr(), timeout=15).json()
        cur["mobile"] = "8887776666"
        u = requests.put(f"{API}/vendors/{vid}", headers=_hdr(), json=cur, timeout=15)
        assert u.status_code == 200, u.text
        assert requests.get(f"{API}/vendors/{vid}", headers=_hdr(), timeout=15).json()["mobile"] == "8887776666"

    def test_mechanic_create_and_persist(self, ctx):
        mid = ctx["mechanic"]["id"]
        g = requests.get(f"{API}/mechanics/{mid}", headers=_hdr(), timeout=15)
        assert g.status_code == 200, g.text
        assert g.json()["skill"] == "Diesel Fitter"
        assert "_id" not in g.json()

    def test_vendor_ledger_endpoint(self, ctx):
        r = requests.get(f"{API}/vendors/{ctx['vendor']['id']}/ledger", headers=_hdr(), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "rows" in d or "entries" in d, d

    def test_mechanic_ledger_endpoint(self, ctx):
        r = requests.get(f"{API}/mechanics/{ctx['mechanic']['id']}/ledger", headers=_hdr(), timeout=20)
        assert r.status_code == 200, r.text


# ---------------- twin-write core invariant ----------------

class TestTwinWriteCore:
    def test_full_repair_flow_25k(self, ctx):
        vid = ctx["vehicle"]["id"]
        base = requests.get(f"{API}/vehicles/{vid}/cost-summary", headers=_hdr(), timeout=20).json()["total_cost"]
        EVIDENCE["baseline_total_cost"] = base

        # repair event (no monetary total)
        rev = requests.post(f"{API}/repair-events", headers=_hdr(_idem()), json={
            "vehicle_id": vid, "vehicle_number": ctx["vehicle"]["vehicle_number"],
            "event_date": "2029-09-01", "workshop_name": "UAT Workshop",
            "description": "Slice A UAT", "odometer": 0, "status": "open",
        }, timeout=20)
        assert rev.status_code == 200, rev.text
        rid = rev.json()["id"]
        ctx["rid"] = rid
        EVIDENCE["repair_id"] = rid

        bill_no = f"UAT-BILL-{uuid.uuid4().hex[:5].upper()}"
        ctx["bill_no"] = bill_no
        b = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
            "vendor_id": ctx["vendor"]["id"], "bill_number": bill_no,
            "bill_date": "2029-09-01", "bill_amount": 18000,
            "vehicle_id": vid, "vehicle_number": ctx["vehicle"]["vehicle_number"],
            "repair_event_id": rid, "narration": f"{TAG} parts",
        }, timeout=20)
        assert b.status_code == 200, b.text
        bill = b.json()
        ctx["bill_id"] = bill["id"]
        EVIDENCE["bill_id"] = bill["id"]

        e1 = requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
            "date": "2029-09-01", "category": "Repair-Parts", "amount": 18000,
            "vehicle_id": vid, "vehicle_number": ctx["vehicle"]["vehicle_number"],
            "repair_event_id": rid, "party_type": "vendor", "vendor_bill_id": bill["id"],
            "narration": f"{TAG} parts", "supplier_owned_vehicle": False,
            "supplier_settlement_mode": "n/a",
        }, timeout=20)
        assert e1.status_code == 200, e1.text

        w = requests.post(f"{API}/mechanic-work-orders", headers=_hdr(_idem()), json={
            "mechanic_id": ctx["mechanic"]["id"], "work_date": "2029-09-01",
            "amount": 7000, "hours_worked": 4, "vehicle_id": vid,
            "vehicle_number": ctx["vehicle"]["vehicle_number"], "repair_event_id": rid,
            "narration": f"{TAG} labour",
        }, timeout=20)
        assert w.status_code == 200, w.text
        wo = w.json()
        ctx["wo_id"] = wo["id"]
        EVIDENCE["wo_id"] = wo["id"]

        e2 = requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
            "date": "2029-09-01", "category": "Repair-Labour", "amount": 7000,
            "vehicle_id": vid, "vehicle_number": ctx["vehicle"]["vehicle_number"],
            "repair_event_id": rid, "party_type": "mechanic",
            "mechanic_work_order_id": wo["id"], "narration": f"{TAG} labour",
            "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        }, timeout=20)
        assert e2.status_code == 200, e2.text
        EVIDENCE["twin_expense_ids"] = [e1.json()["id"], e2.json()["id"]]

        # EXACTLY 2 expense rows summing 25000
        exps = requests.get(f"{API}/expenses", headers=_hdr(), params={"repair_event_id": rid}, timeout=20).json()
        assert len(exps) == 2, exps
        assert sum(x["amount"] for x in exps) == 25000

        # cost-summary increases by exactly 25000
        after = requests.get(f"{API}/vehicles/{vid}/cost-summary", headers=_hdr(), timeout=20).json()["total_cost"]
        assert after - base == 25000, (base, after)

        bills = requests.get(f"{API}/vendor-bills", headers=_hdr(), params={"repair_event_id": rid}, timeout=20).json()
        assert len(bills) == 1 and bills[0]["bill_amount"] == 18000
        wos = requests.get(f"{API}/mechanic-work-orders", headers=_hdr(), params={"repair_event_id": rid}, timeout=20).json()
        assert len(wos) == 1 and wos[0]["amount"] == 7000

        hist = requests.get(f"{API}/vehicles/{vid}/repair-history", headers=_hdr(), timeout=20).json()
        ev = next(e for e in hist["events"] if e["id"] == rid)
        assert ev["total_repair_cost"] == 25000, ev
        assert ev["parts_cost"] == 18000
        assert ev["labour_cost"] == 7000
        assert ev["vendor_outstanding"] == 18000
        assert ev["mechanic_outstanding"] == 7000
        EVIDENCE["scenarios"]["twin_write_25k"] = "PASS"

    def test_duplicate_bill_number_409(self, ctx):
        r = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
            "vendor_id": ctx["vendor"]["id"], "bill_number": ctx["bill_no"],
            "bill_date": "2029-09-01", "bill_amount": 18000,
            "vehicle_id": ctx["vehicle"]["id"], "repair_event_id": ctx["rid"],
        }, timeout=20)
        assert r.status_code == 409, r.status_code
        bills = requests.get(f"{API}/vendor-bills", headers=_hdr(),
                             params={"vendor_id": ctx["vendor"]["id"]}, timeout=20).json()
        assert len([b for b in bills if b.get("bill_number") == ctx["bill_no"]]) == 1

    def test_payment_reduces_outstanding_not_vehicle_cost(self, ctx):
        vid = ctx["vehicle"]["id"]
        p = requests.post(f"{API}/vendors/{ctx['vendor']['id']}/payments", headers=_hdr(), json={
            "vendor_id": ctx["vendor"]["id"], "type": "payment_out", "date": "2029-09-02",
            "amount": 10000, "mode": "Bank", "against": "bill",
            "vendor_bill_id": ctx["bill_id"], "remarks": f"{TAG} pay",
        }, timeout=20)
        assert p.status_code == 200, p.text
        EVIDENCE["payment_id"] = p.json().get("id")
        cost = requests.get(f"{API}/vehicles/{vid}/cost-summary", headers=_hdr(), timeout=20).json()["total_cost"]
        assert cost - EVIDENCE["baseline_total_cost"] == 25000, cost
        hist = requests.get(f"{API}/vehicles/{vid}/repair-history", headers=_hdr(), timeout=20).json()
        ev = next(e for e in hist["events"] if e["id"] == ctx["rid"])
        assert ev["vendor_paid"] == 10000, ev
        assert ev["vendor_outstanding"] == 8000, ev
        assert ev["total_repair_cost"] == 25000
        EVIDENCE["scenarios"]["payment_no_cost_change"] = "PASS"

    def test_mechanic_payment(self, ctx):
        vid = ctx["vehicle"]["id"]
        p = requests.post(f"{API}/mechanics/{ctx['mechanic']['id']}/payments", headers=_hdr(), json={
            "mechanic_id": ctx["mechanic"]["id"], "type": "payment_out", "date": "2029-09-02",
            "amount": 4000, "mode": "Cash", "against": "work_order",
            "mechanic_work_order_id": ctx["wo_id"], "remarks": f"{TAG} pay-mech",
        }, timeout=20)
        assert p.status_code == 200, p.text
        hist = requests.get(f"{API}/vehicles/{vid}/repair-history", headers=_hdr(), timeout=20).json()
        ev = next(e for e in hist["events"] if e["id"] == ctx["rid"])
        assert ev["mechanic_outstanding"] == 3000, ev
        cost = requests.get(f"{API}/vehicles/{vid}/cost-summary", headers=_hdr(), timeout=20).json()["total_cost"]
        assert cost - EVIDENCE["baseline_total_cost"] == 25000


# ---------------- supplier-owned settlement ----------------

class TestSupplierOwned:
    def test_supplier_vehicle_settlement_mode(self):
        sup = requests.post(f"{API}/suppliers", headers=_hdr(_idem()),
                            json={"name": f"{TAG} Sup", "mobile": "9990001111"}, timeout=20).json()
        veh = requests.post(f"{API}/vehicles", headers=_hdr(_idem()), json={
            "vehicle_number": f"AP99SS{uuid.uuid4().hex[:4].upper()}",
            "vehicle_type": "supplier", "supplier_id": sup["id"],
        }, timeout=20).json()
        rid = requests.post(f"{API}/repair-events", headers=_hdr(_idem()), json={
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "event_date": "2029-09-03", "workshop_name": "UAT WS", "status": "open",
        }, timeout=20).json()["id"]
        vendor = requests.post(f"{API}/vendors", headers=_hdr(),
                               json={"name": f"{TAG} Vendor2", "mobile": "9111111111"}, timeout=20).json()
        bill = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
            "vendor_id": vendor["id"], "bill_number": f"UAT-SUP-{uuid.uuid4().hex[:5].upper()}",
            "bill_date": "2029-09-03", "bill_amount": 5000, "vehicle_id": veh["id"],
            "vehicle_number": veh["vehicle_number"], "repair_event_id": rid,
        }, timeout=20).json()
        e = requests.post(f"{API}/expenses", headers=_hdr(_idem()), json={
            "date": "2029-09-03", "category": "Repair-Parts", "amount": 5000,
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "repair_event_id": rid, "party_type": "vendor", "vendor_bill_id": bill["id"],
            "supplier_owned_vehicle": True,
            "supplier_settlement_mode": "supplier_settlement_adjustment",
        }, timeout=20)
        assert e.status_code == 200, e.text
        rows = requests.get(f"{API}/expenses", headers=_hdr(), params={"repair_event_id": rid}, timeout=20).json()
        assert len(rows) == 1
        assert rows[0]["supplier_owned_vehicle"] is True
        assert rows[0]["supplier_settlement_mode"] == "supplier_settlement_adjustment"
        EVIDENCE["scenarios"]["supplier_settlement"] = "PASS"


# ---------------- legacy trip canonical XOR ----------------

class TestLegacyTripXor:
    def test_trip_toll_single_canonical_expense(self):
        cust = requests.get(f"{API}/customers", headers=_hdr(), timeout=20).json()
        items = cust.get("items", cust) if isinstance(cust, dict) else cust
        veh = requests.post(f"{API}/vehicles", headers=_hdr(_idem()), json={
            "vehicle_number": f"AP99TR{uuid.uuid4().hex[:4].upper()}", "vehicle_type": "own"}, timeout=20).json()
        trip = requests.post(f"{API}/trips", headers=_hdr(_idem()), json={
            "customer_id": items[0]["id"], "date": "2029-09-04",
            "vehicle_number": veh["vehicle_number"], "vehicle_id": veh["id"], "vehicle_type": "own",
            "tons": 15, "loaded_qty": 15, "unloaded_qty": 15,
            "freight_mode": "per_ton", "rate_per_ton": 850, "product_rate_per_mt": 40000,
            "from_location": "A", "to_location": "B", "driver_name": f"{TAG} Drv",
            "expenses": {"toll": 1000}, "other_expenditures": [],
        }, timeout=25)
        assert trip.status_code == 200, trip.text
        td = trip.json()
        assert td.get("has_canonical_expenses") is True, td.get("has_canonical_expenses")
        rows = requests.get(f"{API}/expenses", headers=_hdr(), params={"trip_id": td["id"]}, timeout=20).json()
        assert len(rows) == 1, rows
        assert rows[0]["source_type"] == "trip_legacy"
        assert rows[0]["category"] == "Toll"
        assert rows[0]["amount"] == 1000


def test_zz_write_evidence():
    Path("/app/artifacts").mkdir(parents=True, exist_ok=True)
    p = Path("/app/artifacts/Iter133_Expense_UI_SliceA_UAT_backend_evidence.json")
    p.write_text(json.dumps(EVIDENCE, indent=2))
    assert p.exists()
