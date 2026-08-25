"""Iter127a · Master duplicate prevention — customer / vehicle / supplier.

Locked rules:
  Customer  · GSTIN hard 409, PAN hard 409 (when GSTIN empty), name/phone → soft
  Vehicle   · normalised vehicle_number hard 409
  Supplier  · GSTIN / PAN / normalised name hard 409, mobile → soft
Scope      · always per (user_id, company_id).
Override   · X-Duplicate-Override: allow + duplicate_override_reason (≥6 chars) +
             Owner/Admin role. Accountant/staff → 403.
"""
from __future__ import annotations

import os
import uuid
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _mk_gstin(prefix="27") -> str:
    """Deterministic 15-char GSTIN-shaped string per test."""
    tail = uuid.uuid4().hex[:13].upper()
    return f"{prefix}{tail}"[:15].ljust(15, "Z")


def _mk_pan() -> str:
    return f"ABCDE{uuid.uuid4().hex[:5].upper()}"[:10]


# ------------------------------------------------------------ Customer
def test_customer_gstin_duplicate_returns_409():
    gstin = _mk_gstin()
    r1 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": f"C1-{uuid.uuid4().hex[:6]}", "gstin": gstin,
    }, timeout=15)
    assert r1.status_code == 200, r1.text
    # Same GSTIN in different casing / spacing must still collide.
    r2 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": f"Different Name {uuid.uuid4().hex[:6]}",
        "gstin": f" {gstin.lower()} ",
    }, timeout=15)
    assert r2.status_code == 409, r2.text
    body = r2.json()["detail"]
    assert body["code"] == "duplicate_master"
    assert body["matched_field"] == "gstin"
    assert body["existing"]["id"] == r1.json()["id"]


def test_customer_pan_duplicate_only_when_gstin_absent():
    pan = _mk_pan()
    r1 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": f"CP1-{uuid.uuid4().hex[:6]}", "pan": pan,  # no GSTIN
    }, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": f"CP2-{uuid.uuid4().hex[:6]}", "pan": pan.lower(),
    }, timeout=15)
    assert r2.status_code == 409
    assert r2.json()["detail"]["matched_field"] == "pan"

    # If the second call provides a DIFFERENT GSTIN we still block on PAN?
    # No — PAN check runs only when GSTIN absent on the NEW payload. A fresh
    # GSTIN should bypass PAN-only detection.
    r3 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": f"CP3-{uuid.uuid4().hex[:6]}", "pan": pan, "gstin": _mk_gstin(),
    }, timeout=15)
    assert r3.status_code == 200


def test_customer_similar_name_or_shared_phone_is_NOT_blocked():
    name = f"AKB & Sons {uuid.uuid4().hex[:5]}"
    phone = "98" + str(uuid.uuid4().int)[:8]  # 10 numeric digits
    r1 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": name, "phone": phone,
    }, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/customers", headers=HDR, json={
        "name": f"{name} Branch-B", "phone": phone,
    }, timeout=15)
    assert r2.status_code == 200, r2.text
    soft = r2.json().get("soft_matches") or []
    assert any(s["matched_field"] == "phone" for s in soft), (phone, soft)


def test_customer_exact_name_match_returns_409_bypassable_by_header():
    """Iter127a UAT · Existing-name warning (soft-block, no role needed).

    First create → 200. Second create with the SAME normalised name
    (different casing / punctuation) → 409 matched_field=name. The user
    can bypass by resending with `X-Confirm-Name-Match: allow` — no reason,
    no Owner/Admin role required."""
    name = f"VIKRAMADITYA ENT {uuid.uuid4().hex[:6].upper()}"
    r1 = requests.post(f"{API}/customers", headers=HDR, json={"name": name}, timeout=15)
    assert r1.status_code == 200, r1.text

    # Different casing + punctuation → same name_norm → 409.
    r2 = requests.post(f"{API}/customers", headers=HDR,
                       json={"name": name.lower().replace(" ", ".  ")}, timeout=15)
    assert r2.status_code == 409, r2.text
    detail = r2.json()["detail"]
    assert detail["code"] == "duplicate_master"
    assert detail["matched_field"] == "name"
    assert detail["existing"]["id"] == r1.json()["id"]

    # Bypass with header — no reason, no role gate.
    r3 = requests.post(f"{API}/customers",
                       headers={**HDR, "X-Confirm-Name-Match": "allow"},
                       json={"name": name}, timeout=15)
    assert r3.status_code == 200, r3.text
    assert r3.json()["id"] != r1.json()["id"]


def test_customer_name_match_isolated_across_companies():
    companies = requests.get(f"{API}/companies", headers=HDR, timeout=10).json()
    companies = companies.get("items", companies) if isinstance(companies, dict) else companies
    if len(companies) < 2:
        import pytest as _pt
        _pt.skip("need at least 2 companies")
    name = f"ACME LOGISTICS {uuid.uuid4().hex[:6].upper()}"
    r1 = requests.post(f"{API}/customers",
                       headers={**HDR, "X-Company-Id": companies[0]["id"]},
                       json={"name": name}, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/customers",
                       headers={**HDR, "X-Company-Id": companies[1]["id"]},
                       json={"name": name}, timeout=15)
    assert r2.status_code == 200, r2.text  # different company → no name collision


def test_cross_company_isolation_customer():
    """Same GSTIN in a DIFFERENT company must not collide."""
    from_hdr = {**HDR}
    # Create a second company just for this test.
    co = requests.post(f"{API}/companies", headers=from_hdr,
                       json={"name": f"Iter127Co-{uuid.uuid4().hex[:6]}", "gstin": ""},
                       timeout=15)
    assert co.status_code == 200, co.text
    co2 = co.json()["id"]

    gstin = _mk_gstin()
    r1 = requests.post(f"{API}/customers", headers=from_hdr,
                       json={"name": f"IsoA-{uuid.uuid4().hex[:8]}", "gstin": gstin}, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/customers",
                       headers={**from_hdr, "X-Company-Id": co2},
                       json={"name": f"IsoB-{uuid.uuid4().hex[:8]}", "gstin": gstin}, timeout=15)
    assert r2.status_code == 200, r2.text  # different company scope


# ------------------------------------------------------------ Vehicle
def test_vehicle_normalisation_and_flags_duplicate():
    vn = f"AP{uuid.uuid4().hex[:6].upper()}TT"
    r1 = requests.post(f"{API}/vehicles", headers=HDR, json={
        "vehicle_number": vn, "vehicle_type": "own",
    }, timeout=15)
    assert r1.status_code == 200
    # Iter127a keeps Iter72 idempotent DATA behaviour for vehicles but flags
    # every duplicate hit explicitly so QuickAdd can toast the user.
    for variant in [f" {vn.lower()} ", f"{vn[:2]}-{vn[2:]}", f"{vn[:2]}.{vn[2:]}"]:
        r = requests.post(f"{API}/vehicles", headers=HDR, json={
            "vehicle_number": variant, "vehicle_type": "own",
        }, timeout=15)
        assert r.status_code == 200, (variant, r.text)
        body = r.json()
        assert body["id"] == r1.json()["id"]
        assert body.get("duplicate") is True
        assert body.get("matched_field") == "vehicle_number"


# ------------------------------------------------------------ Supplier
def test_supplier_gstin_and_name_duplicate_return_409():
    name = f"Iter127Sup-{uuid.uuid4().hex[:6]}"
    gstin = _mk_gstin()
    r1 = requests.post(f"{API}/suppliers", headers=HDR,
                       json={"name": name, "gst_in": gstin, "mobile": "9876543210"},
                       timeout=15)
    assert r1.status_code == 200, r1.text
    # Same GSTIN
    r2 = requests.post(f"{API}/suppliers", headers=HDR,
                       json={"name": f"Other-{uuid.uuid4().hex[:5]}", "gst_in": gstin.lower()},
                       timeout=15)
    assert r2.status_code == 409
    assert r2.json()["detail"]["matched_field"] == "gstin"
    # Same normalised name (no GSTIN)
    r3 = requests.post(f"{API}/suppliers", headers=HDR,
                       json={"name": name.upper()},
                       timeout=15)
    assert r3.status_code == 409
    assert r3.json()["detail"]["matched_field"] == "name"


def test_supplier_shared_mobile_is_soft_not_blocked():
    # Build a valid 10-digit numeric mobile (norm_phone requires 10+ digits).
    mobile = "98" + str(uuid.uuid4().int)[:8]
    r1 = requests.post(f"{API}/suppliers", headers=HDR,
                       json={"name": f"S1-{uuid.uuid4().hex[:5]}", "mobile": mobile},
                       timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/suppliers", headers=HDR,
                       json={"name": f"S2-{uuid.uuid4().hex[:5]}", "mobile": mobile},
                       timeout=15)
    assert r2.status_code == 200, r2.text
    soft = r2.json().get("soft_matches") or []
    assert any(s["matched_field"] == "mobile" for s in soft), (mobile, soft)


# ------------------------------------------------------------ Override
def test_owner_can_override_customer_gstin_duplicate_with_reason():
    gstin = _mk_gstin()
    r1 = requests.post(f"{API}/customers", headers=HDR,
                       json={"name": f"OrigCust-{uuid.uuid4().hex[:8]}", "gstin": gstin}, timeout=15)
    assert r1.status_code == 200

    # Missing reason → 409 stays.
    r = requests.post(f"{API}/customers",
                      headers={**HDR, "X-Duplicate-Override": "allow"},
                      json={"name": f"OverCust-{uuid.uuid4().hex[:8]}", "gstin": gstin}, timeout=15)
    assert r.status_code == 409

    # Reason present + Owner (demo user is owner) → 200.
    r = requests.post(f"{API}/customers",
                      headers={**HDR, "X-Duplicate-Override": "allow",
                               "X-Duplicate-Override-Reason": "Branch office - manual verified"},
                      json={"name": f"OverCust-{uuid.uuid4().hex[:8]}", "gstin": gstin},
                      timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["id"] != r1.json()["id"]


# ------------------------------------------------------------ Admin listing
def test_admin_duplicates_endpoint_lists_but_does_not_mutate():
    r = requests.get(f"{API}/admin/iter127-duplicates", headers=HDR, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("customers_gstin", "vehicles_number", "suppliers_gstin", "suppliers_name"):
        assert k in body, body
        assert isinstance(body[k], list)
