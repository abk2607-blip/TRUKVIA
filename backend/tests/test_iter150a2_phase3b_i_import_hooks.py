"""Iter150A-2 · Phase 3B-i — Bulk import service-level Expense hooks.

Covers the 3 service-level Expense INSERT funnels:
  * services_quick_expense.bulk_create_operational_expenses  (Q1)
  * services_fuel_import.commit_rows                          (F1)
  * services_toll_import.commit_rows                          (T1)

Scope constraints (per Phase 3B-i approval):
  * Hook fires ONLY on status="created". Never on duplicate / failed.
  * NO service hook for the Trip bridge (Phase 3B-ii).
  * NO VendorBill / MechanicWO primary hooks (Phase 4+).
  * Preserves Iter139 / Iter147 / Iter148 semantics exactly.
"""
from __future__ import annotations

import asyncio as _asyncio
import os
import time
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


def _demo():
    d = _db()
    me = d.users.find_one({"email": "demo@bitumen-transport.local"},
                          {"_id": 0, "user_id": 1})
    assert me
    uid = me["user_id"]
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False}, timeout=15)
    cid = r.json()[0]["company_id"]
    return uid, cid


class _Ctx:
    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo()
        self.tag = uuid.uuid4().hex[:10]
        self._expense_ids: list[str] = []
        self._vehicles: list[str] = []
        self._vendors: list[str] = []

    def make_vehicle(self, kind="own"):
        vnum = f"3BI{self.tag[:4].upper()}{len(self._vehicles):02d}"
        r = requests.post(f"{API}/vehicles", headers=HJSON, json={
            "vehicle_number": vnum, "vehicle_type": kind, "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        v = r.json()
        self._vehicles.append(v["id"])
        return v["id"], v["vehicle_number"]

    def make_vendor(self):
        r = requests.post(f"{API}/vendors", headers=HJSON, json={
            "name": f"3BI-V {self.tag}", "is_active": True}, timeout=15)
        assert r.status_code == 200
        vid = r.json()["id"]
        self._vendors.append(vid)
        return vid

    def track(self, eid: str):
        if eid:
            self._expense_ids.append(eid)

    def teardown(self):
        d = self.d
        if self._expense_ids:
            d.expenses.delete_many({"id": {"$in": self._expense_ids}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                   "source_id": {"$in": self._expense_ids}})
            d.fin_hook_failures.delete_many(
                {"user_id": self.uid, "source_id": {"$in": self._expense_ids}})
        if self._vendors:
            d.vendors.delete_many({"id": {"$in": self._vendors}})
        if self._vehicles:
            d.vehicles.delete_many({"id": {"$in": self._vehicles}})


@pytest.fixture
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


def _fin_legs(ctx: _Ctx, source_id: str):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "expense", "source_id": source_id},
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1,
         "ref_source_key": 1, "txn_date": 1},
    ))


# ── 1. Quick-Op Toll → hook fires, EXPENSE + CASH ───────────────────
def test_1_quick_op_toll(ctx):
    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
        "date": "2026-04-01", "category": "Toll", "trip_id": "",
        "entries": [{"client_row_id": f"qt-{ctx.tag}",
                     "vehicle_id": vid, "amount": 250}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    eid = r.json()["results"][0]["expense"]["id"]
    ctx.track(eid)
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    codes = {(l["account_code"], l["direction"], l["amount"]) for l in legs}
    assert codes == {("EXPENSE_DEFAULT", "in", 250.0),
                     ("CASH", "out", 250.0)}


# ── 2. Quick-Op Diesel → 2 legs, qty*rate authoritative ─────────────
def test_2_quick_op_diesel(ctx):
    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
        "date": "2026-04-01", "category": "Diesel", "trip_id": "",
        "entries": [{"client_row_id": f"qd-{ctx.tag}",
                     "vehicle_id": vid, "qty": 25, "rate": 100}],
    }, timeout=15)
    assert r.status_code == 200
    eid = r.json()["results"][0]["expense"]["id"]
    ctx.track(eid)
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    assert all(l["amount"] == 2500.0 for l in legs)


# ── 3. Quick-Op payable (supplier-owned + settlement adjustment) ─────
def test_3_quick_op_supplier_recovery(ctx):
    # Seed a Supplier master and link the vehicle to it (Iter47 gate).
    sr = requests.post(f"{API}/suppliers", headers=HJSON, json={
        "name": f"3BI-Sup {ctx.tag}", "is_active": True}, timeout=15)
    assert sr.status_code == 200, sr.text
    sup_id = sr.json()["id"]
    ctx.d.suppliers.update_one({"id": sup_id}, {"$set": {"_p3bi_cleanup": True}})
    vnum = f"3BIS{ctx.tag[:4].upper()}"
    vr = requests.post(f"{API}/vehicles", headers=HJSON, json={
        "vehicle_number": vnum, "vehicle_type": "supplier",
        "is_active": True, "supplier_id": sup_id,
        "supplier_name": f"3BI-Sup {ctx.tag}",
    }, timeout=15)
    assert vr.status_code == 200, vr.text
    vid = vr.json()["id"]
    ctx._vehicles.append(vid)
    try:
        r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
            "date": "2026-04-01", "category": "Batta", "trip_id": "",
            "entries": [{"client_row_id": f"qs-{ctx.tag}",
                         "vehicle_id": vid, "amount": 500,
                         "supplier_settlement_mode": "supplier_settlement_adjustment"}],
        }, timeout=15)
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["status"] == "created", res
        eid = res["expense"]["id"]
        ctx.track(eid)
        legs = _fin_legs(ctx, eid)
        assert len(legs) == 2
        codes = {(l["account_code"], l["direction"]) for l in legs}
        assert codes == {("EXPENSE_DEFAULT", "in"), ("AP_SUPPLIER", "out")}
    finally:
        ctx.d.suppliers.delete_one({"id": sup_id})


# ── 4. Quick-Op Diesel cash_now vendor Model A → NO AP_VENDOR ──────
def test_4_quick_op_cash_now_model_A(ctx):
    vid, _ = ctx.make_vehicle()
    ven = ctx.make_vendor()
    r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
        "date": "2026-04-01", "category": "Diesel", "trip_id": "",
        "entries": [{"client_row_id": f"qm-{ctx.tag}",
                     "vehicle_id": vid, "qty": 10, "rate": 95,
                     "vendor_id": ven}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    eid = r.json()["results"][0]["expense"]["id"]
    ctx.track(eid)
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    codes = {l["account_code"] for l in legs}
    assert codes == {"EXPENSE_DEFAULT", "CASH"}
    assert "AP_VENDOR" not in codes  # Model A protection

    # No VendorPayment created either.
    vpay = list(ctx.d.vendor_payments.find(
        {"user_id": ctx.uid, "company_id": ctx.cid, "vendor_id": ven},
        {"_id": 0, "id": 1}))
    assert vpay == []


# ── 5. Quick-Op duplicate source_key → no hook, no extra FinTxn ────
def test_5_quick_op_duplicate(ctx):
    vid, _ = ctx.make_vehicle()
    body = {
        "date": "2026-04-01", "category": "Parking", "trip_id": "",
        "entries": [{"client_row_id": f"dup-{ctx.tag}",
                     "vehicle_id": vid, "amount": 100}],
    }
    r1 = requests.post(f"{API}/expenses/bulk-operational",
                       headers=HJSON, json=body, timeout=15)
    assert r1.status_code == 200
    eid = r1.json()["results"][0]["expense"]["id"]
    ctx.track(eid)
    assert len(_fin_legs(ctx, eid)) == 2

    # Repeat submission → duplicate
    r2 = requests.post(f"{API}/expenses/bulk-operational",
                       headers=HJSON, json=body, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["results"][0]["status"] == "duplicate"
    # Still 2 legs — no extra projection.
    assert len(_fin_legs(ctx, eid)) == 2


# ── 6-8. Fleet-card Fuel Import → hook, dedup, source identity ──────
def _fleet_row(vid, tag, idx=1, litres=10.0, amount=800.0):
    return {
        "row_index": idx,
        "resolved_vehicle_id": vid,
        "date": "2026-04-01",
        "litres": litres,
        "rate": amount / litres,
        "amount": amount,
        "station_name": f"IOCL-{tag}",
        "source_txn_ref": f"FUEL-{tag}-{idx}",
        "odometer": 12000 + idx,
    }


def test_6_fuel_import_create(ctx):
    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl",
        "rows": [_fleet_row(vid, ctx.tag, 1, 20, 1800)],
    }, timeout=15)
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["status"] == "created"
    eid = res["expense_id"]
    ctx.track(eid)
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    assert all(l["amount"] == 1800.0 for l in legs)
    src = ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "source_type": 1,
                                                "source": 1, "source_txn_ref": 1})
    assert src["source_type"] == "fleet_card_import"
    assert src["source"] == "iocl"
    assert src["source_txn_ref"] == f"FUEL-{ctx.tag}-1"


def test_7_fuel_possible_dup_override_still_creates(ctx):
    vid, _ = ctx.make_vehicle()
    # First row creates canonical
    r1 = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl",
        "rows": [_fleet_row(vid, ctx.tag, 1, 20, 1800)],
    }, timeout=15)
    ctx.track(r1.json()["results"][0]["expense_id"])
    # Second row with different txn_ref but similar → operator override commits it
    r2 = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl",
        "rows": [_fleet_row(vid, ctx.tag, 2, 20, 1810)],
    }, timeout=15)
    res = r2.json()["results"][0]
    assert res["status"] == "created"
    eid2 = res["expense_id"]
    ctx.track(eid2)
    assert len(_fin_legs(ctx, eid2)) == 2


def test_8_fuel_exact_duplicate_no_hook(ctx):
    vid, _ = ctx.make_vehicle()
    row = _fleet_row(vid, ctx.tag, 1)
    r1 = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl", "rows": [row]}, timeout=15)
    eid = r1.json()["results"][0]["expense_id"]
    ctx.track(eid)
    n1 = len(_fin_legs(ctx, eid))

    # Same txn_ref → exact duplicate
    r2 = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl", "rows": [row]}, timeout=15)
    res = r2.json()["results"][0]
    assert res["status"] == "duplicate"
    # NO extra FinTxn.
    assert len(_fin_legs(ctx, eid)) == n1 == 2


# ── 9. Fleet-card vehicle correction still works after import hook ──
def test_9_fleet_card_vehicle_correction_compatibility(ctx):
    vid_a, _ = ctx.make_vehicle()
    vid_b, vnum_b = ctx.make_vehicle()
    r = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl",
        "rows": [_fleet_row(vid_a, ctx.tag, 1, 20, 1800)],
    }, timeout=15)
    eid = r.json()["results"][0]["expense_id"]
    ctx.track(eid)
    assert len(_fin_legs(ctx, eid)) == 2

    # Correct vehicle via Phase-3A router hook.
    r2 = requests.patch(f"{API}/expenses/{eid}/fleet-card-vehicle",
                        headers=HJSON, json={"vehicle_id": vid_b}, timeout=15)
    assert r2.status_code == 200
    legs = list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_id": eid},
        {"_id": 0, "vehicle_id": 1}))
    assert len(legs) == 2  # still 2 legs — no dup from double-hook
    assert all(l["vehicle_id"] == vid_b for l in legs)


# ── 10-13. FASTag Toll Import ────────────────────────────────────────
def _fastag_row(vid, tag, idx=1, amount=450.0):
    return {
        "row_index": idx,
        "resolved_vehicle_id": vid,
        "date": "2026-04-01",
        "amount": amount,
        "description": "FasTag Toll Payment at PLAZA-3BI",
        "plaza": "PLAZA-3BI",
        "source_txn_ref": f"FT-{tag}-{idx}",
    }


def test_10_fastag_create(ctx):
    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/toll-import/commit", headers=HJSON, json={
        "vendor": "idfc",
        "rows": [_fastag_row(vid, ctx.tag, 1, 275)],
    }, timeout=15)
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["status"] == "created"
    eid = res["expense_id"]
    ctx.track(eid)
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    assert all(l["amount"] == 275.0 for l in legs)
    src = ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "source_type": 1,
                                                "source": 1, "source_txn_ref": 1})
    assert src["source_type"] == "fastag_import"
    assert src["source"] == "idfc"


def test_11_fastag_possible_dup_override(ctx):
    vid, _ = ctx.make_vehicle()
    r1 = requests.post(f"{API}/toll-import/commit", headers=HJSON, json={
        "vendor": "livq",
        "rows": [_fastag_row(vid, ctx.tag, 1, 300)]}, timeout=15)
    ctx.track(r1.json()["results"][0]["expense_id"])
    # Different txn_ref same date/vehicle/amount → operator override commits
    r2 = requests.post(f"{API}/toll-import/commit", headers=HJSON, json={
        "vendor": "livq",
        "rows": [_fastag_row(vid, ctx.tag, 2, 300)]}, timeout=15)
    res = r2.json()["results"][0]
    assert res["status"] == "created"
    eid = res["expense_id"]
    ctx.track(eid)
    assert len(_fin_legs(ctx, eid)) == 2


def test_12_fastag_exact_duplicate_no_hook(ctx):
    vid, _ = ctx.make_vehicle()
    row = _fastag_row(vid, ctx.tag, 1, 400)
    r1 = requests.post(f"{API}/toll-import/commit", headers=HJSON, json={
        "vendor": "idfc", "rows": [row]}, timeout=15)
    eid = r1.json()["results"][0]["expense_id"]
    ctx.track(eid)
    n1 = len(_fin_legs(ctx, eid))
    r2 = requests.post(f"{API}/toll-import/commit", headers=HJSON, json={
        "vendor": "idfc", "rows": [row]}, timeout=15)
    assert r2.json()["results"][0]["status"] == "duplicate"
    assert len(_fin_legs(ctx, eid)) == n1 == 2


def test_13_fastag_import_anyway_single_hook(ctx):
    """Force the possible-dup override path — a second row with a
    unique source_txn_ref but similar amount/vehicle/date must be
    committed exactly once by the operator override."""
    vid, _ = ctx.make_vehicle()
    r1 = requests.post(f"{API}/toll-import/commit", headers=HJSON, json={
        "vendor": "idfc",
        "rows": [_fastag_row(vid, ctx.tag, 1, 500)]}, timeout=15)
    eid1 = r1.json()["results"][0]["expense_id"]
    ctx.track(eid1)
    r2 = requests.post(f"{API}/toll-import/commit", headers=HJSON, json={
        "vendor": "idfc",
        "rows": [_fastag_row(vid, ctx.tag, 999, 500)]}, timeout=15)
    eid2 = r2.json()["results"][0]["expense_id"]
    ctx.track(eid2)
    assert eid1 != eid2
    assert len(_fin_legs(ctx, eid1)) == 2
    assert len(_fin_legs(ctx, eid2)) == 2


# ── 14. Multi-row partial success — some created, some duplicate ────
def test_14_multi_row_partial_success(ctx):
    vid, _ = ctx.make_vehicle()
    # First commit 2 rows
    rows_a = [_fleet_row(vid, ctx.tag, 1, 10, 900),
              _fleet_row(vid, ctx.tag, 2, 15, 1300)]
    r1 = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl", "rows": rows_a}, timeout=15)
    for res in r1.json()["results"]:
        ctx.track(res.get("expense_id", ""))
    # Then commit 4 rows: 2 duplicates of the first batch + 2 new
    rows_b = rows_a + [_fleet_row(vid, ctx.tag, 3, 12, 1000),
                       _fleet_row(vid, ctx.tag, 4, 8, 700)]
    r2 = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl", "rows": rows_b}, timeout=15)
    body = r2.json()
    assert body["created"] == 2
    assert body["duplicate"] == 2
    for res in body["results"]:
        ctx.track(res.get("expense_id", ""))
    # Verify each unique source_key has exactly 2 legs.
    for res in body["results"]:
        if res.get("expense_id"):
            assert len(_fin_legs(ctx, res["expense_id"])) == 2


# ── 15. Forced hook failure in one row — other rows unaffected ──────
def test_15_forced_hook_failure_partial(ctx, monkeypatch):
    """Patch reproject_source to fail; source Expense still committed,
    partial-success contract preserved, failure row queued.
    Note: monkeypatch is process-local; the running backend uses its
    own reference — so we exercise the failure path via a direct
    hook call after the import completes."""
    import services_fin_txn_hooks as hooks

    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl",
        "rows": [_fleet_row(vid, ctx.tag, 1, 10, 800)],
    }, timeout=15)
    eid = r.json()["results"][0]["expense_id"]
    ctx.track(eid)

    orig = hooks.reproject_source
    _LOOP = _asyncio.new_event_loop(); _asyncio.set_event_loop(_LOOP)
    async def _boom(*a, **kw): raise RuntimeError("3bi-forced")
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

    # Source Expense untouched.
    src = ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "amount": 1})
    assert src["amount"] == 800.0


# ── 16. Replay resolves queued failure → legs projected ─────────────
def test_16_replay_resolves(ctx):
    import subprocess, sys as _sys
    vid, _ = ctx.make_vehicle()
    # Insert a fastag-import Expense directly and seed a pending failure.
    eid = f"exp_3bi_replay_{ctx.tag}"
    ctx.d.expenses.insert_one({
        "id": eid, "user_id": ctx.uid, "company_id": ctx.cid,
        "date": "2026-04-01", "category": "Toll", "amount": 210.0,
        "narration": "PLAZA-R", "remarks": f"Txn: R{ctx.tag}",
        "vehicle_id": vid, "vehicle_number": "",
        "trip_id": "", "repair_event_id": "",
        "party_type": "cash", "party_id": "", "party_name": "",
        "vendor_bill_id": "", "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
        "file_ids": [], "source_type": "fastag_import",
        "source_key": f"fastag:idfc:{ctx.cid}:R{ctx.tag}",
        "source": "idfc", "source_txn_ref": f"R{ctx.tag}",
        "source_trip_id": "",
        "created_at": "2026-04-01T00:00:00+00:00", "created_by": ctx.uid,
        "is_deleted": False,
    })
    ctx.track(eid)
    ctx.d.fin_hook_failures.insert_one({
        "id": f"hf_3bi_{ctx.tag}", "user_id": ctx.uid, "company_id": ctx.cid,
        "source_type": "expense", "source_id": eid,
        "action": "upsert", "error": "seeded-pending", "retry_count": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_attempt_at": "2026-01-01T00:00:00+00:00",
        "next_attempt_at": "1970-01-01T00:00:00+00:00",
        "status": "pending", "resolved_at": "", "history": [],
    })
    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": eid}, {"_id": 0})
    assert row["status"] == "resolved"
    assert len(_fin_legs(ctx, eid)) == 2


# ── 17. Idempotency: repeated /fin/reproject → still 2 legs ────────
def test_17_idempotency(ctx):
    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
        "date": "2026-04-01", "category": "Parking",
        "entries": [{"client_row_id": f"idem-{ctx.tag}",
                     "vehicle_id": vid, "amount": 60}],
    }, timeout=15)
    eid = r.json()["results"][0]["expense"]["id"]
    ctx.track(eid)
    assert len(_fin_legs(ctx, eid)) == 2
    for _ in range(3):
        requests.post(f"{API}/fin/reproject", headers=HJSON, json={
            "source_type": "expense", "source_id": eid}, timeout=15)
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    keys = sorted(l["ref_source_key"] for l in legs)
    assert all(k.startswith(f"expense:{eid}:") for k in keys)


# ── 18. Tenant isolation ────────────────────────────────────────────
def test_18_tenant_isolation(ctx):
    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
        "date": "2026-04-01", "category": "Parking",
        "entries": [{"client_row_id": f"iso-{ctx.tag}",
                     "vehicle_id": vid, "amount": 42}],
    }, timeout=15)
    eid = r.json()["results"][0]["expense"]["id"]
    ctx.track(eid)
    other_uid = f"user_iso3bi_{ctx.tag}"
    other_cid = f"co_iso3bi_{ctx.tag}"
    ctx.d.fin_accounts.insert_one({
        "id": f"acc_iso3bi_{ctx.tag}", "user_id": other_uid,
        "company_id": other_cid,
        "code": "EXPENSE_DEFAULT", "name": "iso", "type": "expense",
        "is_system": True, "is_active": True, "created_at": "2026-01-01",
    })
    ctx.d.fin_txn.insert_one({
        "id": f"fintxn_iso3bi_{ctx.tag}",
        "user_id": other_uid, "company_id": other_cid,
        "txn_date": "2026-04-01", "account_id": f"acc_iso3bi_{ctx.tag}",
        "account_code": "EXPENSE_DEFAULT", "direction": "in", "amount": 42.0,
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


# ── 19. Source identity preservation across import + Phase-3A hook ──
def test_19_source_identity(ctx):
    vid, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/toll-import/commit", headers=HJSON, json={
        "vendor": "idfc",
        "rows": [_fastag_row(vid, ctx.tag, 1, 333)]}, timeout=15)
    eid = r.json()["results"][0]["expense_id"]
    ctx.track(eid)
    before = ctx.d.expenses.find_one({"id": eid}, {"_id": 0,
        "source_type": 1, "source": 1, "source_txn_ref": 1, "source_key": 1})
    # Trigger a Phase-3A hook (owner reproject) on the same id
    requests.post(f"{API}/fin/reproject", headers=HJSON, json={
        "source_type": "expense", "source_id": eid}, timeout=15)
    after = ctx.d.expenses.find_one({"id": eid}, {"_id": 0,
        "source_type": 1, "source": 1, "source_txn_ref": 1, "source_key": 1})
    assert before == after
    assert after["source_type"] == "fastag_import"


# ── 20. Day Book reflection ─────────────────────────────────────────
def test_20_day_book_reflection(ctx):
    vid, _ = ctx.make_vehicle()
    date = "2026-04-05"
    r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
        "date": date, "category": "Parking",
        "entries": [{"client_row_id": f"db-{ctx.tag}",
                     "vehicle_id": vid, "amount": 88}],
    }, timeout=15)
    eid = r.json()["results"][0]["expense"]["id"]
    ctx.track(eid)
    day = requests.get(f"{API}/fin/day-book", headers=H,
                       params={"date_from": date, "date_to": date},
                       timeout=15).json()
    hit = any(row.get("source_id") == eid for row in day.get("rows", []))
    assert hit


# ── 21. Accounts reflection ─────────────────────────────────────────
def test_21_accounts_reflection(ctx):
    vid, _ = ctx.make_vehicle()

    def bal(code):
        pipe = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                             "account_code": code, "status": "active"}},
                {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        got = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(pipe)}
        return round(got.get("in", 0.0) - got.get("out", 0.0), 2)

    cash0 = bal("CASH")
    exp0 = bal("EXPENSE_DEFAULT")
    wallet0 = bal("WALLET_FASTAG")
    r = requests.post(f"{API}/toll-import/commit", headers=HJSON, json={
        "vendor": "livq",
        "rows": [_fastag_row(vid, ctx.tag, 1, 135.55)]}, timeout=15)
    eid = r.json()["results"][0]["expense_id"]
    ctx.track(eid)
    # FASTag toll drains WALLET_FASTAG (A-1 §6), not CASH.
    assert round(bal("WALLET_FASTAG") - wallet0, 2) == -135.55
    assert round(bal("EXPENSE_DEFAULT") - exp0, 2) == 135.55
    assert round(bal("CASH") - cash0, 2) == 0.0  # CASH untouched by FASTag


# ── 22. Phase-3A compatibility ──────────────────────────────────────
def test_22_phase3a_compat(ctx):
    """Fuel import → Phase-3B-i hook. Then Phase-3A router hook via
    fleet-card-vehicle correction. Final projection: exactly 2 legs
    with the new vehicle."""
    vid_a, _ = ctx.make_vehicle()
    vid_b, _ = ctx.make_vehicle()
    r = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl",
        "rows": [_fleet_row(vid_a, ctx.tag, 1, 20, 1800)]}, timeout=15)
    eid = r.json()["results"][0]["expense_id"]
    ctx.track(eid)
    requests.patch(f"{API}/expenses/{eid}/fleet-card-vehicle",
                   headers=HJSON, json={"vehicle_id": vid_b}, timeout=15)
    legs = list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_id": eid},
        {"_id": 0, "vehicle_id": 1}))
    assert len(legs) == 2
    assert all(l["vehicle_id"] == vid_b for l in legs)


# ── 23-25. Performance sanity ───────────────────────────────────────
def _run_bulk_import(ctx, n_rows):
    vid, _ = ctx.make_vehicle()
    rows = [_fleet_row(vid, ctx.tag + f"-N{n_rows}", i, 10, 800 + i)
            for i in range(1, n_rows + 1)]
    t0 = time.time()
    r = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl", "rows": rows}, timeout=600)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == n_rows
    for res in body["results"]:
        ctx.track(res.get("expense_id", ""))
    return elapsed, body["created"]


def test_23_perf_200_rows(ctx):
    dur, n = _run_bulk_import(ctx, 200)
    per_row = dur / n
    print(f"\n[perf-200] total={dur:.2f}s, per_row={per_row * 1000:.1f}ms")
    assert per_row < 1.0  # < 1s/row bulk sanity


def test_24_perf_1000_rows(ctx):
    dur, n = _run_bulk_import(ctx, 1000)
    per_row = dur / n
    print(f"\n[perf-1000] total={dur:.2f}s, per_row={per_row * 1000:.1f}ms")
    assert per_row < 1.0


def test_25_perf_2000_rows(ctx):
    dur, n = _run_bulk_import(ctx, 2000)
    per_row = dur / n
    print(f"\n[perf-2000] total={dur:.2f}s, per_row={per_row * 1000:.1f}ms")
    assert per_row < 1.0


# ── 26. A-1 immutability guard ──────────────────────────────────────
def test_26_a1_immutability():
    import services_fin_txn as a1
    import services_fin_txn_hooks as hooks
    import services_quick_expense as qe
    import services_fuel_import as fi
    import services_toll_import as ti
    # Every service module must import hook_after_source_write from Phase-1.
    for mod, name in ((qe, "quick_expense"), (fi, "fuel_import"),
                       (ti, "toll_import")):
        assert mod.hook_after_source_write is hooks.hook_after_source_write, \
            f"{name} service must reuse Phase-1 hook directly"
    # A-1 unchanged.
    for name in ("reproject_source", "SUPPORTED_SOURCE_TYPES"):
        assert getattr(hooks, name) is getattr(a1, name)
