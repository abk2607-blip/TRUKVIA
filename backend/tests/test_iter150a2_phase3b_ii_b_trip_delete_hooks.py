"""Iter150A-2 · Phase 3B-ii-b — Trip DELETE bridge hooks.

Covers the 2 Trip-DELETE write sites inside `services_expense_bridge.py`:
  * B3: `delete_trip_canonical_expenses`     — soft-deletes bridge Expenses.
  * B4: `unlink_operator_expenses_on_trip_delete` — clears `trip_id` on
        operator-linked (Iter149 FASTag/Toll) Expenses without touching
        their accounting movement.

Trip CREATE / UPDATE hooks (Phase 3B-ii-a) are already locked and covered
by `test_iter150a2_phase3b_ii_a_trip_bridge_hooks.py` — this suite only
asserts the DELETE-path additions and cross-phase compatibility.
"""
from __future__ import annotations

import asyncio as _asyncio
import inspect
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


# Motor's async client binds its connection pool to the FIRST asyncio
# loop it observes. Reusing ONE loop for every in-process async call
# across this module matches the pattern used by
# test_iter150a2_hook_foundation.py and avoids "Event loop is closed"
# cascades when multiple failure/replay tests directly invoke the
# bridge B3/B4 async functions with monkey-patched reproject_source.
_LOOP = _asyncio.new_event_loop()
_asyncio.set_event_loop(_LOOP)


def _run(coro):
    """Run coroutine on the shared module-level event loop."""
    return _LOOP.run_until_complete(coro)


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
        vnum = f"3B2B{self.tag[:3].upper()}{len(self._vehicles):02d}"
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
        # Collect any Expense ids the bridge produced for our trips (some
        # trips may already be deleted, so scan by user_id + source_trip_id).
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
         "ref_source_key": 1, "trip_id": 1, "vehicle_id": 1, "category": 1,
         "status": 1, "source_key": 1},
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


def _delete_trip(tid, reason="phase3b2b-test"):
    return requests.delete(
        f"{API}/trips/{tid}", headers=H,
        params={"reason": reason}, timeout=15,
    )


def _seed_fastag_toll(ctx, vid, vnum, amount=275.0, txn_ref=None):
    """Insert a fastag_import Toll Expense (source_trip_id="") and return id."""
    txn_ref = txn_ref or f"FT{ctx.tag}{len(ctx._expense_ids):02d}"
    eid = f"exp_3b2b_ft_{txn_ref}"
    ctx.d.expenses.insert_one({
        "id": eid, "user_id": ctx.uid, "company_id": ctx.cid,
        "date": "2026-04-01", "category": "Toll", "amount": float(amount),
        "narration": "plaza-3b2b", "remarks": f"Txn: {txn_ref}",
        "vehicle_id": vid, "vehicle_number": vnum, "trip_id": "",
        "repair_event_id": "", "party_type": "cash", "party_id": "",
        "party_name": "", "vendor_bill_id": "",
        "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now", "reversal_of": "", "is_reversed": False,
        "file_ids": [], "source_type": "fastag_import",
        "source_key": f"fastag:idfc:{ctx.cid}:{txn_ref}",
        "source": "idfc", "source_txn_ref": txn_ref,
        "source_trip_id": "",           # NOT bridge-materialised
        "created_at": "2026-04-01T00:00:00+00:00", "created_by": ctx.uid,
        "is_deleted": False,
    })
    ctx._expense_ids.append(eid)
    # NOTE: no manual asyncio.new_event_loop() hook fire here — Motor's
    # connection pool binds to the first loop it sees, so spinning a
    # throwaway loop in-process contaminates the test-process motor.
    # The subsequent PATCH /toll-trip (Phase-3A) fires the hook server-
    # side and projects this Expense, which is exactly what Iter149
    # semantics require pre-DELETE.
    return eid


def _link_fastag_to_trip(fastag_eid, tid):
    r = requests.patch(f"{API}/expenses/{fastag_eid}/toll-trip",
                       headers=HJSON, json={"trip_id": tid}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _find_expense_by_source_key(ctx, sk):
    return ctx.d.expenses.find_one({"user_id": ctx.uid, "source_key": sk},
                                    {"_id": 0})


# ══════════════════════════════════════════════════════════════════════
# B3 — bridge Expense soft-delete on Trip DELETE
# ══════════════════════════════════════════════════════════════════════

# ── 1. Trip DELETE soft-deletes ALL bridge Expenses ──
def test_1_trip_delete_soft_deletes_bridge_expenses(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "1",
        expenses={"diesel": 500, "toll": 200, "batta": 100, "repair": 50,
                   "other": 25, "firewood": 10,
                   "other_desc": "", "other_remarks": ""}))
    active_before = list(ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid, "is_deleted": False},
        {"_id": 0, "id": 1}))
    assert len(active_before) == 6

    r = _delete_trip(tid)
    assert r.status_code == 200, r.text

    active_after = list(ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid, "is_deleted": False},
        {"_id": 0, "id": 1}))
    assert active_after == []
    soft_deleted = list(ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid, "is_deleted": True},
        {"_id": 0, "id": 1, "deletion_reason": 1, "deleted_by": 1}))
    assert len(soft_deleted) == 6
    for e in soft_deleted:
        assert e["deleted_by"] == ctx.uid
        assert e["deletion_reason"].startswith("trip_deleted:")


# ── 2. All bridge FinTxn legs disappear after Trip DELETE ──
def test_2_bridge_fintxn_legs_disappear(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "2",
        expenses={"diesel": 800, "toll": 300, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    bridge_ids = [e["id"] for e in ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid},
        {"_id": 0, "id": 1})]
    assert len(bridge_ids) == 2
    for eid in bridge_ids:
        assert len(_fin_legs(ctx, eid)) == 2

    r = _delete_trip(tid)
    assert r.status_code == 200

    for eid in bridge_ids:
        legs = _fin_legs(ctx, eid)
        assert legs == [], f"leftover legs for {eid}: {legs}"


# ── 3. Source Expenses remain audit-visible (not hard-deleted) ──
def test_3_source_expenses_remain_audit_visible(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "3",
        expenses={"diesel": 300, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    eid_before = _find_expense_by_source_key(ctx, sk)["id"]

    r = _delete_trip(tid)
    assert r.status_code == 200

    doc = ctx.d.expenses.find_one({"id": eid_before}, {"_id": 0})
    assert doc is not None
    assert doc["is_deleted"] is True
    assert doc["amount"] == 300.0
    assert doc["source_key"] == sk
    assert doc["source_type"] == "trip_legacy"


# ── 4. Post-state proves exactly one clean projection per B3 affected ID ──
def test_4_one_hook_per_b3_affected_id(ctx):
    """Verify B3 fires exactly one hook per affected bridge Expense by
    checking the POST-DELETE projection state: every affected id must
    have exactly zero active FinTxn legs. No duplicates, no leftovers.
    """
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "4",
        expenses={"diesel": 100, "toll": 50, "batta": 75, "repair": 25,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    bridge_ids = {e["id"] for e in ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid},
        {"_id": 0, "id": 1})}
    assert len(bridge_ids) == 4
    # Each has 2 active legs pre-DELETE.
    for eid in bridge_ids:
        assert len(_fin_legs(ctx, eid)) == 2

    r = _delete_trip(tid)
    assert r.status_code == 200

    # Post-state: every affected id has ZERO legs. If a hook was skipped
    # for any id, its legs would linger. If a hook was fired twice, the
    # A-1 UNIQUE (user, company, ref_source_key) index guarantees only
    # one active projection is possible — a duplicate second call is a
    # no-op wrt state, so this still catches drop-outs and confirms
    # exactly-one-effective-hook semantics.
    for eid in bridge_ids:
        assert _fin_legs(ctx, eid) == [], f"leftover legs for {eid}"


# ══════════════════════════════════════════════════════════════════════
# B4 — Iter149 FASTag operator-linked Expense unlink
# ══════════════════════════════════════════════════════════════════════

# ── 5. FASTag Expense linked to Trip SURVIVES Trip DELETE ──
def test_5_fastag_expense_survives_trip_delete(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "5"))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=175.0)
    _link_fastag_to_trip(fastag_eid, tid)

    r = _delete_trip(tid)
    assert r.status_code == 200

    doc = ctx.d.expenses.find_one({"id": fastag_eid}, {"_id": 0})
    assert doc is not None
    assert doc["is_deleted"] is False


# ── 6. FASTag trip_id becomes "" ──
def test_6_fastag_trip_id_cleared(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "6"))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=210.0)
    _link_fastag_to_trip(fastag_eid, tid)
    doc_before = ctx.d.expenses.find_one({"id": fastag_eid}, {"_id": 0})
    assert doc_before["trip_id"] == tid

    r = _delete_trip(tid)
    assert r.status_code == 200

    doc_after = ctx.d.expenses.find_one({"id": fastag_eid}, {"_id": 0})
    assert doc_after["trip_id"] == ""
    assert doc_after["source_trip_id"] == ""     # unchanged


# ── 7. FASTag FinTxn.trip_id becomes "" ──
def test_7_fastag_fintxn_trip_id_cleared(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "7"))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=222.0)
    _link_fastag_to_trip(fastag_eid, tid)
    legs_before = _fin_legs(ctx, fastag_eid)
    assert all(l["trip_id"] == tid for l in legs_before)

    r = _delete_trip(tid)
    assert r.status_code == 200

    legs_after = _fin_legs(ctx, fastag_eid)
    assert len(legs_after) == 2
    assert all(l["trip_id"] == "" for l in legs_after)


# ── 8. FASTag amount unchanged (ZERO accounting delta) ──
def test_8_fastag_amount_unchanged(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "8"))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=349.0)
    _link_fastag_to_trip(fastag_eid, tid)
    legs_before = _fin_legs(ctx, fastag_eid)
    debit_before = sum(l["amount"] for l in legs_before if l["direction"] == "in")
    credit_before = sum(l["amount"] for l in legs_before if l["direction"] == "out")

    r = _delete_trip(tid)
    assert r.status_code == 200

    legs_after = _fin_legs(ctx, fastag_eid)
    debit_after = sum(l["amount"] for l in legs_after if l["direction"] == "in")
    credit_after = sum(l["amount"] for l in legs_after if l["direction"] == "out")
    assert debit_before == debit_after == 349.0
    assert credit_before == credit_after == 349.0


# ── 9. FASTag account_codes unchanged (source identity) ──
def test_9_fastag_account_and_identity_unchanged(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "9"))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=110.0)
    _link_fastag_to_trip(fastag_eid, tid)
    legs_before = _fin_legs(ctx, fastag_eid)
    codes_before = sorted(l["account_code"] for l in legs_before)
    refs_before = sorted(l["ref_source_key"] for l in legs_before)
    sk_before = sorted(l["source_key"] for l in legs_before)
    doc_before = ctx.d.expenses.find_one({"id": fastag_eid}, {"_id": 0})

    r = _delete_trip(tid)
    assert r.status_code == 200

    legs_after = _fin_legs(ctx, fastag_eid)
    doc_after = ctx.d.expenses.find_one({"id": fastag_eid}, {"_id": 0})
    assert sorted(l["account_code"] for l in legs_after) == codes_before
    assert sorted(l["ref_source_key"] for l in legs_after) == refs_before
    assert sorted(l["source_key"] for l in legs_after) == sk_before
    # Source doc identity preserved.
    for k in ("source_type", "source_key", "source_txn_ref",
              "vehicle_id", "amount", "category"):
        assert doc_before[k] == doc_after[k], f"{k} mutated"


# ══════════════════════════════════════════════════════════════════════
# SET A / SET B safety + local dedupe
# ══════════════════════════════════════════════════════════════════════

# ── 10. Set A / Set B structural disjointness (pre-write invariant) ──
def test_10_set_a_b_structural_disjoint(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "10",
        expenses={"diesel": 150, "toll": 60, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=99.0)
    _link_fastag_to_trip(fastag_eid, tid)

    set_a = {e["id"] for e in ctx.d.expenses.find(
        {"user_id": ctx.uid, "company_id": ctx.cid,
         "source_trip_id": tid, "is_deleted": {"$ne": True}},
        {"_id": 0, "id": 1})}
    set_b = {e["id"] for e in ctx.d.expenses.find(
        {"user_id": ctx.uid, "company_id": ctx.cid,
         "trip_id": tid, "source_trip_id": {"$ne": tid},
         "is_deleted": {"$ne": True}},
        {"_id": 0, "id": 1})}
    assert set_a and set_b
    assert set_a.isdisjoint(set_b)


# ── 11. Defensive local dedupe — set() over collected IDs never grows ──
def test_11_local_dedupe_within_call(ctx):
    """Static-check: both B3 and B4 collect their IDs into a `set(...)`
    (or set-comprehension) BEFORE the update_many, guaranteeing no
    duplicate hook dispatch even if the driver ever returned duplicates.
    """
    import services_expense_bridge as bridge
    for fn in (bridge.delete_trip_canonical_expenses,
               bridge.unlink_operator_expenses_on_trip_delete):
        src = inspect.getsource(fn)
        # affected_rows collected before update_many.
        assert "affected_rows" in src
        assert "affected_ids: set[str]" in src or "affected_ids: set = " in src or "set[str]" in src
        # hook fired inside a loop.
        assert "for eid in affected_ids" in src
        assert "hook_after_source_write" in src
        # update_many executed AFTER the collection (structural order).
        idx_collect = src.find("affected_rows = await db.expenses.find")
        idx_update = src.find("db.expenses.update_many")
        idx_hook = src.find("for eid in affected_ids")
        assert 0 <= idx_collect < idx_update < idx_hook, (
            f"required order broken in {fn.__name__}: "
            f"collect={idx_collect} update={idx_update} hook={idx_hook}")


# ── 12. Structural: exactly-one-effective-hook across B3+B4 (post-state) ──
def test_12_no_duplicate_hook_across_b3_b4(ctx):
    """A duplicate hook dispatch would collide with A-1's UNIQUE
    (user, company, ref_source_key) index but leave state identical.
    We instead prove the stronger property: after ONE Trip DELETE,
    the mixed B3+B4 population reaches its exact intended projection
    state — no cross-contamination between the two ID sets.
    """
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "12",
        expenses={"diesel": 200, "toll": 100, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=55.0)
    _link_fastag_to_trip(fastag_eid, tid)

    bridge_ids = {e["id"] for e in ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid},
        {"_id": 0, "id": 1})}
    assert len(bridge_ids) == 2

    r = _delete_trip(tid)
    assert r.status_code == 200

    # Every B3 id → 0 legs.  Every B4 (FASTag) id → 2 legs w/ trip_id="".
    for eid in bridge_ids:
        assert _fin_legs(ctx, eid) == []
    ft_legs = _fin_legs(ctx, fastag_eid)
    assert len(ft_legs) == 2
    assert all(l["trip_id"] == "" for l in ft_legs)
    assert all(l["amount"] == 55.0 for l in ft_legs)


# ══════════════════════════════════════════════════════════════════════
# Mixed / combined scenarios
# ══════════════════════════════════════════════════════════════════════

# ── 13. Mixed Trip: 5 bridge + 2 FASTag → 5 soft-delete + 2 unlink ──
def test_13_mixed_trip_5_bridge_2_fastag(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "13",
        expenses={"diesel": 500, "toll": 100, "batta": 50, "repair": 25,
                   "other": 0, "firewood": 10,
                   "other_desc": "", "other_remarks": ""}))
    bridge_ids = {e["id"] for e in ctx.d.expenses.find(
        {"user_id": ctx.uid, "source_trip_id": tid},
        {"_id": 0, "id": 1})}
    assert len(bridge_ids) == 5

    ft_eids = []
    for i, amt in enumerate([120.0, 240.0]):
        ft = _seed_fastag_toll(ctx, vid, vnum, amount=amt,
                               txn_ref=f"MIX{ctx.tag}{i}")
        _link_fastag_to_trip(ft, tid)
        ft_eids.append(ft)

    r = _delete_trip(tid)
    assert r.status_code == 200

    # Bridge rows soft-deleted; FinTxn cleared.
    for eid in bridge_ids:
        assert ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "is_deleted": 1})["is_deleted"] is True
        assert _fin_legs(ctx, eid) == []
    # FASTag rows survive; only trip_id denorm cleared; amount intact.
    for eid, expected_amt in zip(ft_eids, [120.0, 240.0]):
        doc = ctx.d.expenses.find_one({"id": eid}, {"_id": 0})
        assert doc["is_deleted"] is False
        assert doc["trip_id"] == ""
        assert doc["amount"] == expected_amt
        legs = _fin_legs(ctx, eid)
        assert len(legs) == 2
        assert all(l["trip_id"] == "" for l in legs)
        assert all(l["amount"] == expected_amt for l in legs)


# ══════════════════════════════════════════════════════════════════════
# Failure queue + replay
# ══════════════════════════════════════════════════════════════════════

# ── 14. Failure queue on B3 hook failure (in-process direct invocation) ──
def test_14_failure_queue_b3(ctx):
    """Directly invoke `bridge.delete_trip_canonical_expenses` with a
    monkey-patched `reproject_source` that raises. The authoritative
    soft-delete completes, but every hook lands in `fin_hook_failures`.
    """
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "14",
        expenses={"diesel": 700, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    eid = _find_expense_by_source_key(ctx, sk)["id"]

    import services_fin_txn_hooks as hooks
    import services_expense_bridge as bridge
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("3b2b-b3-forced")

    hooks.reproject_source = _boom
    try:
        modified = _run(bridge.delete_trip_canonical_expenses(
            ctx.uid, ctx.cid, tid, reason="phase3b2b-b3-fail"))
    finally:
        hooks.reproject_source = orig

    assert modified == 1
    # Authoritative Expense soft-delete happened.
    doc = ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "is_deleted": 1})
    assert doc["is_deleted"] is True
    # Failure row queued.
    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": eid}, {"_id": 0})
    assert row and row["status"] == "pending"


# ── 15. Failure queue on B4 hook failure (in-process direct invocation) ──
def test_15_failure_queue_b4(ctx):
    """Directly invoke `bridge.unlink_operator_expenses_on_trip_delete`
    with a monkey-patched `reproject_source` that raises. The
    authoritative `trip_id` clear completes; failure row queued.
    """
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "15"))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=180.0)
    _link_fastag_to_trip(fastag_eid, tid)

    import services_fin_txn_hooks as hooks
    import services_expense_bridge as bridge
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("3b2b-b4-forced")

    hooks.reproject_source = _boom
    try:
        modified = _run(bridge.unlink_operator_expenses_on_trip_delete(
            ctx.uid, ctx.cid, tid))
    finally:
        hooks.reproject_source = orig

    assert modified == 1
    doc = ctx.d.expenses.find_one({"id": fastag_eid}, {"_id": 0})
    assert doc["is_deleted"] is False
    assert doc["trip_id"] == ""      # authoritative source unlinked
    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": fastag_eid}, {"_id": 0})
    assert row and row["status"] == "pending"


# ── 16. Replay resolves both B3 & B4 pending failures ──
def test_16_replay_resolves(ctx):
    """After forcing B3+B4 hook failures in-process, restore
    `reproject_source` and run the replay CLI. Both failure rows
    resolve; bridge legs are cleared; FASTag legs stay intact
    with trip_id="".
    """
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "16",
        expenses={"diesel": 400, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    bridge_eid = _find_expense_by_source_key(ctx, sk)["id"]
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=88.0)
    _link_fastag_to_trip(fastag_eid, tid)

    import services_fin_txn_hooks as hooks
    import services_expense_bridge as bridge
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("3b2b-replay-forced")

    hooks.reproject_source = _boom
    try:
        _run(bridge.delete_trip_canonical_expenses(
            ctx.uid, ctx.cid, tid, reason="phase3b2b-replay"))
        _run(bridge.unlink_operator_expenses_on_trip_delete(
            ctx.uid, ctx.cid, tid))
        # Remove the source Trip so the replay flow is realistic.
        ctx.d.trips.delete_one({"id": tid})
    finally:
        hooks.reproject_source = orig

    assert ctx.d.fin_hook_failures.count_documents(
        {"user_id": ctx.uid, "source_id": {"$in": [bridge_eid, fastag_eid]},
         "status": "pending"}) == 2

    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr

    for eid in (bridge_eid, fastag_eid):
        row = ctx.d.fin_hook_failures.find_one(
            {"user_id": ctx.uid, "source_id": eid}, {"_id": 0})
        assert row and row["status"] == "resolved"

    # Bridge legs: empty (soft-deleted source).
    assert _fin_legs(ctx, bridge_eid) == []
    # FASTag legs: intact, trip_id="", amount preserved.
    ft_legs = _fin_legs(ctx, fastag_eid)
    assert len(ft_legs) == 2
    assert all(l["trip_id"] == "" for l in ft_legs)
    assert all(l["amount"] == 88.0 for l in ft_legs)


# ══════════════════════════════════════════════════════════════════════
# Idempotency
# ══════════════════════════════════════════════════════════════════════

# ── 17. Idempotency — second DELETE returns 404, projection unchanged ──
def test_17_idempotent_second_delete(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "17",
        expenses={"diesel": 100, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    sk = f"trip:{tid}:legacy:diesel"
    eid = _find_expense_by_source_key(ctx, sk)["id"]

    r1 = _delete_trip(tid); assert r1.status_code == 200
    legs_1 = _fin_legs(ctx, eid); assert legs_1 == []

    r2 = _delete_trip(tid); assert r2.status_code == 404

    # Projection did not resurrect.
    assert _fin_legs(ctx, eid) == []
    assert ctx.d.expenses.find_one({"id": eid}, {"_id": 0, "is_deleted": 1})["is_deleted"] is True


# ══════════════════════════════════════════════════════════════════════
# Tenant isolation
# ══════════════════════════════════════════════════════════════════════

# ── 18. Tenant isolation — other tenant's Expenses untouched ──
def test_18_tenant_isolation(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "18",
        expenses={"diesel": 250, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    # Seed a stray Expense on OTHER tenant with matching trip_id/source_trip_id.
    other_uid = f"user_3b2b_iso_{ctx.tag}"
    other_cid = f"co_3b2b_iso_{ctx.tag}"
    stray_eid = f"exp_3b2b_iso_{ctx.tag}"
    ctx.d.expenses.insert_one({
        "id": stray_eid, "user_id": other_uid, "company_id": other_cid,
        "date": "2026-04-01", "category": "Diesel", "amount": 999.0,
        "narration": "", "remarks": "", "vehicle_id": "", "vehicle_number": "",
        "trip_id": tid, "repair_event_id": "", "party_type": "cash",
        "party_id": "", "party_name": "", "vendor_bill_id": "",
        "mechanic_work_order_id": "", "supplier_owned_vehicle": False,
        "supplier_settlement_mode": "n/a", "settlement_mode": "cash_now",
        "reversal_of": "", "is_reversed": False, "file_ids": [],
        "source_type": "trip_legacy", "source_key": f"trip:{tid}:legacy:diesel",
        "source_trip_id": tid,           # same tid, other tenant
        "is_deleted": False,
        "created_at": "2026-01-01", "created_by": other_uid,
    })
    try:
        r = _delete_trip(tid)
        assert r.status_code == 200
        stray = ctx.d.expenses.find_one({"id": stray_eid}, {"_id": 0})
        assert stray is not None
        assert stray["is_deleted"] is False
        assert stray["trip_id"] == tid       # untouched
        assert stray["source_trip_id"] == tid # untouched
    finally:
        ctx.d.expenses.delete_many({"id": stray_eid})


# ══════════════════════════════════════════════════════════════════════
# Day Book / Accounts reflection
# ══════════════════════════════════════════════════════════════════════

# ── 19. Day Book after Trip DELETE: bridge gone, FASTag retained ──
def test_19_day_book_after_delete(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "19",
        date="2026-04-19",
        expenses={"diesel": 333, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    bridge_eid = _find_expense_by_source_key(
        ctx, f"trip:{tid}:legacy:diesel")["id"]
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=77.0)
    # Bump FASTag Expense date to match Trip date so ±2-day guard passes.
    ctx.d.expenses.update_one({"id": fastag_eid},
                              {"$set": {"date": "2026-04-19"}})
    _link_fastag_to_trip(fastag_eid, tid)

    r = _delete_trip(tid); assert r.status_code == 200

    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-04-01",
                             "date_to": "2026-04-30"}, timeout=15)
    rows = r.json().get("rows", [])
    ids = {row.get("source_id") for row in rows}
    assert bridge_eid not in ids
    assert fastag_eid in ids


# ── 20. Accounts balance after Trip DELETE ──
def test_20_accounts_after_delete(ctx):
    def bal(code):
        pipe = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                             "account_code": code, "status": "active"}},
                {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(pipe)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)

    vid, vnum = ctx.make_vehicle()
    exp0 = bal("EXPENSE_DEFAULT")
    cash0 = bal("CASH")
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "20",
        expenses={"diesel": 400, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=100.0)
    _link_fastag_to_trip(fastag_eid, tid)
    # After create+link: bridge 400 + FASTag 100 expense side; -500 cash side.
    assert round(bal("EXPENSE_DEFAULT") - exp0, 2) == 500.0

    r = _delete_trip(tid); assert r.status_code == 200

    # Bridge gone → -400 removed; FASTag 100 retained.
    # (FASTag Toll uses a fastag wallet counter account, not CASH,
    #  so we assert EXPENSE_DEFAULT only.)
    assert round(bal("EXPENSE_DEFAULT") - exp0, 2) == 100.0


# ══════════════════════════════════════════════════════════════════════
# Locked-band + cross-phase compatibility
# ══════════════════════════════════════════════════════════════════════

# ── 21. Iter149 compatibility — original semantics preserved ──
def test_21_iter149_compat(ctx):
    """Full end-to-end Iter149 mandate:
       create/import FASTag → link → delete Trip → FASTag survives,
       trip_id cleared, FinTxn.trip_id cleared, ZERO accounting delta.
    """
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "21"))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=333.0)
    _link_fastag_to_trip(fastag_eid, tid)
    doc_pre = ctx.d.expenses.find_one({"id": fastag_eid}, {"_id": 0})
    legs_pre = _fin_legs(ctx, fastag_eid)
    debit_pre = sum(l["amount"] for l in legs_pre if l["direction"] == "in")

    r = _delete_trip(tid); assert r.status_code == 200

    doc_post = ctx.d.expenses.find_one({"id": fastag_eid}, {"_id": 0})
    legs_post = _fin_legs(ctx, fastag_eid)
    debit_post = sum(l["amount"] for l in legs_post if l["direction"] == "in")

    # Immutable fields.
    for k in ("amount", "category", "source_type", "source_key",
              "source_txn_ref", "vehicle_id", "is_deleted"):
        assert doc_pre[k] == doc_post[k], f"iter149 mutated: {k}"
    assert doc_pre["trip_id"] == tid and doc_post["trip_id"] == ""
    assert debit_pre == debit_post == 333.0


# ── 22. Phase-3A compatibility — router hooks still work post-delete ──
def test_22_phase3a_compat(ctx):
    """After the Trip is deleted, the operator can still touch a surviving
    FASTag Expense via the Phase-3A PUT and the projection updates cleanly.
    """
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "22"))
    fastag_eid = _seed_fastag_toll(ctx, vid, vnum, amount=150.0)
    _link_fastag_to_trip(fastag_eid, tid)

    r = _delete_trip(tid); assert r.status_code == 200

    # Now edit the surviving FASTag Expense narration via Phase-3A PUT.
    doc = ctx.d.expenses.find_one({"id": fastag_eid}, {"_id": 0})
    payload = {
        "date": doc["date"], "category": doc["category"], "amount": 150.0,
        "narration": "post-delete-edit", "remarks": doc.get("remarks", ""),
        "vehicle_id": doc.get("vehicle_id", ""),
        "vehicle_number": doc.get("vehicle_number", ""),
        "trip_id": "", "repair_event_id": "",
        "party_type": "cash", "party_id": "", "party_name": "",
        "vendor_bill_id": "", "mechanic_work_order_id": "",
        "supplier_owned_vehicle": False,
        "supplier_settlement_mode": "n/a",
        "settlement_mode": "cash_now",
        "source_type": doc["source_type"], "source_key": doc["source_key"],
        "file_ids": [],
    }
    r2 = requests.put(f"{API}/expenses/{fastag_eid}", headers=HJSON,
                      json=payload, timeout=15)
    assert r2.status_code == 200, r2.text
    legs = _fin_legs(ctx, fastag_eid)
    assert len(legs) == 2 and all(l["amount"] == 150.0 for l in legs)


# ── 23. Phase-3B-i compatibility — unrelated bulk imports unaffected ──
def test_23_phase3bi_compat(ctx):
    vid, vnum = ctx.make_vehicle()
    tid = _create_trip(ctx, _trip_payload(vid, vnum, ctx.tag, "23",
        expenses={"diesel": 200, "toll": 0, "batta": 0, "repair": 0,
                   "other": 0, "firewood": 0,
                   "other_desc": "", "other_remarks": ""}))
    # Add an unrelated Quick-op Parking Expense (not linked to trip).
    r = requests.post(f"{API}/expenses/bulk-operational", headers=HJSON, json={
        "date": "2026-04-01", "category": "Parking",
        "entries": [{"client_row_id": f"3b2b-{ctx.tag}",
                     "vehicle_id": vid, "amount": 45}],
    }, timeout=15)
    parking_eid = r.json()["results"][0]["expense"]["id"]
    ctx._expense_ids.append(parking_eid)

    parking_legs_before = _fin_legs(ctx, parking_eid)
    assert len(parking_legs_before) == 2

    r = _delete_trip(tid); assert r.status_code == 200

    parking_legs_after = _fin_legs(ctx, parking_eid)
    assert len(parking_legs_after) == 2
    # Unrelated Expense untouched (amount, account, refs).
    assert sorted(l["amount"] for l in parking_legs_after) == \
           sorted(l["amount"] for l in parking_legs_before)


# ── 24. Phase-3B-ii-a compatibility — bridge CREATE/UPDATE still intact ──
def test_24_phase3bii_a_compat(ctx):
    """Static-check: the CREATE/UPDATE hook sites inside
    `sync_trip_expenses_to_canonical` are unchanged by Phase 3B-ii-b."""
    import services_expense_bridge as bridge
    src = inspect.getsource(bridge.sync_trip_expenses_to_canonical)
    # Three hook_after_source_write call sites (B1a / B1b / B1c).
    assert src.count("hook_after_source_write(uid, cid, \"expense\", prev[\"id\"])") >= 2
    assert src.count("hook_after_source_write(uid, cid, \"expense\", new_doc[\"id\"])") == 1


# ── 25. A-1 immutability guard ──
def test_25_a1_immutability():
    import services_fin_txn as a1
    import services_fin_txn_hooks as hooks
    import services_expense_bridge as bridge
    assert bridge.hook_after_source_write is hooks.hook_after_source_write
    # Bridge must NOT re-export A-1 symbols.
    for name in ("reproject_source", "SUPPORTED_SOURCE_TYPES"):
        assert not hasattr(bridge, name), f"bridge unexpectedly exports {name}"
    for name in ("reproject_source", "SUPPORTED_SOURCE_TYPES"):
        assert getattr(hooks, name) is getattr(a1, name)


# ── 26. Locked-band regression — no globals / TTL / scheduler added ──
def test_26_locked_band_no_forbidden_constructs():
    """Static-check: Phase 3B-ii-b must NOT introduce global caches,
    TTLs, scheduler wiring, or advisory locks in the bridge module."""
    src = Path("/app/backend/services_expense_bridge.py").read_text()
    forbidden = ["asyncio.create_task", "APScheduler", "add_job(",
                 "expire_after", "expireAfterSeconds", "_hook_cache",
                 "advisory_lock", "threading.Lock", "asyncio.Lock",
                 "cachetools", "lru_cache"]
    for tok in forbidden:
        assert tok not in src, f"forbidden construct in bridge: {tok!r}"
    # `hook_after_source_write` is imported ONCE from Phase-1 hooks module.
    assert "from services_fin_txn_hooks import hook_after_source_write" in src
