"""Iter127b-UAT-fix · /api/auth/health hardening tests.

RCA: staff UAT was intermittently blocked by "REFRESHING…" because
/api/auth/health would 503 on ANY exception in the auxiliary lookups
(index_information, deploy_status), even when the DB was healthy. This
suite locks in the new contract:

  A. 200 whenever the DB ping succeeds, regardless of aux lookup state.
  B. Response contract unchanged (keys still present; aux values may be null).
  C. Endpoint returns quickly (< 1.5 s) — never blocks the toast poll.
"""
from __future__ import annotations

import os
import time

import httpx

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def test_health_returns_200_and_expected_shape():
    r = httpx.get(f"{API}/auth/health", timeout=8)
    assert r.status_code == 200, r.text
    body = r.json()
    # Contract-locked keys (must never disappear — SilentRestartToast +
    # deploy healthcheck + regression guard all rely on them).
    for k in (
        "ok", "db", "session_index_unique", "demo_ready", "demo_expiry",
        "regression_guard", "timestamp",
    ):
        assert k in body, f"missing key '{k}' in health payload: {body}"
    for gk in ("status", "exit_code", "checked_at", "strict_mode", "consecutive_failures"):
        assert gk in body["regression_guard"], f"missing regression_guard.{gk}"
    assert body["ok"] is True
    assert body["db"] == "up"


def test_health_is_fast_never_blocks_toast_poll():
    """SilentRestartToast now aborts probes after 4 s. The health endpoint
    must be safely under that ceiling even under mild load."""
    start = time.time()
    r = httpx.get(f"{API}/auth/health", timeout=6)
    elapsed = time.time() - start
    assert r.status_code == 200
    assert elapsed < 1.5, f"/auth/health took {elapsed:.2f}s — should be < 1.5s"


def test_health_survives_burst_polling():
    """20 back-to-back polls in a tight loop must all return 200. This is
    the exact worst-case the toast could produce on a slow network."""
    codes = []
    for _ in range(20):
        try:
            codes.append(httpx.get(f"{API}/auth/health", timeout=6).status_code)
        except Exception as e:
            codes.append(f"exc:{type(e).__name__}")
    # Every response must be 200 — no 503 fall-through from aux lookups.
    assert all(c == 200 for c in codes), f"burst produced non-200: {codes}"


def test_health_no_longer_hard_blocks_on_aux_lookup():
    """Read the source once — the auxiliary lookup (deploy_status /
    index_information / demo-session) must be wrapped in its own try/except
    so an aux failure NEVER 503s the endpoint. This is a source-level
    guardrail against regression."""
    src = open("/app/backend/routers/auth_router.py").read()
    # There should be exactly one raise HTTPException(status_code=503 ...
    # in the health function (the DB-ping branch).
    fn_start = src.index("async def auth_health")
    fn_end = src.index("\n\n@router", fn_start)
    health_src = src[fn_start:fn_end]
    assert health_src.count("status_code=503") == 1, (
        "auth_health should have exactly one 503 exit — the DB-ping branch. "
        f"Found {health_src.count('status_code=503')} occurrences."
    )
    # The aux-lookup try/except pattern must be present (best-effort).
    assert "except Exception:\n        pass" in health_src, (
        "Auxiliary lookups must be wrapped in `except Exception: pass` so they "
        "never propagate to a 503."
    )
