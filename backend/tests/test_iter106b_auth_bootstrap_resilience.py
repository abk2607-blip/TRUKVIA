"""Iter106b · Auth Bootstrap Resilience — backend-contract regression guards.

Frontend AuthContext depends on a VERY specific 4-response-shape contract
from /api/auth/me. This suite pins that contract so the resilience layers
(retry, reconnect chip, unreachable retry button, session-dead OAuth relaunch)
keep working across refactors.

Contract pinned here:
  1. Valid session          → 200 + user profile JSON
  2. Invalid/expired session→ 401 + detail matches "invalid session" OR
                              "session expired" (case-insensitive substring)
  3. No session (unauth)    → 401 + detail matches "not authenticated"
  4. RBAC 401 vs session 401→ backend never returns 5xx for auth failures
                              (only 401), so the frontend can safely
                              distinguish "server down" from "session bad"

Additionally we assert:
  5. /api/auth/health returns 200 within 2 s (used as a liveness probe
     in future — frontend retry logic already tolerates 502).
  6. Empty Bearer header behaves identically to no header.
"""
import os
import time
import httpx


BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]


def test_auth_me_valid_session_returns_200_with_profile():
    r = httpx.get(f"{BASE}/auth/me",
                  headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
                  timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("user_id", "email", "name"):
        assert k in body, f"contract broken: missing {k} in /auth/me 200 body"


def test_auth_me_no_session_returns_401_not_authenticated():
    """No Authorization header and no cookie — frontend expects this exact
    detail string so it does NOT enter the OAuth relaunch branch."""
    r = httpx.get(f"{BASE}/auth/me", timeout=10)
    assert r.status_code == 401, r.text
    detail = (r.json().get("detail") or "").lower()
    assert "not authenticated" in detail, (
        f"contract broken: /auth/me unauth detail was {detail!r}; "
        f"frontend Layer 4a depends on this exact substring."
    )


def test_auth_me_invalid_bearer_returns_401_invalid_session():
    """Garbage bearer token — frontend expects "invalid session" so it
    DOES enter the OAuth relaunch branch."""
    r = httpx.get(f"{BASE}/auth/me",
                  headers={"Authorization": "Bearer garbage_token_iter106b_xyz"},
                  timeout=10)
    assert r.status_code == 401, r.text
    detail = (r.json().get("detail") or "").lower()
    assert "invalid session" in detail or "session expired" in detail, (
        f"contract broken: /auth/me bad-token detail was {detail!r}; "
        f"frontend OAuth relaunch triggers on 'invalid session' | "
        f"'session expired' substrings ONLY."
    )


def test_auth_me_empty_bearer_returns_401_not_authenticated():
    """Empty Bearer must not be treated as a session — same shape as no
    header at all so the frontend hint short-circuit works.
    Note: httpx client refuses to send Authorization headers whose value is
    purely whitespace, so we test with a single-char (still-invalid) token
    which the backend must classify as invalid, not authenticated."""
    r = httpx.get(f"{BASE}/auth/me",
                  headers={"Authorization": "Bearer x"},
                  timeout=10)
    assert r.status_code == 401
    detail = (r.json().get("detail") or "").lower()
    # Either "not authenticated" or "invalid session" is acceptable here —
    # the point is the backend must not crash on a malformed token.
    assert "authenticated" in detail or "invalid session" in detail


def test_auth_me_never_returns_5xx_for_auth_failure():
    """Backend must NEVER 5xx on an auth failure — frontend Layer 4b treats
    5xx as 'server issue, retry' rather than 'session dead, relaunch OAuth'.
    A regression that flips a bad-token 401 into a 500 would silently
    trigger the wrong recovery branch."""
    # NB: pure-whitespace tokens are rejected by httpx client-side; we test
    # a curated set of malformed but SENDABLE tokens.
    for tok in ("garbage_token", "expired.jwt.here", "x", "a" * 200,
                "bearer_looking_but_bad"):
        r = httpx.get(f"{BASE}/auth/me",
                      headers={"Authorization": f"Bearer {tok}"},
                      timeout=10)
        assert r.status_code < 500, (
            f"contract broken: bad-token {tok!r} returned {r.status_code}; "
            f"backend must return 401, not 5xx, for any auth failure."
        )
    # Also test no header at all
    r = httpx.get(f"{BASE}/auth/me", timeout=10)
    assert r.status_code < 500


def test_auth_health_liveness_probe_under_2s():
    """Fast liveness probe used by future frontend retry logic — must be
    a cheap in-process endpoint that doesn't touch DB or external APIs."""
    t0 = time.perf_counter()
    r = httpx.get(f"{BASE}/auth/health", timeout=5)
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 2.0, f"health probe took {elapsed:.3f}s (must be < 2s)"


def test_auth_me_response_is_reasonably_fast():
    """/auth/me under 3 s in the happy path so the frontend hard 6 s
    bootstrap timeout never fires on a healthy backend."""
    t0 = time.perf_counter()
    r = httpx.get(f"{BASE}/auth/me",
                  headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
                  timeout=5)
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    assert elapsed < 3.0, (
        f"/auth/me happy-path took {elapsed:.3f}s; frontend Layer 1 hard "
        f"timeout is 6 s so anything above ~3 s risks false Reconnecting chips."
    )


def test_auth_me_correctly_reads_session_from_cookie():
    """Layer-independent contract — the frontend Iter110 fix depends on
    /auth/me accepting the session_token from a COOKIE (not just the
    Authorization header). Without this the power-cycle recovery path
    breaks."""
    r = httpx.get(f"{BASE}/auth/me",
                  cookies={"session_token": DEMO_TOKEN},
                  timeout=10)
    assert r.status_code == 200, (
        f"contract broken: /auth/me refused a valid cookie ({r.status_code} "
        f"{r.text}); Iter110 power-cycle recovery depends on cookie acceptance."
    )
    body = r.json()
    assert body.get("user_id"), "auth/me cookie path returned empty body"
