"""Iter127b diagnostics beacon · REMOVED (P0 CLOSURE cleanup, Feb 2026).

After the 24-hour P0 "REFRESHING…" observation met acceptance criteria,
the user approved removal of the temporary diagnostic beacon endpoints.
This test file was previously verifying the beacon contract; it is now
repurposed as a **regression guard** that locks the removal — nothing
must silently re-expose the beacon endpoints in the future.

Still-shipped: `GET /api/diagnostics/build` — required by SilentRestartToast
build-drift detection. Its contract is covered in
`test_iter127b_health_endpoint_hardening.py` and re-asserted here.
"""
from __future__ import annotations

import os
import httpx

# Standard base_url discovery (mirrors other iter127b tests).
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    _env_path = "/app/frontend/.env"
    if os.path.exists(_env_path):
        for line in open(_env_path).read().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
                break
API = f"{BASE_URL.rstrip('/')}/api"


def test_beacon_post_endpoint_is_removed():
    """POST /api/diagnostics/silent-restart-probe must return 404 or 405."""
    r = httpx.post(f"{API}/diagnostics/silent-restart-probe", json={"phase": "x"}, timeout=10)
    assert r.status_code in (404, 405), (
        f"Beacon POST endpoint must be removed after P0 closure. "
        f"Got status={r.status_code} body={r.text[:200]}"
    )


def test_admin_probes_listing_is_removed():
    """GET /api/admin/silent-restart-probes must return 404 or 405."""
    r = httpx.get(f"{API}/admin/silent-restart-probes", timeout=10)
    assert r.status_code in (404, 405), (
        f"Admin probes listing must be removed after P0 closure. "
        f"Got status={r.status_code}"
    )


def test_build_endpoint_still_exposed():
    """GET /api/diagnostics/build MUST remain — SilentRestartToast still uses it."""
    r = httpx.get(f"{API}/diagnostics/build", timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert "build_id" in j
    assert "version" in j
    assert "server_ts" in j
    # Cost is negligible; no PII, no business data leaks.
    for key in j:
        assert key in {"build_id", "version", "server_ts"}, f"unexpected leak: {key}"


def test_source_guardrail_beacon_helpers_removed_from_router():
    """The diagnostics router file must not DEFINE the beacon-write helpers
    or route the beacon endpoints (mentioning them in the module docstring
    as removed items is fine — we check for CODE, not comments)."""
    src = open("/app/backend/routers/diagnostics.py").read()
    # Endpoint routing decorators must not exist.
    assert '@router.post("/diagnostics/silent-restart-probe")' not in src
    assert '@router.get("/admin/silent-restart-probes")' not in src
    # Helper function definitions must not exist.
    assert "def _capped_insert(" not in src
    assert "def _scrub(" not in src
    assert "_ALLOWED_KEYS =" not in src
    assert "_ALLOWED_KEYS:" not in src


def test_source_guardrail_frontend_beacon_removed():
    """SilentRestartToast must no longer POST beacons."""
    src = open("/app/frontend/src/components/SilentRestartToast.jsx").read()
    assert "BEACON_URL" not in src, "beacon URL constant leaked back in"
    assert "sendBeacon" not in src, "sendBeacon helper leaked back in"
    assert "silent-restart-probe" not in src, "beacon POST target leaked back in"
    # BUILD_URL must remain — build-drift check + auto-reload depend on it.
    assert "BUILD_URL" in src
    assert "diagnostics/build" in src
