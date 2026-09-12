"""Iter150I · DriverPayment foundation regression tests.

Additive-only. Strict +X/-0 protected-band posture verified.
"""
import asyncio
import uuid
import subprocess
from pathlib import Path
import pytest

from server import app  # noqa
from db import db
from models import (
    DriverPayment, DriverPaymentCorrection, FIN_SYSTEM_ACCOUNTS,
    ROLE_PERMISSIONS,
)
from services_fin_txn import (
    SUPPORTED_SOURCE_TYPES, project_driver_payment,
    ensure_system_accounts, reproject_source,
)
from services_fin_txn_hooks import hook_after_source_write

REPO = Path("/app")
ITER150G_LOCK = "e655839bfcf0ae4659e4707ded6ad872f6d27c35"
ITER150H_LOCK = "a722778f71f6f8a6bf26691c97c1cf2e1eb62351"

PROTECTED_11 = [
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


async def _mk_ctx():
    uid = f"u_{uuid.uuid4().hex[:8]}"
    cid = f"c_{uuid.uuid4().hex[:8]}"
    await ensure_system_accounts(uid, cid)
    await db.companies.insert_one({"id": cid, "user_id": uid, "name": "T"})
    did = f"drv_{uuid.uuid4().hex[:8]}"
    await db.drivers.insert_one({"user_id": uid, "company_id": cid,
                                  "id": did, "name": "Test Driver"})
    return uid, cid, did


async def _cleanup(uid, cid):
    for c in ("driver_payments", "driver_payment_corrections", "fin_txn",
              "fin_accounts", "drivers", "companies"):
        await db[c].delete_many({"user_id": uid})


# --- 1. Model shape ---
def test_01_driverpayment_model_shape():
    d = DriverPayment(driver_id="drv_x", date="2026-02-14", amount=100)
    assert d.id.startswith("dpay_")
    assert d.type == "payment_out"
    assert d.mode == "Bank"
    assert d.against == "other"
    assert d.bank_snapshot == {} and d.source_bank_snapshot == {}


def test_02_driverpaymentcorrection_model_shape():
    c = DriverPaymentCorrection(payment_id="dpay_x", correction_index=1)
    assert c.id.startswith("dpcr_")
    assert c.kind == "attribute"


# --- 3-5. Source type + seed + account permissions ---
def test_03_driver_payment_in_supported_source_types():
    assert "driver_payment" in SUPPORTED_SOURCE_TYPES


def test_04_driver_outflow_seeded():
    codes = [x["code"] for x in FIN_SYSTEM_ACCOUNTS]
    assert "DRIVER_OUTFLOW" in codes


def test_05_permission_reuse():
    assert "manage_bank_accounts" in ROLE_PERMISSIONS["owner"]
    assert "manage_bank_accounts" in ROLE_PERMISSIONS["accountant"]
    assert "manage_driver_payments" not in ROLE_PERMISSIONS["owner"]


# --- 6-9. Projection shape ---
def test_06_bank_mode_two_legs():
    dp = DriverPayment(driver_id="drv_x", date="2026-02-14",
                       amount=250, mode="Bank").model_dump()
    dp["id"] = "dpay_bank"
    legs = project_driver_payment(dp)
    assert len(legs) == 2
    codes = sorted(l["account_code"] for l in legs)
    assert codes == ["BANK_DEFAULT", "DRIVER_OUTFLOW"]


def test_07_cash_mode_two_legs():
    dp = DriverPayment(driver_id="drv_x", date="2026-02-14",
                       amount=100, mode="Cash").model_dump()
    dp["id"] = "dpay_cash"
    legs = project_driver_payment(dp)
    codes = sorted(l["account_code"] for l in legs)
    assert codes == ["CASH", "DRIVER_OUTFLOW"]


def test_08_all_bank_modes_route_to_bank_default():
    for m in ["UPI", "IMPS", "NEFT", "RTGS", "Cheque", "Other", "Bank"]:
        dp = DriverPayment(driver_id="drv_x", date="2026-02-14",
                           amount=50, mode=m).model_dump()
        dp["id"] = f"dpay_{m}"
        legs = project_driver_payment(dp)
        assert any(l["account_code"] == "BANK_DEFAULT" for l in legs), m


def test_09_reversed_payment_produces_no_legs():
    dp = DriverPayment(driver_id="drv_x", date="2026-02-14",
                       amount=100).model_dump()
    dp["id"] = "dpay_rev"; dp["is_reversed"] = True
    assert project_driver_payment(dp) == []


# --- 10-11. End-to-end via hook ---
def test_10_hook_projects_driver_payment():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            dp = DriverPayment(driver_id=did, date="2026-02-14",
                               amount=500, mode="Bank").model_dump()
            dp["id"] = "dpay_e2e"; dp["user_id"] = uid; dp["company_id"] = cid
            await db.driver_payments.insert_one(dict(dp))
            r = await hook_after_source_write(uid, cid, "driver_payment",
                                                "dpay_e2e")
            assert r["ok"] is True
            assert r["written"] == 2
            n = await db.fin_txn.count_documents(
                {"user_id": uid, "company_id": cid,
                 "source_type": "driver_payment", "source_id": "dpay_e2e"})
            assert n == 2
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_11_reproject_is_idempotent():
    async def _t():
        uid, cid, did = await _mk_ctx()
        try:
            dp = DriverPayment(driver_id=did, date="2026-02-14",
                               amount=200).model_dump()
            dp["id"] = "dpay_idem"; dp["user_id"] = uid; dp["company_id"] = cid
            await db.driver_payments.insert_one(dict(dp))
            await hook_after_source_write(uid, cid, "driver_payment", dp["id"])
            await hook_after_source_write(uid, cid, "driver_payment", dp["id"])
            n = await db.fin_txn.count_documents(
                {"user_id": uid, "source_type": "driver_payment"})
            assert n == 2
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# --- 12. Locked-band strict integrity ---
def test_12_protected_11_zero_diff_vs_iter150g_lock():
    for rel in PROTECTED_11:
        r = subprocess.run(["git", "diff", "--exit-code", ITER150G_LOCK,
                            "--", rel], cwd=REPO,
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{rel} drifted: {r.stdout[:200]}"


def test_13_models_and_fin_files_additive_only():
    for rel in ("backend/models.py", "backend/services_fin_txn.py",
                "backend/services_fin_txn_hooks.py"):
        r = subprocess.run(
            ["git", "diff", "--numstat", ITER150H_LOCK, "--", rel],
            cwd=REPO, capture_output=True, text=True)
        line = (r.stdout or "").strip().split()
        # No diff → empty output allowed. Non-empty must be `+X 0 path`.
        if line:
            added, removed = line[0], line[1]
            assert removed == "0", f"{rel} has removals: {r.stdout}"


def test_14_ceilings_respected():
    caps = {"backend/models.py": 75,
            "backend/services_fin_txn.py": 25,
            "backend/services_fin_txn_hooks.py": 3}
    for rel, cap in caps.items():
        r = subprocess.run(
            ["git", "diff", "--numstat", ITER150H_LOCK, "--", rel],
            cwd=REPO, capture_output=True, text=True)
        line = (r.stdout or "").strip().split()
        added = int(line[0]) if line else 0
        assert added <= cap, f"{rel} exceeded ceiling {cap}: +{added}"


# --- 15. Batta / salary invariants ---
def test_15_batta_semantics_unchanged():
    # Trip.batta flows through Expense (category=batta) to EXPENSE_DEFAULT.
    # We assert no DriverPayment code path touches Expense.
    import inspect
    from routers import driver_payments as dp_router
    src = inspect.getsource(dp_router)
    assert "expenses" not in src.lower() or "db.expenses" not in src
    assert "batta" not in src.lower()


def test_16_salary_endpoints_do_not_project_driver_payment():
    import inspect
    from routers import driver_ledger
    src = inspect.getsource(driver_ledger)
    assert 'source_type="driver_payment"' not in src
    assert "'driver_payment'" not in src
