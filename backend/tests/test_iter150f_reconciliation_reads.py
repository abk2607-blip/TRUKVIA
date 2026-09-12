"""Iter150F · Reconciliation Center — backend read tests."""
from __future__ import annotations
import asyncio
import subprocess
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from server import app
from db import db
from services_fin_txn import ensure_indexes, ensure_system_accounts, reproject_source
from services_fin_txn_hooks import ensure_hook_indexes

REPO = Path("/app")
LOCKED_D = "a7a3997ac275c69454b6a4de7e4aa9533a9d32f2"
PROTECTED_14 = [
    "backend/services_fin_txn.py", "backend/services_fin_txn_hooks.py",
    "backend/models.py", "backend/routers/trips.py",
    "backend/routers/invoices.py", "backend/routers/notes.py",
    "backend/routers/vendor_bills.py",
    "backend/routers/mechanic_work_orders.py",
    "backend/routers/expenses.py", "backend/routers/wallet_recharges.py",
    "backend/routers/wallet_transfers.py",
    "backend/routers/wallet_adjustments.py", "backend/services.py",
    "backend/services_expense_bridge.py",
]


def _run(coro):
    """Use a module-persistent loop so Motor client stays bound."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except Exception:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _mk_ctx():
    uid, cid = f"u_{uuid.uuid4().hex[:8]}", f"c_{uuid.uuid4().hex[:8]}"
    await ensure_indexes()
    await ensure_hook_indexes()
    await ensure_system_accounts(uid, cid)
    from auth import get_current_user
    from company import _active_company_id
    app.dependency_overrides[get_current_user] = lambda: {"user_id": uid, "email": "t@t"}
    app.dependency_overrides[_active_company_id] = lambda *a, **k: cid
    return uid, cid


async def _cleanup(uid, cid):
    app.dependency_overrides.clear()
    for c in ("invoices", "credit_debit_notes", "expenses", "vendor_bills",
              "mechanic_work_orders", "wallet_recharges", "wallet_transfers",
              "wallet_adjustments", "fin_txn", "fin_day_closures",
              "fin_hook_failures", "trips"):
        await db[c].delete_many({"user_id": uid, "company_id": cid})


async def _get(url):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(url)


def test_01_summary_contract():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            r = await _get("/api/fin/reconciliation/summary?from=2026-01-01&to=2026-12-31")
            assert r.status_code == 200
            j = r.json()
            for k in ("period", "company_id", "computed_at", "kpis", "bd5_note"):
                assert k in j
            for d in "ABCDEFGH":
                assert d in j["kpis"]
            assert j["bd5_note"].startswith("Day Closing snapshots do not auto-refresh")
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_02_domain_endpoint_all_domains():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            for d in "ABCDEFGH":
                r = await _get(f"/api/fin/reconciliation/domain/{d}?from=2026-01-01&to=2026-12-31")
                assert r.status_code == 200, d
                j = r.json()
                assert j["domain"] == d
                for k in ("rows", "total", "computed_at"):
                    assert k in j
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_03_domain_unknown_400():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            r = await _get("/api/fin/reconciliation/domain/Z?from=&to=")
            assert r.status_code == 400
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_04_pagination_bounds():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            r = await _get("/api/fin/reconciliation/domain/A?size=501")
            assert r.status_code == 422
            r = await _get("/api/fin/reconciliation/domain/A?size=100&page=1")
            assert r.status_code == 200
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_05_domain_a_missing_legs_then_reproject_clears():
    from services_reconciliation import domain_a
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            inv_id = f"inv_{uuid.uuid4().hex[:6]}"
            await db.invoices.insert_one({"id": inv_id, "user_id": uid, "company_id": cid,
                "invoice_number": "INV/1", "invoice_date": "2026-06-01",
                "customer_id": "cu1", "total_amount": 10000.0, "balance_due": 10000.0,
                "advance_deduction_total": 0, "diesel_deduction_total": 0, "payments": []})
            res = await domain_a(uid, cid, "2026-01-01", "2026-12-31", 1, 500)
            hits = [x for x in res["rows"] if x.get("source_id") == inv_id]
            assert hits and hits[0]["status"] == "rose", hits
            await reproject_source(uid, cid, "invoice", inv_id)
            res2 = await domain_a(uid, cid, "2026-01-01", "2026-12-31", 1, 500)
            hits2 = [x for x in res2["rows"] if x.get("source_id") == inv_id]
            assert not hits2
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_06_domain_b_expense_clean():
    from services_reconciliation import domain_b
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            eid = f"e_{uuid.uuid4().hex[:6]}"
            await db.expenses.insert_one({"id": eid, "user_id": uid, "company_id": cid,
                "date": "2026-06-15", "amount": 5000.0, "category": "Misc",
                "settlement_mode": "cash_now", "party_type": "vendor"})
            await reproject_source(uid, cid, "expense", eid)
            res = await domain_b(uid, cid, "2026-01-01", "2026-12-31")
            assert res["status"] == "emerald", res
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_07_domain_g_pending_amber_permfailed_rose():
    from services_reconciliation import domain_g
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            await db.fin_hook_failures.insert_many([
                {"id": "f1", "user_id": uid, "company_id": cid,
                 "source_type": "invoice", "source_id": "x1",
                 "status": "pending", "retry_count": 0},
                {"id": "f2", "user_id": uid, "company_id": cid,
                 "source_type": "invoice", "source_id": "x2",
                 "status": "permanently_failed", "retry_count": 8},
            ])
            rows = await domain_g(uid, cid, "", "")
            m = {x["key"]: x for x in rows}
            assert m["f1"]["status"] == "amber"
            assert m["f2"]["status"] == "rose"
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_08_domain_h_amber_never_rose_no_snapshot_mutation():
    from services_reconciliation import domain_h
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            cd = {"id": f"dc_{uuid.uuid4().hex[:6]}", "user_id": uid,
                  "company_id": cid, "close_date": "2026-06-30",
                  "status": "closed",
                  "accounts": [{"account_code": "AR", "closing_balance": 100000.0}]}
            await db.fin_day_closures.insert_one(dict(cd))
            rows = await domain_h(uid, cid, "2026-01-01", "2026-12-31")
            assert rows and all(x["status"] == "amber" for x in rows)
            post = await db.fin_day_closures.find_one({"id": cd["id"]}, {"_id": 0})
            assert post["accounts"][0]["closing_balance"] == 100000.0
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_09_no_write_guarantees():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            for _ in range(3):
                await _get("/api/fin/reconciliation/summary")
            colls = await db.list_collection_names()
            assert "fin_reconciliations" not in colls
        finally:
            await _cleanup(uid, cid)
    _run(_t())


def test_10_locked_band_zero_diff():
    for rel in PROTECTED_14:
        r = subprocess.run(["git", "diff", "--exit-code", LOCKED_D, "--", rel],
                           cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0, f"{rel} drifted: {r.stdout[:400]}"


def test_11_mismatch_endpoint_shape():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            r = await _get("/api/fin/reconciliation/mismatch/B/expense_total")
            assert r.status_code == 200
            j = r.json()
            assert j["domain"] == "B" and "computed_at" in j
        finally:
            await _cleanup(uid, cid)
    _run(_t())
