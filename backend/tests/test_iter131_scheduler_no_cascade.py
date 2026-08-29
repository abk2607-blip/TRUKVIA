"""Iter131 · Scheduler-cascade correction tests.

Covers the two guarantees added to break the self-perpetuating regression
cascade that used to fire the guard every ~11 min:

  A. POST /api/admin/deploy-readiness/run-now must short-circuit with
     {"triggered": false, "reason": "already_running"} whenever the
     shared `_regression_lock` is currently held.

  B. On every completion, the on-demand path must refresh `next_check_at`
     to approximately now + 1 hour, so the field never drifts stale when
     only /run-now is in use.

We do not touch the periodic loop (that is enabled independently via
REGRESSION_GUARD_PERIODIC=1) and we do not weaken any assertion in the
existing regression suite."""
import os
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


# ─── A · Source-level guarantees ────────────────────────────────────────

def test_run_now_endpoint_checks_lock():
    """server.py::/run-now must consult _regression_lock.locked() BEFORE
    scheduling _once(), so nested calls (from the regression suite itself)
    cannot queue behind the current run's lock and cascade."""
    src = Path("/app/backend/server.py").read_text()
    # The critical guard: short-circuit when the lock is already held.
    assert "if _regression_lock.locked():" in src, \
        "server.py must guard /run-now against re-entrant scheduling"
    assert '"reason": "already_running"' in src, \
        "the short-circuit must return reason=already_running so the test suite can accept it"


def test_run_now_writes_next_check_at():
    """The on-demand path must also refresh next_check_at (previously only
    the periodic loop wrote it, causing 5-day-stale metadata when /run-now
    was the only trigger in use)."""
    src = Path("/app/backend/server.py").read_text()
    # Both write-sites now set next_check_at
    occurrences = src.count('"next_check_at": (_dt.now(_tz.utc) + _td(hours=1)).isoformat()')
    assert occurrences >= 3, (
        f"next_check_at must be written by both periodic (2) and on-demand (1) "
        f"code paths; found {occurrences}"
    )


def test_periodic_guard_env_flag_present():
    """The hourly loop is enabled via REGRESSION_GUARD_PERIODIC=1 in .env."""
    env = Path("/app/backend/.env").read_text()
    assert "REGRESSION_GUARD_PERIODIC=1" in env, \
        ".env must enable the periodic regression loop"


# ─── B · Live-endpoint guarantees ───────────────────────────────────────

def test_run_now_returns_triggered_or_already_running():
    """POST /run-now must return one of the two accepted shapes; never 5xx."""
    r = httpx.post(f"{API}/admin/deploy-readiness/run-now",
                   headers=HDR, timeout=15)
    assert r.status_code in (200, 202), r.text
    body = r.json()
    if body.get("triggered") is True:
        # Freshly scheduled — nothing else to assert on this branch.
        return
    assert body.get("triggered") is False
    assert body.get("reason") == "already_running", body


def test_run_now_short_circuits_when_lock_held():
    """When a regression run is in flight, a second /run-now must NOT queue
    another task. We detect the lock state directly on the backend by
    importing the module in-process (same env, same singleton)."""
    import sys
    sys.path.insert(0, "/app/backend")
    # Fresh import — the backend process holds its own module state; we
    # import the same module here to reach the same _regression_lock
    # singleton via the shared asyncio event loop is NOT possible from
    # pytest. So we drive this through the HTTP endpoint instead: fire
    # two /run-now calls back-to-back; if the first schedules, the second
    # MUST short-circuit. If both short-circuit (already-running from an
    # unrelated in-flight run) that also proves the guard fires.
    r1 = httpx.post(f"{API}/admin/deploy-readiness/run-now",
                    headers=HDR, timeout=15).json()
    r2 = httpx.post(f"{API}/admin/deploy-readiness/run-now",
                    headers=HDR, timeout=15).json()
    # Between the two calls, at least ONE must be triggered:false with
    # reason:already_running — either r2 (because r1 acquired the lock)
    # or both (because an earlier run was already in flight).
    denied = [r for r in (r1, r2)
              if r.get("triggered") is False and r.get("reason") == "already_running"]
    assert denied, (
        f"Expected at least one /run-now to short-circuit; got r1={r1}, r2={r2}. "
        f"This would indicate the cascade guard is not firing."
    )


def test_next_check_at_is_not_stale():
    """After a successful regression completion, next_check_at must be
    within (now, now + 65 min). Guards against the '5-day-old fossil'
    regression the fix was designed to eliminate."""
    r = httpx.get(f"{API}/admin/deploy-readiness",
                  headers=HDR, timeout=10)
    assert r.status_code == 200
    d = r.json()
    nxt = d.get("next_check_at")
    assert nxt, "deploy-readiness must include next_check_at"
    try:
        # Tolerate both `+00:00` and `Z` suffixes.
        nxt_dt = datetime.fromisoformat(nxt.replace("Z", "+00:00"))
    except Exception as e:
        pytest.fail(f"next_check_at not parseable: {nxt} ({e})")
    now = datetime.now(timezone.utc)
    # Guard against fossil timestamps (must be in the future, or at
    # worst freshly minted within the last 5 s of a just-completed run).
    delta = (nxt_dt - now).total_seconds()
    assert -5 <= delta <= 65 * 60, (
        f"next_check_at is not within (~now, now+65m): nxt={nxt}, delta={delta:.0f}s"
    )
