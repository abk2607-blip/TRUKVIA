"""Iter150A-2 · Phase 5 — Trip.customer_receipts hooks.

Covers the 6 Trip mutation sites in `backend/routers/trips.py`:
  * create_trip           — POST  /api/trips
  * update_trip           — PUT   /api/trips/{tid}
  * delete_trip           — DELETE /api/trips/{tid}
  * bulk_delete_trips     — POST  /api/trips/bulk-delete (per-tid loop)
  * duplicate_trip        — POST  /api/trips/{tid}/duplicate
  * quick_repeat_trip     — POST  /api/trips/quick-repeat/{last_trip_id}

Plus the one authorised A-1 micro-amendment in `services_fin_txn.py`:
add `_delete_by_source(uid, cid, "trip_customer_receipt", f"{tid}:*")`
cascade prefix — mirrors the existing invoice_payment pattern.
project_trip_customer_receipts is UNCHANGED; source_id format
`{tid}:{rid}` is preserved; SUPPORTED_SOURCE_TYPES is unchanged.
"""
from __future__ import annotations

import asyncio as _asyncio
import os
import subprocess
import sys as _sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/frontend/.env"))
load_dotenv(Path("/app/backend/.env"))

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
TOK = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {TOK}"}
HJSON = {**H, "Content-Type": "application/json"}


# Motor's async client binds its connection pool to the first asyncio
# loop it observes. Reuse ONE loop for every in-process async call to
# match the pattern already used by Phase-3B-ii-b / Phase-4 tests and
# avoid "Event loop is closed" cascades.
_LOOP = _asyncio.new_event_loop()
_asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _demo():
    d = _db()
    me = d.users.find_one(
        {"email": "demo@bitumen-transport.local"}, {"_id": 0, "user_id": 1})
    assert me
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False}, timeout=15)
    return me["user_id"], r.json()[0]["company_id"]


class _Ctx:
    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo()
        self.tag = uuid.uuid4().hex[:10]
        self._trips: list[str] = []
        self._vehicles: list[str] = []
        self._customers: list[str] = []
        self._iso_uid = f"iso_p5_{self.tag}"
        self._iso_cid = f"co_iso_p5_{self.tag}"
        self._iso_trips: list[str] = []

    def make_vehicle(self):
        vnum = f"P5V{self.tag[:3].upper()}{len(self._vehicles):02d}"
        r = requests.post(f"{API}/vehicles", headers=HJSON, json={
            "vehicle_number": vnum, "vehicle_type": "own", "is_active": True,
        }, timeout=15)
        v = r.json()
        self._vehicles.append(v["id"])
        return v["id"], v["vehicle_number"]

    def make_customer(self):
        r = requests.post(f"{API}/customers", headers=HJSON, json={
            "name": f"Cust-P5-{self.tag}", "is_active": True,
        }, timeout=15)
        c = r.json()
        self._customers.append(c["id"])
        return c["id"]

    def _trip_payload(self, cid_cust, vid, vnum, receipts=None,
                      date="2026-06-01"):
        return {
            "customer_id": cid_cust,
            "date": date,
            "vehicle_number": vnum,
            "vehicle_id": vid,
            "vehicle_type": "own",
            "tons": 10.0,
            "freight_mode": "fixed",
            "fixed_amount": 5000.0,
            "customer_receipts": list(receipts or []),
        }

    def create_trip(self, cust_id, vid, vnum, receipts=None,
                    date="2026-06-01"):
        payload = self._trip_payload(cust_id, vid, vnum,
                                      receipts=receipts, date=date)
        r = requests.post(f"{API}/trips", headers=HJSON,
                          json=payload, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()
        self._trips.append(t["id"])
        return t

    def update_trip(self, tid, doc):
        """PUT /trips/{tid} — payload must be a full Trip model."""
        payload = {k: v for k, v in doc.items()
                   if k not in ("_id", "user_id")}
        payload["id"] = tid
        r = requests.put(f"{API}/trips/{tid}", headers=HJSON,
                         json=payload, timeout=15)
        assert r.status_code == 200, r.text
        return r.json()

    def teardown(self):
        d = self.d
        if self._trips:
            d.trips.delete_many({"id": {"$in": self._trips}})
            d.fin_txn.delete_many({
                "user_id": self.uid,
                "source_type": "trip_customer_receipt",
                "trip_id": {"$in": self._trips},
            })
            d.fin_hook_failures.delete_many({
                "user_id": self.uid,
                "source_type": "trip_customer_receipt",
                "source_id": {"$in": self._trips},
            })
            d.expenses.delete_many({
                "user_id": self.uid, "source_trip_id": {"$in": self._trips}})
            d.fin_txn.delete_many({
                "user_id": self.uid, "source_type": "expense",
                "trip_id": {"$in": self._trips}})
        if self._customers:
            d.customers.delete_many({"id": {"$in": self._customers}})
        if self._vehicles:
            d.vehicles.delete_many({"id": {"$in": self._vehicles}})
        if self._iso_trips:
            d.trips.delete_many({"id": {"$in": self._iso_trips}})
            d.fin_txn.delete_many({"user_id": self._iso_uid})
            d.fin_accounts.delete_many({"user_id": self._iso_uid})


@pytest.fixture
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


# ── Helpers ──────────────────────────────────────────────────────────────

def _legs(ctx, tid):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "trip_customer_receipt",
         "trip_id": tid, "status": "active"},
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1,
         "counter_account_code": 1, "ref_source_key": 1, "source_id": 1,
         "txn_type": 1, "category": 1}))


def _receipt(rid, amount, mode="Bank", rtype="advance",
             date="2026-06-01"):
    d = {"date": date, "type": rtype, "amount": float(amount), "mode": mode}
    if rid:
        d["id"] = rid
    return d


# ────────────────────────────────────────────────────────────────────────
# 1. CREATE — zero receipts → zero legs but hook fires without error
# ────────────────────────────────────────────────────────────────────────
def test_01_create_zero_receipts(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[])
    assert _legs(ctx, t["id"]) == []
    # No failure row either.
    assert ctx.d.fin_hook_failures.count_documents({
        "user_id": ctx.uid, "source_type": "trip_customer_receipt",
        "source_id": t["id"]}) == 0


# ────────────────────────────────────────────────────────────────────────
# 2. CREATE — single receipt → 2 legs (BANK debit + CUSTOMER_ADVANCE credit)
# ────────────────────────────────────────────────────────────────────────
def test_02_create_single_receipt(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 2500.0, mode="Bank", rtype="advance"),
    ])
    legs = _legs(ctx, t["id"])
    assert len(legs) == 2
    bank = next(l for l in legs if l["direction"] == "in")
    ca = next(l for l in legs if l["direction"] == "out")
    assert bank["account_code"] == "BANK_DEFAULT"
    assert bank["counter_account_code"] == "CUSTOMER_ADVANCE"
    assert ca["account_code"] == "CUSTOMER_ADVANCE"
    assert bank["amount"] == ca["amount"] == 2500.0
    assert bank["source_id"] == f"{t['id']}:r1"


# ────────────────────────────────────────────────────────────────────────
# 3. CREATE — multiple receipts → 2 legs each
# ────────────────────────────────────────────────────────────────────────
def test_03_create_multiple_receipts(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 1000.0, mode="Bank", rtype="advance"),
        _receipt("r2", 2000.0, mode="Cash", rtype="diesel"),
        _receipt("r3", 500.0, mode="UPI", rtype="advance"),
    ])
    legs = _legs(ctx, t["id"])
    assert len(legs) == 6
    src_ids = sorted({l["source_id"] for l in legs})
    assert src_ids == [f"{t['id']}:r1", f"{t['id']}:r2", f"{t['id']}:r3"]


# ────────────────────────────────────────────────────────────────────────
# 4. CREATE — mixed receipt types + mode → account resolver
# ────────────────────────────────────────────────────────────────────────
def test_04_mixed_types_and_modes(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("adv1", 1500.0, mode="Bank", rtype="advance"),
        _receipt("dsl1", 3000.0, mode="Cash", rtype="diesel"),
    ])
    legs = _legs(ctx, t["id"])
    # Advance / Bank → BANK_DEFAULT debit
    adv_bank = next(l for l in legs
                    if l["source_id"] == f"{t['id']}:adv1"
                    and l["direction"] == "in")
    assert adv_bank["account_code"] == "BANK_DEFAULT"
    assert adv_bank["category"] == "advance"
    # Diesel / Cash → CASH debit
    dsl_bank = next(l for l in legs
                    if l["source_id"] == f"{t['id']}:dsl1"
                    and l["direction"] == "in")
    assert dsl_bank["account_code"] == "CASH"
    assert dsl_bank["category"] == "diesel"


# ────────────────────────────────────────────────────────────────────────
# 5. UPDATE — add a receipt → new legs appear alongside existing
# ────────────────────────────────────────────────────────────────────────
def test_05_update_add_receipt(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 1000.0),
    ])
    assert len(_legs(ctx, t["id"])) == 2
    doc = ctx.d.trips.find_one({"id": t["id"]}, {"_id": 0})
    doc["customer_receipts"] = list(doc.get("customer_receipts") or []) + [
        _receipt("r2", 2000.0, mode="Cash", rtype="diesel"),
    ]
    ctx.update_trip(t["id"], doc)
    legs = _legs(ctx, t["id"])
    assert len(legs) == 4
    assert {l["source_id"] for l in legs} == {
        f"{t['id']}:r1", f"{t['id']}:r2"}


# ────────────────────────────────────────────────────────────────────────
# 6. UPDATE — remove a receipt → obsolete {tid}:{rid} legs disappear
#    (this is the case the A-1 cascade amendment unlocked)
# ────────────────────────────────────────────────────────────────────────
def test_06_update_remove_receipt(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 1000.0),
        _receipt("r2", 2000.0),
    ])
    assert len(_legs(ctx, t["id"])) == 4
    doc = ctx.d.trips.find_one({"id": t["id"]}, {"_id": 0})
    # Remove r1, keep r2.
    doc["customer_receipts"] = [_receipt("r2", 2000.0)]
    ctx.update_trip(t["id"], doc)
    legs = _legs(ctx, t["id"])
    assert len(legs) == 2
    assert {l["source_id"] for l in legs} == {f"{t['id']}:r2"}
    # r1 legs must be gone.
    assert ctx.d.fin_txn.count_documents({
        "user_id": ctx.uid, "source_type": "trip_customer_receipt",
        "source_id": f"{t['id']}:r1"}) == 0


# ────────────────────────────────────────────────────────────────────────
# 7. UPDATE — change amount on existing receipt → legs refresh
# ────────────────────────────────────────────────────────────────────────
def test_07_update_change_amount(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 1000.0),
    ])
    doc = ctx.d.trips.find_one({"id": t["id"]}, {"_id": 0})
    doc["customer_receipts"] = [_receipt("r1", 4444.44)]
    ctx.update_trip(t["id"], doc)
    legs = _legs(ctx, t["id"])
    assert len(legs) == 2
    assert all(l["amount"] == 4444.44 for l in legs)
    assert all(l["source_id"] == f"{t['id']}:r1" for l in legs)


# ────────────────────────────────────────────────────────────────────────
# 8. UPDATE — change receipt id → old legs vanish, new legs appear
# ────────────────────────────────────────────────────────────────────────
def test_08_update_change_receipt_id(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("old_id", 1200.0),
    ])
    doc = ctx.d.trips.find_one({"id": t["id"]}, {"_id": 0})
    doc["customer_receipts"] = [_receipt("new_id", 1200.0)]
    ctx.update_trip(t["id"], doc)
    src_ids = {l["source_id"] for l in _legs(ctx, t["id"])}
    assert src_ids == {f"{t['id']}:new_id"}
    assert ctx.d.fin_txn.count_documents({
        "user_id": ctx.uid, "source_id": f"{t['id']}:old_id"}) == 0


# ────────────────────────────────────────────────────────────────────────
# 9. UPDATE — reorder receipts with stable ids → no duplication
# ────────────────────────────────────────────────────────────────────────
def test_09_reorder_stable_ids(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("a", 100.0),
        _receipt("b", 200.0),
        _receipt("c", 300.0),
    ])
    refs_before = sorted(l["ref_source_key"] for l in _legs(ctx, t["id"]))
    doc = ctx.d.trips.find_one({"id": t["id"]}, {"_id": 0})
    doc["customer_receipts"] = [
        _receipt("c", 300.0), _receipt("a", 100.0), _receipt("b", 200.0),
    ]
    ctx.update_trip(t["id"], doc)
    refs_after = sorted(l["ref_source_key"] for l in _legs(ctx, t["id"]))
    assert refs_before == refs_after
    assert len(refs_after) == 6


# ────────────────────────────────────────────────────────────────────────
# 10. LEGACY receipt without explicit id → idxN fallback (A-1 UAT-fix #1)
# ────────────────────────────────────────────────────────────────────────
def test_10_legacy_receipt_no_id(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    # Send receipts WITHOUT `id` — legacy Iter39/40 shape.
    payload = ctx._trip_payload(cust, vid, vnum, receipts=[
        {"date": "2026-06-02", "type": "advance", "mode": "Bank",
         "amount": 700.0},
        {"date": "2026-06-02", "type": "diesel", "mode": "Cash",
         "amount": 300.0},
    ])
    r = requests.post(f"{API}/trips", headers=HJSON, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    t = r.json()
    ctx._trips.append(t["id"])
    src_ids = sorted({l["source_id"] for l in _legs(ctx, t["id"])})
    assert src_ids == [f"{t['id']}:idx0", f"{t['id']}:idx1"]


# ────────────────────────────────────────────────────────────────────────
# 11. TRIP DELETE — all customer_receipt legs disappear
# ────────────────────────────────────────────────────────────────────────
def test_11_trip_delete_clears_all_legs(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 500.0),
        _receipt("r2", 700.0),
    ])
    assert len(_legs(ctx, t["id"])) == 4
    r = requests.delete(f"{API}/trips/{t['id']}", headers=H,
                        params={"reason": "phase5 test delete"}, timeout=15)
    assert r.status_code == 200
    assert _legs(ctx, t["id"]) == []


# ────────────────────────────────────────────────────────────────────────
# 12. TRIP DELETE + Phase-3B bridge — receipt legs AND canonical expense
#     legs both clear correctly (no cross-interference).
# ────────────────────────────────────────────────────────────────────────
def test_12_trip_delete_with_bridge(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    # Payload includes both customer_receipts (Phase-5) AND legacy expenses
    # (Phase-3B-ii-a canonical materialisation).
    payload = ctx._trip_payload(cust, vid, vnum, receipts=[
        _receipt("r1", 1500.0),
    ])
    payload["expenses"] = {"diesel": 900.0, "toll": 200.0, "batta": 0,
                            "repair": 0, "other": 0}
    r = requests.post(f"{API}/trips", headers=HJSON, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    t = r.json()
    ctx._trips.append(t["id"])
    # Confirm both bridges wrote something.
    assert len(_legs(ctx, t["id"])) == 2
    exp_legs = ctx.d.fin_txn.count_documents({
        "user_id": ctx.uid, "source_type": "expense",
        "trip_id": t["id"], "status": "active"})
    assert exp_legs > 0
    # Delete the trip.
    r = requests.delete(f"{API}/trips/{t['id']}", headers=H,
                        params={"reason": "p5 combined"}, timeout=15)
    assert r.status_code == 200
    # Customer-receipt legs gone.
    assert _legs(ctx, t["id"]) == []
    # Bridge expenses soft-deleted → their fin_txn legs gone.
    exp_legs_after = ctx.d.fin_txn.count_documents({
        "user_id": ctx.uid, "source_type": "expense",
        "trip_id": t["id"], "status": "active"})
    assert exp_legs_after == 0


# ────────────────────────────────────────────────────────────────────────
# 13. IDEMPOTENCY — repeated hook execution creates zero duplicates
# ────────────────────────────────────────────────────────────────────────
def test_13_idempotency(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 800.0), _receipt("r2", 1200.0),
    ])
    import services_fin_txn_hooks as hooks
    refs_before = sorted(l["ref_source_key"] for l in _legs(ctx, t["id"]))
    for _ in range(3):
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "trip_customer_receipt", t["id"]))
    refs_after = sorted(l["ref_source_key"] for l in _legs(ctx, t["id"]))
    assert refs_before == refs_after
    assert len(refs_after) == 4


# ────────────────────────────────────────────────────────────────────────
# 14. FAILURE QUEUE — forced projection failure enqueues a pending row
# ────────────────────────────────────────────────────────────────────────
def test_14_failure_queue(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[_receipt("r1", 111.0)])
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("phase5-forced-failure")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "trip_customer_receipt", t["id"]))
        row = ctx.d.fin_hook_failures.find_one({
            "user_id": ctx.uid,
            "source_type": "trip_customer_receipt",
            "source_id": t["id"]}, sort=[("created_at", -1)])
        assert row and row["status"] == "pending"
        assert "phase5-forced-failure" in row["error"]
    finally:
        hooks.reproject_source = orig


# ────────────────────────────────────────────────────────────────────────
# 15. REPLAY — subprocess CLI drains the queue and restores projection
# ────────────────────────────────────────────────────────────────────────
def test_15_replay_restores(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[_receipt("r1", 222.0)])
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("phase5-replay-forced")

    # Force failure first
    hooks.reproject_source = _boom
    try:
        # Clear existing OK legs then trigger a failing reproject via update.
        ctx.d.fin_txn.delete_many({
            "user_id": ctx.uid, "source_type": "trip_customer_receipt",
            "trip_id": t["id"]})
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "trip_customer_receipt", t["id"]))
    finally:
        hooks.reproject_source = orig
    row = ctx.d.fin_hook_failures.find_one({
        "user_id": ctx.uid, "source_type": "trip_customer_receipt",
        "source_id": t["id"]}, sort=[("created_at", -1)])
    assert row and row["status"] == "pending"
    # Now replay via CLI — should reproject cleanly.
    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=45)
    assert res.returncode == 0, res.stderr
    row_after = ctx.d.fin_hook_failures.find_one({
        "user_id": ctx.uid, "source_type": "trip_customer_receipt",
        "source_id": t["id"]}, sort=[("created_at", -1)])
    assert row_after["status"] == "resolved"
    assert len(_legs(ctx, t["id"])) == 2


# ────────────────────────────────────────────────────────────────────────
# 16. TENANT ISOLATION — other tenant sources are never touched
# ────────────────────────────────────────────────────────────────────────
def test_16_tenant_isolation(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[_receipt("r1", 100.0)])
    # Insert a stray trip in another tenant + a stray receipt leg.
    stray_tid = f"trip_iso_{ctx.tag}"
    ctx.d.trips.insert_one({
        "id": stray_tid, "user_id": ctx._iso_uid,
        "company_id": ctx._iso_cid, "customer_id": "cust_iso",
        "date": "2026-06-01", "vehicle_number": "ISO",
        "customer_receipts": [{"id": "r1", "amount": 999.0, "mode": "Bank",
                                "type": "advance", "date": "2026-06-01"}],
        "is_historical": False,
    })
    ctx._iso_trips.append(stray_tid)
    ctx.d.fin_txn.insert_one({
        "id": f"fintxn_iso_p5_{ctx.tag}",
        "user_id": ctx._iso_uid, "company_id": ctx._iso_cid,
        "txn_date": "2026-06-01",
        "account_id": "acc_iso_bank", "account_code": "BANK_DEFAULT",
        "direction": "in", "amount": 999.0,
        "counter_account_code": "CUSTOMER_ADVANCE",
        "counter_account_id": "acc_iso_ca",
        "txn_type": "trip_customer_advance_receipt",
        "source_type": "trip_customer_receipt",
        "source_id": f"{stray_tid}:r1", "source_key": "",
        "ref_source_key": f"trip_customer_receipt:{stray_tid}:r1:bank_debit",
        "party_type": "customer", "party_id": "cust_iso", "party_name": "",
        "vehicle_id": "", "trip_id": stray_tid, "category": "advance",
        "narration": "iso", "transfer_group_id": "", "adjustment_group_id": "",
        "reversal_of": "", "is_reversal": False, "status": "active",
        "is_supplier_settlement_recovery": False,
        "reconciled_at": "", "reconciled_ref": "",
        "created_at": "2026-06-01T00:00:00", "projected_at": "2026-06-01T00:00:00",
    })
    # Delete OUR trip.
    r = requests.delete(f"{API}/trips/{t['id']}", headers=H,
                        params={"reason": "iso test"}, timeout=15)
    assert r.status_code == 200
    # Our legs gone.
    assert _legs(ctx, t["id"]) == []
    # Foreign-tenant leg untouched.
    stray = ctx.d.fin_txn.find_one({
        "user_id": ctx._iso_uid, "source_id": f"{stray_tid}:r1"})
    assert stray and stray["status"] == "active"


# ────────────────────────────────────────────────────────────────────────
# 17. DAY BOOK — receipt legs surface in /fin/day-book on the receipt date
# ────────────────────────────────────────────────────────────────────────
def test_17_day_book_reflects(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 640.0, mode="Bank", rtype="advance",
                 date="2026-06-20"),
    ], date="2026-06-20")
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-06-20",
                             "date_to": "2026-06-20",
                             "source_type": "trip_customer_receipt"},
                     timeout=15)
    assert r.status_code == 200
    ids = {row.get("source_id") for row in r.json().get("rows", [])}
    assert f"{t['id']}:r1" in ids


# ────────────────────────────────────────────────────────────────────────
# 18. ACCOUNTS — CUSTOMER_ADVANCE net delta matches receipt total
# ────────────────────────────────────────────────────────────────────────
def test_18_customer_advance_delta(ctx):
    def net(code):
        pipe = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                             "account_code": code, "status": "active"}},
                {"$group": {"_id": "$direction",
                             "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(pipe)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    ca0 = net("CUSTOMER_ADVANCE")
    ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 1234.0, mode="Bank"),
    ])
    ca1 = net("CUSTOMER_ADVANCE")
    # CUSTOMER_ADVANCE credit → net decreases by 1234.
    assert round(ca0 - ca1, 2) == 1234.0


# ────────────────────────────────────────────────────────────────────────
# 19. BULK DELETE — receipt legs cleared for every deleted trip
# ────────────────────────────────────────────────────────────────────────
def test_19_bulk_delete_clears(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    t1 = ctx.create_trip(cust, vid, vnum, receipts=[_receipt("r1", 100.0)])
    t2 = ctx.create_trip(cust, vid, vnum, receipts=[_receipt("r1", 200.0)])
    t3 = ctx.create_trip(cust, vid, vnum, receipts=[])  # empty on purpose
    assert len(_legs(ctx, t1["id"])) == 2
    assert len(_legs(ctx, t2["id"])) == 2
    r = requests.post(f"{API}/trips/bulk-delete", headers=HJSON, json={
        "trip_ids": [t1["id"], t2["id"], t3["id"]],
        "reason": "phase5 bulk", "force_invoiced": False,
    }, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["deleted_count"] == 3
    for tid in (t1["id"], t2["id"], t3["id"]):
        assert _legs(ctx, tid) == []


# ────────────────────────────────────────────────────────────────────────
# 20. DUPLICATE — cloned trip has its OWN projection under the new tid
# ────────────────────────────────────────────────────────────────────────
def test_20_duplicate_projects_new_tid(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    src = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 400.0),
    ])
    r = requests.post(f"{API}/trips/{src['id']}/duplicate", headers=H,
                      timeout=15)
    assert r.status_code == 200, r.text
    dup = r.json()
    ctx._trips.append(dup["id"])
    # Original still projected.
    assert len(_legs(ctx, src["id"])) == 2
    # Duplicate is a NEW trip_id — receipts are inherited by duplicate_trip
    # (no reset), so a fresh projection must live under the duplicate tid.
    dup_legs = _legs(ctx, dup["id"])
    assert len(dup_legs) == 2
    # source_ids reference the DUPLICATE trip, not the source.
    assert all(l["source_id"].startswith(f"{dup['id']}:")
               for l in dup_legs)


# ────────────────────────────────────────────────────────────────────────
# 21. QUICK REPEAT — same guarantee as duplicate
# ────────────────────────────────────────────────────────────────────────
def test_21_quick_repeat_projects_new_tid(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    src = ctx.create_trip(cust, vid, vnum, receipts=[
        _receipt("r1", 550.0),
    ])
    r = requests.post(f"{API}/trips/quick-repeat/{src['id']}",
                      headers=H, timeout=15)
    assert r.status_code == 200, r.text
    rep = r.json()
    ctx._trips.append(rep["id"])
    assert len(_legs(ctx, src["id"])) == 2
    rep_legs = _legs(ctx, rep["id"])
    assert len(rep_legs) == 2
    assert all(l["source_id"].startswith(f"{rep['id']}:")
               for l in rep_legs)


# ────────────────────────────────────────────────────────────────────────
# 22. ZERO DIRECT fin_txn WRITES in routers/trips.py
# ────────────────────────────────────────────────────────────────────────
def test_22_zero_direct_fin_txn():
    src = Path("/app/backend/routers/trips.py").read_text()
    for tok in ("db.fin_txn", "fin_txn.insert", "fin_txn.update",
                "fin_txn.delete"):
        assert tok not in src, f"forbidden token {tok!r} present in trips.py"


# ────────────────────────────────────────────────────────────────────────
# 23. HOOK COUNT — 6 sites + 1 import = 7 refs total
# ────────────────────────────────────────────────────────────────────────
def test_23_hook_count():
    src = Path("/app/backend/routers/trips.py").read_text()
    assert src.count("hook_after_source_write") == 7


# ────────────────────────────────────────────────────────────────────────
# 24. A-1 IMMUTABILITY — source_type frozen; the ONLY authorized amendment
#     is the trip_customer_receipt cascade line before the exact-match
#     delete. project_trip_customer_receipts, source_id format
#     ({tid}:{rid}), and SUPPORTED_SOURCE_TYPES are unchanged.
# ────────────────────────────────────────────────────────────────────────
def test_24_a1_immutability():
    import services_fin_txn as a1
    assert "trip_customer_receipt" in a1.SUPPORTED_SOURCE_TYPES
    src = Path("/app/backend/services_fin_txn.py").read_text()
    # Cascade pattern for trip_customer_receipt present.
    assert (
        'await _delete_by_source(\n'
        '                uid, cid, "trip_customer_receipt", f"{source_id}:*")'
    ) in src
    # project_trip_customer_receipts still emits {tid}:{rid} source_id.
    assert 'source_id=f"{trip_id}:{rid}"' in src


# ────────────────────────────────────────────────────────────────────────
# 25. PHASE-3B-ii-a / 3B-ii-b COMPATIBILITY — Trip UPDATE that also
#     changes legacy expenses fires BOTH the expense-bridge hooks
#     (Phase-3B-ii-a) AND the customer_receipt hook (Phase 5).
# ────────────────────────────────────────────────────────────────────────
def test_25_phase3b_compat_on_update(ctx):
    cust = ctx.make_customer()
    vid, vnum = ctx.make_vehicle()
    payload = ctx._trip_payload(cust, vid, vnum, receipts=[
        _receipt("r1", 300.0),
    ])
    payload["expenses"] = {"diesel": 500.0, "toll": 0, "batta": 0,
                            "repair": 0, "other": 0}
    r = requests.post(f"{API}/trips", headers=HJSON, json=payload, timeout=15)
    assert r.status_code == 200
    t = r.json()
    ctx._trips.append(t["id"])
    # Both projections exist.
    assert len(_legs(ctx, t["id"])) == 2
    exp_before = ctx.d.fin_txn.count_documents({
        "user_id": ctx.uid, "source_type": "expense",
        "trip_id": t["id"], "status": "active"})
    assert exp_before > 0
    # Update: change diesel + change receipt amount.
    doc = ctx.d.trips.find_one({"id": t["id"]}, {"_id": 0})
    doc["expenses"]["diesel"] = 700.0
    doc["customer_receipts"] = [_receipt("r1", 400.0)]
    ctx.update_trip(t["id"], doc)
    # Receipt projection refreshed.
    legs = _legs(ctx, t["id"])
    assert all(l["amount"] == 400.0 for l in legs) and len(legs) == 2
    # Expense projection still healthy (Phase-3B-ii-a hook fired via
    # sync_trip_expenses_to_canonical inside update_trip).
    exp_after = ctx.d.fin_txn.count_documents({
        "user_id": ctx.uid, "source_type": "expense",
        "trip_id": t["id"], "status": "active"})
    assert exp_after > 0


# ────────────────────────────────────────────────────────────────────────
# 26. LOCKED-BAND FORBIDDEN CONSTRUCTS — no async schedulers, locks or
#     dedupe caches added to trips.py by Phase 5.
# ────────────────────────────────────────────────────────────────────────
def test_26_locked_band_forbidden():
    src = Path("/app/backend/routers/trips.py").read_text()
    for tok in ("asyncio.create_task", "APScheduler", "expire_after",
                "cachetools", "lru_cache", "threading.Lock", "asyncio.Lock"):
        assert tok not in src, f"forbidden token: {tok}"
