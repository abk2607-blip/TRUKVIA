"""Iter127b diagnostics — P0 CLOSURE cleanup (Feb 2026, user-approved).

The temporary REFRESHING… diagnostic beacon endpoints have been REMOVED
after the 24-hour observation window met the P0 acceptance criterion
(no active-session fail_streak >= 3 events during business use).

Only ONE endpoint remains — `GET /api/diagnostics/build` — because it is
still consumed by the frontend `SilentRestartToast` to detect stale
in-memory bundles and drive the passive "App update available — reload"
nudge + v4 auto-reload. It is public, cache-safe, and returns NO business
data — only a build_id (mtime epoch of the SilentRestartToast source) and
a static version string.

Removed endpoints (locked out of production):
  ▸ POST /api/diagnostics/(the beacon path)
  ▸ GET  /api/admin/(the admin listing path)
Removed helpers: `_scrub`, `_capped_insert`, `_ALLOWED_KEYS`, `_MAX_ROWS`,
`_COLLECTION` — all deleted; historical `silent_restart_probes` documents
remain in Mongo but are no longer written to, read from, or exposed.
"""
from __future__ import annotations

import os
import time

from fastapi import APIRouter

router = APIRouter(prefix="/api")

DIAGNOSTIC_VERSION = "iter127b-diag-v1"


def _source_mtime_epoch() -> int:
    """The build_id we hand out is the on-disk mtime of the frontend
    SilentRestartToast source. Whenever it changes, running tabs whose
    baseline captured the OLD mtime will see a NEWER value and can render
    a passive 'App update available — reload' nudge."""
    path = "/app/frontend/src/components/SilentRestartToast.jsx"
    try:
        return int(os.stat(path).st_mtime)
    except Exception:
        return 0


@router.get("/diagnostics/build")
async def diagnostic_build():
    """Public. Small, cacheable-if-you-want probe that the frontend uses to
    detect stale bundles. Contains NO business data."""
    return {
        "build_id": _source_mtime_epoch(),
        "version": DIAGNOSTIC_VERSION,
        "server_ts": int(time.time()),
    }
