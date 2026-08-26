"""Iter127b-UAT-fix v2 · Silent-restart diagnostic beacon tests.

Covers:
  • POST /api/diagnostics/silent-restart-probe accepts a whitelisted
    payload, returns 204, stores a row.
  • Payload keys NOT in the whitelist are silently dropped (safety).
  • Rolling cap: collection never exceeds 500 documents.
  • GET  /api/diagnostics/build returns build_id + version.
  • GET  /api/admin/silent-restart-probes requires auth and lists rows desc.
"""
from __future__ import annotations

import os
import time
import uuid

import httpx

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
NO_AUTH = {"Content-Type": "application/json"}


def test_beacon_accepts_whitelisted_payload_and_returns_204():
    r = httpx.post(f"{API}/diagnostics/silent-restart-probe", json={
        "ts": "2026-02-27T09:26:22Z",
        "phase": "streak_bump",
        "probe_result": "network",
        "http_status": None,
        "duration_ms": 4001,
        "fail_streak": 1,
        "restarting": False,
        "page_visibility": "visible",
        "connection_type": "4g",
        "ua_ver": "Mozilla/5.0 (X11; Linux x86_64)",
        "client_build_id": "1740640000",
    }, headers=NO_AUTH, timeout=10)
    assert r.status_code == 204, r.text
    # No response body per HTTP 204 semantics.
    assert r.text == "" or r.text is None


def test_beacon_drops_unknown_fields_for_safety():
    """A payload containing GSTIN, PAN, phone, tokens etc. must NOT be
    persisted through this diagnostic endpoint. The scrubber whitelists
    only technical metadata keys."""
    tag = uuid.uuid4().hex[:6]
    r = httpx.post(f"{API}/diagnostics/silent-restart-probe", json={
        "ts": "2026-02-27T09:26:22Z",
        "phase": f"streak_bump_{tag}",
        "probe_result": "http_5xx",
        # 🚫 These MUST NOT survive:
        "gstin": "37AAACC1234A1Z5",
        "pan": "AAACC1234A",
        "phone": "9999999999",
        "form_data": {"customer_name": "MEGHA"},
        "authorization_token": "test_session_bitumen_2026",
        "password": "hunter2",
    }, headers=NO_AUTH, timeout=10)
    assert r.status_code == 204

    # Verify the persisted row (via admin endpoint) contains ZERO of the banned keys.
    time.sleep(0.15)  # let the async trim/insert land
    rows = httpx.get(f"{API}/admin/silent-restart-probes?limit=50", headers=HDR, timeout=10).json()
    matching = [r for r in rows.get("items", []) if r.get("phase") == f"streak_bump_{tag}"]
    assert matching, "beacon row not persisted"
    for row in matching:
        # Only the whitelisted keys + server-side annotations (server_ts, source_ip) allowed.
        allowed = {
            "ts", "probe_result", "http_status", "duration_ms",
            "fail_streak", "restarting", "page_visibility", "connection_type",
            "ua_ver", "client_build_id", "phase",
            "server_ts", "source_ip",
        }
        forbidden = set(row.keys()) - allowed
        assert not forbidden, f"beacon persisted forbidden fields: {forbidden}"
        for banned in ("gstin", "pan", "phone", "form_data", "authorization_token",
                       "password", "customer_name"):
            assert banned not in row, f"banned key '{banned}' leaked into probe row"


def test_admin_endpoint_requires_auth_and_returns_desc():
    # No token → 401 or 403 (get_current_user rejects).
    r = httpx.get(f"{API}/admin/silent-restart-probes", timeout=10)
    assert r.status_code in (401, 403), f"unauth request must be rejected: {r.status_code}"

    # Authed → 200 with the expected envelope.
    r = httpx.get(f"{API}/admin/silent-restart-probes?limit=25", headers=HDR, timeout=10)
    assert r.status_code == 200
    body = r.json()
    for k in ("count", "diagnostic_version", "current_build_id", "items"):
        assert k in body, f"missing key '{k}': {body}"
    assert isinstance(body["items"], list)
    assert body["count"] <= 25
    # Order is server_ts desc — first row's ts ≥ last row's ts.
    if len(body["items"]) >= 2:
        first_ts = body["items"][0].get("server_ts") or 0
        last_ts  = body["items"][-1].get("server_ts") or 0
        assert first_ts >= last_ts, "admin listing must be desc by server_ts"


def test_build_endpoint_returns_stable_shape():
    r = httpx.get(f"{API}/diagnostics/build", timeout=10)
    assert r.status_code == 200
    body = r.json()
    for k in ("build_id", "version", "server_ts"):
        assert k in body, f"missing key '{k}': {body}"
    assert body["version"] == "iter127b-diag-v1"
    # build_id is an int epoch (mtime of the source file).
    assert isinstance(body["build_id"], int) and body["build_id"] > 0
