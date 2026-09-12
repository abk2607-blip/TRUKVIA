"""Iter150J · Approval Gate — external HTTP boundary protection.

The middleware sits at the outermost layer of the FastAPI stack. It only
intercepts POST requests targeting the six authorised writer endpoints
(Trip, Invoice, Supplier / Vendor / Mechanic / Driver payment). When the
resolved tenant has the matching approval toggle enabled, the request is
short-circuited with a 409 `approval_required` envelope. The frontend
axios response-interceptor catches this envelope and transparently
reroutes the untouched payload to POST /api/approvals.

Non-goals:
  * No body inspection — payload preservation is the frontend interceptor's
    responsibility via `err.config.data`.
  * No HMAC / no internal bypass header.
  * No modification of any locked writer router.
  * GET / PUT / PATCH / DELETE + unrelated POSTs pass through unchanged.

Trust boundary: this middleware is the ONLY external-HTTP guard. Direct
Python delegation invoked from `services_approvals.py` bypasses HTTP and
therefore bypasses this middleware by construction (no HMAC needed).
"""
from __future__ import annotations

import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.requests import Request
from starlette.types import ASGIApp

from db import db
from models import APPROVAL_GATED_ROUTES, approval_toggle_key

logger = logging.getLogger(__name__)


async def _resolve_user_from_bearer(request: Request):
    """Look up the session user without triggering the auth dependency.

    Mirrors auth.get_current_user's token acquisition path but does NOT
    perform the rolling-refresh write so middleware stays read-only.
    Returns None on any failure so passthrough is preserved.
    """
    token = request.cookies.get("session_token") or ""
    if not token:
        auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        return None
    try:
        # Demo token special-case: rely on auth module's canonical resolver.
        from auth import DEMO_TOKEN, _DEMO_ENABLED, _ensure_demo_session
        if DEMO_TOKEN and token == DEMO_TOKEN and _DEMO_ENABLED:
            await _ensure_demo_session()
    except Exception:
        pass
    try:
        session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
        if not session:
            return None
        user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
        return user
    except Exception:
        return None


async def _resolve_company_id(request: Request, user: dict) -> str:
    override = request.headers.get("x-company-id") or request.headers.get("X-Company-Id") or ""
    if override:
        doc = await db.companies.find_one(
            {"id": override, "user_id": user["user_id"]}, {"id": 1, "_id": 0}
        )
        if doc:
            return override
    doc = await db.companies.find_one(
        {"user_id": user["user_id"], "is_default": True}, {"id": 1, "_id": 0}
    )
    if doc:
        return doc["id"]
    doc = await db.companies.find_one(
        {"user_id": user["user_id"]}, {"id": 1, "_id": 0}
    )
    return doc["id"] if doc else ""


def _match_gated_route(method: str, path: str):
    """Return (entity_kind, party_id) if path matches an approval-gated
    writer, else (None, None). Party-id is captured from the path when
    applicable (payment kinds); trip/invoice return "" for party_id.
    """
    if not path.startswith("/api/"):
        return None, None
    for rx, wanted_method, kind, _party_key in APPROVAL_GATED_ROUTES:
        if method != wanted_method:
            continue
        m = rx.match(path)
        if m:
            party_id = m.group(1) if m.groups() else ""
            return kind, party_id
    return None, None


class ApprovalGateMiddleware(BaseHTTPMiddleware):
    """Iter150J · External-boundary gate.

    Passthrough conditions:
      * Non-POST method.
      * Path outside the six-writer whitelist.
      * `/api/approvals*` (never self-recurse).
      * No valid session (auth dependency will handle 401).
      * Tenant toggle for this entity kind is OFF / missing.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            method = request.method.upper()
            path = request.url.path or ""

            # Fast passthrough: never intercept the approval router itself.
            if path.startswith("/api/approvals"):
                return await call_next(request)

            if method != "POST":
                return await call_next(request)

            entity_kind, party_id = _match_gated_route(method, path)
            if entity_kind is None:
                return await call_next(request)

            # Skip if no session — let downstream auth dependency return 401.
            user = await _resolve_user_from_bearer(request)
            if not user:
                return await call_next(request)

            cid = await _resolve_company_id(request, user)
            if not cid:
                return await call_next(request)

            company = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0})
            if not company:
                return await call_next(request)

            toggle_key = approval_toggle_key(entity_kind)
            if not company.get(toggle_key, False):
                # Legacy tenant (toggle OFF/missing) — preserve current posting.
                return await call_next(request)

            # Gate active — block with a machine-readable envelope. The
            # frontend interceptor re-routes to POST /api/approvals with the
            # ORIGINAL payload (never reconstructed here).
            payload = {
                "detail": "approval_required",
                "approval_required": True,
                "entity_type": entity_kind.split("_")[0] if "_" in entity_kind else entity_kind,
                "entity_kind": entity_kind,
                "party_id": party_id or "",
                "writer_url": path,
                "method": method,
                "redirect": "/api/approvals",
            }
            return JSONResponse(status_code=409, content=payload)
        except Exception as e:
            # Never break the request pipeline if the gate mis-fires.
            logger.warning(f"ApprovalGateMiddleware fault (passthrough): {e}")
            return await call_next(request)
