"""Iter150G · Bank Account Foundation — backend UAT."""
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
LOCKED_F = "226e46ac3804a04c5197e395ff35a2079743fd4c"
PROTECTED_13_NON_MODELS = [
    "backend/services_fin_txn.py", "backend/services_fin_txn_hooks.py",
    "backend/routers/trips.py", "backend/routers/invoices.py",
    "backend/routers/notes.py", "backend/routers/vendor_bills.py",
    "backend/routers/mechanic_work_orders.py", "backend/routers/expenses.py",
    "backend/routers/wallet_recharges.py", "backend/routers/wallet_transfers.py",
    "backend/routers/wallet_adjustments.py", "backend/services.py",
    "backend/services_expense_bridge.py",
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
    # Seed a companies row so _active_company_id resolves this cid via header.
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
    for c in ("suppliers", "vendors", "mechanics", "drivers", "customers",
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


# ── UAT-01 · Company Bank CRUD contract
def test_01_company_crud():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            # empty
            r = await _get("/api/company-bank-accounts", cid=cid)
            assert r.status_code == 200 and r.json() == []
            # create
            r = await _post("/api/company-bank-accounts", {
                "bank_name": "HDFC", "account_holder_name": "TRUKVIA",
                "account_number": "1234567890", "ifsc": "HDFC0000123",
                "account_type": "current", "is_primary": True,
            }, cid=cid)
            assert r.status_code == 200, r.text
            j = r.json()
            bid = j["id"]
            assert j["masked_display"] == "XXXXXX7890"
            # Owner sees full account_number in the create response
            assert j["account_number"] == "1234567890"
            assert j["is_primary"] is True
            # dupe
            r2 = await _post("/api/company-bank-accounts", {
                "bank_name": "HDFC", "account_number": "1234567890",
                "ifsc": "HDFC0000123",
            }, cid=cid)
            assert r2.status_code == 409
            # reveal
            r3 = await _get(f"/api/company-bank-accounts/{bid}/reveal", cid=cid)
            assert r3.status_code == 200
            assert r3.json()["account_number"] == "1234567890"
            # set-primary invariant
            r4 = await _post("/api/company-bank-accounts", {
                "bank_name": "ICICI", "account_number": "9998887776",
                "ifsc": "ICIC0001111",
            }, cid=cid)
            bid2 = r4.json()["id"]
            await _post(f"/api/company-bank-accounts/{bid2}/set-primary", {}, cid=cid)
            rows = (await _get("/api/company-bank-accounts", cid=cid)).json()
            primaries = [x for x in rows if x["is_primary"]]
            assert len(primaries) == 1 and primaries[0]["id"] == bid2
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-02 · deactivate + no-delete
def test_02_deactivate_no_delete():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            r = await _post("/api/company-bank-accounts", {
                "bank_name": "AXIS", "account_number": "1111222233",
                "ifsc": "UTIB0000001",
            }, cid=cid)
            bid = r.json()["id"]
            await _post(f"/api/company-bank-accounts/{bid}/deactivate",
                        {"reason": "closed"}, cid=cid)
            rows = (await _get("/api/company-bank-accounts", cid=cid)).json()
            assert any(not r["is_active"] and r["id"] == bid for r in rows)
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-03 · replace creates new id and deactivates old
def test_03_replace_creates_new_id():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            r = await _post("/api/company-bank-accounts", {
                "bank_name": "SBI", "account_number": "5555666677",
                "ifsc": "SBIN0000001", "is_primary": True,
            }, cid=cid)
            old = r.json()["id"]
            r2 = await _post(f"/api/company-bank-accounts/{old}/replace", {
                "party_type": "supplier", "party_id": "unused",  # ignored for CBA
                "bank_name": "SBI", "account_number": "5555666699",
                "ifsc": "SBIN0000001",
            }, cid=cid)
            assert r2.status_code == 200
            new_id_ = r2.json()["id"]
            assert new_id_ != old
            all_rows = (await _get("/api/company-bank-accounts", cid=cid)).json()
            olds = [x for x in all_rows if x["id"] == old][0]
            assert olds["is_active"] is False
            assert olds["deactivation_reason"] == f"replaced_by:{new_id_}"
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-04 · Party bank CRUD + masking
def test_04_party_bank_crud():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            # Seed a supplier
            sid = f"sup_{uuid.uuid4().hex[:6]}"
            await db.suppliers.insert_one({"id": sid, "user_id": uid,
                "company_id": cid, "name": "SUP1", "is_active": True})
            r = await _post("/api/party-bank-accounts", {
                "party_type": "supplier", "party_id": sid,
                "bank_name": "HDFC", "account_number": "1234567890",
                "ifsc": "HDFC0000123", "is_primary": True,
            }, cid=cid)
            assert r.status_code == 200
            assert r.json()["masked_display"] == "XXXXXX7890"
            r2 = await _get(f"/api/party-bank-accounts?party_type=supplier&party_id={sid}", cid=cid)
            assert r2.status_code == 200 and len(r2.json()) == 1
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-05 · payment write with bank_account_id captures snapshot
def test_05_supplier_payment_snapshot():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            sid = f"sup_{uuid.uuid4().hex[:6]}"
            await db.suppliers.insert_one({"id": sid, "user_id": uid,
                "company_id": cid, "name": "SUP2", "is_active": True})
            r = await _post("/api/party-bank-accounts", {
                "party_type": "supplier", "party_id": sid,
                "bank_name": "HDFC", "account_number": "9876543210",
                "ifsc": "HDFC0000999", "account_holder_name": "SUP2",
            }, cid=cid)
            bid = r.json()["id"]
            rp = await _post(f"/api/suppliers/{sid}/payments", {
                "supplier_id": sid, "date": "2026-06-01", "amount": 500.0,
                "type": "payment_out", "mode": "Bank",
                "bank_account_id": bid,
            }, cid=cid)
            assert rp.status_code == 200, rp.text
            j = rp.json()
            assert j["bank_account_id"] == bid
            snap = j["bank_snapshot"]
            assert set(snap.keys()) == {"bank_name", "masked_number", "ifsc", "holder_name"}
            assert snap["masked_number"] == "XXXXXX3210"
            assert "account_number" not in snap  # full number never in snapshot
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-06 · cross-party / cross-tenant / inactive rejection
def test_06_bank_account_rejection():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            # Create supplier A with a bank
            sA = f"sup_{uuid.uuid4().hex[:6]}"
            sB = f"sup_{uuid.uuid4().hex[:6]}"
            for s in (sA, sB):
                await db.suppliers.insert_one({"id": s, "user_id": uid,
                    "company_id": cid, "name": s, "is_active": True})
            r = await _post("/api/party-bank-accounts", {
                "party_type": "supplier", "party_id": sA,
                "bank_name": "X", "account_number": "1", "ifsc": "X0000001",
            }, cid=cid)
            bA = r.json()["id"]
            # cross-party
            rp = await _post(f"/api/suppliers/{sB}/payments", {
                "supplier_id": sB, "date": "2026-06-01", "amount": 10.0,
                "type": "payment_out", "mode": "Bank",
                "bank_account_id": bA,
            }, cid=cid)
            assert rp.status_code == 400
            # inactive
            await _post(f"/api/party-bank-accounts/{bA}/deactivate", {}, cid=cid)
            rp2 = await _post(f"/api/suppliers/{sA}/payments", {
                "supplier_id": sA, "date": "2026-06-01", "amount": 10.0,
                "type": "payment_out", "mode": "Bank",
                "bank_account_id": bA,
            }, cid=cid)
            assert rp2.status_code == 400
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-07 · legacy compat — empty bank_account_id
def test_07_legacy_empty_compat():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            sid = f"sup_{uuid.uuid4().hex[:6]}"
            await db.suppliers.insert_one({"id": sid, "user_id": uid,
                "company_id": cid, "name": "L", "is_active": True})
            rp = await _post(f"/api/suppliers/{sid}/payments", {
                "supplier_id": sid, "date": "2026-06-01", "amount": 20.0,
                "type": "payment_out", "mode": "Bank",
            }, cid=cid)
            assert rp.status_code == 200
            assert rp.json()["bank_account_id"] == ""
            assert rp.json()["bank_snapshot"] == {}
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-08 · viewer role masking + reveal denied
def test_08_viewer_cannot_reveal():
    async def _t():
        uid, cid = await _mk_ctx(role="viewer")
        try:
            # Owner creates the bank first
            app.dependency_overrides.clear()
            uid2, cid2 = await _mk_ctx(role="owner")
            r = await _post("/api/company-bank-accounts", {
                "bank_name": "X", "account_number": "12345678",
                "ifsc": "X0000001",
            }, cid=cid)
            bid = r.json()["id"]
            # switch to viewer for same uid
            from auth import get_current_user
            app.dependency_overrides[get_current_user] = lambda: {
                "user_id": uid2, "email": "v@v", "effective_role": "viewer",
            }
            r2 = await _get(f"/api/company-bank-accounts/{bid}/reveal", cid=cid)
            assert r2.status_code == 403
            uid, cid = uid2, cid2
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-09 · verification_status default
def test_09_verification_status_default():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            r = await _post("/api/company-bank-accounts", {
                "bank_name": "V", "account_number": "abc",
                "ifsc": "X0000001",
            }, cid=cid)
            assert r.json()["verification_status"] == "unverified"
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-10 · 13 protected files zero-diff vs Iter150F lock
def test_10_locked_band_zero_diff():
    for rel in PROTECTED_13_NON_MODELS:
        r = subprocess.run(["git", "diff", "--exit-code", LOCKED_F, "--", rel],
                            cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0, f"{rel} drifted: {r.stdout[:400]}"


# ── UAT-11 · models.py diff is bounded to authorised additive scope
def test_11_models_diff_bounded():
    r = subprocess.run(["git", "diff", LOCKED_F, "--", "backend/models.py"],
                        cwd=REPO, capture_output=True, text=True)
    diff = r.stdout
    # Additions must ONLY touch bank_account_id / bank_snapshot / Iter150G
    additions = [ln for ln in diff.splitlines()
                 if ln.startswith("+") and not ln.startswith("+++")]
    for ln in additions:
        assert any(k in ln for k in (
            "bank_account_id", "bank_snapshot", "Iter150G",
            "manage_bank_accounts", "view_bank_account_full",
            "post-time", "legacy compat", "additive",
            'create_note", "issue_note"',
            'edit_note_settings",',
        )), f"Unauthorised addition in models.py: {ln}"
    # No removal of any existing content aside from the reflowed comma lines
    removals = [ln for ln in diff.splitlines()
                if ln.startswith("-") and not ln.startswith("---")]
    for ln in removals:
        assert any(k in ln for k in (
            'edit_note_settings"',      # existing owner line reflowed
            'create_note", "issue_note"}',  # existing accountant line reflowed
        )), f"Unauthorised removal in models.py: {ln}"


# ── UAT-12 · Iter150F reconciliation regression still green (excluding the
# 2 pre-Iter150G file-diff assertions that are now stale by design — models.py
# was authorised for an additive unfreeze; behaviour tests remain enforced).
def test_12_iter150f_regression():
    r = subprocess.run(
        ["python", "-m", "pytest", "-n0", "--tb=no", "-q",
         "tests/test_iter150f_reconciliation_reads.py",
         "tests/test_iter150f_uat_matrix.py",
         "--deselect", "tests/test_iter150f_reconciliation_reads.py::test_10_locked_band_zero_diff",
         "--deselect", "tests/test_iter150f_uat_matrix.py::test_uat_16_locked_band_zero_diff_vs_iter150e"],
        cwd=REPO / "backend", capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, r.stdout[-1500:]


# ── UAT-13 · driver / customer party support
def test_13_driver_customer_support():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            did = f"drv_{uuid.uuid4().hex[:6]}"
            await db.drivers.insert_one({"id": did, "user_id": uid,
                "name": "D", "is_active": True})
            r = await _post("/api/party-bank-accounts", {
                "party_type": "driver", "party_id": did,
                "bank_name": "X", "account_number": "1234", "ifsc": "X0000001",
            }, cid=cid)
            assert r.status_code == 200, r.text
            cid_c = f"cust_{uuid.uuid4().hex[:6]}"
            await db.customers.insert_one({"id": cid_c, "user_id": uid,
                "company_id": cid, "name": "C"})
            r2 = await _post("/api/party-bank-accounts", {
                "party_type": "customer", "party_id": cid_c,
                "bank_name": "Y", "account_number": "5678", "ifsc": "Y0000002",
            }, cid=cid)
            assert r2.status_code == 200
        finally:
            await _cleanup(uid, cid)
    _run(_t())
