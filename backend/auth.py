"""Auth + RBAC helpers."""
from datetime import datetime, timezone, timedelta
from fastapi import Request, HTTPException, Depends
from db import db
from models import ROLE_PERMISSIONS, now_utc


# Demo-mode token that auto-provisions a persistent test user with a rolling
# 30-day expiry.  Removes the "logged out every 15 minutes" pain reported
# during testing.  Set DEMO_TOKEN_DISABLED=1 in backend/.env to hard-disable
# once real customers start using the app.
DEMO_TOKEN = "test_session_bitumen_2026"
import os as _os
_DEMO_DISABLED = _os.environ.get("DEMO_TOKEN_DISABLED") == "1"


async def _ensure_demo_session():
    """Idempotently create a demo user + rolling 30-day session for DEMO_TOKEN."""
    user = await db.users.find_one({"session_token_demo": True}, {"_id": 0})
    if not user:
        user_id = f"user_demo_{DEMO_TOKEN[-8:]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": "demo@bitumen-transport.local",
            "name": "Demo User",
            "picture": "",
            "session_token_demo": True,
            "created_at": now_utc().isoformat(),
        })
    else:
        user_id = user["user_id"]
    # Rolling 30-day expiry — refresh every hit so active sessions never die.
    exp = (now_utc() + timedelta(days=30)).isoformat()
    await db.user_sessions.update_one(
        {"session_token": DEMO_TOKEN},
        {"$set": {
            "user_id": user_id,
            "session_token": DEMO_TOKEN,
            "expires_at": exp,
            "created_at": now_utc().isoformat(),
        }},
        upsert=True,
    )
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
    """Read session_token from cookie or Authorization header."""
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Demo token: idempotently self-provision on every request. Rolling 30-day
    # expiry means active users are never bounced back to login.
    if token == DEMO_TOKEN and not _DEMO_DISABLED:
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

    # ── Rolling refresh: every 4 minutes of activity, extend the expiry.
    # Prevents users being logged out mid-form after 15 minutes of Google
    # OAuth session lifetime; demo tokens already refreshed above.
    try:
        if token != DEMO_TOKEN:
            remaining = (exp - now_utc()).total_seconds()
            # Only refresh sessions that are >5 min old but still valid, and
            # haven't been refreshed within the last 4 min.
            last_refresh = session.get("last_refreshed_at")
            need = True
            if last_refresh:
                if isinstance(last_refresh, str):
                    last_refresh = datetime.fromisoformat(last_refresh)
                if last_refresh.tzinfo is None:
                    last_refresh = last_refresh.replace(tzinfo=timezone.utc)
                need = (now_utc() - last_refresh).total_seconds() > 240
            if need and remaining < 6 * 24 * 3600:
                new_exp = (now_utc() + timedelta(days=7)).isoformat()
                await db.user_sessions.update_one(
                    {"session_token": token},
                    {"$set": {"expires_at": new_exp, "last_refreshed_at": now_utc().isoformat()}},
                )
    except Exception:
        pass

    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # RBAC: if this user's email is registered as a team member of another owner, scope data to that owner
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
