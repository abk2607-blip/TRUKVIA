"""Iter77 — Dashboard hot-reload retry window verification.

Verifies:
- /api/dashboard, /api/reports/gst-summary, /api/invoices/overdue return 200 fast
- Spot-checks for iter68/72/74/76 features
"""
import os
import time
import requests
import pytest

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    # Load from frontend .env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE_URL = _load_backend_url()
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module", autouse=True)
def provision_demo_session():
    r = requests.post(f"{BASE_URL}/api/auth/demo-login", timeout=15)
    assert r.status_code in (200, 201), f"demo-login failed: {r.status_code} {r.text[:200]}"


def _timed_get(path, params=None):
    t0 = time.time()
    r = requests.get(f"{BASE_URL}{path}", headers=HEADERS, params=params, timeout=15)
    return r, time.time() - t0


class TestPrimaryEndpoints:
    def test_dashboard(self):
        r, dt = _timed_get("/api/dashboard")
        assert r.status_code == 200, r.text[:300]
        assert dt < 3.0, f"dashboard slow: {dt:.2f}s"
        data = r.json()
        assert isinstance(data, dict)

    def test_gst_summary(self):
        r, dt = _timed_get("/api/reports/gst-summary")
        assert r.status_code == 200, r.text[:300]
        assert dt < 3.0, f"gst-summary slow: {dt:.2f}s"

    def test_overdue_invoices(self):
        r, dt = _timed_get("/api/invoices/overdue", params={"days": 30})
        assert r.status_code == 200, r.text[:300]
        assert dt < 3.0, f"overdue slow: {dt:.2f}s"
        assert isinstance(r.json(), (list, dict))


class TestFeatureSpotChecks:
    def test_customers_list(self):
        # iter68 - customer search
        r = requests.get(f"{BASE_URL}/api/customers", headers=HEADERS, timeout=10)
        assert r.status_code == 200, r.text[:200]

    def test_suppliers_list(self):
        # iter74 - supplier
        r = requests.get(f"{BASE_URL}/api/suppliers", headers=HEADERS, timeout=10)
        assert r.status_code == 200, r.text[:200]

    def test_invoices_list(self):
        # iter76 - invoices
        r = requests.get(f"{BASE_URL}/api/invoices", headers=HEADERS, timeout=10)
        assert r.status_code == 200, r.text[:200]

    def test_auth_me(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=HEADERS, timeout=10)
        assert r.status_code == 200, r.text[:200]


class TestHotReloadRecovery:
    """Restart backend and confirm /api/dashboard recovers within 20s window."""

    def test_dashboard_recovers_after_restart(self):
        import subprocess
        # Baseline: dashboard 200
        r0, _ = _timed_get("/api/dashboard")
        assert r0.status_code == 200

        # Restart backend
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=True, capture_output=True)
        restart_t0 = time.time()

        # Poll — expect backend to be back within 20s
        recovered_at = None
        errors_seen = []
        while time.time() - restart_t0 < 25:
            try:
                r = requests.get(f"{BASE_URL}/api/dashboard", headers=HEADERS, timeout=3)
                if r.status_code == 200:
                    recovered_at = time.time() - restart_t0
                    break
                errors_seen.append(r.status_code)
            except Exception as e:
                errors_seen.append(type(e).__name__)
            time.sleep(0.75)

        assert recovered_at is not None, f"dashboard did not recover in 25s. errors={errors_seen[:20]}"
        print(f"Dashboard recovered in {recovered_at:.2f}s after restart. transient errors: {errors_seen[:15]}")
        # The retry window is ~20s; we assert recovery <20s so the frontend never shows the banner.
        assert recovered_at < 20, f"recovered_at={recovered_at:.2f}s exceeds 20s retry window"
