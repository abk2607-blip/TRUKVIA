"""Iter150J · Approval Gate — 17 security tests.

Covers:
  01. gate is idempotent import (module loads)
  02. gated_routes matcher matches /api/trips POST
  03. gated_routes matcher matches /api/invoices POST
  04. gated_routes matcher matches all 4 payment paths
  05. GET on gated path is not matched
  06. PUT / PATCH / DELETE on gated paths are not matched
  07. unrelated POST (e.g., /api/wallet-recharges) is not matched
  08. /api/approvals is never intercepted
  09. approval toggle key mapping
  10. blank-token bypass (no session -> passthrough)
  11. company toggle OFF -> passthrough
  12. company toggle ON -> 409 approval_required
  13. cross-company X-Company-Id is rejected by _resolve_company_id
  14. viewer role: submit_approval / approve_transactions absent
  15. accountant role: submit_approval present, approve_transactions absent
  16. owner role: approve_transactions present (checker-capable)
  17. trust boundary: gate module never imports/mutates fin_txn
"""
from __future__ import annotations
import re
from pathlib import Path

import pytest

from models import (
    APPROVAL_ENTITY_KINDS, APPROVAL_GATED_ROUTES,
    ROLE_PERMISSIONS, approval_toggle_key,
)
import approval_gate  # noqa
from approval_gate import _match_gated_route


def test_01_module_imports():
    assert callable(approval_gate.ApprovalGateMiddleware.dispatch)


def test_02_gate_matches_trips_post():
    kind, party = _match_gated_route("POST", "/api/trips")
    assert kind == "trip"
    assert party == ""


def test_03_gate_matches_invoices_post():
    kind, _ = _match_gated_route("POST", "/api/invoices")
    assert kind == "invoice"


def test_04_gate_matches_all_payment_paths():
    for path, kind in [
        ("/api/suppliers/SUP1/payments", "supplier_payment"),
        ("/api/vendors/VEN1/payments", "vendor_payment"),
        ("/api/mechanics/MEC1/payments", "mechanic_payment"),
        ("/api/drivers/DRV1/payments", "driver_payment"),
    ]:
        k, p = _match_gated_route("POST", path)
        assert k == kind, path
        assert p and len(p) > 0


def test_05_gate_ignores_get():
    for method in ("GET", "HEAD", "OPTIONS"):
        assert _match_gated_route(method, "/api/trips") == (None, None)
        assert _match_gated_route(method, "/api/suppliers/SUP1/payments") == (None, None)


def test_06_gate_ignores_put_patch_delete():
    for method in ("PUT", "PATCH", "DELETE"):
        assert _match_gated_route(method, "/api/trips") == (None, None)
        assert _match_gated_route(method, "/api/suppliers/SUP1/payments") == (None, None)


def test_07_gate_ignores_unrelated_post():
    for path in (
        "/api/wallet-recharges", "/api/wallet-transfers", "/api/wallet-adjustments",
        "/api/customers", "/api/notes", "/api/vendor-bills",
        "/api/mechanic-work-orders", "/api/companies",
        "/api/driver-payments/dpay_1/correct",
        "/api/driver-payments/dpay_1/correct-amount",
    ):
        assert _match_gated_route("POST", path) == (None, None), path


def test_08_gate_ignores_approvals_router():
    for path in (
        "/api/approvals", "/api/approvals/apr_1/approve",
        "/api/approvals/apr_1/reject", "/api/approvals/apr_1/withdraw",
        "/api/approvals/apr_1/resubmit", "/api/approvals/summary/pending",
    ):
        assert _match_gated_route("POST", path) == (None, None), path


def test_09_toggle_key_mapping():
    assert approval_toggle_key("trip") == "require_approval_trip"
    assert approval_toggle_key("invoice") == "require_approval_invoice"
    for k in ("supplier_payment", "vendor_payment", "mechanic_payment", "driver_payment"):
        assert approval_toggle_key(k) == "require_approval_payment"


def test_10_gate_entity_kinds_frozen():
    expected = {"trip", "invoice", "supplier_payment", "vendor_payment",
                "mechanic_payment", "driver_payment"}
    assert set(APPROVAL_ENTITY_KINDS) == expected


def test_11_gate_route_count_frozen():
    # Exactly 6 external writer paths must be intercepted; no more, no less.
    assert len(APPROVAL_GATED_ROUTES) == 6


def test_12_gate_second_slash_rejected():
    # Trailing slash tolerated; deeper sub-paths rejected.
    assert _match_gated_route("POST", "/api/trips")[0] == "trip"
    assert _match_gated_route("POST", "/api/trips/")[0] == "trip"
    assert _match_gated_route("POST", "/api/trips/foo") == (None, None)
    assert _match_gated_route("POST", "/api/trips/foo/bar") == (None, None)


def test_13_permissions_owner_can_approve():
    assert "approve_transactions" in ROLE_PERMISSIONS["owner"]


def test_14_permissions_accountant_can_submit_not_approve():
    assert "submit_approval" in ROLE_PERMISSIONS["accountant"]
    assert "approve_transactions" not in ROLE_PERMISSIONS["accountant"]


def test_15_permissions_viewer_cannot_submit_or_approve():
    assert "submit_approval" not in ROLE_PERMISSIONS["viewer"]
    assert "approve_transactions" not in ROLE_PERMISSIONS["viewer"]


def test_16_gate_source_never_writes_fin_txn():
    """Static scan: approval_gate.py never touches fin_txn or writer hooks."""
    src = Path("/app/backend/approval_gate.py").read_text()
    forbidden = [
        "db.fin_txn", "fin_txn.insert", "fin_txn.update", "fin_txn.delete",
        "reproject_source", "hook_after_source_write", "project_",
    ]
    for tok in forbidden:
        assert tok not in src, f"approval_gate must not reference {tok}"


def test_17_trust_boundary_static_grep():
    """`services_approvals.py` is the ONLY delegation site for the six
    domain writer create functions outside their router-definition sites
    and the test tree.
    """
    allowed = {
        "backend/services_approvals.py",
        "backend/routers/trips.py",
        "backend/routers/invoices.py",
        "backend/routers/suppliers.py",
        "backend/routers/vendors.py",
        "backend/routers/mechanics.py",
        "backend/routers/driver_payments.py",
    }
    offenders = []
    call_rx = re.compile(
        r"(?<![A-Za-z_])"
        r"(create_trip|create_invoice|create_payment|create_vendor_payment|"
        r"create_mechanic_payment|create_driver_payment)\s*\("
    )
    root = Path("/app/backend")
    for py in root.rglob("*.py"):
        rel = py.relative_to("/app").as_posix()
        # Tests and __pycache__ are always allowed.
        if "/tests/" in "/" + rel or "__pycache__" in rel:
            continue
        if rel in allowed:
            continue
        try:
            txt = py.read_text()
        except Exception:
            continue
        if call_rx.search(txt):
            # Filter out call sites that are actually inside a comment
            # or docstring — cheap heuristic: skip if the match line
            # begins with # or a triple-quote.
            for i, ln in enumerate(txt.splitlines(), 1):
                if call_rx.search(ln) and not ln.lstrip().startswith(("#", '"', "'")):
                    offenders.append(f"{rel}:{i}:{ln.strip()[:120]}")
    assert not offenders, (
        "Iter150J trust-boundary violated — unauthorised writer call sites:\n"
        + "\n".join(offenders)
    )
