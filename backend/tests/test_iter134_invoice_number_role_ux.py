"""Iter134 · Invoice-Number Role UX (frontend) regression.

Guards the InvoiceCreate.jsx role-based disabled state for the Invoice
Number input:
  - Owner  → editable
  - Non-owner → disabled / readOnly, helper says "Owner-only override"
Backend authorization (routers/invoices.py) still enforces owner-only
override at both create-time and PATCH-time. Those cases are covered by
sibling tests; here we only lock the UI shape.
"""
from __future__ import annotations
import re

SRC = "/app/frontend/src/pages/InvoiceCreate.jsx"


def _src() -> str:
    with open(SRC, "r", encoding="utf-8") as f:
        return f.read()


def test_uses_canonical_role_source():
    """isOwner must be derived from user.effective_role || user.role — the
    same canonical pattern used by Notes / PartyLedger / Vendors / Mechanics."""
    src = _src()
    assert 'const isOwner' in src
    assert re.search(
        r'user\?\.effective_role\s*\|\|\s*user\?\.role',
        src,
    ), "canonical (effective_role || role) source missing"
    assert '=== "owner"' in src


def test_invoice_number_input_gated_by_isowner():
    """The `disabled=` prop on the invoice-number input must be `!isOwner`
    (not the old expanded expression, not always-false)."""
    src = _src()
    # Old (bad) expression that made everyone see an editable field
    assert 'data-testid="invoice-number-input"' in src
    # The new gated shape must be present
    assert 'disabled={!isOwner}' in src
    assert 'readOnly={!isOwner}' in src


def test_reason_field_owner_only():
    """The override-reason input is only rendered when Owner actually changes
    the suggested number. Non-owners can never see it."""
    src = _src()
    assert re.search(
        r"isOwner\s*&&\s*invoiceNumberEdited\s*&&\s*invoiceNumber\s*!==\s*suggestedNumber",
        src,
    ), "reason field must be gated behind isOwner + edited + differs-from-suggested"


def test_role_hint_copy_present():
    """Helper text must show the role-specific hint."""
    src = _src()
    assert 'Owner can override the invoice number' in src
    assert 'Owner-only override' in src


def test_no_stale_frontend_gating_expression():
    """The previous inline expression must not resurface."""
    src = _src()
    assert 'Non-owner overrides will be rejected on save' not in src
