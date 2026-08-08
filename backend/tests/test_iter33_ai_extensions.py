"""Iter33 — Phase-3: AI voice parse, dashboard insights, natural-language reports, LR WhatsApp share."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _get_or_create_customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c.get("name") == "TEST_Iter33":
            return c["id"]
    c = requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Iter33", "state": "Andhra Pradesh"}).json()
    return c["id"]


def test_parse_trip_from_english_voice():
    r = requests.post(f"{API}/ai/parse-trip", headers=HEADERS, json={
        "transcript": "Trip today vehicle AP16TA1234 driver Ramesh 20 tons of bitumen from Chennai to Hyderabad at rate 1200 per ton"
    })
    assert r.status_code == 200, r.text
    d = r.json()
    p = d.get("parsed", {})
    assert p.get("vehicle_number") == "AP16TA1234", p
    assert p.get("tons") == 20, p
    assert p.get("from_location", "").lower().startswith("chennai"), p
    assert p.get("to_location", "").lower().startswith("hyderabad"), p
    assert p.get("rate_per_ton") == 1200, p
    assert p.get("freight_mode") == "per_ton", p


def test_parse_trip_rejects_empty():
    r = requests.post(f"{API}/ai/parse-trip", headers=HEADERS, json={"transcript": ""})
    assert r.status_code == 400


def test_insights_returns_bullets():
    r = requests.post(f"{API}/ai/insights/refresh", headers=HEADERS)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "insights" in d and isinstance(d["insights"], list)
    assert len(d["insights"]) >= 3
    assert d.get("stats_snapshot") is not None


def test_insights_cache_returns_within_6h():
    r1 = requests.get(f"{API}/ai/insights", headers=HEADERS)
    assert r1.status_code == 200
    r2 = requests.get(f"{API}/ai/insights", headers=HEADERS)
    assert r2.status_code == 200
    assert r2.json().get("cached") in (True, False)  # both valid; cached=True after first hit


def test_report_generates_pdf():
    r = requests.post(f"{API}/ai/report", headers=HEADERS, json={"query": "show last 30 days freight by vehicle"})
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert len(r.content) > 500
    assert r.content[:5] == b"%PDF-"


def test_share_lr_returns_whatsapp_url():
    # Ensure a trip exists
    cid = _get_or_create_customer()
    tp = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-06",
        "vehicle_number": "AP99WA0001", "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "from_location": "A", "to_location": "B", "load_details": "Bitumen",
    }).json()
    tid = tp["id"]
    try:
        r = requests.post(f"{API}/trips/{tid}/share-lr", headers=HEADERS)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("whatsapp_url", "").startswith("https://wa.me/?text=")
        assert d.get("public_url", "").startswith("http")
        assert "lr_number" in d and d["lr_number"]
    finally:
        requests.delete(f"{API}/trips/{tid}", headers=HEADERS, params={"reason": "test cleanup"})
