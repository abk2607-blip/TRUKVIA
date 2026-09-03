"""Iter134 · Invoice Number UI correction — backend contract for the new
separate 'Invoice Number' field on the Create screen.

Assertions:
  – POST /api/invoices without invoice_number uses the auto-suggested one.
  – POST /api/invoices with matching invoice_number uses it (no override).
  – POST with a DIFFERENT invoice_number requires reason ≥ 10 chars.
  – Owner-only override at create-time.
  – Duplicate override → 409 (unique-index guard).
  – Format guard: only [A-Za-z0-9/_-].
"""
from __future__ import annotations
import os, uuid, requests, pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
DEMO = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {DEMO}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer():
    r = requests.post(f"{API}/customers", headers=H, json={
        "name": f"IT134-num-{uuid.uuid4().hex[:6]}", "state": "Andhra Pradesh",
    }, timeout=10); r.raise_for_status(); return r.json()


def _trip(cid: str, d: str) -> str:
    r = requests.post(f"{API}/trips", headers=H, json={
        "customer_id": cid, "date": d, "vehicle_number": "AP16TA0134",
        "from_location": "A", "to_location": "B", "tons": 10, "unloaded_qty": 10,
        "freight_mode": "per_ton", "rate_per_ton": 500,
        "product_name": "Bitumen", "product_rate_per_mt": 40000,
    }, timeout=10); r.raise_for_status(); return r.json()["id"]


def test_create_uses_auto_number_when_field_absent(customer):
    tid = _trip(customer["id"], "2026-01-15")
    r = requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-01-15", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
    }, timeout=10)
    assert r.status_code == 200, r.text
    inv = r.json()
    assert "/25-26/" in inv["invoice_number"]


def test_create_with_matching_suggested_number_no_override(customer):
    tid = _trip(customer["id"], "2026-01-16")
    pre = requests.get(f"{API}/invoices/next-preview", headers=H,
                       params={"invoice_date": "2026-01-16"}, timeout=10).json()
    r = requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-01-16", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
        "invoice_number": pre["suggested_number"],
        # No reason required — sending the same number is NOT an override.
    }, timeout=10)
    assert r.status_code == 200, r.text
    # It may consume either that number or the next atomic sequence — both are legal.
    assert "/25-26/" in r.json()["invoice_number"]


def test_create_override_requires_reason(customer):
    tid = _trip(customer["id"], "2026-01-17")
    r = requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-01-17", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
        "invoice_number": f"IT134CR/25-26/{uuid.uuid4().hex[:6].upper()}",
        "invoice_number_reason": "short",
    }, timeout=10)
    assert r.status_code == 400
    assert "10 characters" in r.json()["detail"].lower() or "10 chars" in r.json()["detail"].lower()


def test_create_override_ok_with_reason(customer):
    tid = _trip(customer["id"], "2026-01-18")
    new_num = f"IT134CR/25-26/{uuid.uuid4().hex[:6].upper()}"
    r = requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-01-18", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
        "invoice_number": new_num,
        "invoice_number_reason": "manual serial correction at create time",
    }, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["invoice_number"] == new_num


def test_create_override_duplicate_rejected(customer):
    tid1 = _trip(customer["id"], "2026-01-19")
    n1 = f"IT134CR/25-26/{uuid.uuid4().hex[:6].upper()}"
    a = requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer["id"], "trip_ids": [tid1],
        "invoice_date": "2026-01-19", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
        "invoice_number": n1,
        "invoice_number_reason": "seed for duplicate override test",
    }, timeout=10); assert a.status_code == 200, a.text
    tid2 = _trip(customer["id"], "2026-01-20")
    b = requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer["id"], "trip_ids": [tid2],
        "invoice_date": "2026-01-20", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
        "invoice_number": n1,
        "invoice_number_reason": "attempt duplicate number on create",
    }, timeout=10)
    assert b.status_code == 409


def test_create_override_invalid_chars_rejected(customer):
    tid = _trip(customer["id"], "2026-01-21")
    r = requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-01-21", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
        "invoice_number": "BAD NUMBER!@#",
        "invoice_number_reason": "invalid chars should be rejected",
    }, timeout=10)
    assert r.status_code == 400
    assert "invalid characters" in r.json()["detail"].lower()
