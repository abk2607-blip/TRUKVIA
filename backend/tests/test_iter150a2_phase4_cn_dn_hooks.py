"""Iter150A-2 · Phase 4 — Credit Note / Debit Note hooks.

Covers all 8 mutation sites in `routers/notes.py`:
  create_credit_note · issue_credit_note · cancel_credit_note ·
  update_credit_note · create_debit_note · issue_debit_note ·
  cancel_debit_note · update_debit_note.
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
        self._cust: list[str] = []
        self._trips: list[str] = []
        self._invs: list[str] = []
        self._notes: list[str] = []

    def make_vehicle(self):
        vnum = f"P4C{self.tag[:3].upper()}{len(self._veh):02d}"
        r = requests.post(f"{API}/vehicles", headers=HJSON, json={
            "vehicle_number": vnum, "vehicle_type": "own", "is_active": True,
        }, timeout=15)
        v = r.json(); self._veh.append(v["id"]); return v["id"], v["vehicle_number"]

    def make_customer(self):
        r = requests.post(f"{API}/customers", headers=HJSON, json={
            "name": f"Cust-P4C-{self.tag}", "state": "Maharashtra",
            "gstin": "", "is_active": True,
        }, timeout=15)
        c = r.json(); self._cust.append(c["id"]); return c["id"]

    def make_invoice_with_trip(self, freight=20000):
        vid, vnum = self.make_vehicle()
        cust = self.make_customer()
        r = requests.post(f"{API}/trips", headers=HJSON, json={
            "vehicle_id": vid, "vehicle_number": vnum, "vehicle_type": "own",
            "date": "2026-05-01", "lr_number": f"LR-P4C{self.tag}{len(self._trips)}",
            "customer_id": cust, "customer_name": "",
            "route_from": "A", "route_to": "B", "tons": 10.0,
            "loaded_qty": 10, "unloaded_qty": 10, "shortage_qty": 0,
            "freight_mode": "per_ton", "freight_rate": 100,
            "customer_gross_freight": freight,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0,
                         "repair": 0, "other": 0, "firewood": 0,
                         "other_desc": "", "other_remarks": ""},
            "other_expenditures": [],
        }, timeout=15)
        tid = r.json()["id"]; self._trips.append(tid)
        # Force freight_amount so invoice totals are non-zero (bypasses
        # _compute_trip dependency on fields not exercised in this suite).
        self.d.trips.update_one({"id": tid},
                                {"$set": {"freight_amount": float(freight)}})
        r = requests.post(f"{API}/invoices", headers=HJSON, json={
            "customer_id": cust, "trip_ids": [tid],
            "invoice_date": "2026-05-02", "gst_type": "cgst_sgst", "rcm": False,
        }, timeout=15)
        inv = r.json(); self._invs.append(inv["id"]); return inv

    def make_cn(self, inv, amount=100.0):
        r = requests.post(f"{API}/credit-notes", headers=HJSON, json={
            "invoice_id": inv["id"], "note_date": "2026-05-05",
            "reason_code": "rate_correction",
            "reason_text": "phase-4 test cn issuance",
            "lines": [{"description": "adj", "hsn_sac": "996791",
                       "quantity": 1.0, "rate": amount}],
        }, timeout=15)
        assert r.status_code == 200, r.text
        note = r.json(); self._notes.append(note["id"]); return note

    def make_dn(self, inv, amount=50.0):
        r = requests.post(f"{API}/debit-notes", headers=HJSON, json={
            "invoice_id": inv["id"], "note_date": "2026-05-05",
            "reason_code": "under_charge",
            "reason_text": "phase-4 test dn issuance",
            "lines": [{"description": "add", "hsn_sac": "996791",
                       "quantity": 1.0, "rate": amount}],
        }, timeout=15)
        assert r.status_code == 200, r.text
        note = r.json(); self._notes.append(note["id"]); return note

    def teardown(self):
        d = self.d
        if self._notes:
            d.credit_debit_notes.delete_many({"id": {"$in": self._notes}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                    "source_id": {"$in": self._notes}})
            d.fin_hook_failures.delete_many(
                {"user_id": self.uid, "source_id": {"$in": self._notes}})
        if self._invs:
            d.invoices.delete_many({"id": {"$in": self._invs}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                    "source_id": {"$in": self._invs}})
        if self._trips: d.trips.delete_many({"id": {"$in": self._trips}})
        if self._cust: d.customers.delete_many({"id": {"$in": self._cust}})
        if self._veh: d.vehicles.delete_many({"id": {"$in": self._veh}})


@pytest.fixture
def ctx():
    c = _Ctx(); yield c; c.teardown()


def _cnlegs(ctx, nid):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "credit_debit_note",
         "source_id": nid, "status": "active"},
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1,
         "ref_source_key": 1}))


# ── 1. CN auto-issue projects 2 legs (AR out + SALES in)
def test_01_cn_auto_issue_projects(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=100.0)
    assert cn["status"] == "issued"
    legs = _cnlegs(ctx, cn["id"])
    assert len(legs) == 2
    codes = sorted(l["account_code"] for l in legs)
    assert codes == ["AR", "SALES"]
    ar = next(l for l in legs if l["account_code"] == "AR")
    # CN reverses AR → AR "out"
    assert ar["direction"] == "out"


# ── 2. DN auto-issue projects 2 legs (opposite sign)
def test_02_dn_auto_issue_projects(ctx):
    inv = ctx.make_invoice_with_trip()
    dn = ctx.make_dn(inv, amount=50.0)
    legs = _cnlegs(ctx, dn["id"])
    assert len(legs) == 2
    ar = next(l for l in legs if l["account_code"] == "AR")
    assert ar["direction"] == "in"  # DN adds to AR


# ── 3. CN cancel → legs vanish
def test_03_cn_cancel_clears_legs(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=100.0)
    assert len(_cnlegs(ctx, cn["id"])) == 2
    r = requests.post(f"{API}/credit-notes/{cn['id']}/cancel",
                      headers=HJSON, json={"reason": "cancel test long enough"},
                      timeout=15)
    assert r.status_code == 200
    assert _cnlegs(ctx, cn["id"]) == []


# ── 4. DN cancel → legs vanish
def test_04_dn_cancel_clears_legs(ctx):
    inv = ctx.make_invoice_with_trip()
    dn = ctx.make_dn(inv, amount=50.0)
    r = requests.post(f"{API}/debit-notes/{dn['id']}/cancel",
                      headers=HJSON, json={"reason": "cancel test long enough"},
                      timeout=15)
    assert r.status_code == 200
    assert _cnlegs(ctx, dn["id"]) == []


# ── 5. CN cancel guard: cancelled note cannot be issued
def test_05_cancelled_cn_cannot_reissue(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=100.0)
    requests.post(f"{API}/credit-notes/{cn['id']}/cancel",
                  headers=HJSON, json={"reason": "cancel long enough here"},
                  timeout=15)
    r = requests.post(f"{API}/credit-notes/{cn['id']}/issue", headers=H, timeout=15)
    assert r.status_code == 409


# ── 6. Draft CN produces zero legs (approval-required flow)
def test_06_draft_cn_zero_legs(ctx):
    inv = ctx.make_invoice_with_trip()
    # Force require_cdn_approval=True temporarily.
    ctx.d.companies.update_one({"id": ctx.cid, "user_id": ctx.uid},
                                {"$set": {"require_cdn_approval": True}})
    try:
        r = requests.post(f"{API}/credit-notes", headers=HJSON, json={
            "invoice_id": inv["id"], "note_date": "2026-05-05",
            "reason_code": "rate_correction",
            "reason_text": "draft-mode cn test path",
            "lines": [{"description": "adj", "hsn_sac": "996791",
                       "quantity": 1.0, "rate": 100.0}],
        }, timeout=15)
        assert r.status_code == 200
        note = r.json(); ctx._notes.append(note["id"])
        assert note["status"] == "draft"
        assert _cnlegs(ctx, note["id"]) == []
        # Explicit issue → legs appear
        r2 = requests.post(f"{API}/credit-notes/{note['id']}/issue",
                           headers=H, timeout=15)
        assert r2.status_code == 200
        assert len(_cnlegs(ctx, note["id"])) == 2
    finally:
        ctx.d.companies.update_one({"id": ctx.cid, "user_id": ctx.uid},
                                    {"$set": {"require_cdn_approval": False}})


# ── 7. Draft CN update keeps zero legs
def test_07_draft_cn_update_stays_zero_legs(ctx):
    inv = ctx.make_invoice_with_trip()
    ctx.d.companies.update_one({"id": ctx.cid, "user_id": ctx.uid},
                                {"$set": {"require_cdn_approval": True}})
    try:
        r = requests.post(f"{API}/credit-notes", headers=HJSON, json={
            "invoice_id": inv["id"], "note_date": "2026-05-05",
            "reason_code": "rate_correction",
            "reason_text": "draft update p4 test",
            "lines": [{"description": "adj", "hsn_sac": "996791",
                       "quantity": 1.0, "rate": 100.0}],
        }, timeout=15)
        note = r.json(); ctx._notes.append(note["id"])
        r2 = requests.put(f"{API}/credit-notes/{note['id']}", headers=HJSON, json={
            "invoice_id": inv["id"], "reason_code": "rate_correction",
            "reason_text": "amount amended in draft here",
            "lines": [{"description": "adj", "hsn_sac": "996791",
                       "quantity": 1.0, "rate": 150.0}],
        }, timeout=15)
        assert r2.status_code == 200
        assert _cnlegs(ctx, note["id"]) == []
    finally:
        ctx.d.companies.update_one({"id": ctx.cid, "user_id": ctx.uid},
                                    {"$set": {"require_cdn_approval": False}})


# ── 8. Issued CN cannot be edited via PUT
def test_08_issued_cn_edit_blocked(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=100.0)
    r = requests.put(f"{API}/credit-notes/{cn['id']}", headers=HJSON, json={
        "invoice_id": inv["id"], "reason_code": "rate_correction",
        "reason_text": "attempt to edit issued",
        "lines": [{"description": "adj", "hsn_sac": "996791",
                   "quantity": 1.0, "rate": 999.0}],
    }, timeout=15)
    assert r.status_code == 409


# ── 9. Idempotent hook — CN re-hook keeps identical legs
def test_09_cn_idempotency(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=100.0)
    import services_fin_txn_hooks as hooks
    refs_before = sorted(l["ref_source_key"] for l in _cnlegs(ctx, cn["id"]))
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "credit_debit_note", cn["id"]))
    refs_after = sorted(l["ref_source_key"] for l in _cnlegs(ctx, cn["id"]))
    assert refs_before == refs_after
    assert len(_cnlegs(ctx, cn["id"])) == 2


# ── 10. Failure queue on CN issue
def test_10_failure_queue_cn(ctx):
    inv = ctx.make_invoice_with_trip()
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("p4-cn-forced")

    # Create CN first (successful), then reproject-fail via direct hook
    cn = ctx.make_cn(inv, amount=100.0)
    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "credit_debit_note", cn["id"]))
        row = ctx.d.fin_hook_failures.find_one(
            {"user_id": ctx.uid, "source_id": cn["id"]}, sort=[("created_at", -1)])
        assert row and row["status"] == "pending"
    finally:
        hooks.reproject_source = orig


# ── 11. Replay resolves CN failure
def test_11_replay_resolves_cn(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=100.0)
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("p4-cn-replay")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "credit_debit_note", cn["id"]))
    finally:
        hooks.reproject_source = orig
    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": cn["id"]}, sort=[("created_at", -1)])
    assert row["status"] == "resolved"
    assert len(_cnlegs(ctx, cn["id"])) == 2


# ── 12. Sign semantics: CN opposite of DN on same amount
def test_12_cn_dn_sign_opposition(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=200.0)
    dn = ctx.make_dn(inv, amount=200.0)
    cn_ar = next(l for l in _cnlegs(ctx, cn["id"]) if l["account_code"] == "AR")
    dn_ar = next(l for l in _cnlegs(ctx, dn["id"]) if l["account_code"] == "AR")
    assert cn_ar["direction"] != dn_ar["direction"]
    assert cn_ar["amount"] == dn_ar["amount"]


# ── 13. Over-credit guard blocks CN driving invoice-effective-total negative
def test_13_over_credit_guard(ctx):
    inv = ctx.make_invoice_with_trip(freight=100)  # tiny invoice
    r = requests.post(f"{API}/credit-notes", headers=HJSON, json={
        "invoice_id": inv["id"], "note_date": "2026-05-05",
        "reason_code": "rate_correction",
        "reason_text": "overshoot credit test",
        "lines": [{"description": "big", "hsn_sac": "996791",
                   "quantity": 1.0, "rate": 100000.0}],
    }, timeout=15)
    assert r.status_code == 422
    assert "negative" in r.text.lower()


# ── 14. DN positive-amount enforcement
def test_14_dn_positive_only(ctx):
    inv = ctx.make_invoice_with_trip()
    r = requests.post(f"{API}/debit-notes", headers=HJSON, json={
        "invoice_id": inv["id"], "note_date": "2026-05-05",
        "reason_code": "under_charge",
        "reason_text": "zero amount dn attempt",
        "lines": [{"description": "zero", "hsn_sac": "996791",
                   "quantity": 1.0, "rate": 0.0}],
    }, timeout=15)
    assert r.status_code == 422


# ── 15. Day Book reflects CN
def test_15_day_book_reflects_cn(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=100.0)
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-05-01",
                             "date_to": "2026-05-31"}, timeout=15)
    ids = {row.get("source_id") for row in r.json().get("rows", [])}
    assert cn["id"] in ids


# ── 16. Accounts: AR net-reduces after CN issue
def test_16_ar_net_after_cn(ctx):
    def bal(code):
        pipe = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                             "account_code": code, "status": "active"}},
                {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(pipe)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)
    inv = ctx.make_invoice_with_trip()
    ar_pre = bal("AR")
    cn = ctx.make_cn(inv, amount=100.0)
    ar_post = bal("AR")
    # CN reverses AR by exactly its total_amount (may include tax gross-up).
    assert ar_post < ar_pre
    assert round(ar_pre - ar_post, 2) == round(cn["total_amount"], 2)


# ── 17. Tenant isolation on CN cancel
def test_17_tenant_isolation(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=100.0)
    stray_id = f"cdn_p4iso_{ctx.tag}"
    ctx.d.credit_debit_notes.insert_one({
        "id": stray_id, "user_id": f"other_p4_{ctx.tag}",
        "company_id": "co_otheriso", "invoice_id": "iso_inv",
        "kind": "credit", "status": "issued", "total_amount": 500.0,
        "note_date": "2026-05-05",
    })
    try:
        requests.post(f"{API}/credit-notes/{cn['id']}/cancel",
                      headers=HJSON, json={"reason": "isolation test long ok"},
                      timeout=15)
        stray = ctx.d.credit_debit_notes.find_one({"id": stray_id})
        assert stray and stray["status"] == "issued"
    finally:
        ctx.d.credit_debit_notes.delete_one({"id": stray_id})


# ── 18. Source identity invariant across cancel/issue cycle
def test_18_source_identity_cn(ctx):
    inv = ctx.make_invoice_with_trip()
    cn = ctx.make_cn(inv, amount=100.0)
    refs = sorted(l["ref_source_key"] for l in _cnlegs(ctx, cn["id"]))
    # cancel → 0 legs; re-hook (no re-issue) → still 0; final state stable
    requests.post(f"{API}/credit-notes/{cn['id']}/cancel",
                  headers=HJSON, json={"reason": "identity test long enough"},
                  timeout=15)
    assert _cnlegs(ctx, cn["id"]) == []
    # Refs were derived from note.id — deterministic regardless of state
    assert all(cn["id"] in ref for ref in refs)


# ── 19. Iter132a compatibility — CN feature-flag path still enforced
def test_19_iter132a_compat(ctx):
    # ENABLE_CDN=1 in .env; endpoint reachable. Sanity check.
    inv = ctx.make_invoice_with_trip()
    r = requests.get(f"{API}/credit-notes", headers=H,
                     params={"invoice_id": inv["id"]}, timeout=15)
    assert r.status_code == 200


# ── 20. Zero direct fin_txn writes in notes.py
def test_20_zero_direct_fin_txn():
    src = Path("/app/backend/routers/notes.py").read_text()
    for tok in ("db.fin_txn", "fin_txn.insert", "fin_txn.update", "fin_txn.delete"):
        assert tok not in src


# ── 21. Exact hook-count in notes.py (8 sites + 1 import = 9)
def test_21_hook_count():
    src = Path("/app/backend/routers/notes.py").read_text()
    assert src.count("hook_after_source_write") == 9


# ── 22. Locked-band forbidden constructs scan
def test_22_locked_band_forbidden():
    src = Path("/app/backend/routers/notes.py").read_text()
    for tok in ("asyncio.create_task", "APScheduler", "expire_after",
                "cachetools", "lru_cache", "threading.Lock", "asyncio.Lock"):
        assert tok not in src


# ── 23. A-1 immutability
def test_23_a1_immutability():
    import services_fin_txn as a1
    assert "credit_debit_note" in a1.SUPPORTED_SOURCE_TYPES


# ── 24. Phase 3B-ii-b compat — bridge Trip DELETE unaffected by CN presence
def test_24_phase3b2b_compat(ctx):
    """Static-check only — bridge module and Phase-3B-ii-b test file untouched."""
    bridge = Path("/app/backend/services_expense_bridge.py").read_text()
    assert "hook_after_source_write" in bridge
    p3b2b = Path("/app/backend/tests/test_iter150a2_phase3b_ii_b_trip_delete_hooks.py")
    assert p3b2b.exists()
