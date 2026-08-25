"""Iter127a UAT (Feb 2026) · Multi-state GST registration warning.

Real-world requirement: large customers (e.g. MEGHA ENGINEERING) hold
separate GST registrations across states. Same NORMALISED NAME must NOT
hard-block — the user needs a soft warning + Continue Creating option.
Same NORMALISED GSTIN or PAN still remains a hard block.

Cases covered (verbatim from the UAT clarification):
  1. Same name + same GSTIN                        → hard 409 (gstin)
  2. Same name + different GSTIN / state           → 409 (name),
                                                     bypassable via
                                                     X-Confirm-Name-Match
  3. Same name across two ACTIVE companies         → no collision
  4. Similar (not exact) name                      → soft suggestion only
  5. Same PAN (no GSTIN on either side)            → hard 409 (pan)
  6. Existing-row payload carries `state` so the
     modal can help disambiguate multi-state GST.
"""
from __future__ import annotations

import os
import uuid
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _mk_gstin(state_code: str = "36") -> str:
    tail = uuid.uuid4().hex[:13].upper()
    return f"{state_code}{tail}"[:15].ljust(15, "Z")


def _mk_pan() -> str:
    return f"ABCDE{uuid.uuid4().hex[:5].upper()}"[:10]


# --------------------------------------------------------------------- 1
def test_same_name_same_gstin_is_hard_blocked():
    """GSTIN check runs BEFORE name check → matched_field must be 'gstin'."""
    name = f"MEGHA ENG {uuid.uuid4().hex[:6].upper()}"
    gstin = _mk_gstin("36")
    r1 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": name, "gstin": gstin, "state": "Telangana",
    }, timeout=15)
    assert r1.status_code == 200, r1.text

    r2 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": name, "gstin": gstin, "state": "Telangana",
    }, timeout=15)
    assert r2.status_code == 409, r2.text
    detail = r2.json()["detail"]
    assert detail["code"] == "duplicate_master"
    assert detail["matched_field"] == "gstin", \
        "same GSTIN must always be caught by GSTIN check (runs before name)"
    # Existing summary carries state now (Iter127a UAT clarification).
    assert detail["existing"].get("state") == "Telangana"


# --------------------------------------------------------------------- 2
def test_same_name_different_gstin_state_returns_warning_bypassable():
    """The multi-state GST branch case — user must be able to Continue Creating
    after acknowledging the warning."""
    name = f"MEGHA ENG {uuid.uuid4().hex[:6].upper()}"
    r1 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": name, "gstin": _mk_gstin("36"), "state": "Telangana",
    }, timeout=15)
    assert r1.status_code == 200

    # DIFFERENT GSTIN + DIFFERENT STATE, same name → soft warning (409 name).
    r2 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": name, "gstin": _mk_gstin("37"), "state": "Andhra Pradesh",
    }, timeout=15)
    assert r2.status_code == 409, r2.text
    detail = r2.json()["detail"]
    assert detail["matched_field"] == "name", \
        "same name + different GSTIN must produce name-warning (not gstin-block)"
    assert detail["existing"]["state"] == "Telangana", \
        "existing row must carry state so UI can show 'different state GST registration' hint"

    # User acknowledges + retries with confirm header → allowed.
    r3 = requests.post(
        f"{API}/customers",
        headers={**HDR, "X-Confirm-Name-Match": "allow"},
        json={"name": name, "gstin": _mk_gstin("37"), "state": "Andhra Pradesh"},
        timeout=15,
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["id"] != r1.json()["id"], "second registration must be a fresh row"
    assert r3.json()["state"] == "Andhra Pradesh"


# --------------------------------------------------------------------- 3
def test_same_name_isolated_across_companies():
    """Same normalised name across two ACTIVE companies must NOT collide —
    company isolation is stronger than the name rule."""
    companies_resp = requests.get(f"{API}/companies", headers=HDR, timeout=10).json()
    companies = companies_resp.get("items", companies_resp) if isinstance(companies_resp, dict) else companies_resp
    if len(companies) < 2:
        import pytest as _pt
        _pt.skip("need at least 2 companies to exercise isolation")
    name = f"MEGHA ENG {uuid.uuid4().hex[:6].upper()}"
    r1 = requests.post(
        f"{API}/customers",
        headers={**HDR, "X-Company-Id": companies[0]["id"]},
        json={"name": name, "gstin": _mk_gstin("36"), "state": "Telangana"},
        timeout=15,
    )
    assert r1.status_code == 200
    # Same name in a DIFFERENT company → no warning, no block.
    r2 = requests.post(
        f"{API}/customers",
        headers={**HDR, "X-Company-Id": companies[1]["id"]},
        json={"name": name, "gstin": _mk_gstin("37"), "state": "Andhra Pradesh"},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text


# --------------------------------------------------------------------- 4
def test_similar_but_not_exact_name_is_soft_suggestion_only():
    """Similar (but not identical) normalised names must NOT block."""
    base = f"MEGHA GRP {uuid.uuid4().hex[:6].upper()}"
    r1 = requests.post(f"{API}/customers", headers=HDR, json={"name": base}, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(
        f"{API}/customers",
        headers=HDR,
        json={"name": f"{base} Branch-B"},
        timeout=15,
    )
    # Different normalised name → NOT blocked.
    assert r2.status_code == 200, r2.text


# --------------------------------------------------------------------- 5
def test_same_pan_no_gstin_is_hard_blocked():
    pan = _mk_pan()
    r1 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": f"PanCoA {uuid.uuid4().hex[:6]}", "pan": pan,
    }, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": f"PanCoB {uuid.uuid4().hex[:6]}", "pan": pan,
    }, timeout=15)
    assert r2.status_code == 409
    assert r2.json()["detail"]["matched_field"] == "pan"


# --------------------------------------------------------------------- 6
def test_duplicate_existing_payload_shape_includes_state():
    """Contract check — the frontend Duplicate modal depends on `state`
    being present in the 409 payload so it can render the multi-state
    disambiguation row."""
    name = f"STATE PAYLOAD {uuid.uuid4().hex[:6].upper()}"
    requests.post(f"{API}/customers", headers=HDR, json={
        "name": name, "gstin": _mk_gstin("29"), "state": "Karnataka",
    }, timeout=15)
    r = requests.post(f"{API}/customers", headers=HDR, json={
        "name": name, "gstin": _mk_gstin("06"), "state": "Haryana",
    }, timeout=15)
    assert r.status_code == 409
    existing = r.json()["detail"]["existing"]
    for key in ("id", "name", "gstin", "state", "phone"):
        assert key in existing, f"existing payload missing '{key}': {existing}"
    assert existing["state"] == "Karnataka"
