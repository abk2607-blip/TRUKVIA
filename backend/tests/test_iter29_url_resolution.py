"""Iter29: URL resolution helper — verify api.js maps static -> dynamic preview host,
and confirm static URL returns 404 (documenting the runtime fallback rationale)."""
import os
import re
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
STATIC_URL = "https://trip-billing-pro-1.preview.static.emergentagent.com"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}


def test_api_js_contains_static_mapping():
    """Source code must contain the static->dynamic host fallback."""
    path = "/app/frontend/src/api.js"
    with open(path) as f:
        src = f.read()
    assert "_resolveBackendUrl" in src
    assert ".preview.static.emergentagent.com" in src
    assert ".preview.emergentagent.com" in src
    # Sanity: the replace call
    assert re.search(r"replace\(\s*[\"']\.preview\.static\.emergentagent\.com[\"']", src)


def test_aichatbubble_uses_api_import():
    """AIChatBubble should import API from @/api (not use process.env directly)."""
    with open("/app/frontend/src/components/AIChatBubble.jsx") as f:
        src = f.read()
    assert "from \"@/api\"" in src or "from '@/api'" in src
    assert "API" in src
    # Should NOT reference process.env directly for URL
    assert "process.env.REACT_APP_BACKEND_URL" not in src


def test_dynamic_preview_auth_me_ok():
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=HDR, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json().get("email") == "owner@vbklogistics.test"


def test_static_preview_returns_404_documented():
    """Static URL has no backend proxy — 404 is expected. This documents WHY the
    runtime fallback in api.js is the correct fix."""
    try:
        r = requests.get(f"{STATIC_URL}/api/auth/me", headers=HDR, timeout=10)
        # Static origin either returns 404/5xx OR serves the SPA index.html (200 HTML)
        # as an SPA fallback — both indicate NO backend on this host, confirming
        # the runtime-fallback mapping in api.js is the right fix.
        ct = r.headers.get("content-type", "")
        is_no_backend = (
            r.status_code in (404, 502, 503, 504)
            or (r.status_code == 200 and "text/html" in ct)
        )
        assert is_no_backend, (
            f"Static origin unexpectedly served API JSON (status={r.status_code}, ct={ct})"
        )
    except requests.RequestException:
        pytest.skip("static preview URL unreachable")
