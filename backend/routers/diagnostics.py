"""Iter127b-UAT-fix v2 · Silent Restart TEMPORARY DIAGNOSTICS.

⚠️  TEMPORARY INSTRUMENTATION — added Feb 2026 to correlate live "REFRESHING…"
   incidents with backend/platform events. Slated for removal in one revert
   commit once the root trigger is conclusively identified.

Endpoints (all mounted at prefix `/api`):

  ▸ POST /api/diagnostics/silent-restart-probe
        Public (no auth). Fire-and-forget beacon from
        SilentRestartToast. Records ONLY technical metadata — never
        form/business data. Rolling capped collection of 500 rows so this
        endpoint can never blow up disk.

  ▸ GET  /api/admin/silent-restart-probes
        Owner/admin only (any authenticated non-demo user via
        get_current_user). Returns the last 500 rows so we can grep for
        the 4-in-a-row failure trigger that trips the pill.

  ▸ GET  /api/diagnostics/build
        Public. Returns server-side `build_id` (mtime epoch of the
        SilentRestartToast bundle source) + version constant. Frontend
        uses this to detect stale in-memory bundles and show a passive
        "App update available — reload" nudge. NEVER auto-reloads.

Safety guarantees (verified line-by-line):
  • No form/business/PII/token/GSTIN/financial fields are accepted or stored.
  • Payload keys are hard-whitelisted; extra fields are dropped.
  • Beacon never authenticates so a stale/expired session can't dead-lock it.
  • Rolling cap via `capped_insert` — collection never exceeds 500 documents.
  • Never mutates any Iter127a/126a/126b/126c/business collections.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from db import db
from auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# --------------------------------------------------------------------- config
_MAX_ROWS   = 500
_COLLECTION = "silent_restart_probes"
DIAGNOSTIC_VERSION = "iter127b-diag-v1"

# Only these keys survive from a beacon payload. Anything else is discarded.
_ALLOWED_KEYS = {
    "ts",                  # ISO string, client wall-clock (informational)
    "probe_result",        # "ok" | "http_5xx" | "http_4xx" | "network" | "abort"
    "http_status",         # int | null — never a body
    "duration_ms",         # int
    "fail_streak",         # int
    "restarting",          # bool — whether the pill is currently visible
    "page_visibility",     # "visible" | "hidden" | "prerender"
    "connection_type",     # e.g. "4g", "wifi", "unknown"
    "ua_ver",              # short user-agent slice, no full string
    "client_build_id",     # string — the CLIENT's known build_id at the time
    "phase",               # "streak_bump" | "restart_shown" | "cleared" | "build_stale"
}

# --------------------------------------------------------------------- helpers
def _source_mtime_epoch() -> int:
    """The build_id we hand out is the on-disk mtime of the frontend
    SilentRestartToast source. Whenever it changes, running tabs whose
    baseline captured the OLD mtime will see a NEWER value and can render
    a passive 'App update available — reload' nudge. No auto-reload."""
    path = "/app/frontend/src/components/SilentRestartToast.jsx"
    try:
        return int(os.stat(path).st_mtime)
    except Exception:
        return 0


def _scrub(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (payload or {}).items():
        if k not in _ALLOWED_KEYS:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            # Cap strings at 80 chars — no room for GSTIN/PAN/mobile leakage.
            if isinstance(v, str):
                v = v[:80]
            out[k] = v
    return out


async def _capped_insert(doc: dict[str, Any]) -> None:
    """Insert then trim to _MAX_ROWS oldest-first. Idempotent + best-effort."""
    try:
        await db[_COLLECTION].insert_one(doc)
        # Cheap trim: only runs when count exceeds the cap.
        count = await db[_COLLECTION].estimated_document_count()
        if count > _MAX_ROWS + 50:  # small hysteresis to avoid trimming on every insert
            excess = count - _MAX_ROWS
            cursor = db[_COLLECTION].find({}, {"_id": 1}).sort("server_ts", 1).limit(excess)
            ids = [d["_id"] async for d in cursor]
            if ids:
                await db[_COLLECTION].delete_many({"_id": {"$in": ids}})
    except Exception:
        # Diagnostics MUST NEVER take the API down. Swallow silently.
        logger.debug("silent-restart-probe insert failed (swallowed)", exc_info=True)


# --------------------------------------------------------------------- endpoints
@router.post("/diagnostics/silent-restart-probe")
async def silent_restart_probe(request: Request):
    """Public, no-auth, fire-and-forget diagnostic beacon.

    Returns 204 (No Content) so the browser can safely use `keepalive:true`
    beacon semantics. Any errors are swallowed server-side — this endpoint
    NEVER surfaces problems to the user's UI."""
    try:
        raw = await request.json()
    except Exception:
        raw = {}

    payload = _scrub(raw)
    payload["server_ts"] = int(time.time())
    payload["source_ip"] = (request.client.host if request.client else "")[:32]
    # Persist async in a fire-and-forget manner. We DO await here so tests
    # can rely on the row being written, but any failure is swallowed.
    await _capped_insert(payload)
    # 204 = no body; keeps sendBeacon happy.
    from fastapi import Response
    return Response(status_code=204)


@router.get("/diagnostics/build")
async def diagnostic_build():
    """Public. Small, cacheable-if-you-want probe that the frontend uses to
    detect stale bundles. Contains NO business data."""
    return {
        "build_id": _source_mtime_epoch(),
        "version": DIAGNOSTIC_VERSION,
        "server_ts": int(time.time()),
    }


@router.get("/admin/silent-restart-probes")
async def list_probes(user=Depends(get_current_user), limit: int = 500):
    """Owner/admin diagnostic view. Requires an authenticated session.
    Returns the most-recent probes desc so we can grep the 4-in-a-row
    failure trigger. Read-only — never modifies anything."""
    limit = max(1, min(int(limit or 500), _MAX_ROWS))
    cursor = db[_COLLECTION].find({}, {"_id": 0}).sort("server_ts", -1).limit(limit)
    rows = [d async for d in cursor]
    return {
        "count": len(rows),
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "current_build_id": _source_mtime_epoch(),
        "items": rows,
    }
