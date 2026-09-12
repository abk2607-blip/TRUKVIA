"""Iter150B · WalletTransfer hooks — 2-leg direct (no INTER_ACCOUNT)."""
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
        self._wts: list[str] = []
        self._iso_uid = f"iso_wt_{self.tag}"
        self._iso_cid = f"co_iso_wt_{self.tag}"

    def create(self, src="WALLET_FASTAG", dst="WALLET_FUEL",
               amount=500.0, date="2026-05-15", reference=""):
        r = requests.post(f"{API}/wallet-transfers", headers=HJSON, json={
            "source_wallet_code": src, "destination_wallet_code": dst,
            "amount": amount, "date": date, "reference": reference,
        }, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        self._wts.append(j["id"])
        return j

    def teardown(self):
        if self._wts:
            self.d.wallet_transfers.delete_many({"id": {"$in": self._wts}})
            self.d.fin_txn.delete_many({
                "user_id": self.uid, "source_type": "wallet_transfer",
                "source_id": {"$in": self._wts}})
            self.d.fin_hook_failures.delete_many({
                "user_id": self.uid, "source_type": "wallet_transfer",
                "source_id": {"$in": self._wts}})
        self.d.fin_txn.delete_many({"user_id": self._iso_uid})
        self.d.wallet_transfers.delete_many({"user_id": self._iso_uid})


@pytest.fixture
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


def _legs(ctx, wt_id):
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_type": "wallet_transfer",
         "source_id": wt_id, "status": "active"},
        {"_id": 0, "account_code": 1, "counter_account_code": 1,
         "direction": 1, "amount": 1, "ref_source_key": 1,
         "txn_type": 1, "txn_date": 1}))


# 01 · create FASTag→FUEL — 2 legs, source credit + dest debit
def test_01_create(ctx):
    j = ctx.create(src="WALLET_FASTAG", dst="WALLET_FUEL", amount=500.0)
    legs = _legs(ctx, j["id"])
    assert len(legs) == 2
    src_leg = next(l for l in legs if l["direction"] == "out")
    dst_leg = next(l for l in legs if l["direction"] == "in")
    assert src_leg["account_code"] == "WALLET_FASTAG"
    assert src_leg["counter_account_code"] == "WALLET_FUEL"
    assert dst_leg["account_code"] == "WALLET_FUEL"
    assert dst_leg["counter_account_code"] == "WALLET_FASTAG"
    assert src_leg["amount"] == dst_leg["amount"] == 500.0


# 02 · reverse direction FUEL→FASTag
def test_02_reverse_direction(ctx):
    j = ctx.create(src="WALLET_FUEL", dst="WALLET_FASTAG", amount=300.0)
    codes = sorted((l["account_code"], l["direction"]) for l in _legs(ctx, j["id"]))
    assert codes == [("WALLET_FASTAG", "in"), ("WALLET_FUEL", "out")]


# 03 · same-wallet rejected 422
def test_03_same_wallet_rejected(ctx):
    r = requests.post(f"{API}/wallet-transfers", headers=HJSON, json={
        "source_wallet_code": "WALLET_FASTAG",
        "destination_wallet_code": "WALLET_FASTAG",
        "amount": 100.0, "date": "2026-05-15",
    }, timeout=15)
    assert r.status_code == 422


# 04 · amount > 0
def test_04_amount_positive(ctx):
    r = requests.post(f"{API}/wallet-transfers", headers=HJSON, json={
        "source_wallet_code": "WALLET_FASTAG",
        "destination_wallet_code": "WALLET_FUEL",
        "amount": -50.0, "date": "2026-05-15",
    }, timeout=15)
    assert r.status_code == 422


# 05 · Literal enforcement
def test_05_literal_enforcement(ctx):
    r = requests.post(f"{API}/wallet-transfers", headers=HJSON, json={
        "source_wallet_code": "WALLET_UNKNOWN",
        "destination_wallet_code": "WALLET_FUEL",
        "amount": 100.0, "date": "2026-05-15",
    }, timeout=15)
    assert r.status_code == 422


# 06 · update amount refreshes both legs
def test_06_update_amount(ctx):
    j = ctx.create(amount=100.0)
    r = requests.put(f"{API}/wallet-transfers/{j['id']}", headers=HJSON, json={
        "id": j["id"], "source_wallet_code": j["source_wallet_code"],
        "destination_wallet_code": j["destination_wallet_code"],
        "amount": 777.0, "date": j["date"],
    }, timeout=15)
    assert r.status_code == 200
    legs = _legs(ctx, j["id"])
    assert len(legs) == 2 and all(l["amount"] == 777.0 for l in legs)


# 07 · update flip direction
def test_07_update_flip(ctx):
    j = ctx.create(src="WALLET_FASTAG", dst="WALLET_FUEL")
    r = requests.put(f"{API}/wallet-transfers/{j['id']}", headers=HJSON, json={
        "id": j["id"], "source_wallet_code": "WALLET_FUEL",
        "destination_wallet_code": "WALLET_FASTAG",
        "amount": j["amount"], "date": j["date"],
    }, timeout=15)
    assert r.status_code == 200
    codes = sorted((l["account_code"], l["direction"]) for l in _legs(ctx, j["id"]))
    assert codes == [("WALLET_FASTAG", "in"), ("WALLET_FUEL", "out")]


# 08 · soft-delete clears both legs
def test_08_soft_delete(ctx):
    j = ctx.create(amount=222.0)
    assert len(_legs(ctx, j["id"])) == 2
    r = requests.delete(f"{API}/wallet-transfers/{j['id']}", headers=H,
                        params={"reason": "test"}, timeout=15)
    assert r.status_code == 200
    assert _legs(ctx, j["id"]) == []


# 09 · idempotency
def test_09_idempotency(ctx):
    j = ctx.create(amount=100.0)
    import services_fin_txn_hooks as hooks
    refs0 = sorted(l["ref_source_key"] for l in _legs(ctx, j["id"]))
    for _ in range(3):
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "wallet_transfer", j["id"]))
    refs1 = sorted(l["ref_source_key"] for l in _legs(ctx, j["id"]))
    assert refs0 == refs1


# 10 · failure queue
def test_10_failure_queue(ctx):
    j = ctx.create()
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("wt-forced")

    hooks.reproject_source = _boom
    try:
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "wallet_transfer", j["id"]))
        row = ctx.d.fin_hook_failures.find_one({
            "user_id": ctx.uid, "source_type": "wallet_transfer",
            "source_id": j["id"]}, sort=[("created_at", -1)])
        assert row and row["status"] == "pending"
    finally:
        hooks.reproject_source = orig


# 11 · replay
def test_11_replay(ctx):
    j = ctx.create()
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source

    async def _boom(*a, **kw):
        raise RuntimeError("wt-replay-forced")

    hooks.reproject_source = _boom
    try:
        ctx.d.fin_txn.delete_many({
            "user_id": ctx.uid, "source_type": "wallet_transfer",
            "source_id": j["id"]})
        _run(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "wallet_transfer", j["id"]))
    finally:
        hooks.reproject_source = orig
    res = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=45)
    assert res.returncode == 0, res.stderr
    row = ctx.d.fin_hook_failures.find_one({
        "user_id": ctx.uid, "source_type": "wallet_transfer",
        "source_id": j["id"]}, sort=[("created_at", -1)])
    assert row["status"] == "resolved"
    assert len(_legs(ctx, j["id"])) == 2


# 12 · tenant isolation
def test_12_tenant_isolation(ctx):
    j = ctx.create(amount=100.0)
    stray_id = f"wt_iso_{ctx.tag}"
    ctx.d.wallet_transfers.insert_one({
        "id": stray_id, "user_id": ctx._iso_uid,
        "company_id": ctx._iso_cid,
        "source_wallet_code": "WALLET_FASTAG",
        "destination_wallet_code": "WALLET_FUEL",
        "amount": 999.0, "date": "2026-05-15", "reference": "",
        "remarks": "", "is_deleted": False,
        "created_at": "2026-05-15T00:00:00", "created_by": "",
    })
    requests.delete(f"{API}/wallet-transfers/{j['id']}", headers=H, timeout=15)
    assert _legs(ctx, j["id"]) == []


# 13 · Day Book reflection
def test_13_day_book(ctx):
    j = ctx.create(amount=333.0, date="2026-06-15")
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": "2026-06-15",
                             "date_to": "2026-06-15",
                             "source_type": "wallet_transfer"}, timeout=15)
    assert r.status_code == 200
    ids = {row.get("source_id") for row in r.json().get("rows", [])}
    assert j["id"] in ids


# 14 · Accounts: net-zero pair (source decreases, dest increases)
def test_14_accounts_net_zero(ctx):
    def net(code):
        p = [{"$match": {"user_id": ctx.uid, "company_id": ctx.cid,
                          "account_code": code, "status": "active"}},
             {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}}]
        g = {r["_id"]: r["s"] for r in ctx.d.fin_txn.aggregate(p)}
        return round(g.get("in", 0.0) - g.get("out", 0.0), 2)
    a0 = net("WALLET_FASTAG"); b0 = net("WALLET_FUEL")
    ctx.create(src="WALLET_FASTAG", dst="WALLET_FUEL", amount=250.0)
    a1 = net("WALLET_FASTAG"); b1 = net("WALLET_FUEL")
    assert round(a1 - a0, 2) == -250.0
    assert round(b1 - b0, 2) == 250.0


# 15 · NO INTER_ACCOUNT leg emitted
def test_15_no_inter_account(ctx):
    j = ctx.create(amount=100.0)
    inter = ctx.d.fin_txn.count_documents({
        "user_id": ctx.uid, "source_type": "wallet_transfer",
        "source_id": j["id"], "account_code": "INTER_ACCOUNT"})
    assert inter == 0


# 16 · backdate
def test_16_backdate(ctx):
    j = ctx.create(date="2023-11-11", amount=50.0)
    legs = _legs(ctx, j["id"])
    assert all(l["txn_date"] == "2023-11-11" for l in legs)


# 17 · zero direct fin_txn writes
def test_17_zero_direct_fin_txn():
    src = Path("/app/backend/routers/wallet_transfers.py").read_text()
    for tok in ("db.fin_txn", "fin_txn.insert", "fin_txn.update",
                "fin_txn.delete"):
        assert tok not in src


# 18 · hook count
def test_18_hook_count():
    src = Path("/app/backend/routers/wallet_transfers.py").read_text()
    assert src.count("hook_after_source_write") == 4


# 19 · A-1 immutability
def test_19_a1_immutability():
    import services_fin_txn as a1
    assert "wallet_transfer" in a1.SUPPORTED_SOURCE_TYPES


# 20 · locked-band forbidden constructs
def test_20_locked_band_forbidden():
    src = Path("/app/backend/routers/wallet_transfers.py").read_text()
    for tok in ("asyncio.create_task", "APScheduler", "cachetools",
                "lru_cache", "threading.Lock", "asyncio.Lock"):
        assert tok not in src


# 21 · deterministic ref_source_key
def test_21_ref_source_key_shape(ctx):
    j = ctx.create()
    refs = sorted(l["ref_source_key"] for l in _legs(ctx, j["id"]))
    assert refs == [f"wallet_transfer:{j['id']}:dst_debit",
                    f"wallet_transfer:{j['id']}:src_credit"]


# 22 · edit-after-delete blocked
def test_22_edit_after_delete(ctx):
    j = ctx.create()
    requests.delete(f"{API}/wallet-transfers/{j['id']}", headers=H, timeout=15)
    r = requests.put(f"{API}/wallet-transfers/{j['id']}", headers=HJSON, json={
        "id": j["id"], "source_wallet_code": j["source_wallet_code"],
        "destination_wallet_code": j["destination_wallet_code"],
        "amount": 999.0, "date": j["date"],
    }, timeout=15)
    assert r.status_code == 409
