"""Auth + RBAC helpers.

Iter106 · Support-recommended stability fixes:
  1. Rolling refresh is aggressive & unconditional — every request touches
     `expires_at`, so an active session never lapses mid-form.
  2. Session lifetime extended from 7 → 30 days.
  3. `expires_at` is stored as a real BSON Date (not ISO string) so the
     MongoDB TTL index actually fires and prunes stale rows.
  4. The demo session token (env-backed, Iter130) is gated behind
     `IS_PREVIEW_ENV=1` + `ENABLE_DEMO_TOKEN=1` + non-empty
     `DEMO_TOKEN_VALUE` in `backend/.env`. In production these flags are
     absent, so the token is refused with 401. Pytest + local dev keep the
     flags ON so the regression suite keeps working. See `/app/backend/.env`.
  5. Owner account is seeded as `abk2607@gmail.com` (the real signed-in user).
"""
from datetime import datetime, timezone, timedelta
from fastapi import Request, HTTPException, Depends
import os as _os

from db import db
from models import ROLE_PERMISSIONS, now_utc


# ── Constants ─────────────────────────────────────────────────────────────
# Iter130 · Demo-token production guard
#   - Fail-secure: demo access is disabled unless IS_PREVIEW_ENV=1 is set
#     in the environment. Real production deploys omit this flag, so the
#     demo token is rejected even if ENABLE_DEMO_TOKEN=1 is accidentally
#     inherited.
#   - The token value itself is read from DEMO_TOKEN_VALUE at import time.
#     No literal is stored in source. If the env var is missing/empty, the
#     module-level constant is the empty string, which never matches an
#     incoming Bearer header (an empty Bearer is rejected upstream).
_IS_PREVIEW = _os.environ.get("IS_PREVIEW_ENV") == "1"
DEMO_TOKEN = _os.environ.get("DEMO_TOKEN_VALUE", "") if _IS_PREVIEW else ""
_DEMO_LEGACY_DISABLED = _os.environ.get("DEMO_TOKEN_DISABLED") == "1"
_DEMO_ENABLED = (
    _IS_PREVIEW
    and _os.environ.get("ENABLE_DEMO_TOKEN") == "1"
    and not _DEMO_LEGACY_DISABLED
    and DEMO_TOKEN != ""
)

SESSION_LIFETIME_DAYS = 30                # was 7 — extended per support recommendation
ROLLING_REFRESH_MIN_INTERVAL_SEC = 30     # write at most every 30s of activity
OWNER_EMAIL = "abk2607@gmail.com"


async def _ensure_demo_session():
    """Idempotently create a demo user + rolling 30-day session for DEMO_TOKEN.
    Only invoked when ENABLE_DEMO_TOKEN=1 is set on the backend."""
    user = await db.users.find_one({"session_token_demo": True}, {"_id": 0})
    if not user:
        user_id = f"user_demo_{DEMO_TOKEN[-8:]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": "demo@bitumen-transport.local",
            "name": "Demo User",
            "picture": "",
            "session_token_demo": True,
            "created_at": now_utc(),
        })
    else:
        user_id = user["user_id"]
    # BSON Date (not ISO string) so the TTL index can prune expired sessions.
    exp = now_utc() + timedelta(days=SESSION_LIFETIME_DAYS)
    await db.user_sessions.update_one(
        {"session_token": DEMO_TOKEN},
        {"$set": {
            "user_id": user_id,
            "session_token": DEMO_TOKEN,
            "expires_at": exp,
            "created_at": now_utc(),
            "last_refreshed_at": now_utc(),
        }},
        upsert=True,
    )
    return user_id


async def _ensure_owner_user():
    """Ensure the real signed-in owner account (abk2607@gmail.com) exists.
    Idempotent — safe to call from server startup and lazily from get_current_user."""
    existing = await db.users.find_one({"email": OWNER_EMAIL}, {"_id": 0})
    if existing:
        return existing["user_id"]
    import uuid
    user_id = f"user_owner_{uuid.uuid4().hex[:10]}"
    await db.users.insert_one({
        "user_id": user_id,
        "email": OWNER_EMAIL,
        "name": "A Kishore Babu",
        "picture": "",
        "created_at": now_utc(),
        "role": "owner",
    })
    return user_id


def _has_perm(user: dict, perm: str) -> bool:
    role = user.get("effective_role") or "owner"
    return perm in ROLE_PERMISSIONS.get(role, set())


def require_perm(perm: str):
    async def _check(user=Depends(get_current_user)):
        if not _has_perm(user, perm):
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
        return user
    return _check


# ==================== Auth ====================

async def get_current_user(request: Request):
    """Read session_token from cookie or Authorization header.

    Every hit performs a rolling refresh (`expires_at = now + 30d`) so any
    active session never lapses mid-form. Writes are throttled to at most
    once every ROLLING_REFRESH_MIN_INTERVAL_SEC to avoid hammering Mongo.
    """
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Demo token: idempotently self-provision on every request. Rolling 30-day
    # expiry means active users are never bounced back to login.
    # Iter130 — DEMO_TOKEN is "" in production (fail-secure), so this branch
    # is unreachable there and any Bearer will fall through to the normal
    # session lookup (which will return 401 for the old literal too).
    if DEMO_TOKEN and token == DEMO_TOKEN:
        if not _DEMO_ENABLED:
            raise HTTPException(status_code=401, detail="Invalid session")
        await _ensure_demo_session()

    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    exp = session.get("expires_at")
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")

    # ── Rolling refresh (Iter106) — aggressive, throttled to 30s of activity.
    # Persist as BSON Date so the TTL index prunes properly.
    try:
        last_refresh = session.get("last_refreshed_at")
        need = True
        if last_refresh:
            if isinstance(last_refresh, str):
                last_refresh = datetime.fromisoformat(last_refresh)
            if last_refresh.tzinfo is None:
                last_refresh = last_refresh.replace(tzinfo=timezone.utc)
            need = (now_utc() - last_refresh).total_seconds() > ROLLING_REFRESH_MIN_INTERVAL_SEC
        if need:
            new_exp = now_utc() + timedelta(days=SESSION_LIFETIME_DAYS)
            await db.user_sessions.update_one(
                {"session_token": token},
                {"$set": {"expires_at": new_exp, "last_refreshed_at": now_utc()}},
            )
    except Exception:
        pass

    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # RBAC: if this user's email is registered as a team member of another
    # owner, scope data to that owner.
    tm = await db.team_members.find_one({"email": user["email"], "active": True}, {"_id": 0})
    if tm and tm.get("owner_user_id") and tm["owner_user_id"] != user["user_id"]:
        user = dict(user)
        user["user_id"] = tm["owner_user_id"]  # data scope = owner
        user["effective_role"] = tm.get("role", "accountant")
        user["is_staff"] = True
    else:
        user = dict(user)
        user["effective_role"] = "owner"
        user["is_staff"] = False
    return user
