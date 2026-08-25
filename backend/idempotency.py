"""Iter126b · Idempotency-Key middleware for Bucket-B write endpoints.

Contract
--------
Every Bucket-B POST (create / payment / upload / LR regenerate) that carries a
client-generated `Idempotency-Key` header will:

  1. Execute the underlying handler **exactly once** per unique
     (user_id, active company_id, method, path, key) tuple.
  2. Cache the resulting status code + body + preserved headers for 24 h
     (TTL index on `idempotency_keys.created_at`).
  3. Replay the cached response verbatim on any subsequent request with the
     same tuple — no duplicate Trip / Customer / Invoice / Payment / Upload
     row is ever created.
  4. Single-flight concurrent duplicates by claiming the composite `_id`
     with `insert_one`; losers poll until the winner completes (max 30 s).
  5. Isolate keys per user AND per active company — a key reused from a
     different user or company cannot replay another user's response.

Deliberately NOT covered (see PRD Iter126 safety matrix):
  · Bucket A endpoints — client Axios retry already handles those (no
    duplicate side-effects since they're naturally idempotent).
  · Bucket C endpoints — communications / LLM / bulk mutations / auth
    handshakes. These must never auto-retry, so we intentionally do not
    replay them; if a caller sends an Idempotency-Key on a Bucket-C route
    the middleware simply ignores it and passes through.

Failure / edge policy:
  · No Idempotency-Key header  → passthrough (backward compatible).
  · Malformed key (< 8 or > 128 chars) → passthrough (endpoint sees raw
    request; we do not surface a new 400 that older clients wouldn't).
  · Unauthenticated request → passthrough (endpoint returns its own 401;
    we never write an idempotency row for an unauthenticated caller).
  · Handler raises → claim row is deleted so a client retry can proceed.
  · 5xx response → NOT cached (transient error; client is expected to
    retry with the same key — Bucket-A retry logic + this middleware
    together achieve the "retry after 502/503 returns the eventual
    successful result" guarantee).
  · Response body > 5 MiB → NOT cached (avoid Mongo bloat); handler will
    re-run on retry. The three A→B LR endpoints back-fill `lr_number`
    deterministically so re-run still won't create duplicates.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
from datetime import datetime, timezone

from fastapi import Request
from starlette.responses import Response

from db import db

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Bucket B endpoint whitelist (locked with user 2026-Feb).
# --------------------------------------------------------------------------- #
BUCKET_B_PATTERNS: list[re.Pattern] = [re.compile(p) for p in (
    # top-level create endpoints
    r"^/api/trips$",
    r"^/api/companies$",
    r"^/api/customers$",
    r"^/api/suppliers$",
    r"^/api/drivers$",
    r"^/api/vehicles$",
    r"^/api/invoices$",
    r"^/api/products$",
    r"^/api/parties$",
    r"^/api/team$",
    r"^/api/templates$",
    r"^/api/fuel$",
    r"^/api/expenditure-types$",
    r"^/api/saved-trip-filters$",
    r"^/api/driver-shortage-policies$",
    # sub-resource creates
    r"^/api/customers/[^/]+/ship-sites$",
    r"^/api/customers/[^/]+/add-payment$",
    r"^/api/suppliers/[^/]+/payments$",
    r"^/api/invoices/[^/]+/payments$",
    r"^/api/drivers/[^/]+/ledger$",
    r"^/api/drivers/[^/]+/ledger/post-monthly-salary$",
    r"^/api/drivers/[^/]+/ledger/settle$",
    r"^/api/drivers/[^/]+/salary-masters$",
    r"^/api/trips/[^/]+/supplier-diesel$",
    r"^/api/trips/[^/]+/supplier-advance$",
    r"^/api/trips/[^/]+/field-override$",
    r"^/api/trips/[^/]+/duplicate$",
    r"^/api/trips/from-template/[^/]+$",
    r"^/api/trips/quick-repeat/[^/]+$",
    # uploads
    r"^/api/files/upload$",
    r"^/api/files/bulk-upload$",
    r"^/api/company/logo$",
    # bulk imports
    r"^/api/trips/import$",
    r"^/api/vehicles/bulk-import$",
    # A→B LR regenerate moves (audit + optional lr_number back-fill)
    r"^/api/trips/[^/]+/regenerate-lr$",
    r"^/api/trips/bulk-regenerate-lr$",
    r"^/api/trips/bulk-all-copies-zip$",
)]

MAX_STORED_BYTES = 5 * 1024 * 1024   # 5 MiB — bigger responses skip cache
POLL_INTERVAL_SEC = 0.15             # duplicate follower poll cadence
POLL_TIMEOUT_SEC = 30                # duplicate follower wall-clock cap
TTL_SECONDS = 24 * 3600              # 24 h replay window (user-approved)
KEY_MIN_LEN = 8
KEY_MAX_LEN = 128

# Response headers that must be preserved verbatim for a valid replay.
_PRESERVE_HEADERS = {
    "content-type",
    "content-disposition",
    # Iter125 bulk-all-copies-zip surfaces trip counts via response headers;
    # replay must not drop them or the frontend post-download modal breaks.
    "x-iter125-included",
    "x-iter125-skipped",
    "x-iter125-reasons",
    "x-iter125-pdfs",
}


def _matches_bucket_b(method: str, path: str) -> bool:
    if method.upper() != "POST":
        return False
    return any(rx.match(path) for rx in BUCKET_B_PATTERNS)


def _composite_id(user_id: str, company_id: str, method: str, path: str, key: str) -> str:
    payload = f"{user_id}|{company_id or '_'}|{method}|{path}|{key}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _resolve_user_and_company(request: Request) -> tuple[str | None, str]:
    """Cheap Bearer-token lookup — mirrors auth.get_current_user() but read-only
    and returns (None, '') if the caller is not authenticated. We deliberately
    do NOT trigger the rolling-refresh write here; that stays in the handler.
    """
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        return None, ""
    try:
        session = await db.user_sessions.find_one(
            {"session_token": token}, {"_id": 0, "user_id": 1}
        )
    except Exception:
        return None, ""
    if not session:
        return None, ""
    return session.get("user_id"), request.headers.get("X-Company-Id", "") or ""


async def ensure_indexes() -> None:
    """Called at server startup — creates the 24h TTL index on
    idempotency_keys.created_at. Safe to call repeatedly."""
    try:
        await db.idempotency_keys.create_index(
            "created_at", expireAfterSeconds=TTL_SECONDS, name="ttl_created_at"
        )
    except Exception as e:
        logger.warning(f"idempotency_keys TTL index setup: {e}")


def _replay_response(row: dict) -> Response:
    body_b64 = row.get("response_body_b64") or ""
    body = base64.b64decode(body_b64) if body_b64 else b""
    headers = dict(row.get("response_headers") or {})
    headers["x-idempotent-replay"] = "1"
    return Response(
        content=body,
        status_code=int(row.get("status_code", 200)),
        headers=headers,
        media_type=row.get("media_type") or headers.get("content-type"),
    )


async def idempotency_middleware(request: Request, call_next):
    path = request.url.path or ""
    method = request.method
    key = (request.headers.get("Idempotency-Key") or "").strip()

    # Passthrough fast-path — anything outside the locked Bucket B whitelist
    # or without a valid client-supplied key is entirely unaffected.
    if not key or not _matches_bucket_b(method, path):
        return await call_next(request)
    if not (KEY_MIN_LEN <= len(key) <= KEY_MAX_LEN):
        return await call_next(request)

    user_id, company_id = await _resolve_user_and_company(request)
    if not user_id:
        return await call_next(request)

    kid = _composite_id(user_id, company_id, method, path, key)
    coll = db.idempotency_keys
    now = datetime.now(timezone.utc)

    # Try to claim the key (single-flight enforcement via unique _id).
    claimed = True
    try:
        await coll.insert_one({
            "_id": kid,
            "user_id": user_id,
            "company_id": company_id,
            "method": method,
            "path": path,
            "key": key,
            "status": "in_progress",
            "created_at": now,
        })
    except Exception:
        claimed = False  # duplicate _id — replay or wait

    if not claimed:
        # Follower path — either replay a completed row or poll until the
        # leader finishes. On timeout we fall through and let the request
        # run again (better than blocking a caller forever); the caller can
        # still send the same Idempotency-Key on a subsequent retry.
        row = await coll.find_one({"_id": kid})
        if row and row.get("status") == "completed":
            return _replay_response(row)
        deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT_SEC
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            row = await coll.find_one({"_id": kid})
            if row and row.get("status") == "completed":
                return _replay_response(row)
        return await call_next(request)

    # Leader path — run the actual handler.
    try:
        response = await call_next(request)
    except Exception:
        # Release claim so a client retry can proceed cleanly.
        try:
            await coll.delete_one({"_id": kid})
        except Exception:
            pass
        raise

    # Buffer the body so we can both return it AND cache it.
    body_bytes = b""
    try:
        async for chunk in response.body_iterator:
            body_bytes += chunk
    except Exception:
        # If the response has no body_iterator (rare — e.g. a plain Response
        # already assembled), fall back to `.body`.
        body_bytes = getattr(response, "body", b"") or b""

    cacheable = (response.status_code < 500) and (len(body_bytes) <= MAX_STORED_BYTES)
    if cacheable:
        preserved = {
            h: v for h, v in response.headers.items()
            if h.lower() in _PRESERVE_HEADERS
        }
        try:
            await coll.update_one(
                {"_id": kid},
                {"$set": {
                    "status": "completed",
                    "status_code": int(response.status_code),
                    "response_body_b64": base64.b64encode(body_bytes).decode("ascii"),
                    "response_headers": preserved,
                    "media_type": response.media_type,
                    "completed_at": datetime.now(timezone.utc),
                }},
            )
        except Exception as e:
            logger.warning(f"idempotency cache write failed for {path}: {e}")
    else:
        # Not cached — drop the claim so a follow-up retry with the same key
        # can re-run and (for A→B LR endpoints) still be duplicate-safe.
        try:
            await coll.delete_one({"_id": kid})
        except Exception:
            pass

    # Return a fresh Response — the original body_iterator has been drained.
    return Response(
        content=body_bytes,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )
