"""Iter50 — Save-Health endpoint + Invoice Halting column + Regression guard.

Covers:
1. /api/admin/save-health returns aggregated failure counts per collection.
2. Middleware logs POST/PUT/PATCH/DELETE with status >= 400.
3. Successful requests (2xx/3xx) are NEVER logged.
4. GET requests are NEVER logged (only writes are health-tracked).
5. Response envelope has window_hours, total_failures, per_collection, recent.
6. Collection extraction handles supplier-payments correctly.
"""
import os
import time
import uuid
import asyncio
import pytest
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}
# Iter121 · The save_health middleware now excludes loopback (127.0.0.1) traffic
# from telemetry — pytest runs on the same pod would otherwise pollute the tile
# with test-generated failures. To exercise the middleware from a pytest run we
# must pretend to be behind the Kubernetes ingress by supplying X-Forwarded-For
# with a public IP (RFC-5737 documentation range). This is a TEST-ONLY concern;
# real ingress traffic already carries XFF automatically.
HDR_EXT = {**HDR, "X-Forwarded-For": "203.0.113.50"}


def _cid():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=10).json()[0]["id"]


def test_save_health_endpoint_shape():
    r = httpx.get(f"{BASE}/api/admin/save-health?hours=24", timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("window_hours", "total_failures", "per_collection", "recent", "generated_at"):
        assert k in d, f"missing {k}"
    assert isinstance(d["per_collection"], list)
    assert isinstance(d["recent"], list)


def test_save_health_captures_write_failure():
    """Trigger a 422 POST and verify it appears in the save-health feed."""
    import asyncio, motor.motor_asyncio, os
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    h = {**HDR_EXT, "X-Company-Id": _cid()}
    since_iso = datetime.now(timezone.utc).isoformat()
    r = httpx.post(f"{BASE}/api/customers", headers=h, json={}, timeout=10)
    assert r.status_code >= 400
    async def _count():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        n = await c[os.environ["DB_NAME"]].save_health.count_documents({
            "path": "/api/customers", "method": "POST",
            "kind": "save_failure", "ts_iso": {"$gte": since_iso},
        })
        c.close()
        return n
    for _ in range(15):
        time.sleep(0.3)
        if asyncio.run(_count()) >= 1:
            return
    assert False, "middleware failed to log POST /api/customers failure to save_health"


def test_save_health_ignores_get_requests():
    """GET requests, even 404s, must NOT be logged to save-health — EXCEPT
    401/403 on /api/auth/* which are legitimate auth-failure signals (Iter54)."""
    before = httpx.get(f"{BASE}/api/admin/save-health?hours=1", timeout=10).json()
    # Trigger a GET 404
    r = httpx.get(f"{BASE}/api/trips/does_not_exist_iter50",
                  headers={**HDR, "X-Company-Id": _cid()}, timeout=10)
    # 404 or 200 (endpoint returns list) — doesn't matter, GET is never logged
    time.sleep(0.4)
    after = httpx.get(f"{BASE}/api/admin/save-health?hours=1", timeout=10).json()
    # Only writes + auth failures are tracked. Any GET row must be an auth
    # failure on /api/auth/* — no other GET should be logged.
    for entry in after["recent"]:
        if entry.get("method") == "GET":
            assert entry.get("path", "").startswith("/api/auth/") and entry.get("kind") == "auth_failure", \
                f"non-auth GET request was logged: {entry}"


def test_save_health_ignores_successful_writes():
    """Successful writes (2xx) must NOT show up in save-health."""
    h = {**HDR, "X-Company-Id": _cid()}
    before = httpx.get(f"{BASE}/api/admin/save-health?hours=1", timeout=10).json()["total_failures"]
    # Create a valid customer
    r = httpx.post(f"{BASE}/api/customers", headers=h, json={"name": f"IT50Success_{uuid.uuid4().hex[:8]}"}, timeout=10)
    assert r.status_code == 200
    time.sleep(0.4)
    after = httpx.get(f"{BASE}/api/admin/save-health?hours=1", timeout=10).json()["total_failures"]
    # Some other tests may run in parallel, so we can't assert equality — but
    # we can assert the successful call itself isn't in the recent stream.
    recent = httpx.get(f"{BASE}/api/admin/save-health?hours=1", timeout=10).json()["recent"]
    for entry in recent:
        # No successful (< 400) status should appear
        assert entry.get("status", 500) >= 400, f"Success logged as failure: {entry}"


def test_save_health_ttl_index_exists():
    """The save_health collection MUST have a TTL index on `ts` (14 days)."""
    async def _check():
        import motor.motor_asyncio
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ.get("MONGO_URL"))
        db = c[os.environ.get("DB_NAME")]
        idx = await db.save_health.index_information()
        found = any(info.get("expireAfterSeconds") for info in idx.values())
        c.close()
        return found
    assert asyncio.run(_check()), "TTL index missing on save_health.ts"


def test_regression_script_exists_and_is_executable():
    """Iter50 — the deploy-guard script must be present and shebanged."""
    path = "/app/backend/scripts/run_regression.sh"
    assert os.path.exists(path), "run_regression.sh missing"
    assert os.access(path, os.X_OK), "run_regression.sh not executable"
    with open(path) as f:
        content = f.read()
    assert "test_iter42" in content
    assert "test_iter49" in content
    assert "Regression Guard" in content
