"""Iter150A-2 · Phase 4 — MechanicWorkOrder hooks (3 mutation sites)."""
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
        self._mec: list[str] = []
        self._wos: list[str] = []
        self._exp: list[str] = []

    def make_vehicle(self):
        vnum = f"P4M{self.tag[:3].upper()}{len(self._veh):02d}"
        r = requests.post(f"{API}/vehicles", headers=HJSON, json={
            "vehicle_number": vnum, "vehicle_type": "own", "is_active": True,
        }, timeout=15)
        v = r.json(); self._veh.append(v["id"]); return v["id"], v["vehicle_number"]

    def make_mechanic(self):
        r = requests.post(f"{API}/mechanics", headers=HJSON, json={
            "name": f"Mech-P4-{self.tag}", "is_active": True,
        }, timeout=15)
        m = r.json(); self._mec.append(m["id"]); return m["id"]

    def make_wo(self, mec_id, vid, vnum, amount=1000.0, work_date="2026-05-01"):
        payload = {
            "mechanic_id": mec_id, "vehicle_id": vid, "vehicle_number": vnum,
            "amount": amount, "work_date": work_date,
            "description": "phase4 wo test", "file_ids": [],
        }
        r = requests.post(f"{API}/mechanic-work-orders", headers=HJSON,
                          json=payload, timeout=15)
        assert r.status_code == 200, r.text
        w = r.json(); self._wos.append(w["id"]); return w

    def seed_paired_expense(self, mec_id, vid, vnum, wid, amount):
        eid = f"exp_p4m_{uuid.uuid4().hex[:8]}"
        self.d.expenses.insert_one({
            "id": eid, "user_id": self.uid, "company_id": self.cid,
            "date": "2026-05-01", "category": "Repair", "amount": float(amount),
            "narration": "paired-wo", "remarks": "",
            "vehicle_id": vid, "vehicle_number": vnum, "trip_id": "",
            "repair_event_id": "", "party_type": "mechanic",
            "party_id": mec_id, "party_name": "",
            "vendor_bill_id": "", "mechanic_work_order_id": wid,
            "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
            "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
            "file_ids": [], "source_type": "mechanic_work_order",
            "source_key": f"mechanic_work_order:{wid}",
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
        if self._wos:
            d.mechanic_work_orders.delete_many({"id": {"$in": self._wos}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                    "source_id": {"$in": self._wos}})
            d.fin_hook_failures.delete_many(
                {"user_id": self.uid, "source_id": {"$in": self._wos}})
        if self._mec: d.mechanics.delete_many({"id": {"$in": self._mec}})
        if self._veh: d.vehicles.delete_many({"id": {"$in": self._veh}})


@pytest.fixture
def ctx():
    c = _Ctx(); yield c; c.teardown()


def _legs(ctx, wid):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "mechanic_work_order",
         "source_id": wid, "status": "active"},
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1,
         "ref_source_key": 1, "txn_type": 1}))


# ── 1. Unpaired CREATE projects 2 orphan legs (SUSPENSE + AP_MECHANIC)
def test_01_unpaired_create_projects_orphan(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=1200.0)
    legs = _legs(ctx, w["id"])
    assert len(legs) == 2
    codes = sorted(l["account_code"] for l in legs)
    assert codes == ["AP_MECHANIC", "SUSPENSE"]
    assert all(l["txn_type"] == "mechanic_wo_orphan" for l in legs)


# ── 2. Paired-Expense CREATE → 0 orphan legs
def test_02_paired_create_zero_legs(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=600.0)
    ctx.seed_paired_expense(mec, vid, vnum, w["id"], 600.0)
    import services_fin_txn_hooks as hooks
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "mechanic_work_order", w["id"]))
    assert _legs(ctx, w["id"]) == []


# ── 3. UPDATE amount refreshes legs
def test_03_update_amount_refreshes(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=400.0)
    assert _legs(ctx, w["id"])[0]["amount"] == 400.0
    payload = {**w, "amount": 650.0, "file_ids": []}
    payload.pop("_id", None)
    r = requests.put(f"{API}/mechanic-work-orders/{w['id']}", headers=HJSON,
                     json=payload, timeout=15)
    assert r.status_code == 200
    assert all(l["amount"] == 650.0 for l in _legs(ctx, w["id"]))


# ── 4. SOFT-DELETE clears legs
def test_04_soft_delete_clears(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=333.0)
    assert len(_legs(ctx, w["id"])) == 2
    r = requests.delete(f"{API}/mechanic-work-orders/{w['id']}", headers=H,
                        params={"reason": "phase4 delete"}, timeout=15)
    assert r.status_code == 200
    assert _legs(ctx, w["id"]) == []


# ── 5. DELETE blocked when live paired Expense exists
def test_05_delete_blocked_by_paired_expense(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=444.0)
    ctx.seed_paired_expense(mec, vid, vnum, w["id"], 444.0)
    r = requests.delete(f"{API}/mechanic-work-orders/{w['id']}", headers=H,
                        params={"reason": "should-block"}, timeout=15)
    assert r.status_code == 400


# ── 6. Amount must be positive
def test_06_positive_amount_required(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    r = requests.post(f"{API}/mechanic-work-orders", headers=HJSON, json={
        "mechanic_id": mec, "vehicle_id": vid, "vehicle_number": vnum,
        "amount": 0, "work_date": "2026-05-01",
        "description": "", "file_ids": [],
    }, timeout=15)
    assert r.status_code == 400


# ── 7. Idempotent hook
def test_07_idempotency(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=770.0)
    refs = sorted(l["ref_source_key"] for l in _legs(ctx, w["id"]))
    import services_fin_txn_hooks as hooks
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "mechanic_work_order", w["id"]))
    refs_after = sorted(l["ref_source_key"] for l in _legs(ctx, w["id"]))
    assert refs == refs_after and len(refs) == 2


# ── 8. Failure queue
def test_08_failure_queue(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=125.0)
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("p4-wo-forced")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "mechanic_work_order", w["id"]))
        row = ctx.d.fin_hook_failures.find_one(
            {"user_id": ctx.uid, "source_id": w["id"]}, sort=[("created_at", -1)])
        assert row and row["status"] == "pending"
    finally:
        hooks.reproject_source = orig


# ── 9. Replay resolves
def test_09_replay(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=88.0)
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("p4-wo-replay")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "mechanic_work_order", w["id"]))
    finally:
        hooks.reproject_source = orig
    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": w["id"]}, sort=[("created_at", -1)])
    assert row["status"] == "resolved"


# ── 10. Tenant isolation
def test_10_tenant_isolation(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=100.0)
    stray_id = f"wo_p4iso_{ctx.tag}"
    ctx.d.mechanic_work_orders.insert_one({
        "id": stray_id, "user_id": f"other_p4m_{ctx.tag}",
        "company_id": "co_p4miso", "mechanic_id": mec,
        "amount": 999.0, "work_date": "2026-05-01",
        "is_deleted": False,
    })
    try:
        r = requests.delete(f"{API}/mechanic-work-orders/{w['id']}", headers=H,
                            params={"reason": "isolation test"}, timeout=15)
        assert r.status_code == 200
        stray = ctx.d.mechanic_work_orders.find_one({"id": stray_id})
        assert stray and not stray.get("is_deleted")
    finally:
        ctx.d.mechanic_work_orders.delete_one({"id": stray_id})


# ── 11. Source identity invariant
def test_11_source_identity(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=150.0)
    refs = sorted(l["ref_source_key"] for l in _legs(ctx, w["id"]))
    payload = {**w, "work_date": "2026-05-15", "file_ids": []}
    payload.pop("_id", None)
    requests.put(f"{API}/mechanic-work-orders/{w['id']}", headers=HJSON,
                 json=payload, timeout=15)
    refs_after = sorted(l["ref_source_key"] for l in _legs(ctx, w["id"]))
    assert refs == refs_after


# ── 12. Day Book reflects orphan WO
def test_12_day_book_reflects(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=205.0, work_date="2026-05-20")
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-05-01",
                             "date_to": "2026-05-31"}, timeout=15)
    ids = {row.get("source_id") for row in r.json().get("rows", [])}
    assert w["id"] in ids


# ── 13. Accounts: AP_MECHANIC delta = WO amount
def test_13_ap_mechanic_delta(ctx):
    def bal(code):
        pipe = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                             "account_code": code, "status": "active"}},
                {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(pipe)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    ap0 = bal("AP_MECHANIC")
    ctx.make_wo(mec, vid, vnum, amount=111.0)
    ap1 = bal("AP_MECHANIC")
    assert round(ap0 - ap1, 2) == 111.0


# ── 14. Cross-reproject on Expense unlink
def test_14_paired_flag_cross_reproject(ctx):
    vid, vnum = ctx.make_vehicle(); mec = ctx.make_mechanic()
    w = ctx.make_wo(mec, vid, vnum, amount=250.0)
    eid = ctx.seed_paired_expense(mec, vid, vnum, w["id"], 250.0)
    import services_fin_txn_hooks as hooks
    from services_expense_linkage_hooks import refresh_linked_paired_sources
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "mechanic_work_order", w["id"]))
    before = {"id": eid, "mechanic_work_order_id": w["id"], "is_deleted": False, "is_reversed": False}
    after  = {"id": eid, "mechanic_work_order_id": "",       "is_deleted": False, "is_reversed": False}
    ctx.d.expenses.delete_one({"id": eid})
    _run(refresh_linked_paired_sources(ctx.uid, ctx.cid, before, after))
    assert len(_legs(ctx, w["id"])) == 2


# ── 15. Zero direct fin_txn writes
def test_15_zero_direct_fin_txn():
    src = Path("/app/backend/routers/mechanic_work_orders.py").read_text()
    for tok in ("db.fin_txn", "fin_txn.insert", "fin_txn.update", "fin_txn.delete"):
        assert tok not in src


# ── 16. Hook count = 3 sites + 1 import = 4
def test_16_hook_count():
    src = Path("/app/backend/routers/mechanic_work_orders.py").read_text()
    assert src.count("hook_after_source_write") == 4


# ── 17. A-1 immutability
def test_17_a1_immutability():
    import services_fin_txn as a1
    assert "mechanic_work_order" in a1.SUPPORTED_SOURCE_TYPES


# ── 18. Locked-band forbidden constructs
def test_18_locked_band():
    src = Path("/app/backend/routers/mechanic_work_orders.py").read_text()
    for tok in ("asyncio.create_task", "APScheduler", "expire_after",
                "cachetools", "lru_cache", "threading.Lock", "asyncio.Lock"):
        assert tok not in src
