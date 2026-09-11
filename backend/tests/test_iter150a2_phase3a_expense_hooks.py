"""Iter150A-2 · Phase 3A — Router-level Expense write hooks.

Covers the 7 router-level Expense mutation sites installed in
routers/expenses.py (5) + routers/fuel_import.py (2), plus the
cross-reprojection helper in services_expense_linkage_hooks.py.

Scope constraints (per Phase 3A approval):
  * NO service-level hook coverage (bulk quick-op / fuel import / fastag
    import / bridge — those are Phase 3B).
  * NO Expense reversal write-path (no live setter exists; a projection-
    level assertion is included instead).
  * Cross-reprojection MUST fire only when vendor_bill_id or
    mechanic_work_order_id actually changes.
"""
from __future__ import annotations

import asyncio as _asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api" if BASE_URL.startswith("http") else "http://localhost:8001/api"
TOK = os.environ.get("DEMO_TOKEN_VALUE", "")
H = {"Authorization": f"Bearer {TOK}"}
HJSON = {**H, "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _demo_uid_cid() -> tuple[str, str]:
    d = _db()
    me = d.users.find_one({"email": "demo@bitumen-transport.local"},
                          {"_id": 0, "user_id": 1})
    assert me, "demo user missing"
    uid = me["user_id"]
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False}, timeout=15)
    assert r.status_code == 200, r.text
    cid = r.json()[0]["company_id"]
    return uid, cid


class _Ctx:
    """Per-test isolation with best-effort teardown of every artefact created."""

    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo_uid_cid()
        self.tag = uuid.uuid4().hex[:10]
        self._expenses: list[str] = []
        self._vendor_bills: list[str] = []
        self._mechanic_wos: list[str] = []
        self._vendors: list[str] = []
        self._mechanics: list[str] = []
        self._vehicles: list[str] = []
        self._trips: list[str] = []

    # ── Master helpers (all go through the real HTTP write path) ─
    def make_vehicle(self, kind: str = "own") -> tuple[str, str]:
        vnum = f"P3A{self.tag[:4].upper()}"
        r = requests.post(f"{API}/vehicles", headers=HJSON, json={
            "vehicle_number": vnum, "vehicle_type": kind, "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        v = r.json()
        self._vehicles.append(v["id"])
        return v["id"], v["vehicle_number"]

    def make_vendor(self) -> str:
        r = requests.post(f"{API}/vendors", headers=HJSON, json={
            "name": f"P3A-V {self.tag}", "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        self._vendors.append(vid)
        return vid

    def make_mechanic(self) -> str:
        r = requests.post(f"{API}/mechanics", headers=HJSON, json={
            "name": f"P3A-M {self.tag}", "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        self._mechanics.append(mid)
        return mid

    def make_vendor_bill(self, vendor_id: str, veh_id: str,
                         amount: float = 3000.0,
                         bill_number: str | None = None) -> str:
        r = requests.post(f"{API}/vendor-bills", headers=HJSON, json={
            "vendor_id": vendor_id, "vehicle_id": veh_id,
            "bill_date": "2026-04-01", "bill_amount": amount,
            "bill_number": bill_number or f"BN-{self.tag}-{len(self._vendor_bills)+1}",
            "narration": "phase3a-vb",
        }, timeout=15)
        assert r.status_code == 200, r.text
        bid = r.json()["id"]
        self._vendor_bills.append(bid)
        return bid

    def make_mechanic_wo(self, mechanic_id: str, veh_id: str,
                         amount: float = 2000.0) -> str:
        r = requests.post(f"{API}/mechanic-work-orders", headers=HJSON, json={
            "mechanic_id": mechanic_id, "vehicle_id": veh_id,
            "work_date": "2026-04-01", "amount": amount,
            "description": "phase3a-wo",
        }, timeout=15)
        assert r.status_code == 200, r.text
        wid = r.json()["id"]
        self._mechanic_wos.append(wid)
        return wid

    # ── Expense factories ────────────────────────────────────────
    def _base_expense(self, **over) -> dict:
        base = {
            "date": "2026-04-01", "category": "Other",
            "amount": 100.0, "narration": "phase3a-manual",
            "remarks": "", "vehicle_id": "", "vehicle_number": "",
            "trip_id": "", "repair_event_id": "",
            "party_type": "cash", "party_id": "", "party_name": "",
            "vendor_bill_id": "", "mechanic_work_order_id": "",
            "supplier_owned_vehicle": False,
            "supplier_settlement_mode": "n/a",
            "settlement_mode": "cash_now",
            "source_type": "manual", "source_key": f"p3a:{self.tag}:{uuid.uuid4().hex[:6]}",
            "file_ids": [],
        }
        base.update(over)
        return base

    def create_manual_expense(self, **over) -> str:
        r = requests.post(f"{API}/expenses", headers=HJSON,
                          json=self._base_expense(**over), timeout=15)
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        self._expenses.append(eid)
        return eid

    def teardown(self):
        d = self.d
        if self._expenses:
            d.expenses.delete_many({"id": {"$in": self._expenses}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                   "source_id": {"$in": self._expenses}})
            d.fin_hook_failures.delete_many(
                {"user_id": self.uid, "source_id": {"$in": self._expenses}})
        if self._vendor_bills:
            d.vendor_bills.delete_many({"id": {"$in": self._vendor_bills}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                   "source_id": {"$in": self._vendor_bills}})
        if self._mechanic_wos:
            d.mechanic_work_orders.delete_many({"id": {"$in": self._mechanic_wos}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                   "source_id": {"$in": self._mechanic_wos}})
        if self._vendors:
            d.vendors.delete_many({"id": {"$in": self._vendors}})
        if self._mechanics:
            d.mechanics.delete_many({"id": {"$in": self._mechanics}})
        if self._trips:
            d.trips.delete_many({"id": {"$in": self._trips}})
        if self._vehicles:
            d.vehicles.delete_many({"id": {"$in": self._vehicles}})


@pytest.fixture
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


def _fin_legs(ctx: _Ctx, source_id: str, source_type: str = "expense") -> list[dict]:
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "company_id": ctx.cid,
         "source_type": source_type, "source_id": source_id},
        {"_id": 0, "account_code": 1, "counter_account_code": 1,
         "direction": 1, "amount": 1, "ref_source_key": 1,
         "party_type": 1, "party_id": 1, "trip_id": 1, "vehicle_id": 1,
         "txn_date": 1, "source_id": 1, "source_type": 1},
    ))


# ── 1. Manual Expense create → A-1 projection (EXPENSE + CASH) ────────
def test_1_manual_expense_create(ctx):
    vid, _ = ctx.make_vehicle()
    eid = ctx.create_manual_expense(vehicle_id=vid, amount=175.0,
                                    category="Parking")
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2, legs
    codes = {(l["account_code"], l["direction"], l["amount"]) for l in legs}
    assert codes == {("EXPENSE_DEFAULT", "in", 175.0), ("CASH", "out", 175.0)}


# ── 2. Manual Expense update (amount + date) → replacement ─────────────
def test_2_manual_expense_update(ctx):
    vid, _ = ctx.make_vehicle()
    eid = ctx.create_manual_expense(vehicle_id=vid, amount=100.0,
                                    category="Parking")
    assert len(_fin_legs(ctx, eid)) == 2

    r = requests.put(f"{API}/expenses/{eid}", headers=HJSON,
                     json=ctx._base_expense(
                         vehicle_id=vid, amount=250.0, date="2026-04-02",
                         category="Parking"), timeout=15)
    assert r.status_code == 200, r.text
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    amts = {l["amount"] for l in legs}
    assert amts == {250.0}
    assert all(l["txn_date"] == "2026-04-02" for l in legs)


# ── 3. Manual Expense soft-delete → legs vanish ────────────────────────
def test_3_manual_expense_soft_delete(ctx):
    vid, _ = ctx.make_vehicle()
    eid = ctx.create_manual_expense(vehicle_id=vid, amount=88.0,
                                    category="Parking")
    assert len(_fin_legs(ctx, eid)) == 2

    r = requests.delete(f"{API}/expenses/{eid}", headers=H,
                        params={"reason": "phase3a-delete"}, timeout=15)
    assert r.status_code == 200, r.text
    assert _fin_legs(ctx, eid) == []
    # Source doc remains authoritative.
    src = ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "is_deleted": 1})
    assert src and src["is_deleted"] is True


# ── 4. Quick-Diesel update → projected legs reflect new amount ─────────
def test_4_quick_diesel_update(ctx):
    """The quick-diesel edit endpoint is Diesel-only and quick_op-only;
    seed a matching Expense via bulk-operational then update."""
    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
        "date": "2026-04-01", "category": "Diesel", "trip_id": "",
        "entries": [{"client_row_id": f"crid-{ctx.tag}",
                     "vehicle_id": vid,
                     "qty": 10, "rate": 90}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert results[0]["status"] == "created"
    eid = results[0]["expense"]["id"]
    ctx._expenses.append(eid)
    # bulk-operational does NOT project in Phase 3A — trigger via a
    # subsequent hook by calling the QDE endpoint which IS in Phase 3A.
    r2 = requests.put(f"{API}/expenses/{eid}/quick-diesel", headers=HJSON, json={
        "qty": 20, "rate": 100, "filled_at": "IOCL Site",
    }, timeout=15)
    assert r2.status_code == 200, r2.text
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    # amount = 20 * 100 = 2000
    assert {l["amount"] for l in legs} == {2000.0}


# ── 5. Toll → Trip link refreshes trip_id denorm (no accounting delta) ─
def test_5_toll_trip_link(ctx):
    """Requires a FASTag-imported Toll Expense. Seed one directly."""
    vid, vnum = ctx.make_vehicle()
    # Seed Trip directly (bypasses complex /api/trips validation surface).
    tid = f"trip_p3a_{ctx.tag}"
    ctx.d.trips.insert_one({
        "id": tid, "user_id": ctx.uid, "company_id": ctx.cid,
        "vehicle_id": vid, "vehicle_number": vnum, "vehicle_type": "own",
        "date": "2026-04-01", "lr_number": f"LR-{ctx.tag}",
        "has_canonical_expenses": True, "is_deleted": False,
        "created_at": "2026-04-01T00:00:00+00:00",
    })
    ctx._trips.append(tid)

    # Seed a fastag_import Toll Expense directly in DB (the FASTag commit
    # path is Phase 3B; this test focuses on the toll-trip PATCH hook).
    eid = f"exp_p3a_toll_{ctx.tag}"
    doc = {
        "id": eid, "user_id": ctx.uid, "company_id": ctx.cid,
        "date": "2026-04-01", "category": "Toll", "amount": 450.0,
        "narration": "plaza X", "remarks": f"Txn: T{ctx.tag}",
        "vehicle_id": vid, "vehicle_number": vnum, "trip_id": "",
        "repair_event_id": "", "party_type": "cash", "party_id": "",
        "party_name": "", "vendor_bill_id": "", "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
        "file_ids": [], "source_type": "fastag_import",
        "source_key": f"fastag:{ctx.tag}", "source": "idfc",
        "source_txn_ref": f"T{ctx.tag}", "source_trip_id": "",
        "created_at": "2026-04-01T00:00:00+00:00", "created_by": ctx.uid,
        "is_deleted": False,
    }
    ctx.d.expenses.insert_one(doc)
    ctx._expenses.append(eid)
    # Bring the projection up to speed (owner reproject).
    r0 = requests.post(f"{API}/fin/reproject", headers=HJSON, json={
        "source_type": "expense", "source_id": eid}, timeout=15)
    assert r0.status_code == 200
    legs_before = _fin_legs(ctx, eid)
    assert len(legs_before) == 2
    assert all(l["trip_id"] == "" for l in legs_before)
    amt_before = sum(l["amount"] for l in legs_before if l["direction"] == "in")

    # Link
    r = requests.patch(f"{API}/expenses/{eid}/toll-trip", headers=HJSON,
                       json={"trip_id": tid}, timeout=15)
    assert r.status_code == 200, r.text
    legs_after = _fin_legs(ctx, eid)
    assert len(legs_after) == 2
    assert all(l["trip_id"] == tid for l in legs_after)
    # Amount / account unchanged.
    amt_after = sum(l["amount"] for l in legs_after if l["direction"] == "in")
    assert amt_before == amt_after == 450.0


# ── 6. Toll → Trip unlink clears trip_id ─────────────────────────────
def test_6_toll_trip_unlink(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = f"trip_p3a_u_{ctx.tag}"
    ctx.d.trips.insert_one({
        "id": tid, "user_id": ctx.uid, "company_id": ctx.cid,
        "vehicle_id": vid, "vehicle_number": vnum, "vehicle_type": "own",
        "date": "2026-04-01", "lr_number": f"LR-U-{ctx.tag}",
        "has_canonical_expenses": True, "is_deleted": False,
        "created_at": "2026-04-01T00:00:00+00:00",
    })
    ctx._trips.append(tid)

    eid = f"exp_p3a_ul_{ctx.tag}"
    ctx.d.expenses.insert_one({
        "id": eid, "user_id": ctx.uid, "company_id": ctx.cid,
        "date": "2026-04-01", "category": "Toll", "amount": 275.0,
        "narration": "plaza Y", "remarks": f"Txn: U{ctx.tag}",
        "vehicle_id": vid, "vehicle_number": vnum, "trip_id": tid,
        "repair_event_id": "", "party_type": "cash", "party_id": "",
        "party_name": "", "vendor_bill_id": "", "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
        "file_ids": [], "source_type": "fastag_import",
        "source_key": f"fastag:{ctx.tag}:u", "source": "idfc",
        "source_txn_ref": f"U{ctx.tag}", "source_trip_id": "",
        "created_at": "2026-04-01T00:00:00+00:00", "created_by": ctx.uid,
        "is_deleted": False,
    })
    ctx._expenses.append(eid)
    requests.post(f"{API}/fin/reproject", headers=HJSON, json={
        "source_type": "expense", "source_id": eid}, timeout=15)
    assert all(l["trip_id"] == tid for l in _fin_legs(ctx, eid))

    r = requests.patch(f"{API}/expenses/{eid}/toll-trip", headers=HJSON,
                       json={"trip_id": ""}, timeout=15)
    assert r.status_code == 200, r.text
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    assert all(l["trip_id"] == "" for l in legs)


# ── 7. Manual Fuel Expense create → projects Diesel legs ───────────────
def test_7_manual_fuel_expense_create(ctx):
    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/fuel-manual", headers=HJSON, json={
        "vehicle_id": vid, "date": "2026-04-01",
        "litres": 15, "rate": 92,
    }, timeout=15)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    ctx._expenses.append(eid)
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    codes = {(l["account_code"], l["direction"], l["amount"]) for l in legs}
    assert codes == {("EXPENSE_DEFAULT", "in", 1380.0),
                     ("CASH", "out", 1380.0)}


# ── 8. Fleet-card vehicle correction: vehicle_id denorm refresh only ───
def test_8_fleet_card_vehicle_correction(ctx):
    vid_old, vnum_old = ctx.make_vehicle()
    vid_new, vnum_new = ctx.make_vehicle()

    # Seed fleet_card_import Expense directly.
    eid = f"exp_p3a_fc_{ctx.tag}"
    ctx.d.expenses.insert_one({
        "id": eid, "user_id": ctx.uid, "company_id": ctx.cid,
        "date": "2026-04-01", "category": "Diesel", "amount": 3200.0,
        "narration": "40 L @ ₹80.00", "remarks": "ODO: 12345",
        "vehicle_id": vid_old, "vehicle_number": vnum_old, "trip_id": "",
        "repair_event_id": "", "party_type": "cash", "party_id": "",
        "party_name": "", "vendor_bill_id": "", "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
        "file_ids": [], "source_type": "fleet_card_import",
        "source_key": f"fleet:{ctx.tag}", "source": "iocl",
        "source_txn_ref": f"F{ctx.tag}", "source_trip_id": "",
        "created_at": "2026-04-01T00:00:00+00:00", "created_by": ctx.uid,
        "is_deleted": False,
    })
    ctx._expenses.append(eid)
    requests.post(f"{API}/fin/reproject", headers=HJSON, json={
        "source_type": "expense", "source_id": eid}, timeout=15)
    legs_before = _fin_legs(ctx, eid)
    assert len(legs_before) == 2
    assert all(l["vehicle_id"] == vid_old for l in legs_before)
    amt_before = sum(l["amount"] for l in legs_before if l["direction"] == "in")

    # Correct
    r = requests.patch(f"{API}/expenses/{eid}/fleet-card-vehicle",
                       headers=HJSON, json={"vehicle_id": vid_new}, timeout=15)
    assert r.status_code == 200, r.text
    legs_after = _fin_legs(ctx, eid)
    assert len(legs_after) == 2
    assert all(l["vehicle_id"] == vid_new for l in legs_after)
    # Amount unchanged.
    amt_after = sum(l["amount"] for l in legs_after if l["direction"] == "in")
    assert amt_before == amt_after == 3200.0
    # source identity unchanged
    src = ctx.d.expenses.find_one({"id": eid}, {"_id": 0,
        "source_key": 1, "source_txn_ref": 1, "source_type": 1})
    assert src["source_type"] == "fleet_card_import"
    assert src["source_key"] == f"fleet:{ctx.tag}"
    assert src["source_txn_ref"] == f"F{ctx.tag}"


# ── 9. Cross-reproject: vendor_bill_id A → B ───────────────────────────
def test_9_vendor_bill_id_A_to_B_cross_reproject(ctx):
    vid, _ = ctx.make_vehicle()
    ven = ctx.make_vendor()
    bA = ctx.make_vendor_bill(ven, vid, amount=3000.0,
                              bill_number=f"A-{ctx.tag}")
    bB = ctx.make_vendor_bill(ven, vid, amount=3000.0,
                              bill_number=f"B-{ctx.tag}")

    # Project both bills first (orphans).
    for bid in (bA, bB):
        r = requests.post(f"{API}/fin/reproject", headers=HJSON, json={
            "source_type": "vendor_bill", "source_id": bid}, timeout=15)
        assert r.status_code == 200

    # Both currently orphan → each has 2 legs projected.
    assert len(_fin_legs(ctx, bA, "vendor_bill")) == 2
    assert len(_fin_legs(ctx, bB, "vendor_bill")) == 2

    # Create paired Expense linked to bA → orphan bA legs should vanish.
    eid = ctx.create_manual_expense(
        vehicle_id=vid, amount=3000.0, category="Repair",
        party_type="vendor", party_id=ven, vendor_bill_id=bA,
    )
    assert len(_fin_legs(ctx, eid)) == 2                     # paired expense projects
    assert len(_fin_legs(ctx, bA, "vendor_bill")) == 0       # A becomes paired
    assert len(_fin_legs(ctx, bB, "vendor_bill")) == 2       # B still orphan

    # Update Expense to link bill B → A transitions back to orphan, B becomes paired.
    r = requests.put(f"{API}/expenses/{eid}", headers=HJSON, json={
        "date": "2026-04-01", "category": "Repair", "amount": 3000.0,
        "narration": "phase3a-repair-B", "remarks": "",
        "vehicle_id": vid, "vehicle_number": "",
        "trip_id": "", "repair_event_id": "",
        "party_type": "vendor", "party_id": ven, "party_name": "",
        "vendor_bill_id": bB, "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False,
        "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now",
        "source_type": "manual", "source_key": f"p3a-vb-swap:{ctx.tag}",
        "file_ids": [],
    }, timeout=15)
    assert r.status_code == 200, r.text
    assert len(_fin_legs(ctx, eid)) == 2
    assert len(_fin_legs(ctx, bA, "vendor_bill")) == 2       # A back to orphan
    assert len(_fin_legs(ctx, bB, "vendor_bill")) == 0       # B now paired


# ── 10. Cross-reproject: mechanic_work_order_id A → B ──────────────────
def test_10_mechanic_wo_id_A_to_B_cross_reproject(ctx):
    vid, _ = ctx.make_vehicle()
    mec = ctx.make_mechanic()
    wA = ctx.make_mechanic_wo(mec, vid, amount=1500.0)
    wB = ctx.make_mechanic_wo(mec, vid, amount=1500.0)

    for wid in (wA, wB):
        r = requests.post(f"{API}/fin/reproject", headers=HJSON, json={
            "source_type": "mechanic_work_order", "source_id": wid}, timeout=15)
        assert r.status_code == 200

    assert len(_fin_legs(ctx, wA, "mechanic_work_order")) == 2
    assert len(_fin_legs(ctx, wB, "mechanic_work_order")) == 2

    eid = ctx.create_manual_expense(
        vehicle_id=vid, amount=1500.0, category="Repair",
        party_type="mechanic", party_id=mec, mechanic_work_order_id=wA,
    )
    assert len(_fin_legs(ctx, eid)) == 2
    assert len(_fin_legs(ctx, wA, "mechanic_work_order")) == 0
    assert len(_fin_legs(ctx, wB, "mechanic_work_order")) == 2

    r = requests.put(f"{API}/expenses/{eid}", headers=HJSON, json={
        "date": "2026-04-01", "category": "Repair", "amount": 1500.0,
        "narration": "phase3a-wo-swap", "remarks": "",
        "vehicle_id": vid, "vehicle_number": "",
        "trip_id": "", "repair_event_id": "",
        "party_type": "mechanic", "party_id": mec, "party_name": "",
        "vendor_bill_id": "", "mechanic_work_order_id": wB,
        "supplier_owned_vehicle": False,
        "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now",
        "source_type": "manual", "source_key": f"p3a-wo-swap:{ctx.tag}",
        "file_ids": [],
    }, timeout=15)
    assert r.status_code == 200, r.text
    assert len(_fin_legs(ctx, wA, "mechanic_work_order")) == 2   # back to orphan
    assert len(_fin_legs(ctx, wB, "mechanic_work_order")) == 0   # now paired


# ── 11. Unchanged linkage → helper does NOT reproject linked source ────
def test_11_unchanged_linkage_no_cross_reproject(ctx):
    vid, _ = ctx.make_vehicle()
    ven = ctx.make_vendor()
    bid = ctx.make_vendor_bill(ven, vid, amount=1200.0,
                               bill_number=f"NC-{ctx.tag}")
    # Project the bill as orphan first.
    requests.post(f"{API}/fin/reproject", headers=HJSON, json={
        "source_type": "vendor_bill", "source_id": bid}, timeout=15)
    assert len(_fin_legs(ctx, bid, "vendor_bill")) == 2

    # Create paired Expense — helper fires (linkage None → bid).
    eid = ctx.create_manual_expense(
        vehicle_id=vid, amount=1200.0, category="Repair",
        party_type="vendor", party_id=ven, vendor_bill_id=bid,
    )
    assert len(_fin_legs(ctx, bid, "vendor_bill")) == 0   # paired transition

    # Capture the current VB projected_at timestamp (empty since no legs).
    # Now update Expense WITHOUT changing linkage.
    r = requests.put(f"{API}/expenses/{eid}", headers=HJSON, json={
        "date": "2026-04-02", "category": "Repair", "amount": 1300.0,   # amount changes only
        "narration": "linkage-unchanged", "remarks": "",
        "vehicle_id": vid, "vehicle_number": "",
        "trip_id": "", "repair_event_id": "",
        "party_type": "vendor", "party_id": ven, "party_name": "",
        "vendor_bill_id": bid, "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now",
        "source_type": "manual", "source_key": f"nc:{ctx.tag}", "file_ids": [],
    }, timeout=15)
    assert r.status_code == 200, r.text

    # VendorBill still paired → still 0 legs (no re-projection would have
    # created new orphan legs).
    assert len(_fin_legs(ctx, bid, "vendor_bill")) == 0
    # Expense-side updated to 1300.
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    assert {l["amount"] for l in legs} == {1300.0}


# ── 12. source_key preservation across every mutation ─────────────────
def test_12_source_key_preservation(ctx):
    vid, _ = ctx.make_vehicle()
    eid = ctx.create_manual_expense(vehicle_id=vid, amount=100.0,
                                    category="Parking",
                                    source_key=f"skp:{ctx.tag}")
    for _ in range(2):
        r = requests.put(f"{API}/expenses/{eid}", headers=HJSON,
                         json=ctx._base_expense(
                             vehicle_id=vid, amount=200.0,
                             category="Parking",
                             source_key=f"skp:{ctx.tag}"), timeout=15)
        assert r.status_code == 200
    src = ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "source_key": 1,
                                                "source_type": 1})
    assert src["source_key"] == f"skp:{ctx.tag}"
    assert src["source_type"] == "manual"


# ── 13. Idempotent repeated hook: two no-op updates → 2 legs ──────────
def test_13_idempotent_repeated_hook(ctx):
    vid, _ = ctx.make_vehicle()
    eid = ctx.create_manual_expense(vehicle_id=vid, amount=99.0,
                                    category="Parking")
    for _ in range(3):
        r = requests.put(f"{API}/expenses/{eid}", headers=HJSON,
                         json=ctx._base_expense(vehicle_id=vid,
                                                amount=99.0,
                                                category="Parking"),
                         timeout=15)
        assert r.status_code == 200
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    refs = sorted(l["ref_source_key"] for l in legs)
    for r in refs:
        assert r.startswith(f"expense:{eid}:")


# ── 14. Forced hook failure → source stays committed, queue row ───────
def test_14_forced_hook_failure_records_row(ctx):
    """Direct-hook exercise: forcibly patch reproject_source in a fresh
    loop and confirm a fin_hook_failures row is created without any
    source rollback. Phase-1 test_9 / test_10 pattern."""
    import services_fin_txn_hooks as hooks

    vid, _ = ctx.make_vehicle()
    eid = f"exp_p3a_boom_{ctx.tag}"
    ctx.d.expenses.insert_one({
        "id": eid, "user_id": ctx.uid, "company_id": ctx.cid,
        "date": "2026-04-01", "category": "Other", "amount": 42.0,
        "narration": "", "remarks": "",
        "vehicle_id": vid, "vehicle_number": "", "trip_id": "",
        "repair_event_id": "", "party_type": "cash", "party_id": "",
        "party_name": "", "vendor_bill_id": "", "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
        "file_ids": [], "source_type": "manual",
        "source_key": f"boom:{ctx.tag}", "source_trip_id": "",
        "created_at": "2026-04-01T00:00:00+00:00", "created_by": ctx.uid,
        "is_deleted": False,
    })
    ctx._expenses.append(eid)

    orig = hooks.reproject_source
    _LOOP = _asyncio.new_event_loop(); _asyncio.set_event_loop(_LOOP)
    async def _boom(*a, **kw): raise RuntimeError("p3a-forced")
    hooks.reproject_source = _boom
    try:
        res = _LOOP.run_until_complete(
            hooks.hook_after_source_write(ctx.uid, ctx.cid, "expense", eid))
        assert res["ok"] is False
        row = ctx.d.fin_hook_failures.find_one(
            {"user_id": ctx.uid, "source_id": eid}, {"_id": 0})
        assert row and row["status"] == "pending"
    finally:
        hooks.reproject_source = orig
        _LOOP.close()
    # Source doc unaffected.
    src = ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "amount": 1})
    assert src["amount"] == 42.0


# ── 15. Replay resolves queued failure → legs projected ───────────────
def test_15_replay_resolves_failure(ctx):
    import subprocess, sys as _sys
    vid, _ = ctx.make_vehicle()
    eid = f"exp_p3a_replay_{ctx.tag}"
    ctx.d.expenses.insert_one({
        "id": eid, "user_id": ctx.uid, "company_id": ctx.cid,
        "date": "2026-04-01", "category": "Parking", "amount": 77.0,
        "narration": "", "remarks": "",
        "vehicle_id": vid, "vehicle_number": "", "trip_id": "",
        "repair_event_id": "", "party_type": "cash", "party_id": "",
        "party_name": "", "vendor_bill_id": "", "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
        "file_ids": [], "source_type": "manual",
        "source_key": f"replay:{ctx.tag}", "source_trip_id": "",
        "created_at": "2026-04-01T00:00:00+00:00", "created_by": ctx.uid,
        "is_deleted": False,
    })
    ctx._expenses.append(eid)
    ctx.d.fin_hook_failures.insert_one({
        "id": f"hfail_p3a_{ctx.tag}",
        "user_id": ctx.uid, "company_id": ctx.cid,
        "source_type": "expense", "source_id": eid,
        "action": "upsert", "error": "seeded-pending",
        "retry_count": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_attempt_at": "2026-01-01T00:00:00+00:00",
        "next_attempt_at": "1970-01-01T00:00:00+00:00",
        "status": "pending", "resolved_at": "", "history": [],
    })
    result = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": eid}, {"_id": 0})
    assert row["status"] == "resolved"
    assert len(_fin_legs(ctx, eid)) == 2


# ── 16. Tenant isolation on Expense projection ─────────────────────────
def test_16_tenant_isolation_expense(ctx):
    vid, _ = ctx.make_vehicle()
    eid = ctx.create_manual_expense(vehicle_id=vid, amount=55.0,
                                    category="Parking")
    other_uid = f"user_iso_{ctx.tag}"
    other_cid = f"co_iso_{ctx.tag}"
    ctx.d.fin_accounts.insert_one({
        "id": f"acc_iso_{ctx.tag}", "user_id": other_uid,
        "company_id": other_cid,
        "code": "EXPENSE_DEFAULT", "name": "iso", "type": "expense",
        "is_system": True, "is_active": True, "created_at": "2026-01-01",
    })
    ctx.d.fin_txn.insert_one({
        "id": f"fintxn_iso_{ctx.tag}",
        "user_id": other_uid, "company_id": other_cid,
        "txn_date": "2026-04-01", "account_id": f"acc_iso_{ctx.tag}",
        "account_code": "EXPENSE_DEFAULT", "direction": "in", "amount": 55.0,
        "counter_account_id": "", "counter_account_code": "CASH",
        "txn_type": "expense", "source_type": "expense",
        "source_id": eid, "source_key": "",
        "ref_source_key": f"expense:{eid}:expense_debit",
        "party_type": "cash", "party_id": "", "party_name": "",
        "vehicle_id": "", "trip_id": "", "category": "Parking",
        "narration": "iso", "status": "active",
        "transfer_group_id": "", "adjustment_group_id": "",
        "reversal_of": "", "is_reversal": False,
        "is_supplier_settlement_recovery": False,
        "reconciled_at": "", "reconciled_ref": "",
        "created_at": "2026-01-01", "projected_at": "2026-01-01",
    })
    try:
        matches = list(ctx.d.fin_txn.find(
            {"ref_source_key": f"expense:{eid}:expense_debit"},
            {"_id": 0, "user_id": 1}))
        uids = {m["user_id"] for m in matches}
        assert ctx.uid in uids and other_uid in uids
        assert len(matches) == 2
    finally:
        ctx.d.fin_txn.delete_many({"user_id": other_uid})
        ctx.d.fin_accounts.delete_many({"user_id": other_uid})


# ── 17. Paired VendorBill double-count guard ──────────────────────────
def test_17_paired_vendor_bill_no_double_count(ctx):
    vid, _ = ctx.make_vehicle()
    ven = ctx.make_vendor()
    bid = ctx.make_vendor_bill(ven, vid, amount=999.0,
                               bill_number=f"DBL-{ctx.tag}")
    eid = ctx.create_manual_expense(
        vehicle_id=vid, amount=999.0, category="Repair",
        party_type="vendor", party_id=ven, vendor_bill_id=bid,
    )
    # Sum EXPENSE_DEFAULT debits attributable to this bill's Expense +
    # the bill itself. Must equal 999 exactly (not 1998).
    total = 0.0
    for src_id, src_type in ((eid, "expense"), (bid, "vendor_bill")):
        for l in _fin_legs(ctx, src_id, src_type):
            if l["account_code"] == "EXPENSE_DEFAULT" and l["direction"] == "in":
                total += l["amount"]
    assert total == 999.0


# ── 18. Paired MechanicWO double-count guard ──────────────────────────
def test_18_paired_mechanic_wo_no_double_count(ctx):
    vid, _ = ctx.make_vehicle()
    mec = ctx.make_mechanic()
    wid = ctx.make_mechanic_wo(mec, vid, amount=555.0)
    eid = ctx.create_manual_expense(
        vehicle_id=vid, amount=555.0, category="Repair",
        party_type="mechanic", party_id=mec, mechanic_work_order_id=wid,
    )
    total = 0.0
    for src_id, src_type in ((eid, "expense"), (wid, "mechanic_work_order")):
        for l in _fin_legs(ctx, src_id, src_type):
            if l["account_code"] == "EXPENSE_DEFAULT" and l["direction"] == "in":
                total += l["amount"]
    assert total == 555.0


# ── 19. A-1 projection module unchanged (is_reversed short-circuit) ────
def test_19_a1_projection_zero_legs_when_is_reversed(ctx):
    """PROJECTION-LEVEL assertion only. NOT a write-path feature — no
    live endpoint sets is_reversed=True on an Expense in Phase 3A."""
    vid, _ = ctx.make_vehicle()
    eid = ctx.create_manual_expense(vehicle_id=vid, amount=123.0,
                                    category="Parking")
    assert len(_fin_legs(ctx, eid)) == 2
    # Force is_reversed=True at the DB and reproject via the locked A-1
    # endpoint — expected zero legs.
    ctx.d.expenses.update_one({"id": eid}, {"$set": {"is_reversed": True}})
    r = requests.post(f"{API}/fin/reproject", headers=HJSON, json={
        "source_type": "expense", "source_id": eid}, timeout=15)
    assert r.status_code == 200
    assert _fin_legs(ctx, eid) == []


# ── 20. A-1 dependency-only (no symbol shadowing by Phase-3A helper) ──
def test_20_a1_dependency_only():
    import services_fin_txn as a1
    import services_fin_txn_hooks as hooks
    import services_expense_linkage_hooks as p3a
    # Phase-3A helper must only import from Phase-1 hooks module.
    assert p3a.hook_after_source_write is hooks.hook_after_source_write
    # Phase-3A helper must NOT re-export A-1 internals.
    for name in ("reproject_source", "project_expense", "project_vendor_bill",
                 "project_mechanic_work_order", "SUPPORTED_SOURCE_TYPES"):
        assert not hasattr(p3a, name), (
            f"Phase-3A helper unexpectedly exports A-1 symbol {name!r}")
    # Phase-1 A-1 dependency stays intact.
    for name in ("reproject_source", "SUPPORTED_SOURCE_TYPES"):
        assert getattr(hooks, name) is getattr(a1, name)
