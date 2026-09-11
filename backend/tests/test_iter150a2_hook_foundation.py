"""Iter150A-2 · Phase 1 tests — hook foundation + failure queue.

Sequential (`pytest -n0`). Uses the running backend for reproject side-
effects (HTTP path) and pymongo for direct assertions.

Coverage per approved test plan:
  A. Successful hook invokes reproject_source once → success returned.
  B. Hook failure → source untouched; failure row created.
  C. Retry: failed row replayed successfully → status=resolved.
  D. Repeated failure: retry_count increments; row retained.
  E. Tenant isolation: replay scoped to (uid, cid) never touches other.
  F. Idempotency: repeated replay never creates duplicate FinTxn.
  G. Dry-run CLI: zero writes.
  H. CLI company filter: only requested company processed.
  I. A-1 projection untouched (import-only dependency, not modified).

The tests DO NOT wire hooks into production write paths (that is
Phase 2+). They exercise `hook_after_source_write` and
`replay_pending_failures` directly.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BACKEND_DIR = Path("/app/backend")
sys.path.insert(0, str(BACKEND_DIR))

# Import the module under test directly.
import services_fin_txn_hooks as hooks           # noqa: E402
import services_fin_txn                          # noqa: E402


# ── Shared event loop for the whole module ─────────────────────────────
# Motor's async client binds its connection pool to the FIRST asyncio
# loop it observes. Using a fresh loop per test causes "loop is closed"
# errors on subsequent motor operations. We reuse ONE loop for every
# `_run` call across the module — this matches the pattern locked-band
# suites use when direct-invoking Motor helpers.
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    """Run coroutine on the shared module-level event loop."""
    return _LOOP.run_until_complete(coro)


# ── Fixture ──────────────────────────────────────────────────────────────

class _Ctx:
    """Synthetic tenants + minimal fixture docs. Zero touches to demo
    or live tenants beyond invoice/customer/vehicle synthetic rows we
    fully clean at teardown."""
    def __init__(self):
        self.d = _db()
        self.tag = uuid.uuid4().hex[:10]
        self.uid = f"user_a2h_{self.tag}"
        self.cid = f"co_a2h_{self.tag}"
        self.other_uid = f"user_a2h_iso_{self.tag}"
        self.other_cid = f"co_a2h_iso_{self.tag}"
        # Seed A-1 system accounts for both tenants so reproject_source
        # can succeed. The Iter150A-1 helper `ensure_system_accounts`
        # is idempotent and safe on synthetic tenants.
        _run(services_fin_txn.ensure_system_accounts(self.uid, self.cid))
        _run(services_fin_txn.ensure_system_accounts(self.other_uid, self.other_cid))
        _run(hooks.ensure_hook_indexes())
        self._trip_ids = []

    def make_invoice(self, total: float = 1000.0, tenant: str = "main",
                     date: str = "2026-02-15") -> str:
        iid = f"inv_a2h_{uuid.uuid4().hex[:8]}"
        uid, cid = ((self.uid, self.cid) if tenant == "main"
                    else (self.other_uid, self.other_cid))
        self.d.invoices.insert_one({
            "id": iid, "user_id": uid, "company_id": cid,
            "invoice_number": f"A2H/{iid[-6:]}", "customer_id": f"cust_{self.tag}",
            "invoice_date": date, "trip_ids": [],
            "subtotal": total, "total_amount": total,
            "advance_deduction_total": 0.0, "diesel_deduction_total": 0.0,
            "balance_due": total, "payments": [], "is_historical": False,
        })
        return iid

    def teardown(self):
        for uid in (self.uid, self.other_uid):
            self.d.invoices.delete_many({"user_id": uid})
            self.d.fin_txn.delete_many({"user_id": uid})
            self.d.fin_accounts.delete_many({"user_id": uid})
            self.d.fin_hook_failures.delete_many({"user_id": uid})
            self.d.trips.delete_many({"user_id": uid})


@pytest.fixture
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


# ── A · Successful hook ─────────────────────────────────────────────────

def test_A_successful_hook_projects_source_once(ctx):
    iid = ctx.make_invoice(total=2500.0)
    res = _run(hooks.hook_after_source_write(
        ctx.uid, ctx.cid, "invoice", iid))
    assert res["ok"] is True
    assert res["source_type"] == "invoice"
    assert res["source_id"] == iid
    assert res["written"] == 2
    assert res["deleted"] == 0
    assert res["failure_id"] is None
    # No failure row created.
    assert ctx.d.fin_hook_failures.count_documents(
        {"user_id": ctx.uid, "source_id": iid}) == 0
    # FinTxn legs actually landed.
    n = ctx.d.fin_txn.count_documents(
        {"user_id": ctx.uid, "source_type": "invoice", "source_id": iid})
    assert n == 2


def test_A_hook_returns_compact_shape(ctx):
    iid = ctx.make_invoice(total=500.0)
    res = _run(hooks.hook_after_source_write(
        ctx.uid, ctx.cid, "invoice", iid))
    for key in ("ok", "source_type", "source_id", "deleted",
                 "written", "error", "failure_id", "resolved_failure_id"):
        assert key in res, f"missing key: {key}"


# ── B · Hook failure captures without touching source ───────────────────

def test_B_hook_failure_captures_row_without_touching_source(ctx, monkeypatch):
    """Force reproject_source to raise; assert source doc unchanged +
    failure row created with correct tenant/source binding."""
    iid = ctx.make_invoice(total=800.0)
    src_before = ctx.d.invoices.find_one({"id": iid}, {"_id": 0})
    assert src_before is not None

    async def _boom(*a, **kw):
        raise RuntimeError("simulated projection failure")
    monkeypatch.setattr(hooks, "reproject_source", _boom)

    res = _run(hooks.hook_after_source_write(
        ctx.uid, ctx.cid, "invoice", iid))
    assert res["ok"] is False
    assert res["error"].startswith("RuntimeError")
    assert res["failure_id"], "failure_id must be populated"

    # Source doc untouched.
    src_after = ctx.d.invoices.find_one({"id": iid}, {"_id": 0})
    assert src_after == src_before

    # Failure row created with correct scope.
    frow = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "company_id": ctx.cid,
         "source_type": "invoice", "source_id": iid}, {"_id": 0})
    assert frow is not None
    assert frow["status"] == hooks.FAILURE_STATUS_PENDING
    assert frow["retry_count"] == 0
    assert "simulated projection failure" in frow["error"]


def test_B_unsupported_source_type_no_retry_recorded(ctx):
    """Programming errors (unknown source_type) must NOT enqueue a
    retry — they cannot succeed on replay."""
    res = _run(hooks.hook_after_source_write(
        ctx.uid, ctx.cid, "not_a_type", "x123"))
    assert res["ok"] is False
    assert "unsupported source_type" in res["error"]
    assert res["failure_id"] is None
    assert ctx.d.fin_hook_failures.count_documents(
        {"user_id": ctx.uid, "source_id": "x123"}) == 0


# ── C · Retry after failure ─────────────────────────────────────────────

def test_C_replay_resolves_failed_row_and_projects_source(ctx, monkeypatch):
    """First hook call fails → failure row. Reproject_source restored →
    replay picks it up → row status=resolved, FinTxn legs present."""
    iid = ctx.make_invoice(total=1200.0)

    async def _boom(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", iid))
    assert ctx.d.fin_hook_failures.count_documents(
        {"user_id": ctx.uid, "source_id": iid,
         "status": hooks.FAILURE_STATUS_PENDING}) == 1

    # Restore real reproject_source, then replay.
    monkeypatch.setattr(hooks, "reproject_source",
                         services_fin_txn.reproject_source)
    report = _run(hooks.replay_pending_failures(
        user_id=ctx.uid, company_id=ctx.cid,
        ignore_schedule=True, verbose=True))
    assert report["attempted"] == 1
    assert report["succeeded"] == 1
    assert report["failed"] == 0
    assert report["permanently_failed"] == 0

    # Row now resolved and retained.
    frow = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid}, {"_id": 0})
    assert frow["status"] == hooks.FAILURE_STATUS_RESOLVED
    assert frow["resolved_at"]

    # FinTxn legs present.
    n = ctx.d.fin_txn.count_documents(
        {"user_id": ctx.uid, "source_id": iid})
    assert n == 2


def test_C_success_hook_auto_resolves_prior_failure(ctx, monkeypatch):
    """If the same source successfully projects later (e.g., via a
    subsequent source edit that triggers a fresh hook), the pending
    failure row must be auto-resolved."""
    iid = ctx.make_invoice(total=333.0)
    async def _boom(*a, **kw):
        raise RuntimeError("boom-a")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", iid))
    assert ctx.d.fin_hook_failures.count_documents(
        {"user_id": ctx.uid, "source_id": iid,
         "status": hooks.FAILURE_STATUS_PENDING}) == 1

    # Restore and re-hook.
    monkeypatch.setattr(hooks, "reproject_source",
                         services_fin_txn.reproject_source)
    res = _run(hooks.hook_after_source_write(
        ctx.uid, ctx.cid, "invoice", iid))
    assert res["ok"] is True
    assert res["resolved_failure_id"], "should have auto-resolved prior failure"
    frow = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid}, {"_id": 0})
    assert frow["status"] == hooks.FAILURE_STATUS_RESOLVED


# ── D · Repeated failure ────────────────────────────────────────────────

def test_D_repeated_failure_increments_retry_count_and_retains_row(ctx, monkeypatch):
    """Retry that fails again must bump retry_count, remain retryable,
    and never silently delete the record."""
    iid = ctx.make_invoice(total=99.0)
    async def _boom(*a, **kw):
        raise RuntimeError("persistent")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", iid))

    # First replay attempt — should still fail.
    r1 = _run(hooks.replay_pending_failures(
        user_id=ctx.uid, company_id=ctx.cid, ignore_schedule=True))
    assert r1["failed"] == 1
    row1 = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid}, {"_id": 0})
    assert row1["retry_count"] == 1
    assert row1["status"] == hooks.FAILURE_STATUS_RETRYING
    assert len(row1["history"]) == 1

    # Second replay — retry_count=2, still retained.
    r2 = _run(hooks.replay_pending_failures(
        user_id=ctx.uid, company_id=ctx.cid, ignore_schedule=True))
    assert r2["failed"] == 1
    row2 = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid}, {"_id": 0})
    assert row2["retry_count"] == 2
    assert len(row2["history"]) == 2


def test_D_exhausted_retries_mark_permanently_failed_and_retain(ctx, monkeypatch):
    """After MAX_RETRIES attempts, status → permanently_failed. Row
    remains in the DB for human investigation."""
    iid = ctx.make_invoice(total=1.0)
    async def _boom(*a, **kw):
        raise RuntimeError("permanent-fail")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", iid))

    # Fast-forward: drive retry_count up to MAX_RETRIES-1 via replay,
    # then one more attempt should tip into permanently_failed.
    for _ in range(hooks.MAX_RETRIES):
        _run(hooks.replay_pending_failures(
            user_id=ctx.uid, company_id=ctx.cid, ignore_schedule=True))
    row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid}, {"_id": 0})
    assert row["status"] == hooks.FAILURE_STATUS_PERMANENTLY_FAILED
    assert row["retry_count"] >= hooks.MAX_RETRIES

    # A subsequent replay must skip this row (terminal status).
    report = _run(hooks.replay_pending_failures(
        user_id=ctx.uid, company_id=ctx.cid, ignore_schedule=True))
    assert report["attempted"] == 0
    # And the row is still present — never silently deleted.
    assert ctx.d.fin_hook_failures.count_documents(
        {"user_id": ctx.uid, "source_id": iid}) == 1


# ── E · Tenant isolation ────────────────────────────────────────────────

def test_E_replay_scope_never_crosses_tenant(ctx, monkeypatch):
    """Two synthetic tenants each have a pending failure. Replaying
    tenant A must NOT touch tenant B's row."""
    iid_a = ctx.make_invoice(total=100.0, tenant="main")
    iid_b = ctx.make_invoice(total=200.0, tenant="other")
    async def _boom(*a, **kw): raise RuntimeError("x")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", iid_a))
    _run(hooks.hook_after_source_write(
        ctx.other_uid, ctx.other_cid, "invoice", iid_b))
    # Restore + replay ONLY tenant A.
    monkeypatch.setattr(hooks, "reproject_source",
                         services_fin_txn.reproject_source)
    report = _run(hooks.replay_pending_failures(
        user_id=ctx.uid, company_id=ctx.cid, ignore_schedule=True))
    assert report["attempted"] == 1
    assert report["succeeded"] == 1
    # Tenant B's row untouched.
    b_row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.other_uid, "source_id": iid_b}, {"_id": 0})
    assert b_row["status"] == hooks.FAILURE_STATUS_PENDING
    assert b_row["retry_count"] == 0


# ── F · Idempotency of replay ───────────────────────────────────────────

def test_F_repeated_replay_never_creates_duplicate_fintxn(ctx, monkeypatch):
    """Replay the same successful path multiple times; FinTxn row count
    must stay at 2 (per A-1 UNIQUE ref_source_key)."""
    iid = ctx.make_invoice(total=750.0)
    async def _boom(*a, **kw): raise RuntimeError("x")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", iid))
    monkeypatch.setattr(hooks, "reproject_source",
                         services_fin_txn.reproject_source)

    # Successful replay.
    _run(hooks.replay_pending_failures(
        user_id=ctx.uid, company_id=ctx.cid, ignore_schedule=True))
    assert ctx.d.fin_txn.count_documents(
        {"user_id": ctx.uid, "source_id": iid}) == 2

    # The row is now resolved; further replays are no-ops. Force it
    # back to pending, replay again, verify no duplicates.
    ctx.d.fin_hook_failures.update_one(
        {"user_id": ctx.uid, "source_id": iid},
        {"$set": {"status": hooks.FAILURE_STATUS_PENDING,
                  "retry_count": 0,
                  "next_attempt_at": "1970-01-01T00:00:00+00:00"}},
    )
    _run(hooks.replay_pending_failures(
        user_id=ctx.uid, company_id=ctx.cid, ignore_schedule=True))
    assert ctx.d.fin_txn.count_documents(
        {"user_id": ctx.uid, "source_id": iid}) == 2


# ── G · Dry-run CLI writes nothing ──────────────────────────────────────

def test_G_dry_run_writes_nothing(ctx, monkeypatch):
    iid = ctx.make_invoice(total=42.0)
    async def _boom(*a, **kw): raise RuntimeError("x")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", iid))

    monkeypatch.setattr(hooks, "reproject_source",
                         services_fin_txn.reproject_source)
    row_before = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid}, {"_id": 0})
    fin_before = ctx.d.fin_txn.count_documents(
        {"user_id": ctx.uid, "source_id": iid})

    report = _run(hooks.replay_pending_failures(
        user_id=ctx.uid, company_id=ctx.cid,
        dry_run=True, ignore_schedule=True))
    assert report["dry_run"] is True
    assert report["attempted"] == 1
    assert report["succeeded"] == 0

    row_after = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid}, {"_id": 0})
    fin_after = ctx.d.fin_txn.count_documents(
        {"user_id": ctx.uid, "source_id": iid})
    # No changes — status, retry_count, FinTxn row count all identical.
    assert row_after["status"] == row_before["status"]
    assert row_after["retry_count"] == row_before["retry_count"]
    assert fin_after == fin_before


def test_G_cli_dry_run_writes_nothing(ctx, monkeypatch):
    """Exercise the CLI subprocess with --dry-run --company-id."""
    iid = ctx.make_invoice(total=17.0)
    async def _boom(*a, **kw): raise RuntimeError("x")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", iid))

    before_status = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid})["status"]

    result = subprocess.run(
        [sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--dry-run", "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"dry_run": true' in result.stdout
    assert '"attempted": 1' in result.stdout
    # Nothing changed in DB.
    after_status = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid})["status"]
    assert after_status == before_status


# ── H · CLI company filter ──────────────────────────────────────────────

def test_H_replay_company_filter_scopes_sweep(ctx, monkeypatch):
    iid_a = ctx.make_invoice(total=10.0, tenant="main")
    iid_b = ctx.make_invoice(total=20.0, tenant="other")
    async def _boom(*a, **kw): raise RuntimeError("x")
    monkeypatch.setattr(hooks, "reproject_source", _boom)
    _run(hooks.hook_after_source_write(ctx.uid, ctx.cid, "invoice", iid_a))
    _run(hooks.hook_after_source_write(
        ctx.other_uid, ctx.other_cid, "invoice", iid_b))

    monkeypatch.setattr(hooks, "reproject_source",
                         services_fin_txn.reproject_source)
    # Replay only tenant B via company_id filter.
    report = _run(hooks.replay_pending_failures(
        user_id=ctx.other_uid, company_id=ctx.other_cid,
        ignore_schedule=True))
    assert report["attempted"] == 1
    assert report["succeeded"] == 1
    # Tenant A's row untouched.
    a_row = ctx.d.fin_hook_failures.find_one(
        {"user_id": ctx.uid, "source_id": iid_a})
    assert a_row["status"] == hooks.FAILURE_STATUS_PENDING


# ── I · A-1 projection module unchanged ─────────────────────────────────

def test_I_A1_projection_module_is_dependency_only():
    """Guard rail: `services_fin_txn.py` must be imported as-is; the
    hooks module must not monkey-patch or shadow its public helpers.

    We can't detect a future modification here, but we CAN confirm the
    hook module doesn't override any A-1 public symbol at import time.
    """
    a1_public = {
        "reproject_source", "backfill_tenant", "ensure_indexes",
        "ensure_system_accounts", "project_invoice",
        "project_credit_debit_note", "project_supplier_payment",
        "project_vendor_payment", "project_mechanic_payment",
        "project_expense", "project_vendor_bill",
        "project_mechanic_work_order", "project_trip_customer_receipts",
        "SUPPORTED_SOURCE_TYPES", "FIN_SYSTEM_ACCOUNTS",
    }
    for name in a1_public:
        # Must resolve to the A-1 module's symbol, not a shadowed one.
        v_a1 = getattr(services_fin_txn, name, None)
        assert v_a1 is not None, f"A-1 public symbol {name!r} missing"
        # The hooks module may import it, but must not export a
        # different object under the same name.
        if hasattr(hooks, name):
            assert getattr(hooks, name) is v_a1, \
                f"hooks module has shadowed A-1 symbol {name!r}"

    # File-hash sanity: the A-1 file exists and is readable. This is a
    # cheap tripwire — if a future phase modifies A-1, this test
    # doesn't fail (we don't want to lock the file hash), but the
    # symbol-shadow check above catches accidental overrides.
    a1_path = Path("/app/backend/services_fin_txn.py")
    assert a1_path.exists() and a1_path.stat().st_size > 0
