"""Iter43 — Expenditure drill-down, WhatsApp share, Voice refine, AI chat tool."""
import os
import time
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _cust():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c["name"] == "TEST_Iter43":
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Iter43", "state": "Andhra Pradesh"}).json()["id"]


def _drill(exp_type, date, expected_count):
    """Xdist Test Cleanup (approved plan §5b) — retry the drill-down up to
    3 × 500 ms so the just-committed POST /trips is visible to the
    aggregation endpoint even when Mongo commit propagation lags under
    xdist parallel load. Assertions remain on the returned response."""
    last = None
    for _ in range(3):
        r = requests.get(f"{API}/dashboard/expenditure-detail", headers=HEADERS,
                         params={"type": exp_type, "start": date, "end": date})
        if r.status_code == 200 and r.json().get("count") == expected_count:
            return r
        last = r
        time.sleep(0.5)
    return last  # trigger the existing assertion in the caller


def test_expenditure_drill_down_returns_trip_rows():
    import uuid
    cid = _cust()
    ts = int(time.time())
    y = 2060 + (ts % 20)
    m = ((ts // 20) % 12) + 1
    day = ((ts // (20 * 12)) % 27) + 1
    date = f"{y}-{m:02d}-{day:02d}"
    marker = f"ITER43-{uuid.uuid4().hex[:6]}"
    # Iter120 · Use a UNIQUE expenditure type per run so re-invocations (e.g.
    # the isolated CI job racing with the hourly background regression tick)
    # cannot double-count against the same {date, type} pair. This is the
    # root cause of the recurring `assert 700.0 == 350.0` — every prior run
    # left an orphan trip with the same random date + generic `Parking`
    # bucket.
    exp_type = f"Parking-{uuid.uuid4().hex[:6]}"
    requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": date,
        "vehicle_number": f"AP99IT43{uuid.uuid4().hex[:4].upper()}",
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "from_location": "A", "to_location": "B",
        "other_expenditures": [
            {"id": "d1", "date": date, "type": exp_type, "amount": 200, "remarks": marker},
            {"id": "d2", "date": date, "type": exp_type, "amount": 150, "remarks": ""},
            {"id": "d3", "date": date, "type": "Toll",  "amount": 500, "remarks": "Ignored"},
        ],
    })
    r = _drill(exp_type, date, 2)
    assert r.status_code == 200
    d = r.json()
    assert d["type"] == exp_type
    assert d["total"] == 350.0
    assert d["count"] == 2
    # Marker remark preserved
    assert any(r["remarks"] == marker for r in d["trips"])


def test_expenditure_drill_down_400_when_type_missing():
    r = requests.get(f"{API}/dashboard/expenditure-detail", headers=HEADERS)
    assert r.status_code == 422  # FastAPI treats missing required query as 422


def test_supplier_statement_share_returns_wa_url():
    r = requests.post(f"{API}/reports/supplier-statement/share",
                      headers={"Authorization": f"Bearer {TOKEN}"},
                      params={"supplier_name": "Ram"})
    # If Ram has any supplier trips this succeeds; otherwise 404 is acceptable.
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        d = r.json()
        assert d["public_url"].startswith("http")
        assert d["whatsapp_url"].startswith("https://wa.me/")
        assert "supplier_mobile_available" in d
        # Fetch public URL — should be reachable (unauthenticated)
        pdf = requests.get(d["public_url"])
        assert pdf.status_code == 200
        assert pdf.headers.get("content-type", "").startswith("application/pdf")


def test_ai_parse_template_refine_mode_returns_only_deltas():
    """When existing template is provided, only mentioned fields returned."""
    existing = {
        "name": "Kondapalli → Vijayawada",
        "from_location": "Kondapalli", "to_location": "Vijayawada",
        "product_type": "VG-40", "freight_mode": "per_ton",
        "rate_per_ton": 1500, "round_trip_kms": 450,
        "halting_rate_per_day": 2500,
    }
    r = requests.post(f"{API}/ai/parse-template", headers=HEADERS, json={
        "transcript": "Change the rate to 1600",
        "existing": existing,
    })
    assert r.status_code in (200, 502, 503)
    if r.status_code == 200:
        d = r.json()
        assert d.get("refine_mode") is True
        parsed = d["parsed"]
        # Only rate should be present
        assert "rate_per_ton" in parsed
        assert float(parsed["rate_per_ton"]) == 1600.0
        # NO auto-generated name / route
        assert "from_location" not in parsed or not parsed.get("from_location")
        assert "to_location" not in parsed or not parsed.get("to_location")


def test_ai_chat_expenditure_tool_registered():
    """Sanity: the expenditure_breakdown tool schema is registered in the AI router."""
    from routers.ai import TOOL_FN_MAP, TOOL_SCHEMAS
    assert "expenditure_breakdown" in TOOL_FN_MAP
    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    assert "expenditure_breakdown" in names
