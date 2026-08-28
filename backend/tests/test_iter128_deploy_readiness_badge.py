"""Iter128 · Deploy Readiness Badge — role gate + response shape.

Locks the Iter128 behaviour approved by the user for the top-nav badge:

  * GET  /api/admin/deploy-readiness   — Owner / Admin / Manager only (403 otherwise).
  * GET  /api/admin/deploy-history     — Owner / Admin / Manager only (403 otherwise).
  * POST /api/admin/deploy-readiness/run-now — untouched (kept out of MVP badge scope).
  * Response shape used by the badge remains: status, checked_at, elapsed_s, exit_code.

The tests mint fresh session tokens against a live backend (same pattern as
the rest of the /app/backend/tests suite). We insert temp users +
team_members rows via pymongo so a manager/accountant/viewer session is
produced deterministically, then clean up.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pymongo

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_TOKEN = "test_session_bitumen_2026"
DEMO_HDR = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
_mc = pymongo.MongoClient(MONGO_URL)
_db = _mc[DB_NAME]


# ── Session minting helpers ────────────────────────────────────────────────
def _mint_role_session(role: str) -> tuple[str, str, str]:
    """Create a fresh user + team_members row + user_sessions row so a call
    with the returned Bearer token gets `effective_role == role`.

    Returns (session_token, user_id, email) for cleanup.
    """
    # 1. Owner user this staff will belong to (unique per test run).
    owner_uid = f"user_iter128_owner_{uuid.uuid4().hex[:8]}"
    owner_email = f"iter128-owner-{uuid.uuid4().hex[:6]}@example.local"
    _db.users.insert_one({
        "user_id": owner_uid,
        "email": owner_email,
        "name": "Iter128 Owner",
        "created_at": datetime.now(timezone.utc),
        "role": "owner",
    })

    # 2. Staff user that will authenticate.
    staff_uid = f"user_iter128_{role}_{uuid.uuid4().hex[:8]}"
    staff_email = f"iter128-{role}-{uuid.uuid4().hex[:6]}@example.local"
    _db.users.insert_one({
        "user_id": staff_uid,
        "email": staff_email,
        "name": f"Iter128 {role.title()}",
        "created_at": datetime.now(timezone.utc),
    })
    _db.team_members.insert_one({
        "owner_user_id": owner_uid,
        "email": staff_email,
        "name": f"Iter128 {role.title()}",
        "role": role,
        "active": True,
        "created_at": datetime.now(timezone.utc),
    })

    # 3. Session token bound to the staff user.
    token = f"iter128_sess_{uuid.uuid4().hex}"
    _db.user_sessions.insert_one({
        "session_token": token,
        "user_id": staff_uid,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "created_at": datetime.now(timezone.utc),
        "last_refreshed_at": datetime.now(timezone.utc),
    })
    return token, staff_uid, staff_email


def _cleanup(uid: str, email: str, token: str) -> None:
    try: _db.user_sessions.delete_one({"session_token": token})
    except Exception: pass
    try: _db.team_members.delete_many({"email": email})
    except Exception: pass
    try: _db.users.delete_one({"user_id": uid})
    except Exception: pass


# ── Tests ─────────────────────────────────────────────────────────────────

def test_deploy_readiness_returns_current_shape_for_owner():
    """Baseline: demo token (effective owner) hits /deploy-readiness and gets
    the four badge-consumed fields with expected types."""
    r = httpx.get(f"{API}/admin/deploy-readiness", headers=DEMO_HDR, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") in ("pass", "fail", "unknown"), body
    # `checked_at` may be None when unknown; other fields are optional pre-first-run.
    if body["status"] != "unknown":
        assert "checked_at" in body


def test_deploy_readiness_allows_manager():
    token, uid, email = _mint_role_session("manager")
    try:
        r = httpx.get(
            f"{API}/admin/deploy-readiness",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("status") in ("pass", "fail", "unknown")
    finally:
        _cleanup(uid, email, token)


def test_deploy_readiness_rejects_accountant():
    token, uid, email = _mint_role_session("accountant")
    try:
        r = httpx.get(
            f"{API}/admin/deploy-readiness",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == "Owner, Admin, or Manager role required."
    finally:
        _cleanup(uid, email, token)


def test_deploy_readiness_rejects_viewer():
    token, uid, email = _mint_role_session("viewer")
    try:
        r = httpx.get(
            f"{API}/admin/deploy-readiness",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(uid, email, token)


def test_deploy_readiness_rejects_unauthed():
    r = httpx.get(f"{API}/admin/deploy-readiness", timeout=10)
    assert r.status_code == 401, r.text


def test_deploy_history_role_gate_parity_manager():
    token, uid, email = _mint_role_session("manager")
    try:
        r = httpx.get(
            f"{API}/admin/deploy-history",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("count", "passes", "fails", "pass_rate", "history"):
            assert k in body
    finally:
        _cleanup(uid, email, token)


def test_deploy_history_rejects_accountant():
    token, uid, email = _mint_role_session("accountant")
    try:
        r = httpx.get(
            f"{API}/admin/deploy-history",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(uid, email, token)


def test_run_now_endpoint_untouched():
    """MVP explicitly leaves POST run-now alone — sanity-check it still 200s
    for the owner-scoped demo token so we haven't regressed by accident."""
    r = httpx.post(
        f"{API}/admin/deploy-readiness/run-now",
        headers=DEMO_HDR,
        timeout=15,
    )
    assert r.status_code in (200, 202), r.text
    body = r.json()
    assert body.get("triggered") is True
