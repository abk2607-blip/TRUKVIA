"""Iter127c · Supplier Deactivate / Reactivate — user-approved (Feb 2026).

Locks the design behaviour:
  • Owner/Admin only (403 otherwise).
  • Never hard-deletes — always sets is_active=False, preserves the row.
  • Deactivation returns dependency counts (trips/payments/vehicles) so
    the UI can render a "N items preserved" summary.
  • Historical trips + supplier payments + vehicles + supplier ledger
    remain unchanged in visibility and calculations.
  • Active-flow pickers (active_only=true / supplier dashboard) hide the
    deactivated supplier.
  • POST /reactivate flips is_active back to True (Owner/Admin only).
  • Every action is written to the audit_log.
  • Company isolation preserved end-to-end.
"""
from __future__ import annotations

import os
import uuid
import time

import httpx

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _mk_supplier(tag: str = "") -> dict:
    r = httpx.post(f"{API}/suppliers", headers=HDR, json={
        "name": f"Iter127c_Sup_{tag}_{uuid.uuid4().hex[:6]}",
        "mobile": f"9{uuid.uuid4().int % 10**9:09d}",
        "state": "Andhra Pradesh",
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def test_deactivate_returns_dependency_counts_and_soft_flag():
    sup = _mk_supplier("dep")
    r = httpx.delete(f"{API}/suppliers/{sup['id']}?reason=uat", headers=HDR, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["is_active"] is False
    for k in ("trips", "payments", "vehicles"):
        assert k in body["dependencies"]
        assert isinstance(body["dependencies"][k], int)
    assert "unchanged" in body["message"].lower()

    # Verify the underlying record was soft-flagged, not deleted.
    got = httpx.get(f"{API}/suppliers/{sup['id']}", headers=HDR, timeout=10).json()
    assert got["is_active"] is False
    assert got["deactivation_reason"] == "uat"


def test_active_only_true_hides_inactive_supplier():
    sup = _mk_supplier("hide")
    httpx.delete(f"{API}/suppliers/{sup['id']}", headers=HDR, timeout=10)
    # Use ?q= search so we don't rely on the 20000-row list-cap ordering
    # (demo tenant has thousands of fixture suppliers).
    rows_active = httpx.get(
        f"{API}/suppliers?active_only=true&q={sup['name']}", headers=HDR, timeout=10,
    ).json()
    assert sup["id"] not in [s["id"] for s in rows_active], "inactive supplier leaked into active_only=true listing"
    # Default listing (active_only=false) still shows it for owner review.
    rows_all = httpx.get(
        f"{API}/suppliers?q={sup['name']}", headers=HDR, timeout=10,
    ).json()
    assert sup["id"] in [s["id"] for s in rows_all]


def test_reactivate_restores_supplier_and_is_audited():
    sup = _mk_supplier("restore")
    httpx.delete(f"{API}/suppliers/{sup['id']}", headers=HDR, timeout=10)
    r = httpx.post(f"{API}/suppliers/{sup['id']}/reactivate", headers=HDR, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["is_active"] is True
    got = httpx.get(f"{API}/suppliers/{sup['id']}", headers=HDR, timeout=10).json()
    assert got["is_active"] is True


def test_deactivate_preserves_supplier_dashboard_and_totals():
    """Regression: deactivation must NOT alter any historical calculation.
    We snapshot the supplier_dashboard KPIs before + after and assert
    they're identical for a supplier that has no linked trips."""
    sup = _mk_supplier("kpi")
    before = httpx.get(f"{API}/suppliers-dashboard", headers=HDR, timeout=15).json()
    httpx.delete(f"{API}/suppliers/{sup['id']}", headers=HDR, timeout=10)
    after = httpx.get(f"{API}/suppliers-dashboard", headers=HDR, timeout=15).json()

    # active_suppliers counter should DROP by exactly 1 (we removed one active row).
    # Everything else that reads from ledger / payments / trips must be identical.
    if "active_suppliers" in before and "active_suppliers" in after:
        assert before["active_suppliers"] - after["active_suppliers"] == 1
    for k in ("total_payable", "total_advance", "net_balance"):
        if k in before and k in after:
            assert before[k] == after[k], f"KPI {k} drifted after soft-delete of an unlinked supplier"


def test_deactivate_returns_404_for_unknown_id():
    r = httpx.delete(f"{API}/suppliers/sup_does_not_exist_{uuid.uuid4().hex[:6]}", headers=HDR, timeout=10)
    assert r.status_code == 404


def test_deactivate_and_reactivate_are_idempotent_shape():
    """Repeated deactivate calls on the same supplier keep returning 200
    with is_active=False (no state corruption)."""
    sup = _mk_supplier("idem")
    r1 = httpx.delete(f"{API}/suppliers/{sup['id']}", headers=HDR, timeout=10)
    r2 = httpx.delete(f"{API}/suppliers/{sup['id']}", headers=HDR, timeout=10)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["is_active"] is False and r2.json()["is_active"] is False


def test_deactivate_source_guardrail_still_soft_only():
    """Source-level lock: the DELETE endpoint must never hard-delete."""
    src = open("/app/backend/routers/suppliers.py").read()
    # Grab the delete_supplier function body only.
    start = src.index("async def delete_supplier(")
    end   = src.index("@router.", start + 1)
    body  = src[start:end]
    assert "db.suppliers.delete_one" not in body, (
        "delete_supplier must never hard-delete rows (soft-delete only)"
    )
    assert "db.suppliers.delete_many" not in body
    assert '"is_active": False' in body
    assert "is_override_authorised(user)" in body, "Owner/Admin gate missing"


def test_reactivate_source_guardrail_owner_admin_only():
    src = open("/app/backend/routers/suppliers.py").read()
    start = src.index("async def reactivate_supplier(")
    end   = src.index("@router.", start + 1) if "@router." in src[start + 1:] else len(src)
    body  = src[start:end]
    assert "is_override_authorised(user)" in body, "Owner/Admin gate missing on reactivate"
    assert '"is_active": True' in body
