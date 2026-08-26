"""Iter127b-UAT-fix v3 · Startup timing + background-migration contract.

RCA (Feb 2026): "REFRESHING…" P0 was driven by 15-30 s app-startup work
(dedup backfill, Iter49 null-coerce, auth-index de-dupe, fixture-purge) that
blocked `/api/auth/health` after every Emergent Preview pod restart. Those
migrations are now deferred to a background task; only fast, critical work
runs synchronously in the FastAPI startup event.

These tests lock the new contract:
  1. `/api/auth/health` responds < 4 s (well inside SilentRestartToast's 4 s
     abort ceiling) — measured across 5 consecutive probes.
  2. `session_index_unique` becomes True eventually — the background task
     DID complete after startup (proves migrations still run).
  3. Source guardrail: the FastAPI startup handler must NOT invoke
     `ensure_dedup_indexes_and_backfill` / Iter49 null-coerce inline.
"""
from __future__ import annotations

import os
import re
import time

import httpx
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def test_health_endpoint_fast_after_boot():
    """After the server has been up for at least a few seconds, five
    consecutive /auth/health probes must all return 200 in < 4 s each."""
    max_seen = 0.0
    for _ in range(5):
        start = time.time()
        r = httpx.get(f"{API}/auth/health", timeout=6)
        dur = time.time() - start
        assert r.status_code == 200, r.text
        max_seen = max(max_seen, dur)
        time.sleep(0.1)
    assert max_seen < 4.0, f"health endpoint spent {max_seen:.2f}s — must be < 4s"


def test_background_migrations_do_complete_eventually():
    """The auth-index housekeeping is in the background bundle. Give the
    server up to 60 s to catch up (well within our regression budget) and
    then confirm `session_index_unique` reports True."""
    deadline = time.time() + 60
    body = None
    while time.time() < deadline:
        r = httpx.get(f"{API}/auth/health", timeout=6)
        assert r.status_code == 200
        body = r.json()
        if body.get("session_index_unique") is True:
            break
        time.sleep(1.0)
    assert body is not None
    assert body.get("session_index_unique") is True, (
        f"background auth-index migration never marked session_token unique: {body}"
    )


def test_startup_handler_no_longer_calls_heavy_migrations_inline():
    """Source-level guardrail: the FastAPI startup event MUST NOT call
    the heavy migrations directly. Any regression that moves this work
    back into the critical path will fail this assertion."""
    src = open("/app/backend/server.py").read()
    m = re.search(
        r"@app\.on_event\(\"startup\"\)\s+async def startup_event\(\):(.*?)(?=@app\.on_event\(\"shutdown\"\))",
        src, re.DOTALL,
    )
    assert m, "could not locate startup_event handler in server.py"
    startup_body = m.group(1)

    # These heavy calls must NOT appear inside the synchronous startup handler.
    for banned in (
        "await ensure_dedup_indexes_and_backfill",
        "await db.trips.update_many({\"supplier_id\": None}",
        # De-dupe loop iterates ALL user_sessions — heavy.
        "async for s in db.user_sessions.find({}, {\"_id\": 1, \"session_token\": 1",
    ):
        assert banned not in startup_body, (
            f"heavy migration call still present inline in startup_event: {banned!r}"
        )

    # And the background scheduler MUST be present.
    assert "_asyncio.create_task(_run_background_migrations())" in startup_body, (
        "background migration task is no longer being scheduled from startup"
    )


def test_background_migration_lock_prevents_concurrent_runs():
    """The `_background_migrations_lock` guard must be visible in source so
    a future refactor never accidentally schedules two concurrent runs."""
    src = open("/app/backend/server.py").read()
    assert "_background_migrations_lock" in src
    assert "if _background_migrations_lock.locked()" in src


@pytest.mark.parametrize("path", ["/api/auth/health", "/api/diagnostics/build"])
def test_public_endpoints_still_respond_fast(path):
    """Both endpoints the frontend SilentRestartToast hits must stay fast."""
    start = time.time()
    r = httpx.get(f"{BASE_URL}{path}", timeout=6)
    dur = time.time() - start
    assert r.status_code == 200
    assert dur < 2.0, f"{path} took {dur:.2f}s — regression?"
