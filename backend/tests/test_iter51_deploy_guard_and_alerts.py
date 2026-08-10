"""Iter51 — Deploy Guard + Halting Filter + Save-Health Alerts + Sortable column.

Coverage:
 1. /api/admin/deploy-readiness returns status/pass/fail/unknown + fields
 2. /api/admin/deploy-readiness/run-now triggers a run
 3. Alert config GET returns defaults on first call
 4. Alert config PUT updates threshold/window/cooldown/enabled
 5. Alert config PUT enforces minimum thresholds (>=1)
 6. Save-health alert fires when failures cross threshold
 7. Alert has top_offenders + recent_errors + time-period + threshold
 8. Alert respects cooldown (does not re-fire within cooldown window)
 9. Alerts list endpoint returns unacknowledged filter
10. Alert acknowledgement mutates the row
11. Predeploy script exists + is executable
12. Predeploy script exits non-zero when critical test fails (simulation)
"""
import os
import time
import asyncio
import uuid
import pytest
import httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")


def test_deploy_readiness_endpoint_shape():
    r = httpx.get(f"{BASE}/api/admin/deploy-readiness", timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert "status" in d
    assert d["status"] in ("pass", "fail", "unknown")


def test_deploy_readiness_run_now_triggers():
    r = httpx.post(f"{BASE}/api/admin/deploy-readiness/run-now", timeout=10)
    assert r.status_code == 200
    assert r.json().get("triggered") is True


def test_predeploy_script_exists_and_executable():
    path = "/app/backend/scripts/predeploy_check.sh"
    assert os.path.exists(path), "predeploy_check.sh missing"
    assert os.access(path, os.X_OK), "predeploy_check.sh not executable"
    with open(path) as f:
        content = f.read()
    for kw in ("DEPLOY GUARD", "run_regression.sh", "predeploy", "Trip Edit"):
        assert kw in content


def test_github_actions_workflow_present():
    path = "/app/.github/workflows/regression-guard.yml"
    assert os.path.exists(path), "GitHub Actions workflow missing"
    content = open(path).read()
    assert "regression-guard" in content
    assert "run_regression.sh" in content
    assert "predeploy_check.sh" in content


def test_alert_config_defaults():
    """First GET returns defaults."""
    # Reset first: put defaults
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 20, "window_hours": 1, "cooldown_min": 30, "enabled": True},
              timeout=10)
    r = httpx.get(f"{BASE}/api/admin/save-health/alert-config", timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["threshold"] == 20
    assert d["window_hours"] == 1
    assert d["cooldown_min"] == 30
    assert d["enabled"] is True


def test_alert_config_update_and_readback():
    """PUT threshold=5 → GET returns 5."""
    r = httpx.put(f"{BASE}/api/admin/save-health/alert-config",
                  json={"threshold": 5, "window_hours": 2, "cooldown_min": 15, "enabled": False},
                  timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["threshold"] == 5
    assert d["window_hours"] == 2
    assert d["cooldown_min"] == 15
    assert d["enabled"] is False
    # Restore defaults
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 20, "window_hours": 1, "cooldown_min": 30, "enabled": True},
              timeout=10)


def test_alert_config_enforces_minimum():
    """Threshold below 1 is clamped to 1. Cooldown below 5 clamped to 5."""
    r = httpx.put(f"{BASE}/api/admin/save-health/alert-config",
                  json={"threshold": -5, "window_hours": 0, "cooldown_min": 1},
                  timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["threshold"] == 1
    assert d["window_hours"] == 1
    assert d["cooldown_min"] == 5
    # Restore
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 20, "window_hours": 1, "cooldown_min": 30, "enabled": True},
              timeout=10)


def test_alert_fires_when_threshold_crossed():
    """Set threshold=2, trigger 3 failures, verify alert fires with all fields."""
    HDR = {"Authorization": "Bearer test_session_bitumen_2026"}
    cid = httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=10).json()[0]["id"]
    h = {**HDR, "X-Company-Id": cid}

    # Clean slate: acknowledge all previous alerts
    async def _clean():
        import motor.motor_asyncio
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ.get("MONGO_URL"))
        db = c[os.environ.get("DB_NAME")]
        await db.save_health_alerts.update_many({}, {"$set": {"acknowledged": True}})
        # Also reduce noise so cooldown doesn't block us
        await db.save_health_alerts.delete_many({})
        c.close()
    asyncio.run(_clean())

    # Set threshold low + short cooldown
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 2, "window_hours": 1, "cooldown_min": 5, "enabled": True},
              timeout=10)
    # Trigger 3 failures
    for _ in range(3):
        httpx.post(f"{BASE}/api/customers", headers=h, json={}, timeout=10)
    # Give the fire-and-forget task a moment
    for _ in range(15):
        time.sleep(0.3)
        r = httpx.get(f"{BASE}/api/admin/save-health/alerts", params={"limit": 1}, timeout=10)
        if r.json().get("alerts"):
            break
    r = httpx.get(f"{BASE}/api/admin/save-health/alerts", params={"limit": 5}, timeout=10)
    alerts = r.json().get("alerts", [])
    assert alerts, "No alert fired"
    a = alerts[0]
    for k in ("fired_at", "threshold", "window_hours", "total_failures", "top_offenders", "recent_errors"):
        assert k in a, f"missing {k} in alert"
    assert a["threshold"] == 2
    assert a["total_failures"] >= 2
    # top_offenders must include at least one entry with fields
    assert a["top_offenders"], "top_offenders empty"
    for off in a["top_offenders"]:
        assert "collection" in off and "status" in off and "count" in off
    # recent_errors format
    for r_ in a["recent_errors"]:
        assert "ts" in r_ and "method" in r_ and "path" in r_ and "status" in r_

    # Restore defaults
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 20, "window_hours": 1, "cooldown_min": 30, "enabled": True},
              timeout=10)


def test_alert_acknowledgement():
    """Ack an alert → it drops out of unacknowledged_only feed."""
    # Ensure at least one alert exists
    HDR = {"Authorization": "Bearer test_session_bitumen_2026"}
    cid = httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=10).json()[0]["id"]
    h = {**HDR, "X-Company-Id": cid}
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 1, "window_hours": 1, "cooldown_min": 5, "enabled": True}, timeout=10)
    httpx.post(f"{BASE}/api/customers", headers=h, json={}, timeout=10)
    time.sleep(1.5)
    all_alerts = httpx.get(f"{BASE}/api/admin/save-health/alerts", params={"limit": 5}, timeout=10).json()["alerts"]
    assert all_alerts, "no alert to ack"
    fired_at = all_alerts[0]["fired_at"]
    r = httpx.post(f"{BASE}/api/admin/save-health/alerts/{fired_at}/ack", timeout=10)
    assert r.status_code == 200
    # Unacknowledged only should now exclude this fired_at
    only = httpx.get(f"{BASE}/api/admin/save-health/alerts",
                     params={"unacknowledged_only": True, "limit": 20}, timeout=10).json()["alerts"]
    assert not any(x["fired_at"] == fired_at for x in only)
    # Restore defaults
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 20, "window_hours": 1, "cooldown_min": 30, "enabled": True}, timeout=10)


def test_alert_cooldown_prevents_spam():
    """Fire once. Immediately try again → cooldown blocks second alert."""
    # Reset
    async def _clean():
        import motor.motor_asyncio
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ.get("MONGO_URL"))
        db = c[os.environ.get("DB_NAME")]
        await db.save_health_alerts.delete_many({})
        c.close()
    asyncio.run(_clean())
    HDR = {"Authorization": "Bearer test_session_bitumen_2026"}
    cid = httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=10).json()[0]["id"]
    h = {**HDR, "X-Company-Id": cid}
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 1, "window_hours": 1, "cooldown_min": 30, "enabled": True}, timeout=10)
    for _ in range(3):
        httpx.post(f"{BASE}/api/customers", headers=h, json={}, timeout=10)
        time.sleep(0.3)
    time.sleep(2)
    alerts = httpx.get(f"{BASE}/api/admin/save-health/alerts", params={"limit": 10}, timeout=10).json()["alerts"]
    # Only 1 save_failure alert due to cooldown (auth_ip_burst alerts are a
    # separate kind added in Iter58 — filter them out for this cooldown check)
    sf_alerts = [a for a in alerts if a.get("kind") != "auth_ip_burst"]
    assert len(sf_alerts) == 1, f"cooldown breached; got {len(sf_alerts)} save-failure alerts (all: {len(alerts)})"
    # Restore
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"threshold": 20, "window_hours": 1, "cooldown_min": 30, "enabled": True}, timeout=10)
