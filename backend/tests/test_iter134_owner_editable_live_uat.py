"""Iter134 · Owner Editability LIVE UAT — role-hydration race.

The failure the operator hit ("field is read-only for Owner") had NOTHING
to do with the disabled=/readOnly= gate itself — it was a role-hydration
timing bug:

  1. Owner logs in via Google OAuth.
  2. POST /auth/session returns `{user_id, email, name, picture,
     session_token}` — NO role field.
  3. AuthCallback caches that role-less object in localStorage
     (auth_user).
  4. AuthContext hydrates state SYNCHRONOUSLY from the cache on mount
     (`useState(readCachedUser)`).
  5. /auth/me fires async and eventually returns the role — but the
     first paint of /invoices/new happens BEFORE that.
  6. With a strict `role === "owner"` check, the first paint (and every
     paint until /auth/me lands) treats the Owner as non-owner and
     disables the field.

Fix: PERMISSIVE default. When no role information is present on the
`user` object yet, `isOwner` is true. Only an explicit non-"owner" role
disables the field. Backend authorization stays the final gate.

This suite pins that behaviour in InvoiceCreate.jsx source and covers
the four role shapes it must handle.
"""
from __future__ import annotations
import os, re

SRC = "/app/frontend/src/pages/InvoiceCreate.jsx"


def _src() -> str:
    with open(SRC, "r", encoding="utf-8") as f:
        return f.read()


def test_permissive_default_when_role_unknown():
    """Unknown / missing role → treated as Owner (backend still enforces)."""
    src = _src()
    assert '_rawRole === "" ? true' in src, (
        "isOwner must default to TRUE when role information is missing "
        "on the user object; otherwise real Owners get locked out during "
        "the split-second between /auth/session and /auth/me."
    )


def test_explicit_owner_role_enabled():
    src = _src()
    # Nullish coalescing preserves "" empty string → permissive branch.
    assert re.search(r'user\?\.effective_role\s*\?\?\s*user\?\.role', src)
    assert '_rawRole === "owner"' in src


def test_explicit_non_owner_role_disabled():
    """Any explicitly present, non-'owner' role must resolve to false so
    the field is disabled."""
    src = _src()
    # Trim + lowercase happens BEFORE the comparison so odd casing /
    # whitespace on the wire cannot flip the gate.
    assert '.toString().trim().toLowerCase()' in src


def test_input_still_uses_isowner_gate():
    """The `disabled` / `readOnly` props on the invoice-number input
    remain wired to isOwner. Any pre-existing role UX regression is
    caught here."""
    src = _src()
    assert 'disabled={!isOwner}' in src
    assert 'readOnly={!isOwner}' in src


def test_reason_field_still_owner_gated():
    """Reason input rendering must stay behind `isOwner`, so the wider
    permissive-default doesn't accidentally show the Reason UI to a
    known non-owner."""
    src = _src()
    assert re.search(
        r'isOwner\s*&&\s*invoiceNumberEdited\s*&&\s*trimmedNum\s*!==\s*\(suggestedNumber',
        src,
    ), "reason input gate must remain (isOwner && edited && trimmedNum !== suggested)"
