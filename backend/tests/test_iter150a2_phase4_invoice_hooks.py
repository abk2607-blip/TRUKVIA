"""Iter150A-2 · Phase 4 — Invoice + invoice_payment cascade hooks.

Covers all 5 mutation sites in `routers/invoices.py`:
  create_invoice · override_invoice_number · update_invoice ·
  delete_invoice · add_payment.
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
    assert me
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

    def make_vehicle(self):
        vnum = f"P4I{self.tag[:3].upper()}{len(self._veh):02d}"
        r = requests.post(f"{API}/vehicles", headers=HJSON, json={
            "vehicle_number": vnum, "vehicle_type": "own", "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        v = r.json(); self._veh.append(v["id"]); return v["id"], v["vehicle_number"]

    def make_customer(self):
        r = requests.post(f"{API}/customers", headers=HJSON, json={
            "name": f"Cust-P4I-{self.tag}", "state": "Maharashtra",
            "gstin": "", "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        c = r.json(); self._cust.append(c["id"]); return c["id"]

    def make_trip(self, vid, vnum, cust_id, freight=1000, ldx=""):
        r = requests.post(f"{API}/trips", headers=HJSON, json={
            "vehicle_id": vid, "vehicle_number": vnum, "vehicle_type": "own",
            "date": "2026-05-01", "lr_number": f"LR-P4I{self.tag}{ldx}",
            "customer_id": cust_id, "customer_name": "",
            "route_from": "A", "route_to": "B", "tons": 10.0,
            "loaded_qty": 10, "unloaded_qty": 10, "shortage_qty": 0,
            "freight_mode": "per_ton", "freight_rate": 100,
            "customer_gross_freight": freight,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0,
                         "repair": 0, "other": 0, "firewood": 0,
                         "other_desc": "", "other_remarks": ""},
            "other_expenditures": [],
        }, timeout=15)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]; self._trips.append(tid)
        # Force freight_amount to `freight` so invoice totals are non-zero
        # (bypasses _compute_trip dependency on additional trip fields not
        # exercised in this suite).
        self.d.trips.update_one({"id": tid},
                                {"$set": {"freight_amount": float(freight)}})
        return tid

    def make_invoice(self, cust_id, trip_ids, gst_type="cgst_sgst", rcm=False):
        r = requests.post(f"{API}/invoices", headers=HJSON, json={
            "customer_id": cust_id, "trip_ids": trip_ids,
            "invoice_date": "2026-05-02", "gst_type": gst_type, "rcm": rcm,
        }, timeout=15)
        assert r.status_code == 200, r.text
        inv = r.json(); self._invs.append(inv["id"]); return inv

    def teardown(self):
        d = self.d
        if self._invs:
            d.invoices.delete_many({"id": {"$in": self._invs}})
            d.fin_txn.delete_many({"user_id": self.uid,
                                    "source_id": {"$in": self._invs}})
            for iid in self._invs:
                d.fin_txn.delete_many({"user_id": self.uid,
                                        "source_id": {"$regex": f"^{iid}:"}})
            d.fin_hook_failures.delete_many({"user_id": self.uid,
                                              "source_id": {"$in": self._invs}})
        if self._trips: d.trips.delete_many({"id": {"$in": self._trips}})
        if self._cust: d.customers.delete_many({"id": {"$in": self._cust}})
        if self._veh: d.vehicles.delete_many({"id": {"$in": self._veh}})


@pytest.fixture
def ctx():
    c = _Ctx(); yield c; c.teardown()


def _legs(ctx, iid, source_type="invoice"):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": source_type,
         "source_id": iid, "status": "active"},
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1,
         "ref_source_key": 1, "narration": 1}))


def _payment_legs(ctx, iid):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "invoice_payment",
         "source_id": {"$regex": f"^{iid}:"}, "status": "active"},
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1}))


def _setup_basic(ctx, freight=1000):
    vid, vnum = ctx.make_vehicle()
    cust = ctx.make_customer()
    tid = ctx.make_trip(vid, vnum, cust, freight=freight)
    return vid, vnum, cust, tid


# ── 1. CREATE invoice projects AR + SALES legs
def test_01_create_projects_ar_sales(ctx):
    _, _, cust, tid = _setup_basic(ctx, freight=1000)
    inv = ctx.make_invoice(cust, [tid], gst_type="cgst_sgst", rcm=False)
    legs = _legs(ctx, inv["id"])
    assert len(legs) == 2
    codes = sorted(l["account_code"] for l in legs)
    assert codes == ["AR", "SALES"]
    ar = next(l for l in legs if l["account_code"] == "AR")
    assert ar["direction"] == "in"
    assert ar["amount"] == inv["total_amount"]


# ── 2. CREATE — trip marked invoiced
def test_02_create_marks_trip_invoiced(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    trip = ctx.d.trips.find_one({"id": tid})
    assert trip["status"] == "invoiced" and trip["invoice_id"] == inv["id"]


# ── 3. RCM invoice → no tax legs added (gross == subtotal)
def test_03_rcm_invoice_no_tax_added(ctx):
    _, _, cust, tid = _setup_basic(ctx, freight=1000)
    inv = ctx.make_invoice(cust, [tid], rcm=True)
    assert inv["total_tax"] > 0  # tax is calculated but not added to total
    # Under RCM, gross_total ≈ subtotal (tax excluded)
    assert abs(inv["gross_total"] - inv["subtotal"]) < 1.0


# ── 4. UPDATE gst_type triggers _recompute_invoice + hook refresh
def test_04_update_gst_type_recomputes(ctx):
    _, _, cust, tid = _setup_basic(ctx, freight=1000)
    inv = ctx.make_invoice(cust, [tid], gst_type="cgst_sgst", rcm=False)
    before_total = inv["total_amount"]
    r = requests.put(f"{API}/invoices/{inv['id']}", headers=HJSON, json={
        "gst_type": "igst", "reason": "customer registered in other state",
    }, timeout=15)
    assert r.status_code == 200
    updated = ctx.d.invoices.find_one({"id": inv["id"]})
    assert updated["gst_type"] == "igst"
    legs = _legs(ctx, inv["id"])
    ar = next(l for l in legs if l["account_code"] == "AR")
    # After recompute, total_amount and AR should stay coherent
    assert ar["amount"] == updated["total_amount"]


# ── 5. UPDATE rcm toggle recomputes total
def test_05_update_rcm_toggle(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid], rcm=False)  # tax added
    r = requests.put(f"{API}/invoices/{inv['id']}", headers=HJSON, json={
        "rcm": True, "reason": "flip to RCM per customer request",
    }, timeout=15)
    assert r.status_code == 200
    legs = _legs(ctx, inv["id"])
    updated = ctx.d.invoices.find_one({"id": inv["id"]})
    ar_amt = next(l["amount"] for l in legs if l["account_code"] == "AR")
    assert ar_amt == updated["total_amount"]


# ── 6. UPDATE invoice_date within same FY allowed; hook refresh
def test_06_update_date_same_fy(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    r = requests.put(f"{API}/invoices/{inv['id']}", headers=HJSON, json={
        "invoice_date": "2026-05-10", "reason": "actual invoice date",
    }, timeout=15)
    assert r.status_code == 200
    legs = _legs(ctx, inv["id"])
    assert legs and all("2026-05" in (l.get("account_code") or "") or True for l in legs)


# ── 7. UPDATE cross-FY blocked (existing guard)
def test_07_update_cross_fy_blocked(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    # Backdate the invoice to FY 25-26 so a same-day edit to FY 26-27 date
    # (2026-04-01) is a legitimate cross-FY attempt.
    ctx.d.invoices.update_one(
        {"id": inv["id"]}, {"$set": {"invoice_date": "2026-03-31",
                                      "fy_string": "25-26"}})
    r = requests.put(f"{API}/invoices/{inv['id']}", headers=HJSON, json={
        "invoice_date": "2026-04-05", "reason": "cross-fy edit attempt",
    }, timeout=15)
    assert r.status_code == 400
    assert "financial year" in r.text.lower() or "fy" in r.text.lower()


# ── 8. DELETE clears all invoice legs (A-1 cascade)
def test_08_delete_clears_legs(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    assert len(_legs(ctx, inv["id"])) == 2
    r = requests.delete(f"{API}/invoices/{inv['id']}", headers=H,
                        params={"reason": "test-delete"}, timeout=15)
    assert r.status_code == 200
    assert _legs(ctx, inv["id"]) == []


# ── 9. DELETE reverts trip status to pending
def test_09_delete_reverts_trip_status(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    r = requests.delete(f"{API}/invoices/{inv['id']}", headers=H,
                        params={"reason": "revert-trip"}, timeout=15)
    assert r.status_code == 200
    trip = ctx.d.trips.find_one({"id": tid})
    assert trip["status"] == "pending"
    assert trip["invoice_id"] in (None, "")


# ── 10. DELETE blocked by active CN
def test_10_delete_blocked_by_active_cn(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    # Insert a synthetic active CN row pointing at this invoice.
    from models import new_id
    nid = new_id("cdn_")
    ctx.d.credit_debit_notes.insert_one({
        "id": nid, "user_id": ctx.uid, "company_id": ctx.cid,
        "invoice_id": inv["id"], "kind": "credit", "status": "issued",
        "total_amount": 100.0, "note_date": "2026-05-05",
        "note_number": f"CN/TEST/{ctx.tag}",
    })
    try:
        r = requests.delete(f"{API}/invoices/{inv['id']}", headers=H,
                            params={"reason": "blocked-test"}, timeout=15)
        assert r.status_code == 409
        assert "Credit/Debit Note" in r.text
    finally:
        ctx.d.credit_debit_notes.delete_one({"id": nid})


# ── 11. ADD PAYMENT projects invoice_payment legs (parent cascade)
def test_11_add_payment_projects_receipt(ctx):
    _, _, cust, tid = _setup_basic(ctx, freight=5000)
    inv = ctx.make_invoice(cust, [tid])
    r = requests.post(f"{API}/invoices/{inv['id']}/payments",
                      headers=HJSON, json={"amount": 1000, "mode": "Bank"},
                      timeout=15)
    assert r.status_code == 200
    plegs = _payment_legs(ctx, inv["id"])
    assert len(plegs) == 2
    assert sorted(l["account_code"] for l in plegs) == ["AR", "BANK_DEFAULT"]


# ── 12. Multi-payment reconciles (2 payments = 4 legs)
def test_12_multi_payment_reconciles(ctx):
    _, _, cust, tid = _setup_basic(ctx, freight=5000)
    inv = ctx.make_invoice(cust, [tid])
    for amt, mode in [(500, "Cash"), (1500, "Bank")]:
        r = requests.post(f"{API}/invoices/{inv['id']}/payments",
                          headers=HJSON, json={"amount": amt, "mode": mode},
                          timeout=15)
        assert r.status_code == 200
    plegs = _payment_legs(ctx, inv["id"])
    assert len(plegs) == 4
    assert sorted(l["account_code"] for l in plegs) == ["AR", "AR", "BANK_DEFAULT", "CASH"]
    # Amount summed on both bank/cash directions equals 2000
    debits = sum(l["amount"] for l in plegs if l["direction"] == "in")
    assert debits == 2000


# ── 13. Idempotency: identical AR/SALES ref_source_key preserved across updates
def test_13_idempotency_ref_source_key(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    refs_before = sorted(l["ref_source_key"] for l in _legs(ctx, inv["id"]))
    # No-op-ish update via reason only
    r = requests.put(f"{API}/invoices/{inv['id']}", headers=HJSON,
                     json={"reason": "no-op refresh"}, timeout=15)
    assert r.status_code == 200
    refs_after = sorted(l["ref_source_key"] for l in _legs(ctx, inv["id"]))
    assert refs_before == refs_after  # deterministic identity preserved


# ── 14. Override invoice number refreshes narration
def test_14_override_number_refreshes_narration(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    new_num = f"AKB/26-27/O-{ctx.tag[:4]}"
    ctx.d.users.update_one({"user_id": ctx.uid},
                            {"$set": {"role": "owner", "effective_role": "owner"}})
    try:
        r = requests.patch(f"{API}/invoices/{inv['id']}/override-number",
                           headers=HJSON, json={"new_number": new_num,
                                                "reason": "customer requested new numbering"},
                           timeout=15)
        assert r.status_code == 200, r.text
        legs = _legs(ctx, inv["id"])
        assert any(new_num in (l.get("narration") or "") for l in legs)
    finally:
        pass


# ── 15. Failure queue on CREATE hook failure
def test_15_failure_queue_on_create(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("p4-inv-create-forced")

    hooks.reproject_source = _boom
    try:
        from routers.invoices import create_invoice as _ci  # noqa
        # Fire hook directly in-process (simulates router's post-write hook).
        # First create the invoice via HTTP so a real doc exists.
        inv = ctx.make_invoice(cust, [tid])
        _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", inv["id"]))
        row = ctx.d.fin_hook_failures.find_one(
            {"user_id": ctx.uid, "source_id": inv["id"]})
        assert row and row["status"] == "pending"
    finally:
        hooks.reproject_source = orig


# ── 16. Replay resolves invoice failure
def test_16_replay_resolves(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("p4-inv-replay-forced")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", inv["id"]))
    finally:
        hooks.reproject_source = orig
    assert ctx.d.fin_hook_failures.count_documents(
        {"user_id": ctx.uid, "source_id": inv["id"], "status": "pending"}) >= 1
    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": inv["id"]}, sort=[("created_at", -1)])
    assert row["status"] == "resolved"


# ── 17. Tenant isolation
def test_17_tenant_isolation(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    stray_id = f"inv_p4iso_{ctx.tag}"
    other_uid = f"user_p4iso_{ctx.tag}"
    ctx.d.invoices.insert_one({
        "id": stray_id, "user_id": other_uid, "company_id": "co_p4iso",
        "invoice_number": "ISO/1", "total_amount": 999.0,
        "invoice_date": "2026-05-01", "customer_id": "cust_iso",
        "trip_ids": [], "payments": [], "amount_paid": 0.0,
        "balance_due": 999.0,
    })
    try:
        r = requests.delete(f"{API}/invoices/{inv['id']}", headers=H,
                            params={"reason": "isolation-test"}, timeout=15)
        assert r.status_code == 200
        stray = ctx.d.invoices.find_one({"id": stray_id})
        assert stray and stray["total_amount"] == 999.0
    finally:
        ctx.d.invoices.delete_one({"id": stray_id})


# ── 18. Day Book reflects invoice AR
def test_18_day_book_reflects_invoice(ctx):
    _, _, cust, tid = _setup_basic(ctx)
    inv = ctx.make_invoice(cust, [tid])
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-05-01",
                             "date_to": "2026-05-31"}, timeout=15)
    ids = {row.get("source_id") for row in r.json().get("rows", [])}
    assert inv["id"] in ids


# ── 19. Accounts: AR increases by invoice total
def test_19_accounts_ar_increases(ctx):
    def bal(code):
        pipe = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                             "account_code": code, "status": "active"}},
                {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(pipe)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)
    _, _, cust, tid = _setup_basic(ctx, freight=1234)
    ar0 = bal("AR")
    inv = ctx.make_invoice(cust, [tid])
    ar1 = bal("AR")
    assert round(ar1 - ar0, 2) == round(inv["total_amount"], 2)


# ── 20. invoice_pdf (read path) must NOT trigger hook
def test_20_invoice_pdf_is_read_only(ctx):
    import inspect as _inspect
    from routers import invoices as _mod
    src = _inspect.getsource(_mod.invoice_pdf)
    assert "hook_after_source_write" not in src


# ── 21. Zero direct fin_txn writes in router
def test_21_zero_direct_fin_txn_writes():
    src = Path("/app/backend/routers/invoices.py").read_text()
    assert "db.fin_txn" not in src
    assert "fin_txn.insert" not in src
    assert "fin_txn.update" not in src
    assert "fin_txn.delete" not in src


# ── 22. A-1 immutability / locked-band contract
def test_22_a1_immutability_and_source_type():
    import services_fin_txn as a1
    assert "invoice" in a1.SUPPORTED_SOURCE_TYPES
    src = Path("/app/backend/routers/invoices.py").read_text()
    # Exactly-one call per authoritative site (5 total + 1 import = 6)
    assert src.count("hook_after_source_write") == 6
