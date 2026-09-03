"""Iter134 · Owner Editability — FAIL-CLOSED role gating.

Correction of the earlier permissive-default fix.  The updated contract:

  authLoading = true                       → field disabled (fail-closed)
  role resolved AND role === "owner"       → field editable
  role resolved AND role !== "owner"       → field disabled

A non-owner must NEVER see the field even momentarily editable while
`/auth/me` is in flight.  Backend authorization
(`routers/invoices.py`) remains the final security boundary and
continues to return 403 for forged non-owner override attempts —
covered by the reason-binding & role-ux suites.

This suite pins that behaviour in InvoiceCreate.jsx source.
"""
from __future__ import annotations
import os, re

SRC = "/app/frontend/src/pages/InvoiceCreate.jsx"


def _src() -> str:
    with open(SRC, "r", encoding="utf-8") as f:
        return f.read()


def test_authloading_pulled_from_useauth():
    """The component must consume the `loading` flag from the canonical
    AuthContext so the field can fail-closed during auth bootstrap."""
    src = _src()
    assert re.search(r"const\s*\{\s*user,\s*loading:\s*authLoading\s*\}\s*=\s*useAuth\(\)", src), (
        "InvoiceCreate must destructure `loading` from useAuth() as `authLoading`"
    )


def test_isowner_failsclosed_while_loading():
    src = _src()
    # The gate MUST be gated behind !authLoading — during bootstrap
    # everyone (including the eventual Owner) is treated as non-owner.
    assert "isOwner = !authLoading && _rawRole === \"owner\"" in src


def test_isowner_disables_when_role_missing():
    """A resolved-but-role-less user object (e.g. a stale cache from
    before /auth/me returned role) must be treated as non-owner —
    NOT as an Owner (the previous permissive default is retired)."""
    src = _src()
    # There must be no branch that maps empty role to true.
    assert '_rawRole === "" ? true' not in src
    assert '_rawRole === "" ? !0' not in src


def test_input_still_uses_isowner_gate():
    src = _src()
    assert 'disabled={!isOwner}' in src
    assert 'readOnly={!isOwner}' in src


def test_canonical_role_derivation_preserved():
    src = _src()
    assert re.search(r'user\?\.effective_role\s*\?\?\s*user\?\.role', src)
    assert '.toString().trim().toLowerCase()' in src


def test_reason_field_still_owner_gated():
    src = _src()
    assert re.search(
        r'isOwner\s*&&\s*invoiceNumberEdited\s*&&\s*trimmedNum\s*!==\s*\(suggestedNumber',
        src,
    ), "reason input gate must remain (isOwner && edited && trimmedNum !== suggested)"
