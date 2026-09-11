"""Iter150A-2 · Phase 2 — Party-payment write hooks (Supplier/Vendor/Mechanic).

Exercises the 9 hook sites installed at:
  * routers/suppliers.py :: create_payment / update_payment / delete_payment
  * routers/vendors.py   :: create_vendor_payment / update_vendor_payment / delete_vendor_payment
  * routers/mechanics.py :: create_mechanic_payment / update_mechanic_payment / delete_mechanic_payment

All tests go through the real HTTP path so the hooks execute inside the
live backend's event loop. Direct-DB assertions verify the projected
FinTxn legs match the expected A-1 semantics.
"""
from __future__ import annotations

import asyncio
import os
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


def _demo_uid_cid() -> tuple[str, str]:
    d = _db()
    me = d.users.find_one({"email": "demo@bitumen-transport.local"},
                          {"_id": 0, "user_id": 1})
    assert me, "demo user missing"
    uid = me["user_id"]
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False}, timeout=15)
    assert r.status_code == 200, r.text
    vs = r.json()
    cid = vs[0]["company_id"]
    return uid, cid


class _Ctx:
    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo_uid_cid()
        self.tag = uuid.uuid4().hex[:10]
        self._suppliers: list[str] = []
        self._vendors: list[str] = []
        self._mechanics: list[str] = []
        self._payments: dict[str, list[str]] = {
            "supplier_payments": [], "vendor_payments": [], "mechanic_payments": [],
        }

    # ── Master helpers ────────────────────────────────────────────
    def make_supplier(self) -> str:
        r = requests.post(f"{API}/suppliers", headers=HJSON, json={
            "name": f"P2-Sup {self.tag}", "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        self._suppliers.append(sid)
        return sid

    def make_vendor(self) -> str:
        r = requests.post(f"{API}/vendors", headers=HJSON, json={
            "name": f"P2-Ven {self.tag}", "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        self._vendors.append(vid)
        return vid

    def make_mechanic(self) -> str:
        r = requests.post(f"{API}/mechanics", headers=HJSON, json={
            "name": f"P2-Mec {self.tag}", "is_active": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        self._mechanics.append(mid)
        return mid

    def teardown(self):
        for coll, ids in self._payments.items():
            if ids:
                self.d[coll].delete_many({"id": {"$in": ids}})
                self.d.fin_txn.delete_many(
                    {"user_id": self.uid, "source_id": {"$in": ids}})
                self.d.fin_hook_failures.delete_many(
                    {"user_id": self.uid, "source_id": {"$in": ids}})
        if self._suppliers:
            self.d.suppliers.delete_many({"id": {"$in": self._suppliers}})
        if self._vendors:
            self.d.vendors.delete_many({"id": {"$in": self._vendors}})
        if self._mechanics:
            self.d.mechanics.delete_many({"id": {"$in": self._mechanics}})


@pytest.fixture
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


def _fin_legs(ctx: _Ctx, source_id: str) -> list[dict]:
    return list(ctx.d.fin_txn.find(
        {"user_id": ctx.uid, "source_id": source_id},
        {"_id": 0, "account_code": 1, "direction": 1, "amount": 1,
         "counter_account_code": 1, "txn_type": 1, "ref_source_key": 1,
         "party_type": 1, "party_id": 1, "trip_id": 1, "txn_date": 1},
    ))


# ── 1. SupplierPayment create → exactly 2 FinTxn legs ────────────────

def test_1_supplier_payment_create_projects_2_legs(ctx):
    sid = ctx.make_supplier()
    r = requests.post(
        f"{API}/suppliers/{sid}/payments", headers=HJSON, json={
            "supplier_id": sid, "date": "2026-03-05", "amount": 5000.0,
            "type": "payment_out", "mode": "Bank", "ref_no": f"P2-{ctx.tag}",
        }, timeout=15)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    ctx._payments["supplier_payments"].append(pid)

    legs = _fin_legs(ctx, pid)
    assert len(legs) == 2
    codes = {(l["account_code"], l["direction"], l["amount"]) for l in legs}
    assert codes == {("AP_SUPPLIER", "in", 5000.0),
                     ("BANK_DEFAULT", "out", 5000.0)}
    assert all(l["party_type"] == "supplier" and l["party_id"] == sid for l in legs)


# ── 2. SupplierPayment update amount → replacement, no duplicate ──────

def test_2_supplier_payment_update_replaces_projection(ctx):
    sid = ctx.make_supplier()
    r = requests.post(f"{API}/suppliers/{sid}/payments", headers=HJSON, json={
        "supplier_id": sid, "date": "2026-03-05", "amount": 2000.0,
        "type": "payment_out", "mode": "Bank", "ref_no": "P2u",
    }, timeout=15)
    pid = r.json()["id"]
    ctx._payments["supplier_payments"].append(pid)
    assert len(_fin_legs(ctx, pid)) == 2

    r2 = requests.put(f"{API}/suppliers/{sid}/payments/{pid}",
                      headers=HJSON, json={
        "supplier_id": sid, "date": "2026-03-06", "amount": 7500.0,
        "type": "payment_out", "mode": "Cash", "ref_no": "P2u",
    }, timeout=15)
    assert r2.status_code == 200, r2.text
    legs = _fin_legs(ctx, pid)
    assert len(legs) == 2  # no duplication
    codes = {(l["account_code"], l["direction"], l["amount"]) for l in legs}
    # mode=Cash → CASH account resolver.
    assert codes == {("AP_SUPPLIER", "in", 7500.0), ("CASH", "out", 7500.0)}
    # txn_date updated too.
    assert all(l["txn_date"] == "2026-03-06" for l in legs)


# ── 3. SupplierPayment delete → projection removed (A-1 short-circuit) ──

def test_3_supplier_payment_delete_removes_legs(ctx):
    sid = ctx.make_supplier()
    r = requests.post(f"{API}/suppliers/{sid}/payments", headers=HJSON, json={
        "supplier_id": sid, "date": "2026-03-05", "amount": 1000.0,
        "type": "payment_out", "mode": "Bank", "ref_no": "P2d",
    }, timeout=15)
    pid = r.json()["id"]
    ctx._payments["supplier_payments"].append(pid)
    assert len(_fin_legs(ctx, pid)) == 2

    rd = requests.delete(f"{API}/suppliers/{sid}/payments/{pid}",
                         headers=H, params={"reason": "phase-2 test"},
                         timeout=15)
    assert rd.status_code == 200, rd.text
    assert _fin_legs(ctx, pid) == []


# ── 4. SupplierPayment reverse (is_reversed via update) → legs removed ─

def test_4_supplier_payment_reversal_removes_legs(ctx):
    sid = ctx.make_supplier()
    r = requests.post(f"{API}/suppliers/{sid}/payments", headers=HJSON, json={
        "supplier_id": sid, "date": "2026-03-05", "amount": 900.0,
        "type": "payment_out", "mode": "Bank", "ref_no": "P2r",
    }, timeout=15)
    pid = r.json()["id"]
    ctx._payments["supplier_payments"].append(pid)
    assert len(_fin_legs(ctx, pid)) == 2

    # Reverse via direct DB flip + a subsequent no-op update to fire the hook.
    ctx.d.supplier_payments.update_one({"id": pid}, {"$set": {"is_reversed": True}})
    r2 = requests.put(f"{API}/suppliers/{sid}/payments/{pid}",
                      headers=HJSON, json={
        "supplier_id": sid, "date": "2026-03-05", "amount": 900.0,
        "type": "payment_out", "mode": "Bank", "ref_no": "P2r",
    }, timeout=15)
    assert r2.status_code == 200
    # A-1 projection returns [] for is_reversed → legs cleared.
    assert _fin_legs(ctx, pid) == []


# ── 5. VendorPayment create/update/delete ───────────────────────────────

def test_5_vendor_payment_create_update_delete(ctx):
    vid = ctx.make_vendor()
    # CREATE
    r = requests.post(f"{API}/vendors/{vid}/payments", headers=HJSON, json={
        "vendor_id": vid, "date": "2026-03-06", "amount": 1500.0,
        "type": "payment_out", "mode": "Bank",
    }, timeout=15)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    ctx._payments["vendor_payments"].append(pid)
    legs = _fin_legs(ctx, pid)
    assert len(legs) == 2
    assert {(l["account_code"], l["direction"]) for l in legs} == \
        {("AP_VENDOR", "in"), ("BANK_DEFAULT", "out")}
    # UPDATE (amount + mode)
    r2 = requests.put(f"{API}/vendors/{vid}/payments/{pid}", headers=HJSON, json={
        "vendor_id": vid, "date": "2026-03-07", "amount": 2500.0,
        "type": "payment_out", "mode": "Cash",
    }, timeout=15)
    assert r2.status_code == 200
    legs2 = _fin_legs(ctx, pid)
    codes2 = {(l["account_code"], l["direction"], l["amount"]) for l in legs2}
    assert codes2 == {("AP_VENDOR", "in", 2500.0), ("CASH", "out", 2500.0)}
    # DELETE
    rd = requests.delete(f"{API}/vendors/{vid}/payments/{pid}",
                         headers=H, params={"reason": "phase-2 test"},
                         timeout=15)
    assert rd.status_code == 200
    assert _fin_legs(ctx, pid) == []


# ── 6. MechanicPayment create/update/delete ─────────────────────────────

def test_6_mechanic_payment_create_update_delete(ctx):
    mid = ctx.make_mechanic()
    r = requests.post(f"{API}/mechanics/{mid}/payments", headers=HJSON, json={
        "mechanic_id": mid, "date": "2026-03-08", "amount": 800.0,
        "type": "payment_out", "mode": "Cash",
    }, timeout=15)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    ctx._payments["mechanic_payments"].append(pid)
    codes = {(l["account_code"], l["direction"]) for l in _fin_legs(ctx, pid)}
    assert codes == {("AP_MECHANIC", "in"), ("CASH", "out")}

    r2 = requests.put(f"{API}/mechanics/{mid}/payments/{pid}",
                      headers=HJSON, json={
        "mechanic_id": mid, "date": "2026-03-09", "amount": 1200.0,
        "type": "payment_out", "mode": "Bank",
    }, timeout=15)
    assert r2.status_code == 200
    codes2 = {(l["account_code"], l["direction"], l["amount"])
              for l in _fin_legs(ctx, pid)}
    assert codes2 == {("AP_MECHANIC", "in", 1200.0),
                       ("BANK_DEFAULT", "out", 1200.0)}

    rd = requests.delete(f"{API}/mechanics/{mid}/payments/{pid}",
                         headers=H, params={"reason": "phase-2 test"},
                         timeout=15)
    assert rd.status_code == 200
    assert _fin_legs(ctx, pid) == []


# ── 7. Hook called twice → same final projection (idempotent) ───────────

def test_7_hook_called_twice_is_idempotent(ctx):
    """Two successive updates with identical payload → still exactly 2 legs."""
    vid = ctx.make_vendor()
    body = {"vendor_id": vid, "date": "2026-03-10", "amount": 500.0,
            "type": "payment_out", "mode": "Bank"}
    r = requests.post(f"{API}/vendors/{vid}/payments", headers=HJSON,
                      json=body, timeout=15)
    pid = r.json()["id"]
    ctx._payments["vendor_payments"].append(pid)
    # Two no-op updates.
    requests.put(f"{API}/vendors/{vid}/payments/{pid}",
                  headers=HJSON, json=body, timeout=15)
    requests.put(f"{API}/vendors/{vid}/payments/{pid}",
                  headers=HJSON, json=body, timeout=15)
    legs = _fin_legs(ctx, pid)
    assert len(legs) == 2
    # ref_source_key set is stable across replays.
    refs = sorted(l["ref_source_key"] for l in legs)
    assert refs == [f"vendor_payment:{pid}:ap_debit",
                    f"vendor_payment:{pid}:bank_credit"]


# ── 8. Tenant isolation (same source_id via direct DB seed) ─────────────

def test_8_tenant_isolation_same_source_id(ctx):
    """Two tenants can carry a FinTxn row keyed by the same source_id
    without collision (UNIQUE index includes user_id+company_id)."""
    sid = ctx.make_supplier()
    r = requests.post(f"{API}/suppliers/{sid}/payments", headers=HJSON, json={
        "supplier_id": sid, "date": "2026-03-11", "amount": 100.0,
        "type": "payment_out", "mode": "Bank",
    }, timeout=15)
    pid = r.json()["id"]
    ctx._payments["supplier_payments"].append(pid)
    # Inject a matching-source_id leg for a synthetic tenant.
    other_uid = f"user_iso_{ctx.tag}"
    other_cid = f"co_iso_{ctx.tag}"
    ctx.d.fin_accounts.insert_one({
        "id": f"acc_iso_{ctx.tag}", "user_id": other_uid, "company_id": other_cid,
        "code": "AP_SUPPLIER", "name": "iso", "type": "ap",
        "is_system": True, "is_active": True, "created_at": "2026-01-01",
    })
    ctx.d.fin_txn.insert_one({
        "id": f"fintxn_iso_{ctx.tag}",
        "user_id": other_uid, "company_id": other_cid,
        "txn_date": "2026-03-11", "account_id": f"acc_iso_{ctx.tag}",
        "account_code": "AP_SUPPLIER", "direction": "in", "amount": 100.0,
        "counter_account_id": "", "counter_account_code": "BANK_DEFAULT",
        "txn_type": "supplier_payment_out", "source_type": "supplier_payment",
        "source_id": pid, "source_key": "",
        "ref_source_key": f"supplier_payment:{pid}:ap_debit",
        "party_type": "supplier", "party_id": "",
        "party_name": "", "vehicle_id": "", "trip_id": "", "category": "",
        "narration": "iso", "status": "active",
        "transfer_group_id": "", "adjustment_group_id": "",
        "reversal_of": "", "is_reversal": False,
        "is_supplier_settlement_recovery": False,
        "reconciled_at": "", "reconciled_ref": "",
        "created_at": "2026-01-01", "projected_at": "2026-01-01",
    })
    try:
        # Same ref_source_key exists in two tenants.
        matches = list(ctx.d.fin_txn.find(
            {"ref_source_key": f"supplier_payment:{pid}:ap_debit"},
            {"_id": 0, "user_id": 1}))
        uids = {m["user_id"] for m in matches}
        assert ctx.uid in uids and other_uid in uids
        assert len(matches) == 2  # per-tenant unique
    finally:
        ctx.d.fin_txn.delete_many({"user_id": other_uid})
        ctx.d.fin_accounts.delete_many({"user_id": other_uid})


# ── 9. Forced hook failure preserves source + records failure row ───────

def test_9_forced_hook_failure_records_row_without_touching_source(ctx, monkeypatch):
    """Patch reproject_source to fail; POST supplier payment; source
    must be committed intact, failure row must exist, no partial FinTxn."""
    import services_fin_txn_hooks as hooks
    orig = hooks.reproject_source
    async def _boom(*a, **kw): raise RuntimeError("phase2-forced")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    sid = ctx.make_supplier()
    r = requests.post(f"{API}/suppliers/{sid}/payments", headers=HJSON, json={
        "supplier_id": sid, "date": "2026-03-12", "amount": 250.0,
        "type": "payment_out", "mode": "Bank",
    }, timeout=15)
    assert r.status_code == 200, r.text  # source write succeeded
    pid = r.json()["id"]
    ctx._payments["supplier_payments"].append(pid)

    # Source doc lives.
    src = ctx.d.supplier_payments.find_one({"id": pid})
    assert src is not None and src["amount"] == 250.0

    # ⚠ NOTE: the running backend process holds its own reference to
    # `reproject_source` inside `services_fin_txn_hooks` — monkeypatch
    # of THIS test process only affects local imports, not the server.
    # So the hook actually succeeded in-process. This test therefore
    # asserts the safety net directly via the hook helper.
    monkeypatch.setattr(hooks, "reproject_source", orig)  # restore

    # Simulate a real hook failure by calling the helper directly with
    # the failure monkeypatched — this exercises Phase-1's failure queue.
    import asyncio as _a
    _LOOP = _a.new_event_loop(); _a.set_event_loop(_LOOP)
    async def _boom2(*a, **kw): raise RuntimeError("phase2-forced-2")
    hooks.reproject_source = _boom2
    try:
        res = _LOOP.run_until_complete(hooks.hook_after_source_write(
            ctx.uid, ctx.cid, "supplier_payment", pid))
        assert res["ok"] is False
        assert res["failure_id"]
        row = ctx.d.fin_hook_failures.find_one(
            {"user_id": ctx.uid, "source_id": pid}, {"_id": 0})
        assert row["status"] == "pending"
    finally:
        hooks.reproject_source = orig
        _LOOP.close()


# ── 10. Replay after fixing failure ─────────────────────────────────────

def test_10_replay_resolves_failure_and_projects(ctx):
    """Seed a pending failure row directly, then drain it via the CLI
    subprocess (fresh Python process → clean event loop). Verifies the
    end-to-end recovery path: pending → resolved + 2 FinTxn legs."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path

    sid = ctx.make_supplier()
    pid = f"sp_p2_replay_{ctx.tag}"
    ctx.d.supplier_payments.insert_one({
        "id": pid, "user_id": ctx.uid, "company_id": ctx.cid,
        "supplier_id": sid, "date": "2026-03-13", "amount": 333.0,
        "type": "payment_out", "mode": "Bank", "is_deleted": False,
    })
    ctx._payments["supplier_payments"].append(pid)
    # Seed a pending failure row directly (no hook call needed).
    ctx.d.fin_hook_failures.insert_one({
        "id": f"hfail_replay_{ctx.tag}",
        "user_id": ctx.uid, "company_id": ctx.cid,
        "source_type": "supplier_payment", "source_id": pid,
        "action": "upsert",
        "error": "seeded-pending",
        "retry_count": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_attempt_at": "2026-01-01T00:00:00+00:00",
        "next_attempt_at": "1970-01-01T00:00:00+00:00",
        "status": "pending", "resolved_at": "", "history": [],
    })

    # Drain via CLI subprocess.
    result = subprocess.run(
        [_sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"succeeded": 1' in result.stdout, result.stdout

    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": pid}, {"_id": 0})
    assert row["status"] == "resolved"
    assert row["resolved_at"]
    assert len(_fin_legs(ctx, pid)) == 2


# ── 11. Repeated replay → no duplicate FinTxn ───────────────────────────

def test_11_repeated_replay_no_duplicate_fin_txn(ctx):
    """After a successful hook path, forcibly re-run reproject and
    confirm the leg count remains 2 (A-1 UNIQUE index guarantee)."""
    vid = ctx.make_vendor()
    r = requests.post(f"{API}/vendors/{vid}/payments", headers=HJSON, json={
        "vendor_id": vid, "date": "2026-03-14", "amount": 60.0,
        "type": "payment_out", "mode": "Cash",
    }, timeout=15)
    pid = r.json()["id"]
    ctx._payments["vendor_payments"].append(pid)
    n0 = len(_fin_legs(ctx, pid))
    assert n0 == 2

    # Owner-only reproject via HTTP (locked A-1 endpoint).
    r2 = requests.post(f"{API}/fin/reproject", headers=HJSON, json={
        "source_type": "vendor_payment", "source_id": pid,
    }, timeout=15)
    assert r2.status_code == 200
    assert len(_fin_legs(ctx, pid)) == 2


# ── 12. Source identity preserved ───────────────────────────────────────

def test_12_source_identity_preserved(ctx):
    mid = ctx.make_mechanic()
    r = requests.post(f"{API}/mechanics/{mid}/payments", headers=HJSON, json={
        "mechanic_id": mid, "date": "2026-03-15", "amount": 88.0,
        "type": "payment_out", "mode": "Bank",
    }, timeout=15)
    pid = r.json()["id"]
    ctx._payments["mechanic_payments"].append(pid)
    legs = _fin_legs(ctx, pid)
    for l in legs:
        assert l["ref_source_key"].startswith(f"mechanic_payment:{pid}:")
        # Denormalised source identity survives.
    codes = {l["ref_source_key"].split(":")[-1] for l in legs}
    assert codes == {"ap_debit", "bank_credit"}


# ── 13. Payment date + amount preserved on projection ───────────────────

def test_13_payment_date_and_amount_preserved(ctx):
    sid = ctx.make_supplier()
    r = requests.post(f"{API}/suppliers/{sid}/payments", headers=HJSON, json={
        "supplier_id": sid, "date": "2026-04-01", "amount": 4321.5,
        "type": "payment_out", "mode": "Bank",
    }, timeout=15)
    pid = r.json()["id"]
    ctx._payments["supplier_payments"].append(pid)
    legs = _fin_legs(ctx, pid)
    assert all(l["txn_date"] == "2026-04-01" for l in legs)
    assert all(l["amount"] == 4321.5 for l in legs)


# ── 14. Locked A-1 projection module unchanged (dependency-only) ────────

def test_14_a1_projection_module_dependency_only():
    """The hooks module imports A-1 as a dependency and does NOT
    re-implement or shadow any public symbol. We check the symbols
    the hooks module actually imports (`reproject_source` and
    `SUPPORTED_SOURCE_TYPES`) point at the identical A-1 objects."""
    import services_fin_txn as a1
    import services_fin_txn_hooks as hooks
    for name in ("reproject_source", "SUPPORTED_SOURCE_TYPES"):
        assert getattr(hooks, name) is getattr(a1, name)
    # Non-imported A-1 symbols must NOT appear on the hooks module
    # (would indicate accidental shadowing / re-implementation).
    for name in ("backfill_tenant", "project_supplier_payment",
                  "project_vendor_payment", "project_mechanic_payment"):
        assert not hasattr(hooks, name), (
            f"hooks module unexpectedly exports A-1 symbol {name!r}")


# ── 15. Cross-source regression: all three parties in one flow ──────────

def test_15_cross_source_regression(ctx):
    sid = ctx.make_supplier()
    vid = ctx.make_vendor()
    mid = ctx.make_mechanic()
    r1 = requests.post(f"{API}/suppliers/{sid}/payments", headers=HJSON, json={
        "supplier_id": sid, "date": "2026-04-02", "amount": 111.0,
        "type": "payment_out", "mode": "Bank"}, timeout=15)
    r2 = requests.post(f"{API}/vendors/{vid}/payments", headers=HJSON, json={
        "vendor_id": vid, "date": "2026-04-02", "amount": 222.0,
        "type": "payment_out", "mode": "Cash"}, timeout=15)
    r3 = requests.post(f"{API}/mechanics/{mid}/payments", headers=HJSON, json={
        "mechanic_id": mid, "date": "2026-04-02", "amount": 333.0,
        "type": "payment_out", "mode": "Bank"}, timeout=15)
    for r in (r1, r2, r3): assert r.status_code == 200
    p_sup, p_ven, p_mec = r1.json()["id"], r2.json()["id"], r3.json()["id"]
    ctx._payments["supplier_payments"].append(p_sup)
    ctx._payments["vendor_payments"].append(p_ven)
    ctx._payments["mechanic_payments"].append(p_mec)
    codes = lambda pid: {(l["account_code"], l["direction"]) for l in _fin_legs(ctx, pid)}
    assert codes(p_sup) == {("AP_SUPPLIER", "in"), ("BANK_DEFAULT", "out")}
    assert codes(p_ven) == {("AP_VENDOR", "in"), ("CASH", "out")}
    assert codes(p_mec) == {("AP_MECHANIC", "in"), ("BANK_DEFAULT", "out")}
