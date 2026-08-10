"""Iter54 — Login-Failure Tracking (P1).

Coverage:
 1. Invalid token → 401 on /api/auth/me is logged with kind='auth_failure'
 2. Missing token → 401 on /api/auth/me is logged with kind='auth_failure'
 3. Valid token → 200 on /api/auth/me is NOT logged
 4. POST/save failure → still classified as kind='save_failure'
 5. /api/admin/* endpoints are excluded from save-health tracking
 6. /api/admin/save-health response exposes auth_failures + save_failures counts
 7. Recent failure rows include the `kind` field
 8. Frontend Save-Health tile renders the auth vs save split (testid)
 9. login_failure=False alert_type toggle prevents auth-only alert firing
"""
import os
import time
import uuid
import asyncio
import pytest
import httpx
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = "test_session_bitumen_2026"
HDR = {"Authorization": f"Bearer {TOKEN}"}


def _cid():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=10).json()[0]["id"]


def _h():
    return {**HDR, "X-Company-Id": _cid()}


async def _count_recent(kind: str, path_prefix: str, since_iso: str) -> int:
    """Count save_health rows since `since_iso` matching kind and path prefix."""
    import motor.motor_asyncio
    c = motor.motor_asyncio.AsyncIOMotorClient(os.environ.get("MONGO_URL"))
    db = c[os.environ.get("DB_NAME")]
    n = await db.save_health.count_documents({
        "kind": kind,
        "path": {"$regex": f"^{path_prefix}"},
        "ts_iso": {"$gte": since_iso},
    })
    c.close()
    return n


def test_invalid_token_401_is_logged_as_auth_failure():
    since = datetime.now(timezone.utc).isoformat()
    r = httpx.get(f"{BASE}/api/auth/me",
                  headers={"Authorization": "Bearer definitely_not_a_valid_token_xyz"},
                  timeout=10)
    assert r.status_code == 401
    time.sleep(0.5)  # middleware writes after response
    n = asyncio.run(_count_recent("auth_failure", "/api/auth/", since))
    assert n >= 1, f"invalid-token 401 not logged as auth_failure (got {n} rows)"


def test_missing_token_401_is_logged_as_auth_failure():
    since = datetime.now(timezone.utc).isoformat()
    r = httpx.get(f"{BASE}/api/auth/me", timeout=10)  # no Authorization header
    assert r.status_code == 401
    time.sleep(0.5)
    n = asyncio.run(_count_recent("auth_failure", "/api/auth/", since))
    assert n >= 1, f"missing-token 401 not logged as auth_failure (got {n} rows)"


def test_valid_token_is_not_logged():
    since = datetime.now(timezone.utc).isoformat()
    r = httpx.get(f"{BASE}/api/auth/me", headers=HDR, timeout=10)
    assert r.status_code == 200
    time.sleep(0.5)
    n = asyncio.run(_count_recent("auth_failure", "/api/auth/", since))
    assert n == 0, f"valid-token 200 was incorrectly logged as auth_failure (got {n} rows)"


def test_post_failure_still_tagged_as_save_failure():
    """Regression — /api/customers POST with invalid payload must still be
    tagged 'save_failure', not 'auth_failure', even after Iter54 change."""
    since = datetime.now(timezone.utc).isoformat()
    r = httpx.post(f"{BASE}/api/customers", headers=_h(), json={}, timeout=10)
    assert r.status_code >= 400
    time.sleep(0.5)
    save_n = asyncio.run(_count_recent("save_failure", "/api/customers", since))
    auth_n = asyncio.run(_count_recent("auth_failure", "/api/customers", since))
    assert save_n >= 1, f"customers POST failure not logged as save_failure (got {save_n})"
    assert auth_n == 0, f"customers POST wrongly tagged auth_failure (got {auth_n})"


def test_admin_endpoints_are_excluded():
    """/api/admin/* must never generate save_health rows even when they 404 or 401."""
    since = datetime.now(timezone.utc).isoformat()
    # Hitting an admin path with a bogus subpath — should 404 or 405, but must not be logged
    r = httpx.get(f"{BASE}/api/admin/definitely-not-a-real-admin-endpoint-xyz", timeout=10)
    assert r.status_code >= 400
    time.sleep(0.5)
    n_auth = asyncio.run(_count_recent("auth_failure", "/api/admin/", since))
    n_save = asyncio.run(_count_recent("save_failure", "/api/admin/", since))
    assert n_auth == 0 and n_save == 0, (
        f"admin endpoint was logged: auth={n_auth} save={n_save}"
    )


def test_save_health_endpoint_exposes_split_counts():
    r = httpx.get(f"{BASE}/api/admin/save-health?hours=24", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "auth_failures" in body, "auth_failures missing from /admin/save-health"
    assert "save_failures" in body, "save_failures missing from /admin/save-health"
    assert isinstance(body["auth_failures"], int)
    assert isinstance(body["save_failures"], int)
    # Sum of parts <= total (there could be un-kinded legacy rows)
    assert body["auth_failures"] + body["save_failures"] <= body["total_failures"] + 5


def test_recent_rows_include_kind_field():
    # Generate a fresh auth failure so we know at least one recent row exists
    httpx.get(f"{BASE}/api/auth/me",
              headers={"Authorization": "Bearer iter54_marker_bogus"},
              timeout=10)
    time.sleep(0.5)
    r = httpx.get(f"{BASE}/api/admin/save-health?hours=1", timeout=10).json()
    recent = r.get("recent", [])
    assert recent, "no recent failures returned"
    # Every fresh row should have `kind` set
    kinds = [row.get("kind") for row in recent]
    assert any(k == "auth_failure" for k in kinds), f"no auth_failure kind in recent: {kinds}"


def test_frontend_dashboard_exposes_split_testids():
    with open("/app/frontend/src/pages/Dashboard.jsx") as f:
        content = f.read()
    for tid in ("save-health-auth-failures", "save-health-save-failures", "save-health-recent-kind-"):
        assert tid in content, f"testid {tid!r} missing from Dashboard.jsx"


def test_login_failure_toggle_off_suppresses_auth_alert():
    """When alert_types.login_failure=False AND save_failure=False, auth
    failures must NOT trigger a save-health alert even if threshold is 1."""
    marker_since = datetime.now(timezone.utc).isoformat()
    # Ack pre-existing alerts so we can filter for 'new' ones
    async def _ack_all():
        import motor.motor_asyncio
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ.get("MONGO_URL"))
        db = c[os.environ.get("DB_NAME")]
        await db.save_health_alerts.update_many({"acknowledged": {"$ne": True}},
                                                {"$set": {"acknowledged": True}})
        c.close()
    asyncio.run(_ack_all())
    # Disable both save + login failure alert types
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 1, "window_hours": 1, "cooldown_min": 5, "enabled": True,
                    "alert_types": {"save_failure": False, "login_failure": False,
                                    "deployment_failure": True, "trip_save_failure": True,
                                    "invoice_save_failure": True},
                    "email_recipients": ["bitumentra@gmail.com"], "channels": ["email"]},
              timeout=10)
    # Generate 3 auth failures
    for _ in range(3):
        httpx.get(f"{BASE}/api/auth/me",
                  headers={"Authorization": f"Bearer iter54_toggle_off_{uuid.uuid4().hex[:6]}"},
                  timeout=10)
        time.sleep(0.2)
    time.sleep(1.5)
    alerts = httpx.get(f"{BASE}/api/admin/save-health/alerts?unacknowledged_only=true&limit=5",
                       timeout=10).json()["alerts"]
    assert not alerts, f"alert fired despite login_failure=False and save_failure=False: {alerts}"
    # Restore all-on with sane threshold
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 20,
                    "alert_types": {"save_failure": True, "login_failure": True,
                                    "deployment_failure": True, "trip_save_failure": True,
                                    "invoice_save_failure": True}},
              timeout=10)
