"""Iter33 extras — spec items not covered by test_iter33_ai_extensions.py:
- /api/files/public rejects non-lr_shares/public paths with 404
- /api/ai/report response includes X-Report-Spec header with JSON spec
- Public LR file is accessible without auth after share-lr
- Insights response schema
"""
import os
import json
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _get_or_create_customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c.get("name") == "TEST_Iter33":
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS,
                         json={"name": "TEST_Iter33", "state": "Andhra Pradesh"}).json()["id"]


# --- /files/public prefix restriction ---
def test_public_file_rejects_invalid_prefix():
    r = requests.get(f"{BASE_URL}/api/files/public/some/other/path.pdf")
    assert r.status_code == 404


def test_public_file_rejects_traversal_prefix():
    r = requests.get(f"{BASE_URL}/api/files/public/uploads/x.pdf")
    assert r.status_code == 404


# --- Report PDF spec header ---
def test_report_pdf_has_report_spec_header():
    r = requests.post(f"{API}/ai/report", headers=HEADERS,
                      json={"query": "show last 30 days freight by vehicle"})
    assert r.status_code == 200, r.text
    spec_hdr = r.headers.get("X-Report-Spec") or r.headers.get("x-report-spec")
    assert spec_hdr, f"Missing X-Report-Spec header. Headers={dict(r.headers)}"
    spec = json.loads(spec_hdr)
    # spec should have some notion of metric or group_by keys
    assert isinstance(spec, dict) and len(spec) > 0, spec


# --- Insights shape ---
def test_insights_response_schema():
    r = requests.get(f"{API}/ai/insights", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert "insights" in d and isinstance(d["insights"], list)
    assert "generated_at" in d
    assert "cached" in d
    # stats_snapshot is only present on fresh generation, not on cached responses
    if not d.get("cached"):
        assert "stats_snapshot" in d


# --- LR share end-to-end: public URL is fetchable without auth ---
def test_share_lr_public_url_downloadable_without_auth():
    cid = _get_or_create_customer()
    tp = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06",
        "vehicle_number": "AP99WA0099", "tons": 8, "freight_mode": "per_ton",
        "rate_per_ton": 1400, "from_location": "X", "to_location": "Y",
        "load_details": "Bitumen",
    }).json()
    tid = tp["id"]
    try:
        r = requests.post(f"{API}/trips/{tid}/share-lr", headers=HEADERS)
        assert r.status_code == 200, r.text
        d = r.json()
        pub = d["public_url"]
        wa = d["whatsapp_url"]
        assert wa.startswith("https://wa.me/?text=")
        assert "/api/files/public/lr_shares/" in pub or "/files/public/lr_shares/" in pub, pub
        # download without any auth headers
        r2 = requests.get(pub)
        assert r2.status_code == 200, f"pub_url={pub} status={r2.status_code}"
        assert r2.content[:5] == b"%PDF-"
        assert len(r2.content) > 500
        # auto-LR: trip should now have lr_number set even if it was blank
        assert d.get("lr_number")
    finally:
        requests.delete(f"{API}/trips/{tid}", headers=HEADERS, params={"reason": "test cleanup"})
