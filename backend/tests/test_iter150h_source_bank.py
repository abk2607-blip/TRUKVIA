"""Iter150H · Company Source Bank Foundation — backend UAT."""
from __future__ import annotations
import asyncio
import subprocess
import uuid
from pathlib import Path

from httpx import AsyncClient, ASGITransport

from server import app
from db import db
from services_fin_txn import ensure_indexes, ensure_system_accounts
from services_fin_txn_hooks import ensure_hook_indexes

REPO = Path("/app")
LOCKED_G = "e655839bfcf0ae4659e4707ded6ad872f6d27c35"

# Iter150G's 14-file protected manifest.  13 of these must remain 0-diff
# vs the Iter150G lock; only backend/models.py is under authorised Iter150H
# additive narrow unfreeze.
PROTECTED_13_NON_MODELS = [
    "backend/services.py",
    "backend/services_fin_txn.py",
    "backend/services_fin_txn_hooks.py",
    "backend/services_expense_bridge.py",
    "backend/routers/trips.py",
    "backend/routers/invoices.py",
    "backend/routers/notes.py",
    "backend/routers/vendor_bills.py",
    "backend/routers/mechanic_work_orders.py",
    "backend/routers/expenses.py",
    "backend/routers/wallet_recharges.py",
    "backend/routers/wallet_transfers.py",
    "backend/routers/wallet_adjustments.py",
]


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError()
    except Exception:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _mk_ctx(role="owner"):
    uid, cid = f"u_{uuid.uuid4().hex[:8]}", f"c_{uuid.uuid4().hex[:8]}"
    await ensure_indexes()
    await ensure_hook_indexes()
    await ensure_system_accounts(uid, cid)
    await db.companies.insert_one({
        "id": cid, "user_id": uid, "name": "TEST CO", "is_default": True,
    })
    from auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": uid, "email": "t@t", "effective_role": role, "role": role,
    }
    return uid, cid


async def _cleanup(uid, cid):
    app.dependency_overrides.clear()
    for c in ("suppliers", "vendors", "mechanics",
              "company_bank_accounts", "party_bank_accounts",
              "supplier_payments", "vendor_payments", "mechanic_payments",
              "fin_txn", "audit_logs", "companies"):
        await db[c].delete_many({"user_id": uid})


def _hdr(cid):
    return {"X-Company-Id": cid}


async def _post(url, body, cid=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(url, json=body, headers=_hdr(cid) if cid else {})


async def _get(url, cid=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(url, headers=_hdr(cid) if cid else {})


async def _mk_supplier(uid, cid, name="SUP UAT"):
    sid = f"sup_{uuid.uuid4().hex[:8]}"
    await db.suppliers.insert_one({
        "id": sid, "user_id": uid, "company_id": cid, "name": name,
        "is_deleted": False,
    })
    return sid


async def _mk_vendor(uid, cid, name="VEN UAT"):
    vid = f"ven_{uuid.uuid4().hex[:8]}"
    await db.vendors.insert_one({
        "id": vid, "user_id": uid, "company_id": cid, "name": name,
        "is_deleted": False, "type": "spare_parts",
    })
    return vid


async def _mk_mechanic(uid, cid, name="MEC UAT"):
    mid = f"mec_{uuid.uuid4().hex[:8]}"
    await db.mechanics.insert_one({
        "id": mid, "user_id": uid, "company_id": cid, "name": name,
        "is_deleted": False,
    })
    return mid


async def _mk_cba(cid, primary=True, active=True, acc="1234567890"):
    r = await _post("/api/company-bank-accounts", {
        "bank_name": "SBI", "branch": "MAIN", "account_holder_name": "TRUKVIA",
        "account_number": acc, "ifsc": "SBIN0000123",
        "account_type": "current", "is_primary": primary,
    }, cid=cid)
    assert r.status_code == 200, r.text
    j = r.json()
    if not active:
        await db.company_bank_accounts.update_one(
            {"id": j["id"]}, {"$set": {"is_active": False}}
        )
    return j["id"]


# ── 01 · legacy empty compat
def test_01_legacy_empty_compat():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            sid = await _mk_supplier(uid, cid)
            r = await _post(f"/api/suppliers/{sid}/payments", {
                "supplier_id": sid, "date": "2026-02-14", "amount": 100.0,
                "mode": "UPI", "remarks": "legacy",
            }, cid=cid)
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["company_bank_account_id"] == ""
            assert j["source_bank_snapshot"] == {}
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 02 · valid source-bank capture · supplier
def test_02_supplier_source_bank_capture():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            sid = await _mk_supplier(uid, cid)
            cbid = await _mk_cba(cid)
            r = await _post(f"/api/suppliers/{sid}/payments", {
                "supplier_id": sid, "date": "2026-02-14", "amount": 200.0,
                "mode": "NEFT", "company_bank_account_id": cbid,
            }, cid=cid)
            assert r.status_code == 200, r.text
            j = r.json()
            snap = j["source_bank_snapshot"]
            assert set(snap.keys()) == {"bank_name", "masked_number", "ifsc", "branch", "holder_name"}
            assert snap["masked_number"] == "XXXXXX7890"
            assert snap["bank_name"] == "SBI"
            assert snap["ifsc"] == "SBIN0000123"
            assert snap["branch"] == "MAIN"
            assert snap["holder_name"] == "TRUKVIA"
            assert "account_number" not in snap
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 03 · valid source-bank capture · vendor + mechanic
def test_03_vendor_mechanic_source_bank_capture():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            vid = await _mk_vendor(uid, cid)
            mid = await _mk_mechanic(uid, cid)
            cbid = await _mk_cba(cid, acc="9876543210")
            for path, party_key, party_val in (
                (f"/api/vendors/{vid}/payments", "vendor_id", vid),
                (f"/api/mechanics/{mid}/payments", "mechanic_id", mid),
            ):
                r = await _post(path, {
                    party_key: party_val, "date": "2026-02-14",
                    "amount": 300.0, "mode": "RTGS",
                    "company_bank_account_id": cbid,
                }, cid=cid)
                assert r.status_code == 200, r.text
                snap = r.json()["source_bank_snapshot"]
                assert set(snap.keys()) == {"bank_name", "masked_number", "ifsc", "branch", "holder_name"}
                assert snap["masked_number"] == "XXXXXX3210"
                assert "account_number" not in snap
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 04 · inactive rejection
def test_04_inactive_source_bank_rejected():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            sid = await _mk_supplier(uid, cid)
            cbid = await _mk_cba(cid, active=False)
            r = await _post(f"/api/suppliers/{sid}/payments", {
                "supplier_id": sid, "date": "2026-02-14", "amount": 100.0,
                "mode": "Bank", "company_bank_account_id": cbid,
            }, cid=cid)
            assert r.status_code == 400
            assert "Company bank account" in r.json()["detail"]
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 05 · cross-tenant rejection
def test_05_cross_tenant_source_bank_rejected():
    async def _t():
        uid_a, cid_a = await _mk_ctx()
        cbid_a = await _mk_cba(cid_a)
        # switch to tenant B
        app.dependency_overrides.clear()
        uid_b, cid_b = await _mk_ctx()
        try:
            sid_b = await _mk_supplier(uid_b, cid_b)
            r = await _post(f"/api/suppliers/{sid_b}/payments", {
                "supplier_id": sid_b, "date": "2026-02-14", "amount": 100.0,
                "mode": "Bank", "company_bank_account_id": cbid_a,
            }, cid=cid_b)
            assert r.status_code == 400
        finally:
            await _cleanup(uid_a, cid_a)
            await _cleanup(uid_b, cid_b)
    _run(_t())


# ── 06 · unknown id rejection
def test_06_unknown_source_bank_rejected():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            sid = await _mk_supplier(uid, cid)
            r = await _post(f"/api/suppliers/{sid}/payments", {
                "supplier_id": sid, "date": "2026-02-14", "amount": 100.0,
                "mode": "Bank", "company_bank_account_id": "cba_does_not_exist",
            }, cid=cid)
            assert r.status_code == 400
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 07 · replaced rejection (replaced row becomes is_active=false)
def test_07_replaced_source_bank_rejected():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            sid = await _mk_supplier(uid, cid)
            cbid_old = await _mk_cba(cid, acc="1111111111")
            # replace → returns new_id; old becomes inactive
            r = await _post(f"/api/company-bank-accounts/{cbid_old}/replace", {
                "reason": "rotate",
                "bank_name": "SBI", "account_number": "2222222222",
                "ifsc": "SBIN0000123", "account_type": "current",
                "account_holder_name": "TRUKVIA",
            }, cid=cid)
            assert r.status_code == 200, r.text
            # attempt to use old replaced id
            r2 = await _post(f"/api/suppliers/{sid}/payments", {
                "supplier_id": sid, "date": "2026-02-14", "amount": 100.0,
                "mode": "Bank", "company_bank_account_id": cbid_old,
            }, cid=cid)
            assert r2.status_code == 400
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 08 · historical snapshot immutability
def test_08_historical_snapshot_immutability():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            sid = await _mk_supplier(uid, cid)
            cbid = await _mk_cba(cid, acc="5555555555")
            r = await _post(f"/api/suppliers/{sid}/payments", {
                "supplier_id": sid, "date": "2026-02-14", "amount": 100.0,
                "mode": "NEFT", "company_bank_account_id": cbid,
            }, cid=cid)
            pid = r.json()["id"]
            snap_at_post = dict(r.json()["source_bank_snapshot"])
            # mutate the master (deactivate it)
            await _post(f"/api/company-bank-accounts/{cbid}/deactivate", {
                "reason": "test-mutate",
            }, cid=cid)
            # fetch the payment back — snapshot must be identical
            rows = await _get(f"/api/suppliers/{sid}/payments", cid=cid)
            row = [p for p in rows.json() if p["id"] == pid][0]
            assert row["source_bank_snapshot"] == snap_at_post
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 09 · BANK_DEFAULT accounting invariant preserved
def test_09_bank_default_unchanged():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            sid = await _mk_supplier(uid, cid)
            cbid = await _mk_cba(cid, acc="7777777777")
            r = await _post(f"/api/suppliers/{sid}/payments", {
                "supplier_id": sid, "date": "2026-02-14", "amount": 500.0,
                "mode": "NEFT", "company_bank_account_id": cbid,
            }, cid=cid)
            pid = r.json()["id"]
            # projection: exactly BANK_DEFAULT (mode=NEFT) credited
            legs = await db.fin_txn.find({
                "user_id": uid, "company_id": cid,
                "source_id": pid,
            }, {"_id": 0}).to_list(20)
            assert legs, "hook_after_source_write should have projected"
            bank_legs = [l for l in legs if l.get("account_code") == "BANK_DEFAULT"]
            assert bank_legs, "BANK_DEFAULT leg must be present"
            # no per-bank code exists
            assert not any(
                l.get("account_code", "").startswith("BANK_SBI") for l in legs
            )
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 10 · protected-band 13-file zero-diff vs Iter150G lock
def test_10_protected_13_zero_diff():
    for rel in PROTECTED_13_NON_MODELS:
        out = subprocess.check_output(
            ["git", "diff", "--numstat", LOCKED_G, "--", rel],
            cwd=str(REPO),
        ).decode().strip()
        assert out == "", f"{rel} has drift vs Iter150G lock: {out!r}"


# ── 11 · models.py bounded diff — only Iter150H additive fields
def test_11_models_bounded_diff():
    diff = subprocess.check_output(
        ["git", "diff", LOCKED_G, "--", "backend/models.py"],
        cwd=str(REPO),
    ).decode()
    # Must contain exactly the six Iter150H additive lines
    assert diff.count("+    company_bank_account_id: str = \"\"") == 3
    assert diff.count("+    source_bank_snapshot: dict = Field(default_factory=dict)") == 3
    # No removals of the pre-existing Iter150G/dormant fields
    assert "-    bank_account_id: str = \"\"" not in diff
    assert "-    bank_snapshot: dict = Field(default_factory=dict)" not in diff
    assert "-    account_id: str = \"\"" not in diff


# ── 12 · Iter150G bank routers still work end-to-end (regression)
def test_12_iter150g_regression():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            cbid = await _mk_cba(cid)
            r = await _get("/api/company-bank-accounts", cid=cid)
            assert r.status_code == 200 and any(x["id"] == cbid for x in r.json())
            r2 = await _get(f"/api/company-bank-accounts/{cbid}/reveal", cid=cid)
            assert r2.status_code == 200
            assert r2.json()["account_number"]  # owner sees full
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 13 · masked_display is what appears on lists (Iter150G unchanged)
def test_13_list_masked_display():
    async def _t():
        uid, cid = await _mk_ctx(role="accountant")
        try:
            cbid = await _mk_cba(cid)
            r = await _get("/api/company-bank-accounts", cid=cid)
            row = [x for x in r.json() if x["id"] == cbid][0]
            # accountant has view_bank_account_full — so list returns raw acct#
            # (permission-gated). Masked_display should still exist.
            assert row["masked_display"] == "XXXXXX7890"
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── 14 · additive helper snapshot_from_company_bank contract
def test_14_snapshot_helper_shape():
    from services_bank_accounts import snapshot_from_company_bank
    snap = snapshot_from_company_bank({
        "bank_name": "HDFC", "account_number": "1122334455",
        "ifsc": "HDFC0001234", "branch": "BR1",
        "account_holder_name": "COMPANY X",
    })
    assert set(snap.keys()) == {"bank_name", "masked_number", "ifsc", "branch", "holder_name"}
    assert snap["masked_number"] == "XXXXXX4455"
    assert "account_number" not in snap
    assert snap["branch"] == "BR1"
