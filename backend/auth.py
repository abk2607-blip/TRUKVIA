"""Auth + RBAC helpers."""
from datetime import datetime, timezone
from fastapi import Request, HTTPException, Depends
from db import db
from models import ROLE_PERMISSIONS, now_utc


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
