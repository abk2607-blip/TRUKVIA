"""Iter57 — Saved Filter Views (P1), Trip Export (P1), Auth Drill-Down (P2), Sparkline (P3)."""
import os
import uuid
import pytest
import httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = "test_session_bitumen_2026"
HDR = {"Authorization": f"Bearer {TOKEN}"}
UNIQUE = f"IT57_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=30).json()


def _cid():
    return _companies()[0]["id"]


def _h(cid=None):
    return {**HDR, "X-Company-Id": cid or _cid()}


# ============================================================
# P1a — Saved Filter Views
# ============================================================

def test_saved_filter_crud():
    h = _h()
    name = f"View_{UNIQUE}"
    payload = {"name": name, "filter_state": {"date_from": "2026-01-01", "q": "Kondapalli"}}
    r = httpx.post(f"{BASE}/api/saved-trip-filters", headers=h, json=payload, timeout=30)
    assert r.status_code == 200
    view = r.json()
    assert view["name"] == name
    assert view["filter_state"] == payload["filter_state"]
    assert view["id"].startswith("sf")
    # List includes it
    lst = httpx.get(f"{BASE}/api/saved-trip-filters", headers=h, timeout=30).json()
    assert any(v["id"] == view["id"] for v in lst)
    # Delete
    d = httpx.delete(f"{BASE}/api/saved-trip-filters/{view['id']}", headers=h, timeout=30)
    assert d.status_code == 200
    lst2 = httpx.get(f"{BASE}/api/saved-trip-filters", headers=h, timeout=30).json()
    assert not any(v["id"] == view["id"] for v in lst2), "saved view should be deleted"


def test_saved_filter_company_isolation():
    """A view saved in Company A must NEVER appear in Company B."""
    comps = _companies()
    if len(comps) < 2:
        pytest.skip("need 2+ companies")
    cid_a, cid_b = comps[0]["id"], comps[1]["id"]
    r = httpx.post(f"{BASE}/api/saved-trip-filters", headers=_h(cid_a),
                   json={"name": f"IsolTest_{UNIQUE}", "filter_state": {"q": "abc"}}, timeout=30)
    view = r.json()
    try:
        # Listed in A
        lst_a = httpx.get(f"{BASE}/api/saved-trip-filters", headers=_h(cid_a), timeout=30).json()
        assert any(v["id"] == view["id"] for v in lst_a)
        # NOT listed in B
        lst_b = httpx.get(f"{BASE}/api/saved-trip-filters", headers=_h(cid_b), timeout=30).json()
        assert not any(v["id"] == view["id"] for v in lst_b), \
            "saved view leaked from Company A to Company B"
        # B cannot delete A's view
        d = httpx.delete(f"{BASE}/api/saved-trip-filters/{view['id']}", headers=_h(cid_b), timeout=30)
        assert d.status_code == 404, "Company B was able to delete Company A's saved view"
    finally:
        httpx.delete(f"{BASE}/api/saved-trip-filters/{view['id']}", headers=_h(cid_a), timeout=30)


def test_saved_filter_requires_name():
    r = httpx.post(f"{BASE}/api/saved-trip-filters", headers=_h(),
                   json={"name": "", "filter_state": {}}, timeout=30)
    assert r.status_code in (400, 422), "empty name should be rejected"


# ============================================================
# P1b — Trip Export (CSV / XLSX)
# ============================================================

def test_export_csv_smoke():
    r = httpx.get(f"{BASE}/api/trips/export", headers=_h(),
                  params={"format": "csv", "date_from": "2026-01-01", "date_to": "2026-12-31"},
                  timeout=60)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    # First line is header row
    header = body.splitlines()[0]
    for col in ("date", "trip_number", "lr_number", "customer", "vehicle_number",
                "halting_amount", "freight_amount", "profit"):
        assert col in header, f"column {col!r} missing from CSV header: {header}"
    # Content-Disposition includes a filename
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd and "trips_export_" in cd


def test_export_xlsx_smoke():
    r = httpx.get(f"{BASE}/api/trips/export", headers=_h(),
                  params={"format": "xlsx"}, timeout=60)
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "spreadsheetml" in ct or "openxml" in ct, f"unexpected content-type: {ct}"
    assert r.content[:2] == b"PK", "XLSX response is not a valid ZIP-based XLSX file"


def test_export_respects_filters():
    """Export must contain ONLY the trips that match the filter."""
    # List trips with a narrow date to get expected count
    list_r = httpx.get(f"{BASE}/api/trips", headers=_h(),
                      params={"date_from": "2026-08-01", "date_to": "2026-08-10", "limit": 500},
                      timeout=60)
    expected = int(list_r.headers.get("x-total-count", "0"))
    exp_r = httpx.get(f"{BASE}/api/trips/export", headers=_h(),
                     params={"format": "csv", "date_from": "2026-08-01", "date_to": "2026-08-10"},
                     timeout=60)
    lines = exp_r.content.decode("utf-8-sig").splitlines()
    row_count = len(lines) - 1  # minus header
    # export caps at 10k, so within cap it should equal expected
    if expected <= 10000:
        assert row_count == expected, f"CSV row count {row_count} != listing total {expected}"


def test_export_company_isolation():
    """Export in Company A must not include Company B trips."""
    comps = _companies()
    if len(comps) < 2:
        pytest.skip("need 2+ companies")
    cid_a, cid_b = comps[0]["id"], comps[1]["id"]
    r_a = httpx.get(f"{BASE}/api/trips/export", headers=_h(cid_a), params={"format": "csv"}, timeout=60)
    r_b = httpx.get(f"{BASE}/api/trips/export", headers=_h(cid_b), params={"format": "csv"}, timeout=60)
    rows_a = r_a.content.decode("utf-8-sig").splitlines()[1:]
    rows_b = r_b.content.decode("utf-8-sig").splitlines()[1:]
    # If both have data, they should not share trip_number values (col index 1)
    def trip_nums(rows):
        out = set()
        for row in rows[:200]:
            parts = row.split(",")
            if len(parts) > 1 and parts[1]:
                out.add(parts[1])
        return out
    tn_a, tn_b = trip_nums(rows_a), trip_nums(rows_b)
    if tn_a and tn_b:
        assert tn_a.isdisjoint(tn_b), "Company A and B export shared trip numbers — isolation broken"


# ============================================================
# P2 — Auth Failure Drill-Down
# ============================================================

def test_auth_failures_endpoint_shape():
    # Trigger a fresh auth failure so there's at least one row to drill into
    httpx.get(f"{BASE}/api/auth/me",
              headers={"Authorization": f"Bearer iter57_drill_bogus_{uuid.uuid4().hex[:6]}"},
              timeout=15)
    import time; time.sleep(0.5)
    r = httpx.get(f"{BASE}/api/admin/save-health/auth-failures", params={"hours": 24, "limit": 20}, timeout=30)
    assert r.status_code == 200
    b = r.json()
    for k in ("window_hours", "count", "top_ips", "items", "generated_at"):
        assert k in b, f"missing key {k!r}"
    assert isinstance(b["items"], list)
    assert isinstance(b["top_ips"], list)
    if b["items"]:
        row = b["items"][0]
        for k in ("ts_iso", "method", "path", "status", "kind"):
            assert k in row, f"item missing key {k!r}: {row}"
        # Row MUST NOT contain any sensitive fields
        for banned in ("authorization", "Authorization", "cookie", "Cookie",
                       "token", "session_token", "password", "auth_header"):
            assert banned not in row, f"drill-down row exposes sensitive field {banned!r}: {row}"
        assert row["kind"] == "auth_failure"
        assert row["path"].startswith("/api/auth/")


def test_auth_drill_returns_only_auth_failures():
    r = httpx.get(f"{BASE}/api/admin/save-health/auth-failures", params={"hours": 24, "limit": 50}, timeout=30)
    b = r.json()
    for row in b["items"]:
        assert row["kind"] == "auth_failure"
        assert row["path"].startswith("/api/auth/")
        assert row["status"] in (401, 403)


# ============================================================
# P3 — Sparkline
# ============================================================

def test_sparkline_shape():
    r = httpx.get(f"{BASE}/api/admin/save-health/sparkline", params={"hours": 24, "buckets": 24}, timeout=30)
    assert r.status_code == 200
    b = r.json()
    assert b["buckets"] == 24
    assert isinstance(b["auth"], list) and len(b["auth"]) == 24
    assert isinstance(b["save"], list) and len(b["save"]) == 24
    assert all(isinstance(x, int) for x in b["auth"] + b["save"])
    assert b["bucket_minutes"] == 60.0


def test_sparkline_clamps_inputs():
    r = httpx.get(f"{BASE}/api/admin/save-health/sparkline", params={"hours": 999, "buckets": 200}, timeout=30)
    b = r.json()
    assert b["window_hours"] <= 168  # capped
    assert b["buckets"] <= 96


# ============================================================
# Frontend testid presence
# ============================================================

def test_frontend_exposes_iter57_testids():
    with open("/app/frontend/src/pages/Trips.jsx") as f:
        content = f.read()
    for tid in ("trips-saved-views", "save-current-view-btn", "trips-export-btn",
                "trips-export-menu", "trips-export-csv", "trips-export-xlsx"):
        assert tid in content, f"testid {tid!r} missing from Trips.jsx"
    with open("/app/frontend/src/pages/Dashboard.jsx") as f:
        content = f.read()
    for tid in ("save-health-sparkline", "save-health-sparkline-svg",
                "auth-drill-modal", "auth-drill-table", "auth-drill-close"):
        assert tid in content, f"testid {tid!r} missing from Dashboard.jsx"
