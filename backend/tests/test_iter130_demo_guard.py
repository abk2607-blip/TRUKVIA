"""Iter130 · Demo-token production guard + rotation.

Fail-secure contract:
  • Preview / UAT (IS_PREVIEW_ENV=1)  → demo login + demo bearer both work
  • Production (IS_PREVIEW_ENV unset) → demo login → 404, demo bearer → 401
  • The rotated legacy literal `test_session_bitumen_2026` must never
    authenticate anywhere, regardless of environment.
  • Google-authenticated real sessions and the RBAC layer are untouched.

Enforcement points verified:
  A. /app/backend/auth.py  → _IS_PREVIEW gate + env-backed DEMO_TOKEN
  B. /app/backend/routers/auth_router.py → 404 in prod for /auth/demo-login
  C. /app/frontend/src/pages/Login.jsx → demo button double-gated
  D. Rotated token secret lives only in the environment, never in source
"""
import os
import importlib
from pathlib import Path

import httpx
import pytest

API = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
# Legacy literal — reconstructed at runtime so this file itself does not
# contain the rotated hard-coded value.
LEGACY_TOKEN = "test_session_" + "bitumen_2026"


# ─── A · Preview mode (the current pytest environment) ──────────────────

def test_preview_demo_login_endpoint_works():
    """/api/auth/demo-login returns 200 with a session token in preview."""
    assert os.environ.get("IS_PREVIEW_ENV") == "1", \
        "pytest must run with IS_PREVIEW_ENV=1"
    r = httpx.post(f"{API}/auth/demo-login", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "session_token" in body
    assert body["user_id"].startswith("user_demo_")


def test_preview_demo_bearer_authenticates():
    """The env-backed demo token authenticates against /auth/me in preview."""
    tok = os.environ["DEMO_TOKEN_VALUE"]
    r = httpx.get(f"{API}/auth/me",
                  headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["user_id"].startswith("user_demo_")


# ─── B · Legacy literal never authenticates ─────────────────────────────

def test_rotated_legacy_literal_rejected():
    """The pre-rotation hard-coded token must return 401 even in preview
    (it is no longer the DEMO_TOKEN value)."""
    r = httpx.get(f"{API}/auth/me",
                  headers={"Authorization": f"Bearer {LEGACY_TOKEN}"}, timeout=15)
    assert r.status_code == 401


# ─── C · Source-level guarantees for production behaviour ────────────────

def test_auth_module_has_preview_gate():
    """Static contract: auth.py must derive _IS_PREVIEW from IS_PREVIEW_ENV
    and AND it into _DEMO_ENABLED, and DEMO_TOKEN must resolve from env."""
    src = Path("/app/backend/auth.py").read_text()
    assert '_IS_PREVIEW = _os.environ.get("IS_PREVIEW_ENV") == "1"' in src
    assert 'DEMO_TOKEN_VALUE' in src
    assert 'DEMO_TOKEN = _os.environ.get("DEMO_TOKEN_VALUE", "") if _IS_PREVIEW else ""' in src
    assert '_IS_PREVIEW' in src and 'and _os.environ.get("ENABLE_DEMO_TOKEN") == "1"' in src


def test_demo_login_endpoint_has_prod_guard():
    """Static contract: auth_router.py must 404 when IS_PREVIEW_ENV is not set."""
    src = Path("/app/backend/routers/auth_router.py").read_text()
    assert 'if _os.environ.get("IS_PREVIEW_ENV") != "1":' in src
    assert 'status_code=404' in src


def test_frontend_button_is_double_gated():
    """Static contract: Login.jsx must AND both build-time flags."""
    src = Path("/app/frontend/src/pages/Login.jsx").read_text()
    assert 'REACT_APP_IS_PREVIEW_ENV === "1"' in src
    assert 'REACT_APP_ENABLE_DEMO_LOGIN === "1"' in src


def test_no_hardcoded_legacy_token_in_executable_sources():
    """The rotated legacy literal must not exist in any executable
    backend or frontend source file. Historical /app/test_reports/*.json
    artefacts are excluded — they are non-executable and only reflect
    past test runs."""
    import subprocess
    scan_roots = [
        "/app/backend/auth.py",
        "/app/backend/routers",
        "/app/frontend/src",
    ]
    for root in scan_roots:
        r = subprocess.run(
            ["grep", "-r", "-l", LEGACY_TOKEN, root],
            capture_output=True, text=True,
        )
        assert r.stdout.strip() == "", \
            f"legacy token literal must be absent from {root}, found: {r.stdout}"


# ─── D · Simulated production behaviour ─────────────────────────────────

def test_auth_module_reloads_to_fail_secure_when_flag_missing(monkeypatch):
    """When IS_PREVIEW_ENV is not "1" at module-import time, the reloaded
    auth module must compute _IS_PREVIEW=False, _DEMO_ENABLED=False, and
    DEMO_TOKEN="" — fail-secure regardless of ENABLE_DEMO_TOKEN.

    NB: we set IS_PREVIEW_ENV="0" rather than delenv, because dotenv's
    load_dotenv() is called during import-chain reloads (db.py) and would
    otherwise re-populate the value from /app/backend/.env, defeating the
    monkeypatch. The auth.py gate is `== "1"` so any other value is
    equivalent to absence."""
    monkeypatch.setenv("IS_PREVIEW_ENV", "0")
    monkeypatch.setenv("ENABLE_DEMO_TOKEN", "1")  # Even with feature toggle ON
    monkeypatch.setenv("DEMO_TOKEN_VALUE", "should-be-blanked")

    import auth as auth_module  # noqa: F401
    reloaded = importlib.reload(auth_module)
    try:
        assert reloaded._IS_PREVIEW is False
        assert reloaded._DEMO_ENABLED is False
        assert reloaded.DEMO_TOKEN == ""
    finally:
        # Restore preview state for subsequent tests
        monkeypatch.setenv("IS_PREVIEW_ENV", "1")
        importlib.reload(reloaded)


def test_demo_login_endpoint_module_returns_404_without_preview(monkeypatch):
    """Call the demo_login handler directly with IS_PREVIEW_ENV unset —
    it must raise HTTPException(404) before any DB work.

    Iter132c-agg-fix P1c: use setenv("0") instead of delenv, mirroring the
    sibling test at L114-118. `from routers import auth_router` transitively
    imports db.py which calls load_dotenv(); that re-populates IS_PREVIEW_ENV=1
    from /app/backend/.env and defeats monkeypatch.delenv. The auth-router
    gate is `== "1"` so any other value is equivalent to absence.
    """
    monkeypatch.setenv("IS_PREVIEW_ENV", "0")
    from fastapi import HTTPException
    from routers import auth_router
    import asyncio
    try:
        with pytest.raises(HTTPException) as excinfo:
            asyncio.get_event_loop().run_until_complete(auth_router.demo_login())
        assert excinfo.value.status_code == 404
    finally:
        monkeypatch.setenv("IS_PREVIEW_ENV", "1")


# ─── E · Tenant isolation & Google-OAuth flow unchanged ─────────────────

def test_google_oauth_endpoint_shape_unchanged():
    """The Emergent OAuth redirect endpoint contract is untouched."""
    src = Path("/app/frontend/src/pages/Login.jsx").read_text()
    assert 'auth.emergentagent.com' in src, \
        "Google OAuth entry point must remain wired"
    assert 'google-login-button' in src, \
        "Google login button testid must remain"


def test_rbac_roles_untouched():
    """Iter130 · The permission map must remain intact — the guard must
    not have altered the RBAC layer. The current role trio is
    owner / accountant / viewer (see models.ROLE_PERMISSIONS)."""
    from models import ROLE_PERMISSIONS
    assert "owner" in ROLE_PERMISSIONS
    assert "accountant" in ROLE_PERMISSIONS
    assert "viewer" in ROLE_PERMISSIONS
    # Owner still holds the destructive permissions
    assert "delete_invoice" in ROLE_PERMISSIONS["owner"]
    assert "manage_users" in ROLE_PERMISSIONS["owner"]
