"""Iter126b · Frontend Idempotency wiring — end-to-end verification.

Backend-only tests (via `requests`) can't drive the browser axios interceptor
directly, but we can enforce the CONTRACT the frontend must honour:

  1. The Bucket-B whitelist embedded in `/app/frontend/src/api.js` MUST
     mirror `/app/backend/idempotency.py`. Any drift is caught immediately
     by comparing the two literal pattern lists.
  2. Simulating the frontend's request-time behaviour (send the SAME
     Idempotency-Key on two POSTs to a Bucket-B endpoint) MUST NOT create
     a duplicate — this is the real-world "user double-clicked Save"
     scenario after Iter126b frontend wiring.
"""
from __future__ import annotations

import os
import re
import uuid
import pathlib
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR_BASE = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}


def _repo_file(*parts: str) -> pathlib.Path:
    """The container path when it exists, otherwise the same file in the repo.

    The deployed pod holds the tree at /app; a checkout does not. Resolving
    from __file__ lets the identical assertions run in both places.
    """
    deployed = pathlib.Path("/app").joinpath(*parts)
    if deployed.exists():
        return deployed
    return pathlib.Path(__file__).resolve().parents[2].joinpath(*parts)


def _block(text: str, start_marker: str, end_marker: str) -> str:
    """The source between start_marker and the first end_marker after it.

    Scoping the search to the declaration matters: api.js holds other arrays
    of regex literals (_APPROVAL_ROUTE_MATCHERS among them) whose entries look
    identical to a file-wide regex scan. Sweeping those in inflated the count
    and produced phantom "frontend only" drift that no change to the Bucket-B
    list could ever clear.
    """
    i = text.index(start_marker)
    j = text.index(end_marker, i + len(start_marker))
    return text[i:j]


def test_frontend_bucket_b_mirrors_backend_bucket_b():
    """Frontend patterns (without /api prefix) must match backend patterns
    (with /api prefix). If they drift, a save on an endpoint the backend
    protects will silently skip the key on the client (creating duplicates
    on retry) — this test is the guard-rail."""
    fe_src = _repo_file("frontend", "src", "api.js").read_text(encoding="utf-8")
    be_src = _repo_file("backend", "idempotency.py").read_text(encoding="utf-8")

    # Only the two Bucket-B declarations — never the rest of either file.
    fe = _block(fe_src, "export const BUCKET_B_POST = [", "];")
    be = _block(be_src, "BUCKET_B_PATTERNS", ")]")

    # Frontend patterns look like `/^\/trips$/`,
    fe_matches = re.findall(r"/\^\\/(.+?)\$/,", fe)
    # Backend patterns look like  `r"^/api/trips$"`,
    be_matches = re.findall(r'r"\^/api/(.+?)\$"', be)

    # Frontend patterns use JS-escaped forward-slashes (`\/`); strip them.
    fe_norm = {p.replace("\\/", "/") for p in fe_matches}
    be_norm = set(be_matches)

    assert fe_norm == be_norm, (
        f"Bucket-B whitelist drift detected!\n"
        f"  frontend only: {sorted(fe_norm - be_norm)}\n"
        f"  backend only:  {sorted(be_norm - fe_norm)}"
    )
    # Sanity: the locked count. 37 at Iter126b, plus the 15 Iter133
    # write endpoints the client was not keying until PR #3.
    assert len(fe_norm) == 52, f"expected 52 patterns, got {len(fe_norm)}"


def _first_customer_id() -> str:
    r = requests.get(f"{API}/customers", headers=HDR_BASE, timeout=10)
    r.raise_for_status()
    d = r.json()
    items = d.get("items", d) if isinstance(d, dict) else d
    return items[0]["id"]


def test_double_click_save_with_frontend_key_creates_one_row():
    """Simulates two rapid Save clicks that reuse the SAME axios config
    (post, retry). Frontend wiring guarantees the same key on both."""
    key = f"fe-doubleclick-{uuid.uuid4().hex[:16]}"
    vehicle = f"AP99FE{uuid.uuid4().hex[:4].upper()}"
    payload = {
        "customer_id": _first_customer_id(),
        "date": "2029-09-09",
        "vehicle_number": vehicle,
        "vehicle_type": "own",
        "tons": 12,
        "loaded_qty": 12,
        "unloaded_qty": 11.95,
        "freight_mode": "per_ton",
        "rate_per_ton": 900,
        "product_rate_per_mt": 40000,
        "from_location": "Kakinada",
        "to_location": "Vizag",
        "driver_name": "Iter126b FE Wiring",
    }
    h = {**HDR_BASE, "Idempotency-Key": key}

    r1 = requests.post(f"{API}/trips", headers=h, json=payload, timeout=15)
    r2 = requests.post(f"{API}/trips", headers=h, json=payload, timeout=15)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"], (
        "double-click Save with the same frontend-generated key must NOT "
        "produce two Trip rows"
    )
    assert r2.headers.get("x-idempotent-replay") == "1"

    # Verify the DB has only one row for the unique vehicle number.
    q = requests.get(f"{API}/trips", headers=HDR_BASE,
                     params={"vehicle_number": vehicle}, timeout=10)
    q.raise_for_status()
    rows = q.json().get("items", q.json()) if isinstance(q.json(), dict) else q.json()
    matches = [t for t in rows if t.get("vehicle_number") == vehicle]
    assert len(matches) == 1


def test_frontend_api_js_has_key_attach_hook():
    """Guards against a refactor that accidentally deletes the request
    interceptor's Idempotency-Key attachment block."""
    src = _repo_file("frontend", "src", "api.js").read_text(encoding="utf-8")
    assert '_isBucketBPost(cfg)' in src, "Bucket-B check missing from api.js"
    assert 'Idempotency-Key' in src, "Idempotency-Key header not attached in api.js"
    assert '_newUuid()' in src, "UUID generator not wired in api.js"
