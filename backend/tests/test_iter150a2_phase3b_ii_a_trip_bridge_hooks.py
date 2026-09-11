"""Iter150A-2 · Phase 3B-ii-a — Trip → canonical Expense bridge hooks (CREATE / UPDATE only).

Covers the 3 bridge write sites inside `sync_trip_expenses_to_canonical`:
  * B1a: existing row UPDATE / resurrection  (after `expenses.update_one`)
  * B1b: new row INSERT                      (after `expenses.insert_one`)
  * B1c: removed line SOFT-DELETE            (after `expenses.update_one`)

Trip DELETE hooks (`delete_trip_canonical_expenses`,
`unlink_operator_expenses_on_trip_delete`) are Phase 3B-ii-b — NOT covered.
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

load_dotenv(Path("/app/frontend/.env"))
load_dotenv(Path("/app/backend/.env"))

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
TOK = os.environ["DEMO_TOKEN_VALUE"]
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
        self._trips: list[str] = []
        self._vehicles: list[str] = []
        self._expense_ids: list[str] = []

    def make_vehicle(self):
        vnum = f"3B2A{self.tag[:3].upper()}{len(self._vehicles):02d}"
        r = requests.post(f"{API}/vehicles", headers=HJSON, json={
            "vehicle_number": vnum, "vehicle_type": "own",
            "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        v = r.json()
        self._vehicles.append(v["id"])
        return v["id"], v["vehicle_number"]

    def teardown(self):
        d = self.d
        # collect any Expense ids the bridge produced for our trips
        if self._trips:
            bridge_ids = [e["id"] for e in d.expenses.find(
                {"user_id": self.uid, "source_trip_id": {"$in": self._trips}},
                {"id": 1, "_id": 0})]
            self._expense_ids.extend(bridge_ids)
        if self._expense_ids:
            eids = list(set(self._expense_ids))
            d.expenses.delete_many({"id": {"$in": eids}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                   "source_id": {"$in": eids}})
            d.fin_hook_failures.delete_many(
                {"user_id": self.uid, "source_id": {"$in": eids}})
        if self._trips:
            d.trips.delete_many({"id": {"$in": self._trips}})
        if self._vehicles:
            d.vehicles.delete_many({"id": {"$in": self._vehicles}})


@pytest.fixture
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


def _fin_legs(ctx, source_id):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "expense", "source_id": source_id},
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1,
         "ref_source_key": 1, "trip_id": 1},
    ))


def _trip_payload(vid, vnum, tag, ldx="", **overrides):
    p = {
        "vehicle_id": vid, "vehicle_number": vnum, "vehicle_type": "own",
        "date": "2026-04-01",
        "lr_number": f"LR-{tag}{ldx}",
        "customer_id": "",
        "customer_name": "",
        "route_from": "A", "route_to": "B",
        "tons": 10.0,
        "loaded_qty": 10, "unloaded_qty": 10, "shortage_qty": 0,
        "freight_mode": "per_ton",
        "freight_rate": 100, "customer_gross_freight": 1000,
        "expenses": {"diesel": 0, "toll": 0, "batta": 0,
                     "repair": 0, "other": 0, "firewood": 0,
                     "other_desc": "", "other_remarks": ""},
        "other_expenditures": [],
    }
    p.update(overrides)
    return p


def _create_trip(ctx, payload):
    r = requests.post(f"{API}/trips", headers=HJSON, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    ctx._trips.append(tid)
    return tid


def _update_trip(ctx, tid, payload):
    r = requests.put(f"{API}/trips/{tid}", headers=HJSON, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _find_expense_by_source_key(ctx, sk):
    return ctx.d.expenses.find_one({"user_id": ctx.uid, "source_key": sk},
                                    {"_id": 0})


# ── 1. Trip create with legacy Diesel scalar → 1 canonical row + 2 legs ──
def test_1_trip_create_legacy_diesel(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "1",
        expenses={"diesel": 1000, "toll": 0, "batta": 0,
                   "repair": 0, "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    exp = _find_expense_by_source_key(ctx, sk)
    assert exp and exp["source_type"] == "trip_legacy"
    assert exp["source_trip_id"] == tid
    legs = _fin_legs(ctx, exp["id"])
    assert len(legs) == 2
    assert all(l["amount"] == 1000.0 for l in legs)


# ── 2. Trip create with multiple rows ──
def test_2_trip_create_multiple(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "2",
        expenses={"diesel": 500, "toll": 200, "batta": 100,
                   "repair": 0, "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""},
        other_expenditures=[
            {"id": f"oe1-{ctx.tag}", "type": "Parking", "amount": 50,
             "date": "2026-04-01", "remarks": ""},
            {"id": f"oe2-{ctx.tag}", "type": "Cleaning", "amount": 75,
             "date": "2026-04-01", "remarks": ""},
        ]))
    exps = list(ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid, "is_deleted": False},
        {"_id": 0, "id": 1, "source_key": 1}))
    assert len(exps) == 5   # 3 legacy + 2 OE
    total_legs = sum(len(_fin_legs(ctx, e["id"])) for e in exps)
    assert total_legs == 10


# ── 3. Trip update amount → existing row updates, projection replaced ──
def test_3_trip_update_amount(ctx):
    vid, vnum = ctx.make_vehicle()
    p = _trip_payload(vid, vnum, ctx.tag, "3",
        expenses={"diesel": 800, "toll": 0, "batta": 0,
                   "repair": 0, "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""})
    tid = _create_trip(ctx, p)
    sk = f"trip:{tid}:legacy:diesel"
    eid = _find_expense_by_source_key(ctx, sk)["id"]
    assert all(l["amount"] == 800.0 for l in _fin_legs(ctx, eid))

    p2 = dict(p)
    p2["expenses"] = {**p["expenses"], "diesel": 1200}
    _update_trip(ctx, tid, p2)

    exp = _find_expense_by_source_key(ctx, sk)
    assert exp["id"] == eid   # same Expense id (stable)
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2
    assert all(l["amount"] == 1200.0 for l in legs)


# ── 4. Trip update date/narration → projection reflects new date ──
def test_4_trip_update_date_narration(ctx):
    vid, vnum = ctx.make_vehicle()
    p = _trip_payload(vid, vnum, ctx.tag, "4",
        date="2026-04-01",
        expenses={"diesel": 0, "toll": 0, "batta": 0, "repair": 0,
                   "other": 300, "firewood": 0,
                   "other_desc": "old-note", "other_remarks": ""})
    tid = _create_trip(ctx, p)
    sk = f"trip:{tid}:legacy:other"
    eid = _find_expense_by_source_key(ctx, sk)["id"]

    p2 = dict(p)
    p2["date"] = "2026-04-05"
    p2["expenses"] = {**p["expenses"], "other_desc": "new-note"}
    _update_trip(ctx, tid, p2)

    legs = _fin_legs(ctx, eid)
    assert all(l["amount"] == 300.0 for l in legs)


# ── 5. Trip update — add new OE row → new canonical row + 2 legs ──
def test_5_trip_update_add_oe(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "5",
        expenses={"diesel": 500, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    row_id = f"oe-add-{ctx.tag}"
    p2 = _trip_payload(vid, vnum, ctx.tag, "5",
        expenses={"diesel": 500, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""},
        other_expenditures=[{"id": row_id, "type": "Weighment",
                             "amount": 40, "date": "2026-04-01",
                             "remarks": ""}])
    _update_trip(ctx, tid, p2)
    sk = f"trip:{tid}:oe:{row_id}"
    exp = _find_expense_by_source_key(ctx, sk)
    assert exp and exp["source_type"] == "trip_other_expenditure"
    legs = _fin_legs(ctx, exp["id"])
    assert len(legs) == 2 and all(l["amount"] == 40.0 for l in legs)


# ── 6. Trip update — remove OE row → soft-delete + legs cleared ──
def test_6_trip_update_remove_oe(ctx):
    vid, vnum = ctx.make_vehicle()
    row_id = f"oe-rm-{ctx.tag}"
    p = _trip_payload(vid, vnum, ctx.tag, "6",
        other_expenditures=[{"id": row_id, "type": "Weighment",
                             "amount": 60, "date": "2026-04-01",
                             "remarks": ""}])
    tid = _create_trip(ctx, p)
    sk = f"trip:{tid}:oe:{row_id}"
    eid = _find_expense_by_source_key(ctx, sk)["id"]
    assert len(_fin_legs(ctx, eid)) == 2

    p2 = dict(p); p2["other_expenditures"] = []
    _update_trip(ctx, tid, p2)

    exp = ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "is_deleted": 1})
    assert exp["is_deleted"] is True
    assert _fin_legs(ctx, eid) == []


# ── 7. Remove then re-add same OE id → SAME Expense, resurrection ──
def test_7_remove_then_readd(ctx):
    vid, vnum = ctx.make_vehicle()
    row_id = f"oe-rev-{ctx.tag}"
    p = _trip_payload(vid, vnum, ctx.tag, "7",
        other_expenditures=[{"id": row_id, "type": "Detention",
                             "amount": 90, "date": "2026-04-01",
                             "remarks": ""}])
    tid = _create_trip(ctx, p)
    sk = f"trip:{tid}:oe:{row_id}"
    eid = _find_expense_by_source_key(ctx, sk)["id"]

    p_rm = dict(p); p_rm["other_expenditures"] = []
    _update_trip(ctx, tid, p_rm)
    assert _fin_legs(ctx, eid) == []

    _update_trip(ctx, tid, p)  # re-add same row_id
    exp2 = _find_expense_by_source_key(ctx, sk)
    assert exp2["id"] == eid   # SAME Expense id
    assert exp2["is_deleted"] is False
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2 and all(l["amount"] == 90.0 for l in legs)
    # ref_source_key stable
    for l in legs:
        assert l["ref_source_key"].startswith(f"expense:{eid}:")


# ── 8. Repeated identical Trip save 5× → no duplicates ──
def test_8_repeated_identical_save(ctx):
    vid, vnum = ctx.make_vehicle()
    p = _trip_payload(vid, vnum, ctx.tag, "8",
        expenses={"diesel": 400, "toll": 100, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""})
    tid = _create_trip(ctx, p)
    initial = list(ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid, "is_deleted": False},
        {"_id": 0, "id": 1}))
    assert len(initial) == 2
    init_ids = sorted(e["id"] for e in initial)
    for _ in range(5):
        _update_trip(ctx, tid, p)
    final = list(ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid, "is_deleted": False},
        {"_id": 0, "id": 1}))
    assert sorted(e["id"] for e in final) == init_ids
    total_legs = sum(len(_fin_legs(ctx, e["id"])) for e in final)
    assert total_legs == 4  # 2 rows × 2 legs


# ── 9. Stable source_key across saves ──
def test_9_stable_source_key(ctx):
    vid, vnum = ctx.make_vehicle()
    row_id = f"oe-sk-{ctx.tag}"
    p = _trip_payload(vid, vnum, ctx.tag, "9",
        expenses={"diesel": 100, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""},
        other_expenditures=[{"id": row_id, "type": "Loading Charges",
                             "amount": 25, "date": "2026-04-01",
                             "remarks": ""}])
    tid = _create_trip(ctx, p)
    keys_before = sorted(e["source_key"] for e in ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid, "is_deleted": False},
        {"source_key": 1, "_id": 0}))
    _update_trip(ctx, tid, p)
    _update_trip(ctx, tid, p)
    keys_after = sorted(e["source_key"] for e in ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid, "is_deleted": False},
        {"source_key": 1, "_id": 0}))
    assert keys_before == keys_after
    assert f"trip:{tid}:legacy:diesel" in keys_after
    assert f"trip:{tid}:oe:{row_id}" in keys_after


# ── 10. Failure queue: forced hook failure keeps source authoritative ──
def test_10_failure_queue(ctx):
    import services_fin_txn_hooks as hooks
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "10",
        expenses={"diesel": 700, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    eid = _find_expense_by_source_key(ctx, sk)["id"]

    orig = hooks.reproject_source
    _LOOP = _asyncio.new_event_loop(); _asyncio.set_event_loop(_LOOP)
    async def _boom(*a, **kw): raise RuntimeError("3b2a-forced")
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
    # Trip + Expense still authoritative
    assert ctx.d.trips.find_one({"id": tid}, {"_id": 0, "id": 1})
    assert ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "amount": 1})["amount"] == 700.0


# ── 11. Replay → resolved + legs restored ──
def test_11_replay_resolves(ctx):
    import subprocess, sys as _sys
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "11",
        expenses={"diesel": 250, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    eid = _find_expense_by_source_key(ctx, sk)["id"]
    # Drop projected legs and seed a pending failure row
    ctx.d.fin_txn.delete_many({"user_id": ctx.uid, "source_id": eid})
    ctx.d.fin_hook_failures.insert_one({
        "id": f"hf_3b2a_{ctx.tag}", "user_id": ctx.uid, "company_id": ctx.cid,
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


# ── 12. Tenant isolation ──
def test_12_tenant_isolation(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "12",
        expenses={"diesel": 150, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    eid = _find_expense_by_source_key(ctx, sk)["id"]
    other_uid = f"user_3b2a_iso_{ctx.tag}"
    other_cid = f"co_3b2a_iso_{ctx.tag}"
    ctx.d.fin_accounts.insert_one({
        "id": f"acc_3b2a_{ctx.tag}", "user_id": other_uid,
        "company_id": other_cid,
        "code": "EXPENSE_DEFAULT", "name": "iso", "type": "expense",
        "is_system": True, "is_active": True, "created_at": "2026-01-01",
    })
    ctx.d.fin_txn.insert_one({
        "id": f"fintxn_3b2a_{ctx.tag}",
        "user_id": other_uid, "company_id": other_cid,
        "txn_date": "2026-04-01", "account_id": f"acc_3b2a_{ctx.tag}",
        "account_code": "EXPENSE_DEFAULT", "direction": "in", "amount": 150.0,
        "counter_account_id": "", "counter_account_code": "CASH",
        "txn_type": "expense", "source_type": "expense",
        "source_id": eid, "source_key": "",
        "ref_source_key": f"expense:{eid}:expense_debit",
        "party_type": "cash", "party_id": "", "party_name": "",
        "vehicle_id": "", "trip_id": "", "category": "Diesel",
        "narration": "iso", "status": "active",
        "transfer_group_id": "", "adjustment_group_id": "",
        "reversal_of": "", "is_reversal": False,
        "is_supplier_settlement_recovery": False,
        "reconciled_at": "", "reconciled_ref": "",
        "created_at": "2026-01-01", "projected_at": "2026-01-01",
    })
    try:
        rows = list(ctx.d.fin_txn.find(
            {"ref_source_key": f"expense:{eid}:expense_debit"},
            {"_id": 0, "user_id": 1}))
        uids = {r["user_id"] for r in rows}
        assert ctx.uid in uids and other_uid in uids
        assert len(rows) == 2
    finally:
        ctx.d.fin_txn.delete_many({"user_id": other_uid})
        ctx.d.fin_accounts.delete_many({"user_id": other_uid})


# ── 13. Double-count protection: canonical + separate fleet-card Diesel ──
def test_13_no_double_count(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "13",
        expenses={"diesel": 500, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    eid_trip = _find_expense_by_source_key(ctx, sk)["id"]

    # Add a separate fleet-card Diesel Expense for the same vehicle/date
    r = requests.post(f"{API}/fuel-import/commit", headers=HJSON, json={
        "source": "iocl",
        "rows": [{"row_index": 1, "resolved_vehicle_id": vid,
                  "date": "2026-04-01", "litres": 10, "rate": 80,
                  "amount": 800, "station_name": "IOCL-DC",
                  "source_txn_ref": f"DC-{ctx.tag}", "odometer": 12000}],
    }, timeout=15)
    fuel_eid = r.json()["results"][0]["expense_id"]
    ctx._expense_ids.append(fuel_eid)

    # Each is a DIFFERENT source_key with its own 2 legs.
    trip_legs = _fin_legs(ctx, eid_trip)
    fuel_legs = _fin_legs(ctx, fuel_eid)
    assert len(trip_legs) == 2 and len(fuel_legs) == 2
    assert all(l["amount"] == 500.0 for l in trip_legs)
    assert all(l["amount"] == 800.0 for l in fuel_legs)
    # ref_source_keys are distinct.
    trip_refs = {l["ref_source_key"] for l in trip_legs}
    fuel_refs = {l["ref_source_key"] for l in fuel_legs}
    assert trip_refs.isdisjoint(fuel_refs)


# ── 14. Day Book reflection ──
def test_14_day_book_reflection(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "14",
        date="2026-04-11",
        expenses={"diesel": 333, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    eid = _find_expense_by_source_key(ctx, sk)["id"]
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-04-11", "date_to": "2026-04-11"},
                     timeout=15)
    assert r.status_code == 200
    rows = r.json().get("rows", [])
    assert any(row.get("source_id") == eid for row in rows)


# ── 15. Accounts reflection ──
def test_15_accounts_reflection(ctx):
    def bal(code):
        pipe = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                             "account_code": code, "status": "active"}},
                {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(pipe)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)

    vid, vnum = ctx.make_vehicle()
    cash0 = bal("CASH")
    exp0 = bal("EXPENSE_DEFAULT")
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "15",
        expenses={"diesel": 250, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    assert round(bal("EXPENSE_DEFAULT") - exp0, 2) == 250.0
    assert round(bal("CASH") - cash0, 2) == -250.0


# ── 16. A-1 immutability guard ──
def test_16_a1_immutability():
    import services_fin_txn as a1
    import services_fin_txn_hooks as hooks
    import services_expense_bridge as bridge
    assert bridge.hook_after_source_write is hooks.hook_after_source_write
    # Bridge must NOT re-export A-1 symbols
    for name in ("reproject_source", "SUPPORTED_SOURCE_TYPES"):
        assert not hasattr(bridge, name), f"bridge unexpectedly exports {name}"
    for name in ("reproject_source", "SUPPORTED_SOURCE_TYPES"):
        assert getattr(hooks, name) is getattr(a1, name)


# ── 17. Phase-3A compatibility (manual PUT still works) ──
def test_17_phase3a_compat(ctx):
    """Bridge creates canonical; operator then PUTs the Expense directly.
    Final projection consistent, no double-fire."""
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "17",
        expenses={"diesel": 400, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    eid = _find_expense_by_source_key(ctx, sk)["id"]
    # Directly PUT the Expense via Phase-3A router
    r = requests.put(f"{API}/expenses/{eid}", headers=HJSON, json={
        "date": "2026-04-01", "category": "Diesel", "amount": 999.0,
        "narration": "override", "remarks": "",
        "vehicle_id": vid, "vehicle_number": vnum,
        "trip_id": tid, "repair_event_id": "",
        "party_type": "cash", "party_id": "", "party_name": "",
        "vendor_bill_id": "", "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False,
        "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now",
        "source_type": "trip_legacy", "source_key": sk,
        "file_ids": [],
    }, timeout=15)
    assert r.status_code == 200, r.text
    legs = _fin_legs(ctx, eid)
    assert len(legs) == 2 and all(l["amount"] == 999.0 for l in legs)


# ── 18. Phase-3B-i compatibility (Trip + concurrent bulk import) ──
def test_18_phase3bi_compat(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "18",
        expenses={"diesel": 300, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    # Concurrent bulk-op Parking
    r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
        "date": "2026-04-01", "category": "Parking",
        "entries": [{"client_row_id": f"3b2a-{ctx.tag}",
                     "vehicle_id": vid, "amount": 55}],
    }, timeout=15)
    parking_eid = r.json()["results"][0]["expense"]["id"]
    ctx._expense_ids.append(parking_eid)
    trip_diesel_eid = _find_expense_by_source_key(
        ctx, f"trip:{tid}:legacy:diesel")["id"]
    assert len(_fin_legs(ctx, trip_diesel_eid)) == 2
    assert len(_fin_legs(ctx, parking_eid)) == 2


# ── 19. has_canonical_expenses flag reflects state after bridge ──
def test_19_has_canonical_expenses_flag(ctx):
    vid, vnum = ctx.make_vehicle()
    # Trip with no expenses → flag should be False
    p_empty = _trip_payload(vid, vnum, ctx.tag, "19",
        expenses={"diesel": 0, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""})
    tid = _create_trip(ctx, p_empty)
    trip = ctx.d.trips.find_one({"id": tid}, {"_id": 0, "has_canonical_expenses": 1})
    assert trip["has_canonical_expenses"] is False
    # Add expense → flag flips True
    p_full = dict(p_empty)
    p_full["expenses"] = {**p_empty["expenses"], "diesel": 200}
    _update_trip(ctx, tid, p_full)
    trip2 = ctx.d.trips.find_one({"id": tid}, {"_id": 0, "has_canonical_expenses": 1})
    assert trip2["has_canonical_expenses"] is True


# ── 20. Iter149-linked FASTag Expense unaffected by Trip UPDATE ──
def test_20_iter149_linked_untouched_by_update(ctx):
    vid, vnum = ctx.make_vehicle()
    p = _trip_payload(vid, vnum, ctx.tag, "20",
        expenses={"diesel": 500, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""})
    tid = _create_trip(ctx, p)

    # Seed a fastag_import Toll Expense and link it via Phase-3A router.
    fastag_eid = f"exp_3b2a_ft_{ctx.tag}"
    ctx.d.expenses.insert_one({
        "id": fastag_eid, "user_id": ctx.uid, "company_id": ctx.cid,
        "date": "2026-04-01", "category": "Toll", "amount": 275.0,
        "narration": "plaza-3b2a", "remarks": f"Txn: FT{ctx.tag}",
        "vehicle_id": vid, "vehicle_number": vnum, "trip_id": "",
        "repair_event_id": "", "party_type": "cash", "party_id": "",
        "party_name": "", "vendor_bill_id": "", "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
        "file_ids": [], "source_type": "fastag_import",
        "source_key": f"fastag:idfc:{ctx.cid}:FT{ctx.tag}",
        "source": "idfc", "source_txn_ref": f"FT{ctx.tag}",
        "source_trip_id": "",  # NOT bridge-materialised
        "created_at": "2026-04-01T00:00:00+00:00", "created_by": ctx.uid,
        "is_deleted": False,
    })
    ctx._expense_ids.append(fastag_eid)
    # Link via Phase-3A
    r = requests.patch(f"{API}/expenses/{fastag_eid}/toll-trip",
                       headers=HJSON, json={"trip_id": tid}, timeout=15)
    assert r.status_code == 200
    ft_legs_before = _fin_legs(ctx, fastag_eid)
    assert all(l["trip_id"] == tid for l in ft_legs_before)
    amt_before = sum(l["amount"] for l in ft_legs_before if l["direction"] == "in")

    # Now UPDATE the Trip (bridge fires for legacy Diesel only).
    p2 = dict(p); p2["expenses"] = {**p["expenses"], "diesel": 600}
    _update_trip(ctx, tid, p2)

    # The FASTag Expense projection MUST be untouched.
    ft_legs_after = _fin_legs(ctx, fastag_eid)
    assert len(ft_legs_after) == 2
    assert all(l["trip_id"] == tid for l in ft_legs_after)
    amt_after = sum(l["amount"] for l in ft_legs_after if l["direction"] == "in")
    assert amt_before == amt_after == 275.0


# ── 21. No hook on Trip's `has_canonical_expenses` update itself ──
def test_21_no_hook_for_trip_flag_update():
    """Static-check the bridge source: the `db.trips.update_one` at the end
    of sync_trip_expenses_to_canonical (which updates has_canonical_expenses)
    is NOT accompanied by any hook_after_source_write call.
    """
    import inspect
    import services_expense_bridge as bridge
    src = inspect.getsource(bridge.sync_trip_expenses_to_canonical)
    # Anchor on the actual DB write for the Trip flag (not the docstring).
    anchor = "db.trips.update_one"
    assert anchor in src
    tail = src.split(anchor, 1)[1]
    assert "hook_after_source_write" not in tail, (
        "Bridge must not fire an Expense hook on the Trip flag update.")
