"""Iter150A-2 · Phase 4 — VendorBill hooks (3 mutation sites)."""
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

_LOOP = _asyncio.new_event_loop()
_asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _demo():
    d = _db()
    me = d.users.find_one({"email": "demo@bitumen-transport.local"},
                          {"_id": 0, "user_id": 1})
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False}, timeout=15)
    return me["user_id"], r.json()[0]["company_id"]


class _Ctx:
    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo()
        self.tag = uuid.uuid4().hex[:10]
        self._veh: list[str] = []
        self._ven: list[str] = []
        self._bills: list[str] = []
        self._exp: list[str] = []

    def make_vehicle(self):
        vnum = f"P4V{self.tag[:3].upper()}{len(self._veh):02d}"
        r = requests.post(f"{API}/vehicles", headers=HJSON, json={
            "vehicle_number": vnum, "vehicle_type": "own", "is_active": True,
        }, timeout=15)
        v = r.json(); self._veh.append(v["id"]); return v["id"], v["vehicle_number"]

    def make_vendor(self):
        r = requests.post(f"{API}/vendors", headers=HJSON, json={
            "name": f"Vendor-P4-{self.tag}", "is_active": True,
        }, timeout=15)
        v = r.json(); self._ven.append(v["id"]); return v["id"]

    def make_bill(self, vendor_id, vehicle_id, vnum, amount=1000.0,
                  bill_number="", bill_date="2026-05-01"):
        payload = {
            "vendor_id": vendor_id, "vehicle_id": vehicle_id,
            "vehicle_number": vnum, "bill_amount": amount,
            "bill_date": bill_date, "bill_number": bill_number,
            "description": "phase4 test", "file_ids": [],
        }
        r = requests.post(f"{API}/vendor-bills", headers=HJSON, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        b = r.json(); self._bills.append(b["id"]); return b

    def seed_paired_expense(self, vendor_id, vehicle_id, vnum, bill_id, amount):
        """Directly insert a linked Expense to simulate the paired-Expense path."""
        eid = f"exp_p4v_{uuid.uuid4().hex[:8]}"
        self.d.expenses.insert_one({
            "id": eid, "user_id": self.uid, "company_id": self.cid,
            "date": "2026-05-01", "category": "Repair", "amount": float(amount),
            "narration": "paired-bill", "remarks": "",
            "vehicle_id": vehicle_id, "vehicle_number": vnum, "trip_id": "",
            "repair_event_id": "", "party_type": "vendor",
            "party_id": vendor_id, "party_name": "",
            "vendor_bill_id": bill_id, "mechanic_work_order_id": "",
            "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
            "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
            "file_ids": [], "source_type": "vendor_bill",
            "source_key": f"vendor_bill:{bill_id}",
            "source_trip_id": "",
            "created_at": "2026-05-01T00:00:00+00:00", "created_by": self.uid,
            "is_deleted": False,
        })
        self._exp.append(eid); return eid

    def teardown(self):
        d = self.d
        if self._exp:
            d.expenses.delete_many({"id": {"$in": self._exp}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                    "source_id": {"$in": self._exp}})
        if self._bills:
            d.vendor_bills.delete_many({"id": {"$in": self._bills}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                    "source_id": {"$in": self._bills}})
            d.fin_hook_failures.delete_many(
                {"user_id": self.uid, "source_id": {"$in": self._bills}})
        if self._ven: d.vendors.delete_many({"id": {"$in": self._ven}})
        if self._veh: d.vehicles.delete_many({"id": {"$in": self._veh}})


@pytest.fixture
def ctx():
    c = _Ctx(); yield c; c.teardown()


def _legs(ctx, bid):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "vendor_bill",
         "source_id": bid, "status": "active"},
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1,
         "ref_source_key": 1, "txn_type": 1}))


# ── 1. Unpaired CREATE projects 2 orphan legs (SUSPENSE + AP_VENDOR)
def test_01_unpaired_create_projects_orphan(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=1500.0)
    legs = _legs(ctx, b["id"])
    assert len(legs) == 2
    codes = sorted(l["account_code"] for l in legs)
    assert codes == ["AP_VENDOR", "SUSPENSE"]
    assert all(l["txn_type"] == "vendor_bill_orphan" for l in legs)


# ── 2. Paired-Expense CREATE → 0 orphan legs on VendorBill
def test_02_paired_create_zero_legs(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=800.0)
    ctx.seed_paired_expense(ven, vid, vnum, b["id"], 800.0)
    # Re-fire the hook — should now emit 0 legs (paired guard).
    import services_fin_txn_hooks as hooks
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "vendor_bill", b["id"]))
    assert _legs(ctx, b["id"]) == []


# ── 3. UPDATE amount refreshes leg amounts
def test_03_update_amount_refreshes(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=500.0)
    assert _legs(ctx, b["id"])[0]["amount"] == 500.0
    payload = {**b, "bill_amount": 750.0, "file_ids": []}
    payload.pop("_id", None)
    r = requests.put(f"{API}/vendor-bills/{b['id']}", headers=HJSON,
                     json=payload, timeout=15)
    assert r.status_code == 200
    legs = _legs(ctx, b["id"])
    assert all(l["amount"] == 750.0 for l in legs)


# ── 4. SOFT-DELETE clears legs
def test_04_soft_delete_clears(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=999.0)
    assert len(_legs(ctx, b["id"])) == 2
    r = requests.delete(f"{API}/vendor-bills/{b['id']}", headers=H,
                        params={"reason": "phase4 test delete"}, timeout=15)
    assert r.status_code == 200
    assert _legs(ctx, b["id"]) == []


# ── 5. DELETE blocked when live paired Expense exists
def test_05_delete_blocked_by_paired_expense(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=333.0)
    ctx.seed_paired_expense(ven, vid, vnum, b["id"], 333.0)
    r = requests.delete(f"{API}/vendor-bills/{b['id']}", headers=H,
                        params={"reason": "should-be-blocked"}, timeout=15)
    assert r.status_code == 400
    assert "expenses" in r.text.lower() or "payments" in r.text.lower()


# ── 6. Duplicate bill_number rejected
def test_06_duplicate_bill_number(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    bn = f"BN-P4V-{ctx.tag}"
    ctx.make_bill(ven, vid, vnum, amount=100.0, bill_number=bn)
    r = requests.post(f"{API}/vendor-bills", headers=HJSON, json={
        "vendor_id": ven, "vehicle_id": vid, "vehicle_number": vnum,
        "bill_amount": 200.0, "bill_date": "2026-05-01",
        "bill_number": bn, "file_ids": [], "description": "",
    }, timeout=15)
    assert r.status_code == 409


# ── 7. Idempotent hook
def test_07_idempotency(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=1100.0)
    refs_before = sorted(l["ref_source_key"] for l in _legs(ctx, b["id"]))
    import services_fin_txn_hooks as hooks
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "vendor_bill", b["id"]))
    refs_after = sorted(l["ref_source_key"] for l in _legs(ctx, b["id"]))
    assert refs_before == refs_after and len(refs_before) == 2


# ── 8. Failure queue
def test_08_failure_queue(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=250.0)
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("p4-vb-forced")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "vendor_bill", b["id"]))
        row = ctx.d.fin_hook_failures.find_one(
            {"user_id": ctx.uid, "source_id": b["id"]}, sort=[("created_at", -1)])
        assert row and row["status"] == "pending"
    finally:
        hooks.reproject_source = orig


# ── 9. Replay resolves
def test_09_replay(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=175.0)
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("p4-vb-replay")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "vendor_bill", b["id"]))
    finally:
        hooks.reproject_source = orig
    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": b["id"]}, sort=[("created_at", -1)])
    assert row["status"] == "resolved"


# ── 10. Tenant isolation
def test_10_tenant_isolation(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=100.0)
    stray_id = f"vb_p4iso_{ctx.tag}"
    ctx.d.vendor_bills.insert_one({
        "id": stray_id, "user_id": f"other_p4v_{ctx.tag}",
        "company_id": "co_p4viso", "vendor_id": ven,
        "bill_amount": 999.0, "bill_date": "2026-05-01",
        "is_deleted": False,
    })
    try:
        r = requests.delete(f"{API}/vendor-bills/{b['id']}", headers=H,
                            params={"reason": "isolation test"}, timeout=15)
        assert r.status_code == 200
        stray = ctx.d.vendor_bills.find_one({"id": stray_id})
        assert stray and not stray.get("is_deleted")
    finally:
        ctx.d.vendor_bills.delete_one({"id": stray_id})


# ── 11. Source identity invariant on update
def test_11_source_identity(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=100.0)
    refs = sorted(l["ref_source_key"] for l in _legs(ctx, b["id"]))
    # Update bill_date
    payload = {**b, "bill_date": "2026-05-15", "file_ids": []}
    payload.pop("_id", None)
    requests.put(f"{API}/vendor-bills/{b['id']}", headers=HJSON,
                 json=payload, timeout=15)
    refs_after = sorted(l["ref_source_key"] for l in _legs(ctx, b["id"]))
    assert refs == refs_after  # deterministic identity by bill.id, not date


# ── 12. Day Book reflects orphan bill
def test_12_day_book_reflects(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=444.0, bill_date="2026-05-20")
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-05-01",
                             "date_to": "2026-05-31"}, timeout=15)
    ids = {row.get("source_id") for row in r.json().get("rows", [])}
    assert b["id"] in ids


# ── 13. Accounts: AP_VENDOR net delta = orphan bill amount
def test_13_ap_vendor_delta(ctx):
    def bal(code):
        pipe = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                             "account_code": code, "status": "active"}},
                {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(pipe)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    ap0 = bal("AP_VENDOR")
    ctx.make_bill(ven, vid, vnum, amount=222.0)
    ap1 = bal("AP_VENDOR")
    # Orphan projection: AP_VENDOR credit → net -222
    assert round(ap0 - ap1, 2) == 222.0


# ── 14. Paired-flag cross-reproject when Expense unlinks (via linkage helper)
def test_14_paired_flag_cross_reproject(ctx):
    vid, vnum = ctx.make_vehicle(); ven = ctx.make_vendor()
    b = ctx.make_bill(ven, vid, vnum, amount=500.0)
    eid = ctx.seed_paired_expense(ven, vid, vnum, b["id"], 500.0)
    import services_fin_txn_hooks as hooks
    from services_expense_linkage_hooks import refresh_linked_paired_sources
    # Simulate Expense unlink: before had vendor_bill_id=b, after empty.
    before = {"id": eid, "vendor_bill_id": b["id"], "is_deleted": False, "is_reversed": False}
    after  = {"id": eid, "vendor_bill_id": "",       "is_deleted": False, "is_reversed": False}
    # Re-hook parent to establish 0-leg state first.
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "vendor_bill", b["id"]))
    # Manually clear the paired expense to simulate unlink actually applied.
    ctx.d.expenses.delete_one({"id": eid})
    _run(refresh_linked_paired_sources(ctx.uid, ctx.cid, before, after))
    # Now VendorBill should be orphan → 2 legs.
    legs = _legs(ctx, b["id"])
    assert len(legs) == 2


# ── 15. Zero direct fin_txn writes
def test_15_zero_direct_fin_txn():
    src = Path("/app/backend/routers/vendor_bills.py").read_text()
    for tok in ("db.fin_txn", "fin_txn.insert", "fin_txn.update", "fin_txn.delete"):
        assert tok not in src


# ── 16. Hook count = 3 sites + 1 import = 4
def test_16_hook_count():
    src = Path("/app/backend/routers/vendor_bills.py").read_text()
    assert src.count("hook_after_source_write") == 4


# ── 17. A-1 immutability
def test_17_a1_immutability():
    import services_fin_txn as a1
    assert "vendor_bill" in a1.SUPPORTED_SOURCE_TYPES
    # project_vendor_bill still short-circuits on is_deleted (verified by test #4)


# ── 18. Locked-band forbidden constructs
def test_18_locked_band():
    src = Path("/app/backend/routers/vendor_bills.py").read_text()
    for tok in ("asyncio.create_task", "APScheduler", "expire_after",
                "cachetools", "lru_cache", "threading.Lock", "asyncio.Lock"):
        assert tok not in src
