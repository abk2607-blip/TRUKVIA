"""Iter150B · WalletRecharge hooks — canonical projection UAT.

Verifies:
  * 6 mutation surfaces: POST/PUT/DELETE + list
  * Canonical accounting: wallet_code DEBIT + BANK/CASH CREDIT
  * Zero direct fin_txn writes in routers/wallet_recharges.py
  * Idempotency, failure queue, CLI replay
  * Tenant isolation, Day Book reflection, Accounts delta
  * Backdate any past date
  * A-1 immutability probe
  * Locked-band forbidden constructs
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
    me = d.users.find_one(
        {"email": "demo@bitumen-transport.local"}, {"_id": 0, "user_id": 1})
    assert me
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False, "limit": 1}, timeout=30)
    return me["user_id"], r.json()[0]["company_id"]


class _Ctx:
    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo()
        self.tag = uuid.uuid4().hex[:10]
        self._wrs: list[str] = []
        self._iso_uid = f"iso_wr_{self.tag}"
        self._iso_cid = f"co_iso_wr_{self.tag}"

    def create(self, wallet_code="WALLET_FASTAG", funding_mode="Bank",
               amount=1000.0, date="2026-05-15", reference="",
               remarks=""):
        r = requests.post(f"{API}/wallet-recharges", headers=HJSON, json={
            "wallet_code": wallet_code, "funding_mode": funding_mode,
            "amount": amount, "date": date, "reference": reference,
            "remarks": remarks,
        }, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        self._wrs.append(j["id"])
        return j

    def teardown(self):
        if self._wrs:
            self.d.wallet_recharges.delete_many({"id": {"$in": self._wrs}})
            self.d.fin_txn.delete_many({
                "user_id": self.uid, "source_type": "wallet_recharge",
                "source_id": {"$in": self._wrs}})
            self.d.fin_hook_failures.delete_many({
                "user_id": self.uid, "source_type": "wallet_recharge",
                "source_id": {"$in": self._wrs}})
        self.d.fin_txn.delete_many({"user_id": self._iso_uid})
        self.d.wallet_recharges.delete_many({"user_id": self._iso_uid})


@pytest.fixture
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


def _legs(ctx, wr_id):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "wallet_recharge",
         "source_id": wr_id, "status": "active"},
        {"_id": 0, "account_code": 1, "counter_account_code": 1,
         "direction": 1, "amount": 1, "ref_source_key": 1,
         "txn_type": 1, "txn_date": 1}))


# ── 01 · create · WALLET_FASTAG + Bank → 2 legs ──────────────────────────
def test_01_create_fastag_bank(ctx):
    j = ctx.create(wallet_code="WALLET_FASTAG", funding_mode="Bank",
                   amount=1000.0)
    legs = _legs(ctx, j["id"])
    assert len(legs) == 2
    debit = next(l for l in legs if l["direction"] == "in")
    credit = next(l for l in legs if l["direction"] == "out")
    assert debit["account_code"] == "WALLET_FASTAG"
    assert debit["counter_account_code"] == "BANK_DEFAULT"
    assert credit["account_code"] == "BANK_DEFAULT"
    assert credit["amount"] == debit["amount"] == 1000.0


# ── 02 · create · WALLET_FUEL + Cash ─────────────────────────────────────
def test_02_create_fuel_cash(ctx):
    j = ctx.create(wallet_code="WALLET_FUEL", funding_mode="Cash",
                   amount=750.0)
    legs = _legs(ctx, j["id"])
    codes = sorted((l["account_code"], l["direction"]) for l in legs)
    assert codes == [("CASH", "out"), ("WALLET_FUEL", "in")]


# ── 03 · UPI / IMPS not accepted (Literal enforcement) ───────────────────
def test_03_funding_mode_literal(ctx):
    r = requests.post(f"{API}/wallet-recharges", headers=HJSON, json={
        "wallet_code": "WALLET_FASTAG", "funding_mode": "UPI",
        "amount": 500.0, "date": "2026-05-15",
    }, timeout=15)
    assert r.status_code == 422


# ── 04 · unknown wallet_code rejected ────────────────────────────────────
def test_04_wallet_code_literal(ctx):
    r = requests.post(f"{API}/wallet-recharges", headers=HJSON, json={
        "wallet_code": "WALLET_UNKNOWN", "funding_mode": "Bank",
        "amount": 500.0, "date": "2026-05-15",
    }, timeout=15)
    assert r.status_code == 422


# ── 05 · amount must be > 0 ─────────────────────────────────────────────
def test_05_amount_positive(ctx):
    r = requests.post(f"{API}/wallet-recharges", headers=HJSON, json={
        "wallet_code": "WALLET_FASTAG", "funding_mode": "Bank",
        "amount": 0.0, "date": "2026-05-15",
    }, timeout=15)
    assert r.status_code == 422


# ── 06 · update refresh amount ──────────────────────────────────────────
def test_06_update_amount(ctx):
    j = ctx.create(amount=1000.0)
    r = requests.put(f"{API}/wallet-recharges/{j['id']}", headers=HJSON, json={
        "id": j["id"], "wallet_code": "WALLET_FASTAG",
        "funding_mode": "Bank", "amount": 4444.44,
        "date": "2026-05-15",
    }, timeout=15)
    assert r.status_code == 200
    legs = _legs(ctx, j["id"])
    assert len(legs) == 2 and all(l["amount"] == 4444.44 for l in legs)


# ── 07 · update funding_mode Bank→Cash refreshes account codes ──────────
def test_07_update_funding_mode(ctx):
    j = ctx.create(funding_mode="Bank")
    r = requests.put(f"{API}/wallet-recharges/{j['id']}", headers=HJSON, json={
        "id": j["id"], "wallet_code": j["wallet_code"],
        "funding_mode": "Cash", "amount": j["amount"], "date": j["date"],
    }, timeout=15)
    assert r.status_code == 200
    codes = {(l["account_code"], l["direction"]) for l in _legs(ctx, j["id"])}
    assert codes == {("CASH", "out"), (j["wallet_code"], "in")}


# ── 08 · soft-delete clears legs ────────────────────────────────────────
def test_08_soft_delete(ctx):
    j = ctx.create(amount=500.0)
    assert len(_legs(ctx, j["id"])) == 2
    r = requests.delete(f"{API}/wallet-recharges/{j['id']}", headers=H,
                        params={"reason": "test"}, timeout=15)
    assert r.status_code == 200
    assert _legs(ctx, j["id"]) == []
    # doc still exists, is_deleted=True
    doc = ctx.d.wallet_recharges.find_one({"id": j["id"]}, {"_id": 0})
    assert doc and doc["is_deleted"] is True


# ── 09 · edit-after-delete blocked ──────────────────────────────────────
def test_09_edit_after_delete(ctx):
    j = ctx.create()
    requests.delete(f"{API}/wallet-recharges/{j['id']}", headers=H, timeout=15)
    r = requests.put(f"{API}/wallet-recharges/{j['id']}", headers=HJSON, json={
        "id": j["id"], "wallet_code": j["wallet_code"],
        "funding_mode": "Bank", "amount": 999.0, "date": j["date"],
    }, timeout=15)
    assert r.status_code == 409


# ── 10 · idempotency: 3× hook → same refs ───────────────────────────────
def test_10_idempotency(ctx):
    j = ctx.create(amount=333.0)
    import services_fin_txn_hooks as hooks
    refs0 = sorted(l["ref_source_key"] for l in _legs(ctx, j["id"]))
    for _ in range(3):
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "wallet_recharge", j["id"]))
    refs1 = sorted(l["ref_source_key"] for l in _legs(ctx, j["id"]))
    assert refs0 == refs1 and len(refs1) == 2


# ── 11 · failure queue ──────────────────────────────────────────────────
def test_11_failure_queue(ctx):
    j = ctx.create()
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("wr-forced-failure")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "wallet_recharge", j["id"]))
        row = ctx.d.fin_hook_failures.find_one({
            "user_id": ctx.uid, "source_type": "wallet_recharge",
            "source_id": j["id"]}, sort=[("created_at", -1)])
        assert row and row["status"] == "pending"
        assert "wr-forced-failure" in row["error"]
    finally:
        hooks.reproject_source = orig


# ── 12 · CLI replay restores ────────────────────────────────────────────
def test_12_replay(ctx):
    j = ctx.create(amount=222.0)
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("wr-replay-forced")

    hooks.reproject_source = _boom
    try:
        ctx.d.fin_txn.delete_many({
            "user_id": ctx.uid, "source_type": "wallet_recharge",
            "source_id": j["id"]})
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "wallet_recharge", j["id"]))
    finally:
        hooks.reproject_source = orig
    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=45)
    assert res.returncode == 0, res.stderr
    row = ctx.d.fin_hook_failures.find_one({
        "user_id": ctx.uid, "source_type": "wallet_recharge",
        "source_id": j["id"]}, sort=[("created_at", -1)])
    assert row["status"] == "resolved"
    assert len(_legs(ctx, j["id"])) == 2


# ── 13 · tenant isolation ───────────────────────────────────────────────
def test_13_tenant_isolation(ctx):
    j = ctx.create(amount=100.0)
    stray_id = f"wr_iso_{ctx.tag}"
    ctx.d.wallet_recharges.insert_one({
        "id": stray_id, "user_id": ctx._iso_uid,
        "company_id": ctx._iso_cid,
        "wallet_code": "WALLET_FASTAG", "funding_mode": "Bank",
        "amount": 999.0, "date": "2026-05-15", "reference": "",
        "remarks": "", "is_deleted": False,
        "created_at": "2026-05-15T00:00:00", "created_by": "",
    })
    ctx.d.fin_txn.insert_one({
        "id": f"fintxn_iso_wr_{ctx.tag}",
        "user_id": ctx._iso_uid, "company_id": ctx._iso_cid,
        "txn_date": "2026-05-15",
        "account_id": "acc_iso", "account_code": "WALLET_FASTAG",
        "direction": "in", "amount": 999.0,
        "counter_account_code": "BANK_DEFAULT",
        "counter_account_id": "acc_iso_bank",
        "txn_type": "wallet_recharge_in",
        "source_type": "wallet_recharge", "source_id": stray_id,
        "source_key": "",
        "ref_source_key": f"wallet_recharge:{stray_id}:wallet_debit",
        "party_type": "", "party_id": "", "party_name": "",
        "vehicle_id": "", "trip_id": "", "category": "", "narration": "",
        "transfer_group_id": "", "adjustment_group_id": "",
        "reversal_of": "", "is_reversal": False, "status": "active",
        "is_supplier_settlement_recovery": False,
        "reconciled_at": "", "reconciled_ref": "",
        "created_at": "2026-05-15T00:00:00",
        "projected_at": "2026-05-15T00:00:00",
    })
    # Soft-delete our WR.
    requests.delete(f"{API}/wallet-recharges/{j['id']}", headers=H, timeout=15)
    assert _legs(ctx, j["id"]) == []
    stray = ctx.d.fin_txn.find_one({"user_id": ctx._iso_uid,
                                     "source_id": stray_id})
    assert stray and stray["status"] == "active"


# ── 14 · Day Book reflection ────────────────────────────────────────────
def test_14_day_book(ctx):
    j = ctx.create(amount=1234.0, date="2026-06-01")
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-06-01",
                             "date_to": "2026-06-01",
                             "source_type": "wallet_recharge"}, timeout=15)
    assert r.status_code == 200
    ids = {row.get("source_id") for row in r.json().get("rows", [])}
    assert j["id"] in ids


# ── 15 · Accounts delta: WALLET debit increases; BANK decreases ────────
def test_15_accounts_delta(ctx):
    def net(code):
        p = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                          "account_code": code, "status": "active"}},
             {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(p)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)
    w0 = net("WALLET_FASTAG"); b0 = net("BANK_DEFAULT")
    ctx.create(wallet_code="WALLET_FASTAG", funding_mode="Bank", amount=500.0)
    w1 = net("WALLET_FASTAG"); b1 = net("BANK_DEFAULT")
    assert round(w1 - w0, 2) == 500.0
    assert round(b1 - b0, 2) == -500.0


# ── 16 · backdate any past date ─────────────────────────────────────────
def test_16_backdate(ctx):
    j = ctx.create(date="2024-01-15", amount=100.0)
    legs = _legs(ctx, j["id"])
    assert all(l["txn_date"] == "2024-01-15" for l in legs)


# ── 17 · created_at independent of business date ────────────────────────
def test_17_created_at_distinct(ctx):
    j = ctx.create(date="2024-01-01")
    doc = ctx.d.wallet_recharges.find_one({"id": j["id"]}, {"_id": 0})
    assert doc["date"] == "2024-01-01"
    assert doc["created_at"].startswith("2026")  # today


# ── 18 · zero direct fin_txn writes in router ───────────────────────────
def test_18_zero_direct_fin_txn():
    src = Path("/app/backend/routers/wallet_recharges.py").read_text()
    for tok in ("db.fin_txn", "fin_txn.insert", "fin_txn.update",
                "fin_txn.delete"):
        assert tok not in src, f"forbidden token {tok!r}"


# ── 19 · hook wired at 3 mutation sites ─────────────────────────────────
def test_19_hook_count():
    src = Path("/app/backend/routers/wallet_recharges.py").read_text()
    # 1 import + 3 mutation sites (create/update/delete)
    assert src.count("hook_after_source_write") == 4


# ── 20 · A-1 immutability probe: SUPPORTED_SOURCE_TYPES + wallet source
def test_20_a1_immutability():
    import services_fin_txn as a1
    assert "wallet_recharge" in a1.SUPPORTED_SOURCE_TYPES
    # existing 9 types still present in order
    for t in ("invoice", "credit_debit_note", "supplier_payment",
              "vendor_payment", "mechanic_payment", "expense",
              "vendor_bill", "mechanic_work_order", "trip_customer_receipt"):
        assert t in a1.SUPPORTED_SOURCE_TYPES


# ── 21 · locked-band forbidden constructs ───────────────────────────────
def test_21_locked_band_forbidden():
    src = Path("/app/backend/routers/wallet_recharges.py").read_text()
    for tok in ("asyncio.create_task", "APScheduler", "cachetools",
                "lru_cache", "threading.Lock", "asyncio.Lock"):
        assert tok not in src


# ── 22 · list endpoint filters + soft-delete visibility ────────────────
def test_22_list_filters(ctx):
    a = ctx.create(wallet_code="WALLET_FASTAG", amount=100.0,
                    date="2026-06-01")
    b = ctx.create(wallet_code="WALLET_FUEL", amount=200.0,
                    date="2026-06-10")
    r = requests.get(f"{API}/wallet-recharges", headers=H,
                     params={"wallet_code": "WALLET_FASTAG",
                             "date_from": "2026-06-01",
                             "date_to": "2026-06-05"}, timeout=15)
    ids = [row["id"] for row in r.json()]
    assert a["id"] in ids
    assert b["id"] not in ids
    # Delete b, verify it disappears from default list, reappears with include_deleted
    requests.delete(f"{API}/wallet-recharges/{b['id']}", headers=H, timeout=15)
    r2 = requests.get(f"{API}/wallet-recharges", headers=H,
                      params={"wallet_code": "WALLET_FUEL"}, timeout=15)
    assert b["id"] not in [row["id"] for row in r2.json()]
    r3 = requests.get(f"{API}/wallet-recharges", headers=H,
                      params={"wallet_code": "WALLET_FUEL",
                              "include_deleted": True}, timeout=15)
    assert b["id"] in [row["id"] for row in r3.json()]


# ── 23 · deterministic ref_source_key format ────────────────────────────
def test_23_ref_source_key_shape(ctx):
    j = ctx.create()
    refs = sorted(l["ref_source_key"] for l in _legs(ctx, j["id"]))
    assert refs == [f"wallet_recharge:{j['id']}:funding_credit",
                    f"wallet_recharge:{j['id']}:wallet_debit"]


# ── 24 · double-click / re-post creates two separate WRs (each hooked)
def test_24_double_post(ctx):
    a = ctx.create(amount=100.0)
    b = ctx.create(amount=100.0)
    assert a["id"] != b["id"]
    assert len(_legs(ctx, a["id"])) == 2
    assert len(_legs(ctx, b["id"])) == 2
