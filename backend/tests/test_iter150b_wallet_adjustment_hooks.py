"""Iter150B · WalletAdjustment hooks — SUSPENSE contra + append-only reversal."""
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
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False, "limit": 1}, timeout=30)
    return me["user_id"], r.json()[0]["company_id"]


class _Ctx:
    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo()
        self.tag = uuid.uuid4().hex[:10]
        self._was: list[str] = []
        self._iso_uid = f"iso_wa_{self.tag}"
        self._iso_cid = f"co_iso_wa_{self.tag}"

    def create(self, wallet_code="WALLET_FASTAG", direction="increase",
               amount=100.0, date="2026-05-15", reason="stock take"):
        r = requests.post(f"{API}/wallet-adjustments", headers=HJSON, json={
            "wallet_code": wallet_code, "direction": direction,
            "amount": amount, "date": date, "reason": reason,
        }, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        self._was.append(j["id"])
        return j

    def reverse(self, wa_id, date="2026-05-16", reason="mistake"):
        r = requests.post(f"{API}/wallet-adjustments/{wa_id}/reverse",
                          headers=HJSON, json={"date": date, "reason": reason},
                          timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        self._was.append(j["id"])
        return j

    def teardown(self):
        if self._was:
            self.d.wallet_adjustments.delete_many({"id": {"$in": self._was}})
            self.d.fin_txn.delete_many({
                "user_id": self.uid, "source_type": "wallet_adjustment",
                "source_id": {"$in": self._was}})
            self.d.fin_hook_failures.delete_many({
                "user_id": self.uid, "source_type": "wallet_adjustment",
                "source_id": {"$in": self._was}})
        self.d.fin_txn.delete_many({"user_id": self._iso_uid})
        self.d.wallet_adjustments.delete_many({"user_id": self._iso_uid})


@pytest.fixture
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


def _legs(ctx, wa_id):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "wallet_adjustment",
         "source_id": wa_id, "status": "active"},
        {"_id": 0, "account_code": 1, "counter_account_code": 1,
         "direction": 1, "amount": 1, "ref_source_key": 1,
         "txn_type": 1, "txn_date": 1}))


# 01 · create positive · Wallet DEBIT + SUSPENSE CREDIT
def test_01_create_positive(ctx):
    j = ctx.create(direction="increase", amount=200.0)
    legs = _legs(ctx, j["id"])
    codes = sorted((l["account_code"], l["direction"]) for l in legs)
    assert codes == [("SUSPENSE", "out"), ("WALLET_FASTAG", "in")]
    assert all(l["amount"] == 200.0 for l in legs)


# 02 · create negative · Wallet CREDIT + SUSPENSE DEBIT
def test_02_create_negative(ctx):
    j = ctx.create(direction="decrease", amount=150.0)
    legs = _legs(ctx, j["id"])
    codes = sorted((l["account_code"], l["direction"]) for l in legs)
    assert codes == [("SUSPENSE", "in"), ("WALLET_FASTAG", "out")]


# 03 · reason required
def test_03_reason_required(ctx):
    r = requests.post(f"{API}/wallet-adjustments", headers=HJSON, json={
        "wallet_code": "WALLET_FASTAG", "direction": "increase",
        "amount": 50.0, "date": "2026-05-15", "reason": "",
    }, timeout=15)
    assert r.status_code == 422


# 04 · amount > 0
def test_04_amount_positive(ctx):
    r = requests.post(f"{API}/wallet-adjustments", headers=HJSON, json={
        "wallet_code": "WALLET_FASTAG", "direction": "increase",
        "amount": 0.0, "date": "2026-05-15", "reason": "x",
    }, timeout=15)
    assert r.status_code == 422


# 05 · Literal enforcement
def test_05_literal_enforcement(ctx):
    r = requests.post(f"{API}/wallet-adjustments", headers=HJSON, json={
        "wallet_code": "WALLET_UNKNOWN", "direction": "increase",
        "amount": 10.0, "date": "2026-05-15", "reason": "x",
    }, timeout=15)
    assert r.status_code == 422
    r2 = requests.post(f"{API}/wallet-adjustments", headers=HJSON, json={
        "wallet_code": "WALLET_FASTAG", "direction": "+",
        "amount": 10.0, "date": "2026-05-15", "reason": "x",
    }, timeout=15)
    assert r2.status_code == 422


# 06 · update refresh amount + direction
def test_06_update(ctx):
    j = ctx.create(direction="increase", amount=100.0)
    r = requests.put(f"{API}/wallet-adjustments/{j['id']}", headers=HJSON, json={
        "id": j["id"], "wallet_code": j["wallet_code"],
        "direction": "decrease", "amount": 350.0,
        "date": j["date"], "reason": "flip",
    }, timeout=15)
    assert r.status_code == 200
    codes = sorted((l["account_code"], l["direction"]) for l in _legs(ctx, j["id"]))
    assert codes == [("SUSPENSE", "in"), ("WALLET_FASTAG", "out")]
    assert all(l["amount"] == 350.0 for l in _legs(ctx, j["id"]))


# 07 · soft-delete clears legs
def test_07_soft_delete(ctx):
    j = ctx.create(amount=100.0)
    assert len(_legs(ctx, j["id"])) == 2
    r = requests.delete(f"{API}/wallet-adjustments/{j['id']}", headers=H,
                        params={"reason": "test"}, timeout=15)
    assert r.status_code == 200
    assert _legs(ctx, j["id"]) == []


# 08 · reverse happy path — original preserved, offsetting entry created
def test_08_reverse(ctx):
    orig = ctx.create(direction="increase", amount=250.0,
                       date="2026-05-15")
    rev = ctx.reverse(orig["id"], date="2026-05-16", reason="user error")
    # original still projected
    orig_legs = _legs(ctx, orig["id"])
    assert len(orig_legs) == 2
    orig_codes = sorted((l["account_code"], l["direction"]) for l in orig_legs)
    assert orig_codes == [("SUSPENSE", "out"), ("WALLET_FASTAG", "in")]
    # reversal projected with opposite direction
    rev_legs = _legs(ctx, rev["id"])
    assert len(rev_legs) == 2
    rev_codes = sorted((l["account_code"], l["direction"]) for l in rev_legs)
    assert rev_codes == [("SUSPENSE", "in"), ("WALLET_FASTAG", "out")]
    # reverses_id set on the reversal doc
    assert rev["reverses_id"] == orig["id"]
    assert rev["direction"] == "decrease"
    assert rev["amount"] == 250.0
    # original doc UNCHANGED
    orig_doc = ctx.d.wallet_adjustments.find_one({"id": orig["id"]}, {"_id": 0})
    assert orig_doc["is_deleted"] is False
    assert orig_doc["reverses_id"] == ""
    assert orig_doc["direction"] == "increase"


# 09 · reverse-a-reversal blocked 409
def test_09_reverse_a_reversal(ctx):
    orig = ctx.create()
    rev = ctx.reverse(orig["id"])
    r = requests.post(f"{API}/wallet-adjustments/{rev['id']}/reverse",
                      headers=HJSON,
                      json={"date": "2026-05-17", "reason": "x"}, timeout=15)
    assert r.status_code == 409


# 10 · double-reverse blocked (only one active reversal per original)
def test_10_double_reverse(ctx):
    orig = ctx.create()
    ctx.reverse(orig["id"])
    r = requests.post(f"{API}/wallet-adjustments/{orig['id']}/reverse",
                      headers=HJSON,
                      json={"date": "2026-05-17", "reason": "x"}, timeout=15)
    assert r.status_code == 409


# 11 · edit-when-referenced blocked
def test_11_edit_when_referenced(ctx):
    orig = ctx.create()
    ctx.reverse(orig["id"])
    r = requests.put(f"{API}/wallet-adjustments/{orig['id']}",
                     headers=HJSON, json={
                         "id": orig["id"], "wallet_code": orig["wallet_code"],
                         "direction": orig["direction"],
                         "amount": 999.0, "date": orig["date"],
                         "reason": "try",
                     }, timeout=15)
    assert r.status_code == 409


# 12 · delete-when-referenced blocked
def test_12_delete_when_referenced(ctx):
    orig = ctx.create()
    ctx.reverse(orig["id"])
    r = requests.delete(f"{API}/wallet-adjustments/{orig['id']}", headers=H,
                        timeout=15)
    assert r.status_code == 409


# 13 · edit-reversal blocked
def test_13_edit_reversal(ctx):
    orig = ctx.create()
    rev = ctx.reverse(orig["id"])
    r = requests.put(f"{API}/wallet-adjustments/{rev['id']}", headers=HJSON,
                     json={
                         "id": rev["id"], "wallet_code": rev["wallet_code"],
                         "direction": rev["direction"],
                         "amount": 999.0, "date": rev["date"],
                         "reason": "try",
                     }, timeout=15)
    assert r.status_code == 409


# 14 · delete-reversal blocked
def test_14_delete_reversal(ctx):
    orig = ctx.create()
    rev = ctx.reverse(orig["id"])
    r = requests.delete(f"{API}/wallet-adjustments/{rev['id']}", headers=H,
                        timeout=15)
    assert r.status_code == 409


# 15 · reversal with same date is allowed (backdate any past date)
def test_15_reversal_backdate(ctx):
    orig = ctx.create(date="2024-01-01")
    rev = ctx.reverse(orig["id"], date="2023-12-31", reason="backdate")
    legs = _legs(ctx, rev["id"])
    assert all(l["txn_date"] == "2023-12-31" for l in legs)


# 16 · idempotency
def test_16_idempotency(ctx):
    j = ctx.create(amount=100.0)
    import services_fin_txn_hooks as hooks
    refs0 = sorted(l["ref_source_key"] for l in _legs(ctx, j["id"]))
    for _ in range(3):
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "wallet_adjustment", j["id"]))
    refs1 = sorted(l["ref_source_key"] for l in _legs(ctx, j["id"]))
    assert refs0 == refs1


# 17 · failure queue
def test_17_failure_queue(ctx):
    j = ctx.create()
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("wa-forced")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "wallet_adjustment", j["id"]))
        row = ctx.d.fin_hook_failures.find_one({
            "user_id": ctx.uid, "source_type": "wallet_adjustment",
            "source_id": j["id"]}, sort=[("created_at", -1)])
        assert row and row["status"] == "pending"
    finally:
        hooks.reproject_source = orig


# 18 · CLI replay
def test_18_replay(ctx):
    j = ctx.create()
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("wa-replay-forced")

    hooks.reproject_source = _boom
    try:
        ctx.d.fin_txn.delete_many({
            "user_id": ctx.uid, "source_type": "wallet_adjustment",
            "source_id": j["id"]})
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "wallet_adjustment", j["id"]))
    finally:
        hooks.reproject_source = orig
    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=45)
    assert res.returncode == 0, res.stderr
    row = ctx.d.fin_hook_failures.find_one({
        "user_id": ctx.uid, "source_type": "wallet_adjustment",
        "source_id": j["id"]}, sort=[("created_at", -1)])
    assert row["status"] == "resolved"
    assert len(_legs(ctx, j["id"])) == 2


# 19 · tenant isolation
def test_19_tenant_isolation(ctx):
    j = ctx.create()
    stray_id = f"wa_iso_{ctx.tag}"
    ctx.d.wallet_adjustments.insert_one({
        "id": stray_id, "user_id": ctx._iso_uid,
        "company_id": ctx._iso_cid,
        "wallet_code": "WALLET_FASTAG", "direction": "increase",
        "amount": 999.0, "date": "2026-05-15", "reason": "iso",
        "reference": "", "reverses_id": "", "is_deleted": False,
        "created_at": "2026-05-15T00:00:00", "created_by": "",
    })
    requests.delete(f"{API}/wallet-adjustments/{j['id']}", headers=H, timeout=15)
    assert _legs(ctx, j["id"]) == []


# 20 · Day Book reflection
def test_20_day_book(ctx):
    j = ctx.create(amount=88.0, date="2026-07-01")
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-07-01",
                             "date_to": "2026-07-01",
                             "source_type": "wallet_adjustment"}, timeout=15)
    assert r.status_code == 200
    ids = {row.get("source_id") for row in r.json().get("rows", [])}
    assert j["id"] in ids


# 21 · Accounts: original + reversal net to zero on wallet + SUSPENSE
def test_21_accounts_net_zero(ctx):
    def net(code):
        p = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                          "account_code": code, "status": "active"}},
             {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(p)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)
    w0 = net("WALLET_FASTAG"); s0 = net("SUSPENSE")
    orig = ctx.create(direction="increase", amount=400.0)
    ctx.reverse(orig["id"])
    w1 = net("WALLET_FASTAG"); s1 = net("SUSPENSE")
    assert round(w1 - w0, 2) == 0.0
    assert round(s1 - s0, 2) == 0.0


# 22 · backdate any past date
def test_22_backdate(ctx):
    j = ctx.create(date="2022-03-15")
    legs = _legs(ctx, j["id"])
    assert all(l["txn_date"] == "2022-03-15" for l in legs)


# 23 · zero direct fin_txn writes
def test_23_zero_direct_fin_txn():
    src = Path("/app/backend/routers/wallet_adjustments.py").read_text()
    for tok in ("db.fin_txn", "fin_txn.insert", "fin_txn.update",
                "fin_txn.delete"):
        assert tok not in src


# 24 · hook count (create + update + delete + reverse = 4 sites + 1 import = 5)
def test_24_hook_count():
    src = Path("/app/backend/routers/wallet_adjustments.py").read_text()
    assert src.count("hook_after_source_write") == 5


# 25 · A-1 immutability probe
def test_25_a1_immutability():
    import services_fin_txn as a1
    assert "wallet_adjustment" in a1.SUPPORTED_SOURCE_TYPES


# 26 · locked-band forbidden constructs
def test_26_locked_band_forbidden():
    src = Path("/app/backend/routers/wallet_adjustments.py").read_text()
    for tok in ("asyncio.create_task", "APScheduler", "cachetools",
                "lru_cache", "threading.Lock", "asyncio.Lock"):
        assert tok not in src


# 27 · deterministic ref_source_key shapes for both directions
def test_27_ref_source_key_shape(ctx):
    a = ctx.create(direction="increase", amount=10.0)
    b = ctx.create(direction="decrease", amount=20.0)
    refs_a = sorted(l["ref_source_key"] for l in _legs(ctx, a["id"]))
    refs_b = sorted(l["ref_source_key"] for l in _legs(ctx, b["id"]))
    assert refs_a == [f"wallet_adjustment:{a['id']}:suspense_credit",
                      f"wallet_adjustment:{a['id']}:wallet_debit"]
    assert refs_b == [f"wallet_adjustment:{b['id']}:suspense_debit",
                      f"wallet_adjustment:{b['id']}:wallet_credit"]


# 28 · reverse-nonexistent → 404
def test_28_reverse_nonexistent(ctx):
    r = requests.post(f"{API}/wallet-adjustments/wa_ghost/reverse",
                      headers=HJSON,
                      json={"date": "2026-05-16", "reason": "x"}, timeout=15)
    assert r.status_code == 404
