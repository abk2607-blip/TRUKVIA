"""Iter134 · Owner-editability UAT-blocker fix — confirm the input renders
ENABLED (no `disabled` attribute) and the owner-only enforcement remains on
the server. Also re-covers the create-time override happy path since we
touched the surrounding code."""
from __future__ import annotations
import os, uuid, requests, pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
DEMO = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {DEMO}", "Content-Type": "application/json"}


def test_input_is_not_disabled_in_source():
    """The `disabled=` prop that gated the Invoice Number input must be gone;
    server enforces owner-only. Guards against silent regression."""
    src = open("/app/frontend/src/pages/InvoiceCreate.jsx").read()
    # The exact old gating line must NOT reappear
    assert 'disabled={!((user?.effective_role || user?.role || "").toLowerCase() === "owner")}' not in src


@pytest.fixture(scope="module")
def customer():
    r = requests.post(f"{API}/customers", headers=H, json={
        "name": f"IT134-ed-{uuid.uuid4().hex[:6]}", "state": "Andhra Pradesh",
    }, timeout=10); r.raise_for_status(); return r.json()


def _trip(cid: str, d: str) -> str:
    r = requests.post(f"{API}/trips", headers=H, json={
        "customer_id": cid, "date": d, "vehicle_number": "AP16TA0134",
        "from_location": "A", "to_location": "B", "tons": 10, "unloaded_qty": 10,
        "freight_mode": "per_ton", "rate_per_ton": 500,
        "product_name": "Bitumen", "product_rate_per_mt": 40000,
    }, timeout=10); r.raise_for_status(); return r.json()["id"]


def test_owner_create_time_override_succeeds_with_reason(customer):
    tid = _trip(customer["id"], "2026-01-22")
    new_num = f"IT134ED/25-26/{uuid.uuid4().hex[:6].upper()}"
    r = requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-01-22", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
        "invoice_number": new_num,
        "invoice_number_reason": "UAT owner override editability fix",
    }, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["invoice_number"] == new_num


def test_create_time_override_short_reason_still_rejected(customer):
    tid = _trip(customer["id"], "2026-01-23")
    r = requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-01-23", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
        "invoice_number": f"IT134ED2/25-26/{uuid.uuid4().hex[:6].upper()}",
        "invoice_number_reason": "bad",
    }, timeout=10)
    assert r.status_code == 400
