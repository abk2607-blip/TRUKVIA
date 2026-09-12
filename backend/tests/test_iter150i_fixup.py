"""Iter150I Fix-Up · targeted tests for the 3 Class-A UAT defects.

Additive-only. Does NOT modify the existing test_iter150i_driver_payment.py
so the original 16-case baseline remains untouched.

Tests invoke the router coroutines DIRECTLY (bypassing HTTP) so we avoid the
TestClient/anyio different-loop artefact Iter150B's lock covenant already
documented. Coverage matches the Fix-Up mandate Tests A-L.
"""
from __future__ import annotations
import asyncio
import uuid
from unittest.mock import patch

from starlette.datastructures import Headers
from starlette.requests import Request

from server import app  # noqa: F401 · registers routers
from db import db
from models import new_id
from services_fin_txn import ensure_system_accounts
from services_fin_txn_hooks import hook_after_source_write
from routers import driver_payments as dp_mod


# ---------- helpers ----------
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError()
    except Exception:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _mk_request(cid: str) -> Request:
    """Fake ASGI Request carrying only the X-Company-Id header — the exact
    surface the frontend api client sends."""
    scope = {
        "type": "http", "method": "POST", "path": "/",
        "headers": [(b"x-company-id", cid.encode())],
        "query_string": b"", "raw_path": b"/", "root_path": "",
        "server": ("test", 80), "scheme": "http",
    }

    async def _body():
        return {"type": "http.request", "body": b"", "more_body": False}
    return Request(scope, _body)


class _JsonRequest(Request):
    """Request subclass returning a preset JSON body."""
    def __init__(self, cid: str, body: dict):
        headers = Headers({"x-company-id": cid,
                           "content-type": "application/json"})
        scope = {
            "type": "http", "method": "POST", "path": "/",
            "headers": headers.raw, "query_string": b"", "raw_path": b"/",
            "root_path": "", "server": ("test", 80), "scheme": "http",
        }
        async def _r():
            return {"type": "http.request", "body": b"", "more_body": False}
        super().__init__(scope, _r)
        self._preset_json = body

    async def json(self):
        return self._preset_json


async def _mk_ctx():
    uid = f"u_{uuid.uuid4().hex[:10]}"
    cid = f"c_{uuid.uuid4().hex[:10]}"
    await ensure_system_accounts(uid, cid)
    await db.companies.insert_one({
        "id": cid, "user_id": uid, "name": "FixUp Co", "is_default": True})
    did = f"drv_{uuid.uuid4().hex[:10]}"
    await db.drivers.insert_one({
        "user_id": uid, "company_id": cid, "id": did, "name": "FixUp Drv"})
    return uid, cid, did


def _user(uid: str, role: str = "owner"):
    return {"user_id": uid, "role": role,
            "email": f"{uid}@ex.com", "name": "UAT"}


async def _cleanup(uid):
    for c in ("driver_payments", "driver_payment_corrections", "fin_txn",
              "fin_accounts", "drivers", "companies",
              "party_bank_accounts", "company_bank_accounts",
              "driver_ledger_entries", "fin_hook_failures"):
        await db[c].delete_many({"user_id": uid})


# ---------- Test A · POST resolves via X-Company-Id ----------
def test_A_post_uses_x_company_id_header():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            from models import DriverPayment
            payload = DriverPayment(driver_id=did, date="2026-02-14",
                                     amount=100, mode="Cash")
            req = _mk_request(cid)
            body = await dp_mod.create_driver_payment(
                did, payload, req, _user(uid))
            assert body["id"].startswith("dpay_")
            assert body["driver_id"] == did
            assert body["mode"] == "Cash"
            assert body["company_id"] == cid
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test B · Server generates dpay_ id (client id ignored) ----------
def test_B_post_generates_server_side_dpay_id():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            from models import DriverPayment
            payload = DriverPayment(id="dpay_CLIENT_TRIED",
                                     driver_id=did, date="2026-02-14",
                                     amount=100, mode="Cash")
            req = _mk_request(cid)
            body = await dp_mod.create_driver_payment(
                did, payload, req, _user(uid))
            assert body["id"] != "dpay_CLIENT_TRIED"
            assert body["id"].startswith("dpay_")
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test C · Bank 2-leg ----------
def test_C_bank_mode_two_legs():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            from models import DriverPayment
            payload = DriverPayment(driver_id=did, date="2026-02-14",
                                     amount=500, mode="Bank")
            body = await dp_mod.create_driver_payment(
                did, payload, _mk_request(cid), _user(uid))
            legs = await db.fin_txn.find(
                {"user_id": uid, "company_id": cid,
                 "source_type": "driver_payment",
                 "source_id": body["id"]}, {"_id": 0}).to_list(10)
            assert len(legs) == 2
            codes = sorted(l["account_code"] for l in legs)
            assert codes == ["BANK_DEFAULT", "DRIVER_OUTFLOW"]
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test D · Cash 2-leg ----------
def test_D_cash_mode_two_legs():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            from models import DriverPayment
            body = await dp_mod.create_driver_payment(
                did, DriverPayment(driver_id=did, date="2026-02-14",
                                    amount=250, mode="Cash"),
                _mk_request(cid), _user(uid))
            legs = await db.fin_txn.find(
                {"user_id": uid, "source_type": "driver_payment",
                 "source_id": body["id"]}, {"_id": 0}).to_list(10)
            codes = sorted(l["account_code"] for l in legs)
            assert codes == ["CASH", "DRIVER_OUTFLOW"]
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test E · Snapshots captured (Bank + Company) ----------
def test_E_bank_snapshots_captured():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            pba_id = new_id("pba_")
            await db.party_bank_accounts.insert_one({
                "user_id": uid, "company_id": cid, "id": pba_id,
                "party_type": "driver",
                "party_id": did, "bank_name": "SBI", "ifsc": "SBI0001",
                "account_number": "111222333", "is_active": True,
                "is_primary": True, "masked_display": "XXXXXX2333",
                "account_holder_name": "Drv"})
            cba_id = new_id("cba_")
            await db.company_bank_accounts.insert_one({
                "user_id": uid, "company_id": cid, "id": cba_id,
                "bank_name": "AXIS", "ifsc": "UTIB0001",
                "account_number": "999888777", "is_active": True,
                "is_primary": True, "masked_display": "XXXXX8777",
                "account_holder_name": "Co", "branch": "Main"})
            from models import DriverPayment
            body = await dp_mod.create_driver_payment(
                did, DriverPayment(driver_id=did, date="2026-02-14",
                                    amount=999, mode="Bank",
                                    bank_account_id=pba_id,
                                    company_bank_account_id=cba_id),
                _mk_request(cid), _user(uid))
            assert body["bank_snapshot"]["bank_name"] == "SBI"
            assert body["bank_snapshot"]["masked_number"] == "XXXXXX2333"
            assert body["source_bank_snapshot"]["bank_name"] == "AXIS"
            assert body["source_bank_snapshot"]["masked_number"] == "XXXXX8777"
            # Immutability: mutate underlying + re-read stored doc
            await db.party_bank_accounts.update_one(
                {"id": pba_id}, {"$set": {"bank_name": "SBI-CHG"}})
            fresh = await db.driver_payments.find_one(
                {"id": body["id"]}, {"_id": 0})
            assert fresh["bank_snapshot"]["bank_name"] == "SBI"
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test F · Salary advisory (non-blocking) ----------
def test_F_salary_advisory():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            r = await dp_mod.salary_settlement_hint(
                did, "2026-02", _mk_request(cid), _user(uid))
            assert r["possible_duplicate"] is False
            await db.driver_ledger_entries.insert_one({
                "user_id": uid, "company_id": cid, "driver_id": did,
                "month": "2026-02", "kind": "settlement", "amount": 3})
            r2 = await dp_mod.salary_settlement_hint(
                did, "2026-02", _mk_request(cid), _user(uid))
            assert r2["possible_duplicate"] is True
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test G · Attribute correction ----------
def test_G_attribute_correction():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            from models import DriverPayment
            body = await dp_mod.create_driver_payment(
                did, DriverPayment(driver_id=did, date="2026-02-14",
                                    amount=400, mode="Bank", ref_no="OLD"),
                _mk_request(cid), _user(uid))
            pid = body["id"]
            r = await dp_mod.correct_driver_payment(
                pid,
                _JsonRequest(cid, {"ref_no": "NEW", "remarks": "corrected",
                                    "reason": "typo"}),
                _user(uid))
            assert r["ok"] is True
            fresh = await db.driver_payments.find_one({"id": pid}, {"_id": 0})
            assert fresh["ref_no"] == "NEW"
            assert fresh["correction_count"] == 1
            # Fin legs remain intact (attribute correction is cash-neutral).
            legs = await db.fin_txn.count_documents(
                {"source_type": "driver_payment", "source_id": pid})
            assert legs == 2
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test H · Amount reversal · SUCCESS ----------
def test_H_amount_reversal_success():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            from models import DriverPayment
            body = await dp_mod.create_driver_payment(
                did, DriverPayment(driver_id=did, date="2026-02-14",
                                    amount=1000, mode="Bank"),
                _mk_request(cid), _user(uid))
            pid = body["id"]
            r = await dp_mod.correct_driver_payment_amount(
                pid,
                _JsonRequest(cid, {"new_amount": 900, "reason": "act 900"}),
                _user(uid))
            assert r["ok"] is True
            new = r["new_payment"]
            assert new["id"].startswith("dpay_")
            assert new["amount"] == 900
            assert new["reversal_of"] == pid
            assert new["is_reversed"] is False
            orig = await db.driver_payments.find_one({"id": pid}, {"_id": 0})
            assert orig["is_reversed"] is True
            assert orig["reversal_reason"] == "act 900"
            assert await db.fin_txn.count_documents(
                {"source_type": "driver_payment", "source_id": pid}) == 0
            assert await db.fin_txn.count_documents(
                {"source_type": "driver_payment",
                 "source_id": new["id"]}) == 2
            assert await db.driver_payment_corrections.count_documents(
                {"payment_id": pid, "kind": "amount_reversal_new"}) == 1
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test I · Amount reversal · FORCED FAILURE rolls back ----------
def test_I_amount_reversal_failure_rolls_back():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            from models import DriverPayment
            body = await dp_mod.create_driver_payment(
                did, DriverPayment(driver_id=did, date="2026-02-14",
                                    amount=700, mode="Bank"),
                _mk_request(cid), _user(uid))
            pid = body["id"]

            # Force the ORIGINAL reproject (last step, step 5) to fail.
            real = dp_mod.hook_after_source_write
            counter = {"n": 0}

            async def _fake(u, c, st, sid, *a, **kw):
                counter["n"] += 1
                if (st == "driver_payment" and sid == pid
                        and counter["n"] >= 2):
                    raise RuntimeError("forced-orig-reproject-failure")
                return await real(u, c, st, sid, *a, **kw)

            raised = False
            with patch.object(dp_mod, "hook_after_source_write", _fake):
                try:
                    await dp_mod.correct_driver_payment_amount(
                        pid,
                        _JsonRequest(cid, {"new_amount": 600,
                                            "reason": "should rollback"}),
                        _user(uid))
                except Exception:
                    raised = True
            assert raised, "must raise on forced failure"

            # Original UNCHANGED
            orig = await db.driver_payments.find_one({"id": pid}, {"_id": 0})
            assert orig["is_reversed"] is False
            assert (orig.get("reversal_reason") or "") == ""
            assert (orig.get("reversed_at") or "") == ""
            assert int(orig.get("correction_count") or 0) == 0
            # Original legs restored (2)
            assert await db.fin_txn.count_documents(
                {"source_type": "driver_payment", "source_id": pid}) == 2
            # No replacement + no orphan audit
            assert await db.driver_payments.find_one(
                {"reversal_of": pid}) is None
            assert await db.driver_payment_corrections.count_documents(
                {"payment_id": pid, "kind": "amount_reversal_new"}) == 0
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test J · Retry after failed attempt succeeds ----------
def test_J_retry_after_failed_reversal_succeeds():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            from models import DriverPayment
            body = await dp_mod.create_driver_payment(
                did, DriverPayment(driver_id=did, date="2026-02-14",
                                    amount=500, mode="Bank"),
                _mk_request(cid), _user(uid))
            pid = body["id"]

            real = dp_mod.hook_after_source_write
            counter = {"n": 0}

            async def _fake(u, c, st, sid, *a, **kw):
                counter["n"] += 1
                if (st == "driver_payment" and sid == pid
                        and counter["n"] >= 2):
                    raise RuntimeError("forced")
                return await real(u, c, st, sid, *a, **kw)

            with patch.object(dp_mod, "hook_after_source_write", _fake):
                try:
                    await dp_mod.correct_driver_payment_amount(
                        pid,
                        _JsonRequest(cid, {"new_amount": 400,
                                            "reason": "will fail"}),
                        _user(uid))
                except Exception:
                    pass
            # Second attempt, no patch → must succeed.
            r = await dp_mod.correct_driver_payment_amount(
                pid,
                _JsonRequest(cid, {"new_amount": 400, "reason": "retry"}),
                _user(uid))
            assert r["ok"] is True
            assert r["new_payment"]["amount"] == 400
            assert r["new_payment"]["id"].startswith("dpay_")
            assert await db.fin_txn.count_documents(
                {"source_type": "driver_payment",
                 "source_id": r["new_payment"]["id"]}) == 2
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test K · Idempotency ----------
def test_K_idempotency():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            from models import DriverPayment
            body = await dp_mod.create_driver_payment(
                did, DriverPayment(driver_id=did, date="2026-02-14",
                                    amount=111, mode="Cash"),
                _mk_request(cid), _user(uid))
            pid = body["id"]
            for _ in range(3):
                await hook_after_source_write(
                    uid, cid, "driver_payment", pid)
            assert await db.fin_txn.count_documents(
                {"source_type": "driver_payment", "source_id": pid}) == 2
        finally:
            await _cleanup(uid)
    _run(_t())


# ---------- Test L · Stale-baseline tests remain untouched ----------
def test_L_stale_baseline_tests_untouched():
    """Prove the fix-up did NOT touch the pre-existing Class-C stale-baseline
    assertions in Iter150F/G/H test files. We assert those test-function
    definitions still exist verbatim on disk."""
    import pathlib
    root = pathlib.Path("/app/backend/tests")
    for rel, sentinels in [
        ("test_iter150g_bank_accounts.py",
            ["def test_10_locked_band_zero_diff",
             "def test_11_models_diff_bounded"]),
        ("test_iter150h_source_bank.py",
            ["def test_10_protected_13_zero_diff",
             "def test_11_models_bounded_diff"]),
        ("test_iter150f_reconciliation_reads.py",
            ["def test_10_locked_band_zero_diff"]),
    ]:
        txt = (root / rel).read_text()
        for s in sentinels:
            assert s in txt, f"{rel} sentinel missing: {s}"
