"""Iter150F · Reconciliation Center — FULL UAT MATRIX (owner-authorised).

Read-only functional UAT covering every explicit business item from the
UAT sweep authorisation. Zero writes. No production code modified.
"""
from __future__ import annotations
import asyncio
import inspect
import subprocess
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from server import app
from db import db
from services_fin_txn import ensure_indexes, ensure_system_accounts, reproject_source
from services_fin_txn_hooks import ensure_hook_indexes
import services_reconciliation as SR

REPO = Path("/app")
LOCKED_E = "54237519de160f06307df8052410d7bc056e0f17"
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


# ── UAT-01 · Authentication required (no dep override)
def test_uat_01_auth_required_no_override():
    async def _t():
        app.dependency_overrides.clear()
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://t") as c:
            for path in [
                "/api/fin/reconciliation/summary",
                "/api/fin/reconciliation/domain/A",
                "/api/fin/reconciliation/mismatch/B/x",
            ]:
                r = await c.get(path)
                # 401 (or 403) — MUST NOT be 200
                assert r.status_code in (401, 403), (path, r.status_code)
    _run(_t())


# ── UAT-02 · Tenant isolation — cid-B docs invisible to cid-A caller
def test_uat_02_tenant_isolation():
    async def _t():
        uid_a, cid_a = await _mk_ctx()
        try:
            # seed an invoice on a DIFFERENT (uid,cid)
            other_uid, other_cid = f"u_{uuid.uuid4().hex[:6]}", f"c_{uuid.uuid4().hex[:6]}"
            await ensure_system_accounts(other_uid, other_cid)
            inv_other = f"inv_{uuid.uuid4().hex[:6]}"
            await db.invoices.insert_one({"id": inv_other, "user_id": other_uid,
                "company_id": other_cid, "invoice_number": "INV/OTHER",
                "invoice_date": "2026-06-01", "customer_id": "cu_x",
                "total_amount": 999.0, "balance_due": 999.0,
                "advance_deduction_total": 0, "diesel_deduction_total": 0,
                "payments": []})
            # caller is uid_a/cid_a
            r = await _get("/api/fin/reconciliation/domain/A?from=2026-01-01&to=2026-12-31&size=500")
            assert r.status_code == 200
            j = r.json()
            leaked = [x for x in j["rows"] if x.get("source_id") == inv_other]
            assert not leaked, f"Tenant leak: {leaked}"
            # cleanup foreign tenant
            await db.invoices.delete_many({"user_id": other_uid,
                                            "company_id": other_cid})
            await db.fin_txn.delete_many({"user_id": other_uid,
                                           "company_id": other_cid})
        finally:
            await _cleanup(uid_a, cid_a)
    _run(_t())


# ── UAT-03 · Business-date filtering (created_at MUST NOT filter)
def test_uat_03_business_date_only():
    """Insert an invoice with business date OUTSIDE window; must not appear."""
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            inv_out = f"inv_{uuid.uuid4().hex[:6]}"
            inv_in = f"inv_{uuid.uuid4().hex[:6]}"
            # OUT-of-window invoice (business date 2025-01-01)
            await db.invoices.insert_one({"id": inv_out, "user_id": uid,
                "company_id": cid, "invoice_number": "INV/OLD",
                "invoice_date": "2025-01-01", "customer_id": "cu1",
                "total_amount": 100.0, "balance_due": 100.0,
                "advance_deduction_total": 0, "diesel_deduction_total": 0,
                "payments": []})
            # IN-window invoice (business date 2026-06-01)
            await db.invoices.insert_one({"id": inv_in, "user_id": uid,
                "company_id": cid, "invoice_number": "INV/NEW",
                "invoice_date": "2026-06-01", "customer_id": "cu1",
                "total_amount": 200.0, "balance_due": 200.0,
                "advance_deduction_total": 0, "diesel_deduction_total": 0,
                "payments": []})
            res = await SR.domain_a(uid, cid, "2026-01-01", "2026-12-31", 1, 500)
            ids = [r.get("source_id") for r in res["rows"]]
            assert inv_in in ids
            assert inv_out not in ids, "Old business-date invoice leaked"
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-04 · Source signature — no `created_at` parameter, only business dates
def test_uat_04_no_created_at_in_source():
    src = inspect.getsource(SR)
    assert "created_at" not in src, "services_reconciliation must not filter by created_at"


# ── UAT-05 · No writer sinks reachable
def test_uat_05_no_writer_sinks_in_source():
    src = inspect.getsource(SR)
    for forbidden in [
        "db.fin_txn.insert", "db.fin_txn.update", "db.fin_txn.delete",
        "db.fin_day_closures.insert", "db.fin_day_closures.update",
        "db.fin_day_closures.delete",
        "db.fin_reconciliations",  # collection must not be referenced
        "create_index", "ensure_index",  # no new indexes
        "reconciled_at", "reconciled_ref",  # FinTxn mutation fields
    ]:
        assert forbidden not in src, f"Forbidden write sink present: {forbidden}"


# ── UAT-06 · Domain B — exact 0.01 boundary (rose vs emerald)
def test_uat_06_domain_b_epsilon_boundary():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            # Case 1 — source ₹100.00 vs projected via reproject → clean emerald
            eid = f"e_{uuid.uuid4().hex[:6]}"
            await db.expenses.insert_one({"id": eid, "user_id": uid, "company_id": cid,
                "date": "2026-06-01", "amount": 100.00, "category": "Misc",
                "settlement_mode": "cash_now", "party_type": "vendor"})
            await reproject_source(uid, cid, "expense", eid)
            res = await SR.domain_b(uid, cid, "2026-01-01", "2026-12-31")
            assert res["status"] == "emerald", res

            # Case 2 — inject an orphan EXPENSE_DEFAULT leg of ₹0.02 (drift > eps)
            # (write to fin_txn ONLY in test to simulate drift; not by service.)
            await db.fin_txn.insert_one({
                "id": f"ft_{uuid.uuid4().hex[:8]}", "user_id": uid,
                "company_id": cid, "source_type": "expense",
                "source_id": "TEST_ORPHAN", "account_code": "EXPENSE_DEFAULT",
                "ref_source_key": f"uat06:orphan:{uuid.uuid4().hex[:6]}",
                "direction": "in", "amount": 0.02, "txn_date": "2026-06-05"})
            res2 = await SR.domain_b(uid, cid, "2026-01-01", "2026-12-31")
            assert res2["status"] == "rose"
            assert abs(res2["delta"] - 0.02) < 1e-9

            # Case 3 — a ₹0.01 drift is at the boundary (|Δ|>0.01 is rose)
            # Reset — remove the 0.02 and inject 0.01 exactly (== eps → emerald)
            await db.fin_txn.delete_one({"source_id": "TEST_ORPHAN"})
            await db.fin_txn.insert_one({
                "id": f"ft_{uuid.uuid4().hex[:8]}", "user_id": uid,
                "company_id": cid, "source_type": "expense",
                "source_id": "TEST_EPS", "account_code": "EXPENSE_DEFAULT",
                "ref_source_key": f"uat06:eps:{uuid.uuid4().hex[:6]}",
                "direction": "in", "amount": 0.01, "txn_date": "2026-06-05"})
            res3 = await SR.domain_b(uid, cid, "2026-01-01", "2026-12-31")
            # |0.01| > FIN_ABS_EPS (0.01) is False → emerald boundary
            assert res3["status"] == "emerald", res3
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-07 · Domain C — inside 5% amber, outside rose
def test_uat_07_domain_c_tolerance_bands():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            # Seed 1 invoice ₹10,000 (balance_due=10,000)
            inv_id = f"inv_{uuid.uuid4().hex[:6]}"
            await db.invoices.insert_one({"id": inv_id, "user_id": uid,
                "company_id": cid, "invoice_number": "INV/T1",
                "invoice_date": "2026-06-01", "customer_id": "cu1",
                "total_amount": 10000.0, "balance_due": 10000.0,
                "advance_deduction_total": 0, "diesel_deduction_total": 0,
                "payments": []})
            await reproject_source(uid, cid, "invoice", inv_id)
            # Baseline should be emerald (perfect match).
            res = await SR.domain_c(uid, cid, "2026-01-01", "2026-12-31")
            assert res["status"] == "emerald", res

            # Introduce a ₹100 AR-in drift (1% of 10,000 → inside amber band)
            await db.fin_txn.insert_one({
                "id": f"ft_{uuid.uuid4().hex[:8]}", "user_id": uid,
                "company_id": cid, "source_type": "invoice",
                "source_id": "TEST_AMBER", "account_code": "AR",
                "ref_source_key": f"uat07:amber:{uuid.uuid4().hex[:6]}",
                "direction": "in", "amount": 100.0, "txn_date": "2026-06-15"})
            res2 = await SR.domain_c(uid, cid, "2026-01-01", "2026-12-31")
            assert res2["status"] == "amber", res2

            # Add another ₹1000 (11% → outside 5% band → rose)
            await db.fin_txn.insert_one({
                "id": f"ft_{uuid.uuid4().hex[:8]}", "user_id": uid,
                "company_id": cid, "source_type": "invoice",
                "source_id": "TEST_ROSE", "account_code": "AR",
                "ref_source_key": f"uat07:rose:{uuid.uuid4().hex[:6]}",
                "direction": "in", "amount": 1000.0, "txn_date": "2026-06-16"})
            res3 = await SR.domain_c(uid, cid, "2026-01-01", "2026-12-31")
            assert res3["status"] == "rose", res3
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-08 · Domain D — issued CN
def test_uat_08_domain_d_issued_cn():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            note_id = f"n_{uuid.uuid4().hex[:6]}"
            await db.credit_debit_notes.insert_one({"id": note_id, "user_id": uid,
                "company_id": cid, "kind": "credit", "status": "issued",
                "note_number": "CN/1", "note_date": "2026-06-01",
                "invoice_id": "inv_x", "customer_id": "cu_x",
                "total_amount": 500.0, "reason": "adj"})
            await reproject_source(uid, cid, "credit_debit_note", note_id)
            rows = await SR.domain_d(uid, cid, "2026-01-01", "2026-12-31")
            cred = next(r for r in rows if r["key"] == "credit")
            assert cred["status"] == "emerald", cred
            assert abs(cred["source"] - 500.0) < 1e-9
            assert abs(cred["projected"] - 500.0) < 1e-9
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-09 · Domain E — wallet recharge → emerald
def test_uat_09_domain_e_wallet_recharge_clean():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            rid = f"wr_{uuid.uuid4().hex[:6]}"
            await db.wallet_recharges.insert_one({"id": rid, "user_id": uid,
                "company_id": cid, "wallet_code": "WALLET_FUEL",
                "date": "2026-06-01", "amount": 2000.0,
                "settlement_mode": "cash_now", "party_type": "vendor"})
            await reproject_source(uid, cid, "wallet_recharge", rid)
            rows = await SR.domain_e(uid, cid, "2026-01-01", "2026-12-31")
            fuel = next(r for r in rows if r["key"] == "WALLET_FUEL")
            assert fuel["status"] == "emerald", fuel
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-10 · Domain F — vendor_bill with no paired expense & no orphan legs → rose
def test_uat_10_domain_f_no_pair_no_orphan_is_rose():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            vb_id = f"vb_{uuid.uuid4().hex[:6]}"
            await db.vendor_bills.insert_one({"id": vb_id, "user_id": uid,
                "company_id": cid, "vendor_id": "v1", "bill_number": "VB/1",
                "bill_date": "2026-06-01", "amount": 1500.0})
            rows = await SR.domain_f(uid, cid, "2026-01-01", "2026-12-31")
            hit = next((r for r in rows if r["source_id"] == vb_id), None)
            assert hit and hit["status"] == "rose", hit
            assert "no paired expense" in hit["note"]
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-11 · Reproject compatibility — after fix, mismatch disappears
def test_uat_11_reproject_compatibility_clears_domain_a():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            inv_id = f"inv_{uuid.uuid4().hex[:6]}"
            await db.invoices.insert_one({"id": inv_id, "user_id": uid,
                "company_id": cid, "invoice_number": "INV/RP",
                "invoice_date": "2026-06-01", "customer_id": "cu1",
                "total_amount": 5000.0, "balance_due": 5000.0,
                "advance_deduction_total": 0, "diesel_deduction_total": 0,
                "payments": []})
            r = await SR.domain_a(uid, cid, "2026-01-01", "2026-12-31", 1, 500)
            hits = [x for x in r["rows"] if x.get("source_id") == inv_id]
            assert hits and hits[0]["status"] == "rose"
            # Corrective action must be the existing reproject endpoint
            m = await SR.mismatch(uid, cid, "A", f"invoice:{inv_id}")
            assert m["found"]
            assert m["corrective_action_hint"]["endpoint"] == "POST /api/fin/reproject"
            assert m["corrective_action_hint"]["owner_only"] is True
            # Execute reproject → mismatch clears
            await reproject_source(uid, cid, "invoice", inv_id)
            r2 = await SR.domain_a(uid, cid, "2026-01-01", "2026-12-31", 1, 500)
            hits2 = [x for x in r2["rows"] if x.get("source_id") == inv_id]
            assert not hits2, hits2
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-12 · Pagination bounds
def test_uat_12_pagination_bounds():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            r = await _get("/api/fin/reconciliation/domain/A?size=501")
            assert r.status_code == 422
            r = await _get("/api/fin/reconciliation/domain/A?page=0")
            assert r.status_code == 422
            r = await _get("/api/fin/reconciliation/domain/A?page=1&size=10")
            assert r.status_code == 200
            j = r.json()
            assert j["page"] == 1 and j["size"] == 10
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-13 · KPI ↔ domain-listing consistency (direct SR call — HTTP router
# resolves _active_company_id from DB and cannot see our synthetic cid)
def test_uat_13_kpi_matches_domain_rows():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            # Inject a bad vendor_bill (no pair, no orphan → rose in F)
            vb = f"vb_{uuid.uuid4().hex[:6]}"
            await db.vendor_bills.insert_one({"id": vb, "user_id": uid,
                "company_id": cid, "vendor_id": "v1", "bill_number": "VB/K",
                "bill_date": "2026-06-01", "amount": 100.0})
            js = await SR.summary(uid, cid, "2026-01-01", "2026-12-31")
            jd = await SR.domain(uid, cid, "F", "2026-01-01", "2026-12-31",
                                  page=1, size=500)
            assert js["kpis"]["F"]["status"] == "rose", js["kpis"]["F"]
            assert jd["total"] >= 1, jd
            statuses = {r["status"] for r in jd["rows"]}
            assert "rose" in statuses
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-14 · Domain H — late-entry drift is amber, snapshot is untouched
def test_uat_14_domain_h_late_entry_amber_no_mutation():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            cd_id = f"dc_{uuid.uuid4().hex[:6]}"
            await db.fin_day_closures.insert_one({"id": cd_id, "user_id": uid,
                "company_id": cid, "close_date": "2026-06-30",
                "status": "closed",
                "accounts": [{"account_code": "AR",
                              "closing_balance": 50000.0}]})
            # Insert a fin_txn AR "in" leg dated on/before close_date to
            # simulate a late-entry projection after closure.
            await db.fin_txn.insert_one({"id": f"ft_{uuid.uuid4().hex[:6]}",
                "user_id": uid, "company_id": cid, "source_type": "invoice",
                "source_id": "late1", "account_code": "AR",
                "direction": "in", "amount": 1234.56, "txn_date": "2026-06-25"})
            rows = await SR.domain_h(uid, cid, "2026-01-01", "2026-12-31")
            assert rows and all(r["status"] == "amber" for r in rows)
            assert any(r["note"].startswith("Day Closing snapshots do not auto-refresh")
                       for r in rows)
            # Snapshot MUST NOT have been mutated
            post = await db.fin_day_closures.find_one({"id": cd_id}, {"_id": 0})
            assert post["accounts"][0]["closing_balance"] == 50000.0
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-15 · No-write guarantee — 5 calls, no new collection created
def test_uat_15_no_write_after_bulk_calls():
    async def _t():
        uid, cid = await _mk_ctx()
        try:
            colls_before = set(await db.list_collection_names())
            for _ in range(5):
                await _get("/api/fin/reconciliation/summary?from=2026-01-01&to=2026-12-31")
                for d in "ABCDEFGH":
                    await _get(f"/api/fin/reconciliation/domain/{d}?from=2026-01-01&to=2026-12-31&size=10")
            colls_after = set(await db.list_collection_names())
            new = colls_after - colls_before
            assert "fin_reconciliations" not in new
            # Iter150F must not have created ANY collection
            assert not new, f"Unexpected new collections: {new}"
        finally:
            await _cleanup(uid, cid)
    _run(_t())


# ── UAT-16 · Locked-band 0-diff vs Iter150E lock
def test_uat_16_locked_band_zero_diff_vs_iter150e():
    for rel in PROTECTED_14:
        r = subprocess.run(["git", "diff", "--exit-code", LOCKED_E, "--", rel],
                           cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0, f"{rel} drifted from Iter150E lock"


# ── UAT-17 · Router registration + prefix
def test_uat_17_router_registered_with_api_prefix():
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/api/fin/reconciliation/summary" in paths
    assert any(p.startswith("/api/fin/reconciliation/domain/") for p in paths)
    assert any(p.startswith("/api/fin/reconciliation/mismatch/") for p in paths)
