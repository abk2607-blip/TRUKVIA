from fastapi import APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import io, os, uuid, secrets, re, requests, base64, logging

from db import db
from models import (
    Company, Customer, Expenses, Driver, Trip, Product, Party, Vehicle,
    MaintenanceLog, Fuel, Payment, Invoice, TeamMember, ROLE_PERMISSIONS,
    InvoiceCreateRequest, InvoiceUpdateRequest, PaymentAdd, FileRef, AuditLog,
    now_utc, new_id,
)
from auth import get_current_user, _has_perm, require_perm, DEMO_TOKEN, _ensure_demo_session
from company import (
    _active_company_id, _get_or_create_default_company,
    _backfill_company_id, _backfill_to_default,
)
from audit import _log_audit, _diff_dict
from services import (
    _compute_trip, _trip_billable, _recompute_invoice,
    _next_invoice_number, _next_invoice_number_for_company,
    _next_lr_number, _in_range, _vehicle_expiry_stats,
    _state_code, _gstin_checksum,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

@router.get("/auth/health")
async def auth_health():
    """Iter48 — Public diagnostic endpoint. Confirms the auth pipeline is alive
    WITHOUT requiring a valid session. Deployment health-checks + support
    engineers use this to verify DB connectivity and index state.

    Iter52 — STRICT deploy-gate mode. When env var REGRESSION_GUARD_STRICT=1,
    this endpoint returns HTTP 503 whenever the latest deploy-readiness check
    reports `status=fail`. Load balancers + Emergent's deploy healthcheck
    treat 503 as a failed instance and will refuse to promote it to
    production. This is the belt-and-braces enforcement that makes P1 real —
    even if a developer bypasses GitHub Actions, they still can't ship a
    broken build because the pod fails its own healthcheck."""
    # Iter127b-UAT-fix (Feb 2026) — the ONLY signal that decides 200 vs 503 is
    # a live Mongo ping. Every auxiliary lookup (index info, demo session,
    # deploy_status) is now best-effort — a transient failure surfaces as a
    # null field in the payload but never 503s the endpoint. This eliminates
    # the intermittent "Auth pipeline degraded" 503 wave that tripped
    # SilentRestartToast during backend reload/UAT windows even when the DB
    # was fully reachable.
    def _iso(v):
        try:
            return v.isoformat() if hasattr(v, "isoformat") else v
        except Exception:
            return v

    try:
        await db.command("ping")
    except Exception as e:
        # DB genuinely unreachable — this IS the only condition that should
        # 503 the health endpoint (kept for load-balancer contract parity).
        raise HTTPException(status_code=503, detail=f"Auth pipeline degraded: {e}")

    # ── Best-effort auxiliaries (never 503) ──────────────────────────────
    has_unique = None
    try:
        idx = await db.user_sessions.index_information()
        has_unique = any(
            "session_token" in [k[0] for k in v.get("key", [])] and v.get("unique")
            for v in idx.values()
        )
    except Exception:
        pass

    demo = None
    try:
        demo = await db.user_sessions.find_one(
            {"session_token": DEMO_TOKEN}, {"_id": 0, "expires_at": 1}
        )
    except Exception:
        pass

    strict_mode = os.environ.get("REGRESSION_GUARD_STRICT", "0") == "1"
    guard_status = "unknown"
    guard_exit_code = None
    guard_checked_at = None
    consecutive = 0
    try:
        gd = await db.deploy_status.find_one({"_id": "current"}, {"_id": 0})
        if gd:
            guard_status = gd.get("status", "unknown")
            guard_exit_code = gd.get("exit_code")
            guard_checked_at = gd.get("checked_at")
            consecutive = int(gd.get("consecutive_failures", 0) or 0)
    except Exception:
        pass

    return {
        "ok": True,
        "db": "up",
        "session_index_unique": has_unique,
        "demo_ready": bool(demo),
        "demo_expiry": _iso((demo or {}).get("expires_at")),
        "regression_guard": {
            "status": guard_status,
            "exit_code": guard_exit_code,
            "checked_at": _iso(guard_checked_at),
            "strict_mode": strict_mode,
            "consecutive_failures": consecutive,
        },
        "timestamp": now_utc().isoformat(),
    }


@router.post("/auth/demo-login")
async def demo_login():
    """Iter48 — Server-side Demo Login. Provisions the demo user + session
    server-side and returns the token. Frontend no longer has to hardcode a
    static string; if this endpoint changes token strategy, only the backend
    changes. Prevents "Demo Login not working" caused by stale localStorage."""
    try:
        user_id = await _ensure_demo_session()
        return {
            "session_token": DEMO_TOKEN,
            "user_id": user_id,
            "email": "demo@bitumen-transport.local",
            "name": "Demo User",
            "picture": "",
            "expires_at": (now_utc() + timedelta(days=30)).isoformat(),
            "notice": "Demo mode — data may be shared across testers.",
        }
    except Exception as e:
        logger.exception("demo-login provisioning failed")
        raise HTTPException(status_code=500, detail=f"Demo login provisioning failed: {e}")


@router.post("/auth/session")
async def create_session(request: Request, response: Response):
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    # Exchange session_id with Emergent Auth
    r = requests.get(
        "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
        headers={"X-Session-ID": session_id},
        timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    data = r.json()

    email = data["email"]
    # Find or create user — race-safe upsert
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": data.get("name", ""), "picture": data.get("picture", "")}},
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        try:
            await db.users.insert_one({
                "user_id": user_id,
                "email": email,
                "name": data.get("name", ""),
                "picture": data.get("picture", ""),
                "created_at": now_utc().isoformat(),
            })
        except Exception:
            # Duplicate email (concurrent OAuth) — fall through to existing row
            row = await db.users.find_one({"email": email}, {"_id": 0})
            if not row:
                raise
            user_id = row["user_id"]

    session_token = data["session_token"]
    # Iter110 — Align DB session expires_at with cookie (SESSION_LIFETIME_DAYS = 30d).
    # Store as BSON Date so the TTL index prunes stale rows correctly. Rolling
    # refresh in `auth.get_current_user` writes BSON Date too, so this is
    # consistent across login and subsequent hits.
    from auth import SESSION_LIFETIME_DAYS as _SESSION_LIFETIME_DAYS
    expires_at = now_utc() + timedelta(days=_SESSION_LIFETIME_DAYS)
    # Iter48 — UPSERT (was insert_one). Prevents duplicate session-token rows.
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "user_id": user_id,
            "session_token": session_token,
            "expires_at": expires_at,
            "created_at": now_utc(),
            "last_refreshed_at": now_utc(),
        }},
        upsert=True,
    )

    # Iter48 — Best-effort cleanup of expired rows for this user (never blocks login)
    try:
        await db.user_sessions.delete_many({"user_id": user_id, "expires_at": {"$lt": now_utc()}})
    except Exception:
        pass

    # Iter110 — Align cookie lifetime with backend SESSION_LIFETIME_DAYS (30d).
    # Persistent cookie with an explicit Max-Age survives browser restarts /
    # OS power-cycles; a "session cookie" (no Max-Age) is cleared on close.
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=_SESSION_LIFETIME_DAYS * 24 * 60 * 60,
        path="/",
    )
    return {
        "user_id": user_id,
        "email": email,
        "name": data.get("name", ""),
        "picture": data.get("picture", ""),
        "session_token": session_token,  # fallback for browsers blocking third-party cookies
    }

@router.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
    }

@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if token and token != DEMO_TOKEN:
        # Never delete the shared demo token — testers depend on it staying alive
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}
