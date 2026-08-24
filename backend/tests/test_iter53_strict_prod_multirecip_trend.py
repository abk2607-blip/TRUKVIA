"""Iter53 — Strict-Mode-in-Prod + Multi-Recipient + Trend Chart tests.

Coverage:
  P1 Strict Mode in Production
   1. REGRESSION_GUARD_STRICT=1 is present in backend/.env
   2. /api/auth/health responds 200 when guard=pass (regardless of strict mode)
   3. /api/auth/health responds 503 with structured `detail` payload when strict + guard=fail
   4. Strict mode with guard=unknown returns 200 + a `warning` message (boot grace)

  P2 Multi-Recipient
   5. Alert config accepts >=1 email recipient and preserves order
   6. Test-alert dispatches to EACH recipient individually (verified by per-recipient sent/errors array)
   7. Frontend cfg-email-recipients-editor is a chip-based editor (via testid presence)

  P3 Guard Trend Chart
   8. /api/admin/deploy-history returns history rows with checked_at, status, failed_tests
   9. DeployHistoryPage renders under /admin/deploy-history (frontend testid trend-chart)
"""
import os
import asyncio
import pytest
import httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")


def test_strict_mode_env_var_present():
    """The .env must contain REGRESSION_GUARD_STRICT=1 for production."""
    with open("/app/backend/.env") as f:
        env = f.read()
    assert "REGRESSION_GUARD_STRICT=1" in env, "Strict mode not enabled in backend/.env"


def test_auth_health_gate_semantics():
    """Iter106 (approved) — `/api/auth/health` no longer 503s on strict+fail.
    The gate was intentionally removed to fix the persistent "REFRESHING"
    pill in the UI. The `regression_guard` block still exposes the cached
    verdict so the Deploy Readiness dashboard can surface it, but the
    endpoint itself reports liveness only.

    Contract now:
    - Always 200 (as long as DB ping succeeds).
    - `regression_guard` block present with status/strict_mode/consecutive.
    """
    r = httpx.get(f"{BASE}/api/auth/health", timeout=10)
    assert r.status_code == 200, f"auth/health must be 200 (liveness only); got {r.status_code}"
    d = r.json()
    guard = d.get("regression_guard", {})
    assert guard.get("status") in ("pass", "fail", "unknown")
    assert isinstance(guard.get("strict_mode"), bool)
    assert isinstance(int(guard.get("consecutive_failures", 0) or 0), int)


def test_deploy_readiness_writes_history():
    """Every guard run should append to the history collection (or already have entries)."""
    r = httpx.get(f"{BASE}/api/admin/deploy-history?limit=50", timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["count"] >= 1, "no history rows recorded"
    for row in d["history"]:
        assert "checked_at" in row
        assert row["status"] in ("pass", "fail")
        assert "failed_tests" in row


def test_alert_config_preserves_multiple_recipients():
    payload = {
        "email_recipients": [
            "owner@example.com",
            "ops@example.com",
            "manager@example.com",
        ],
        "channels": ["email"],
    }
    r = httpx.put(f"{BASE}/api/admin/save-health/alert-config", json=payload, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["email_recipients"] == payload["email_recipients"], \
        f"order not preserved: {d['email_recipients']} vs {payload['email_recipients']}"
    # Restore
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"email_recipients": ["bitumentra@gmail.com"], "channels": ["email"]}, timeout=10)


def test_alert_dispatch_hits_each_recipient():
    """Test-alert must attempt to send to EACH recipient individually — response
    should contain a `sent` OR `errors` entry per recipient (total count matches)."""
    recips = ["bitumentra@gmail.com", "b@undeliverable.invalid", "c@undeliverable.invalid"]
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"email_recipients": recips, "channels": ["email"]}, timeout=10)
    r = httpx.post(f"{BASE}/api/admin/save-health/alerts/test", timeout=30)
    assert r.status_code == 200
    d = r.json()
    email = d.get("email", {})
    attempted = len(email.get("sent", []) or []) + len(email.get("errors", []) or [])
    assert attempted == len(recips), f"expected {len(recips)} attempts, got {attempted}"
    # WhatsApp URL always present
    assert d.get("whatsapp_url", "").startswith("https://wa.me/")
    # Restore single recipient
    httpx.put(f"{BASE}/api/admin/save-health/alert-config",
              json={"email_recipients": ["bitumentra@gmail.com"], "channels": ["email"]}, timeout=10)


def test_trend_page_route_registered():
    """The frontend DeployHistoryPage is registered at /admin/deploy-history."""
    path = "/app/frontend/src/App.js"
    with open(path) as f:
        content = f.read()
    assert "DeployHistoryPage" in content
    assert '/admin/deploy-history' in content


def test_trend_page_file_exists_with_recharts():
    path = "/app/frontend/src/pages/DeployHistoryPage.jsx"
    assert os.path.exists(path)
    content = open(path).read()
    # Uses recharts + core Line chart
    for marker in ("LineChart", "ResponsiveContainer", "trend-chart", "kpi-pass-rate", "recent-runs-table"):
        assert marker in content, f"DeployHistoryPage missing {marker}"


def test_dashboard_links_to_trend_page():
    """The Deploy Guard tile links to the full trend page."""
    path = "/app/frontend/src/pages/Dashboard.jsx"
    content = open(path).read()
    assert "deploy-guard-trend-link" in content
    assert "/admin/deploy-history" in content
