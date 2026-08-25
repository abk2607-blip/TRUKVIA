"""Iter68 · Server-side Customer Search
- q param performs case-insensitive partial match on name, phone, gstin, customer_code
- limit / skip pagination envelope
- Tenant isolation (multi-company) — one company's customers must not leak into another
- `ids` force-includes specific customers (used by pickers to keep the currently-selected
  option visible even when it's outside the current search page)
- No `q` / `limit` / `skip` / `ids` params → legacy array shape preserved (backward compat)
- No duplicate customers in results
"""
import os, uuid, httpx, re
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = "test_session_bitumen_2026"
HDR = {"Authorization": f"Bearer {TOKEN}"}
UNIQUE = f"IT68_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=60).json()


def _mkcust(headers, name, **extra):
    payload = {"name": name, "phone": extra.get("phone", ""), "gstin": extra.get("gstin", ""), "state": extra.get("state", "Andhra Pradesh")}
    if "pan" in extra:
        payload["pan"] = extra["pan"]
    if "customer_code" in extra:
        payload["customer_code"] = extra["customer_code"]
    if "address" in extra:
        payload["address"] = extra["address"]
    return httpx.post(f"{BASE}/api/customers", json=payload, headers=headers, timeout=30).json()


# ---------------------------------------------------------------------------
# Legacy shape preserved when no params
# ---------------------------------------------------------------------------
def test_legacy_no_params_returns_array():
    r = httpx.get(f"{BASE}/api/customers", headers=HDR, timeout=60)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list), "legacy shape must be a JSON array"


# ---------------------------------------------------------------------------
# Paginated envelope when any of q/limit/skip/ids provided
# ---------------------------------------------------------------------------
def test_paginated_envelope_shape():
    r = httpx.get(f"{BASE}/api/customers?limit=5", headers=HDR, timeout=60)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    for k in ("items", "total", "has_more", "limit", "skip"):
        assert k in body
    assert len(body["items"]) <= 5


def test_limit_capped_at_200():
    r = httpx.get(f"{BASE}/api/customers?limit=9999", headers=HDR, timeout=60)
    body = r.json()
    assert body["limit"] == 200


# ---------------------------------------------------------------------------
# Search by name / phone / gstin / customer_code (case-insensitive partial)
# ---------------------------------------------------------------------------
def test_search_by_name_phone_gstin_and_code():
    cs = _companies()
    ha = {**HDR, "X-Company-Id": cs[0]["id"]}
    name = f"{UNIQUE}_Reddy_Traders"
    phone = f"9{uuid.uuid4().int % 10**9:09d}"
    gstin = "37" + uuid.uuid4().hex[:13].upper()
    code = f"CUST-{UNIQUE}"
    _mkcust(ha, name, phone=phone, gstin=gstin, customer_code=code)

    # Partial name — case-insensitive (fixture names need include_fixtures)
    r = httpx.get(f"{BASE}/api/customers?q={UNIQUE.lower()}&include_fixtures=true", headers=ha, timeout=30).json()
    assert r["total"] >= 1
    assert any(name in c["name"] for c in r["items"])

    # Partial phone
    r = httpx.get(f"{BASE}/api/customers?q={phone[:6]}&include_fixtures=true", headers=ha, timeout=30).json()
    assert r["total"] >= 1
    assert any(c.get("phone") == phone for c in r["items"])

    # Partial GSTIN (mid-string)
    r = httpx.get(f"{BASE}/api/customers?q={gstin[2:7]}&include_fixtures=true", headers=ha, timeout=30).json()
    assert r["total"] >= 1
    assert any(c.get("gstin") == gstin for c in r["items"])

    # Customer code partial
    r = httpx.get(f"{BASE}/api/customers?q={code[:8]}&include_fixtures=true", headers=ha, timeout=30).json()
    assert r["total"] >= 1
    assert any(c.get("customer_code") == code for c in r["items"])


def test_search_is_case_insensitive():
    cs = _companies()
    ha = {**HDR, "X-Company-Id": cs[0]["id"]}
    name = f"{UNIQUE}_CaseCheck"
    _mkcust(ha, name)
    r_lower = httpx.get(f"{BASE}/api/customers?q={name.lower()}&include_fixtures=true", headers=ha, timeout=30).json()
    r_upper = httpx.get(f"{BASE}/api/customers?q={name.upper()}&include_fixtures=true", headers=ha, timeout=30).json()
    assert r_lower["total"] >= 1 and r_upper["total"] >= 1
    assert any(c["name"] == name for c in r_lower["items"])
    assert any(c["name"] == name for c in r_upper["items"])


def test_search_regex_metachar_is_escaped():
    """User-supplied q must not blow up mongo regex — parens/dots should be treated as literals."""
    r = httpx.get(f"{BASE}/api/customers?q=(.*)", headers=HDR, timeout=30)
    assert r.status_code == 200
    # Just ensure no 500 and shape is envelope
    assert isinstance(r.json(), dict)


# ---------------------------------------------------------------------------
# No duplicates in results (with or without ids force-include)
# ---------------------------------------------------------------------------
def test_no_duplicates_in_results():
    r = httpx.get(f"{BASE}/api/customers?limit=100", headers=HDR, timeout=60).json()
    ids = [c["id"] for c in r["items"]]
    assert len(ids) == len(set(ids)), "duplicate customer ids present in single page"


def test_ids_param_force_includes_and_dedupes():
    cs = _companies()
    ha = {**HDR, "X-Company-Id": cs[0]["id"]}
    c1 = _mkcust(ha, f"{UNIQUE}_ForceMe1")
    c2 = _mkcust(ha, f"{UNIQUE}_ForceMe2")
    # Search for something that will not match c1/c2 to prove they are still returned
    r = httpx.get(
        f"{BASE}/api/customers",
        params={"q": "ZZZ_DEF_NOT_MATCH_XYZ", "ids": f"{c1['id']},{c2['id']}", "limit": 5, "include_fixtures": "true"},
        headers=ha, timeout=30,
    ).json()
    got_ids = [c["id"] for c in r["items"]]
    assert c1["id"] in got_ids and c2["id"] in got_ids
    assert len(got_ids) == len(set(got_ids)), "ids force-include must dedupe"


def test_ids_only_returns_just_those_customers():
    """Iter70 — When only `ids` is passed (no q, no pagination), the response
    must contain ONLY the requested customers, not first-page + ids."""
    cs = _companies()
    ha = {**HDR, "X-Company-Id": cs[0]["id"]}
    c1 = _mkcust(ha, f"{UNIQUE}_IdsOnly1")
    c2 = _mkcust(ha, f"{UNIQUE}_IdsOnly2")
    r = httpx.get(f"{BASE}/api/customers", params={"ids": f"{c1['id']},{c2['id']}"}, headers=ha, timeout=30).json()
    got = {c["id"] for c in r["items"]}
    assert got == {c1["id"], c2["id"]}, f"ids-only lookup polluted with extras: {got}"
    assert r["total"] == 2


def test_fixture_customers_hidden_by_default_in_paginated_browse():
    """Iter70 — Paginated browse (no q) must NOT return pytest fixture customers
    (names matching IT\\d+, TEST_, etc.). This keeps the demo tenant clean for
    real users. Fixtures still appear when `include_fixtures=true` is passed."""
    cs = _companies()
    ha = {**HDR, "X-Company-Id": cs[0]["id"]}
    fix_cust = _mkcust(ha, f"{UNIQUE}_HiddenTest")  # matches IT\\d+ regex
    # Browse without include_fixtures — must NOT show it
    r = httpx.get(f"{BASE}/api/customers?limit=200", headers=ha, timeout=30).json()
    got_ids = {c["id"] for c in r["items"]}
    assert fix_cust["id"] not in got_ids, "fixture customer leaked into default browse"
    # With include_fixtures=true, it can be found
    r2 = httpx.get(f"{BASE}/api/customers?limit=200&include_fixtures=true&q={UNIQUE}", headers=ha, timeout=30).json()
    assert any(c["id"] == fix_cust["id"] for c in r2["items"])


# ---------------------------------------------------------------------------
# Multi-company isolation — a search in Company A must never leak Company B
# ---------------------------------------------------------------------------
def test_tenant_isolation_across_companies():
    cs = _companies()
    if len(cs) < 2:
        # Create a second company
        cs2 = httpx.post(f"{BASE}/api/companies", json={"name": f"IsoCoB {UNIQUE}"}, headers=HDR, timeout=30).json()
        cs = _companies()

    ca, cb = cs[0], cs[1]
    ha = {**HDR, "X-Company-Id": ca["id"]}
    hb = {**HDR, "X-Company-Id": cb["id"]}

    marker = f"{UNIQUE}_TenantMark"
    a_cust = _mkcust(ha, f"{marker}_A")
    b_cust = _mkcust(hb, f"{marker}_B")

    # Search in company A — must NOT see B's customer
    ra = httpx.get(f"{BASE}/api/customers?q={marker}&include_fixtures=true", headers=ha, timeout=30).json()
    a_ids = {c["id"] for c in ra["items"]}
    assert a_cust["id"] in a_ids
    assert b_cust["id"] not in a_ids, "company A search leaked company B customer"

    # And vice-versa
    rb = httpx.get(f"{BASE}/api/customers?q={marker}&include_fixtures=true", headers=hb, timeout=30).json()
    b_ids = {c["id"] for c in rb["items"]}
    assert b_cust["id"] in b_ids
    assert a_cust["id"] not in b_ids, "company B search leaked company A customer"

    # Also: ids force-include must NOT cross-tenant — asking for A's id under B's headers should not return it
    rb2 = httpx.get(f"{BASE}/api/customers", params={"ids": a_cust["id"], "limit": 5}, headers=hb, timeout=30).json()
    assert a_cust["id"] not in {c["id"] for c in rb2["items"]}, "ids param must respect tenant isolation"


# ---------------------------------------------------------------------------
# Pagination — skip / has_more
# ---------------------------------------------------------------------------
def test_pagination_skip_and_has_more():
    r1 = httpx.get(f"{BASE}/api/customers?limit=5&skip=0", headers=HDR, timeout=30).json()
    r2 = httpx.get(f"{BASE}/api/customers?limit=5&skip=5", headers=HDR, timeout=30).json()
    assert r1["skip"] == 0 and r2["skip"] == 5
    ids1 = {c["id"] for c in r1["items"]}
    ids2 = {c["id"] for c in r2["items"]}
    # Pages should not overlap
    assert ids1.isdisjoint(ids2)
    if r1["total"] > 5:
        assert r1["has_more"] is True


# ---------------------------------------------------------------------------
# Empty query returns paginated results (does NOT dump entire DB)
# ---------------------------------------------------------------------------
def test_empty_query_still_paginates():
    r = httpx.get(f"{BASE}/api/customers?limit=50", headers=HDR, timeout=30).json()
    assert isinstance(r, dict)
    assert len(r["items"]) <= 50
