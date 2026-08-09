"""Iter41 — Voice Templates + Expenditure Analytics + Supplier Statement PDF.

Uses the live backend (same pattern as iter39/40). Verifies:
  1. GET /api/dashboard/expenditure-breakdown aggregates other_expenditures by type
     and returns period/total/count/pct schema.
  2. POST /api/ai/parse-template returns a structured template dict (may 502 if
     Emergent LLM key unavailable — treated as skipped).
  3. GET /api/reports/supplier-statement.pdf renders a PDF containing supplier
     name, per-trip settlement rows, remarks (when set), and totals.
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c["name"] == "TEST_Iter41":
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Iter41", "state": "Andhra Pradesh"}).json()["id"]


def test_expenditure_breakdown_aggregates_by_type():
    import time, uuid
    cid = _customer()
    # Use a unique per-run date so re-runs don't pile up in the aggregate
    ts = int(time.time())
    # Spread across year+month using a stable hash of ts so consecutive runs pick different dates
    y = 2050 + (ts % 30)
    m = ((ts // 30) % 12) + 1
    d = ((ts // (30 * 12)) % 27) + 1
    unique_date = f"{y}-{m:02d}-{d:02d}"
    # Range is exactly that single day
    requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": unique_date,
        "vehicle_number": f"AP99IT41{uuid.uuid4().hex[:6].upper()}", "tons": 10,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "other_expenditures": [
            {"id": "x1", "date": unique_date, "type": "Driver Food", "amount": 300, "remarks": ""},
            {"id": "x2", "date": unique_date, "type": "Toll", "amount": 700, "remarks": ""},
            {"id": "x3", "date": unique_date, "type": "Driver Food", "amount": 200, "remarks": ""},
        ],
    })
    r = requests.get(f"{API}/dashboard/expenditure-breakdown?start={unique_date}&end={unique_date}", headers=HEADERS)
    assert r.status_code == 200
    d_json = r.json()
    assert d_json["period"]["start"] == unique_date
    assert d_json["total"] == 1200.0, f"Total expected 1200, got {d_json['total']}"
    assert d_json["trip_count"] == 1
    types = {row["type"]: row for row in d_json["by_type"]}
    assert types["Driver Food"]["amount"] == 500.0
    assert types["Driver Food"]["count"] == 2
    assert types["Toll"]["amount"] == 700.0
    total_pct = round(sum(r["pct"] for r in d_json["by_type"]))
    assert total_pct == 100


def test_supplier_statement_pdf_renders_with_totals_and_remarks():
    import pymupdf, time
    cid = _customer()
    ts = int(time.time())
    supplier = f"ITER41 Supplier {ts}"
    for i in range(2):
        requests.post(f"{API}/trips", headers=HEADERS, json={
            "customer_id": cid, "date": f"2030-05-{20+i:02d}",
            "vehicle_number": f"AP99I41S{ts%1000}{i}",
            "vehicle_type": "supplier",
            "supplier_name": supplier,
            "tons": 15,
            "freight_mode": "per_ton", "rate_per_ton": 1600,
            "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 1200,
            "supplier_advance": 3000, "supplier_diesel": 2000,
            "supplier_settlement_remarks": f"ITER41 REMARK #{i+1}",
        })
    r = requests.get(
        f"{API}/reports/supplier-statement.pdf",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={"supplier_name": supplier, "start": "2030-05-01", "end": "2030-05-31"},
    )
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    text = ""
    with pymupdf.open(stream=r.content, filetype="pdf") as doc:
        for p in doc:
            text += p.get_text()
    assert supplier in text
    assert "Trip-wise Settlement" in text
    assert "Net Payable" in text
    assert "ITER41 REMARK #1" in text or ("ITER41" in text and "REMARK" in text and "#1" in text)
    assert "ITER41 REMARK #2" in text or ("ITER41" in text and "REMARK" in text and "#2" in text)


def test_supplier_statement_404_when_no_trips():
    r = requests.get(
        f"{API}/reports/supplier-statement.pdf",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={"supplier_name": "ZZZ_DOES_NOT_EXIST_ITER41"},
    )
    assert r.status_code == 404


def test_ai_parse_template_endpoint_exists():
    """Confirms the endpoint is wired. LLM call may fail (502) in CI without
    a network / key — accept 200 or 502 but reject 404/405."""
    r = requests.post(f"{API}/ai/parse-template", headers=HEADERS, json={"transcript": "Kondapalli to Vijayawada route bitumen VG-40 per ton 1500 rupees round trip 450 kilometers"})
    assert r.status_code in (200, 502, 503), f"unexpected status {r.status_code}: {r.text[:200]}"
    if r.status_code == 200:
        d = r.json()
        assert "parsed" in d
        assert "transcript" in d
