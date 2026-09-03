"""Iter134 · Invoice Enhancement — focused numbering/FY/override tests.

Runs against the deployed FastAPI via `requests` + DEMO token — matches the
Iter133 test pattern exactly. Uses past dates safely so preview / create
never trip the future-date guard.

Server calendar today is Sep-2026 → FY 26-27. Historical FY 25-26 dates
(anything in Apr-2025 → Mar-2026) are always safely past.
"""
from __future__ import annotations
import os, uuid, requests, pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]
TAG = f"IT134-{uuid.uuid4().hex[:6].upper()}"


def _hdr(idem: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


@pytest.fixture(scope="module")
def company():
    return requests.get(f"{API}/company", headers=_hdr(), timeout=10).json()


@pytest.fixture(scope="module")
def customer():
    r = requests.post(f"{API}/customers", headers=_hdr(), json={
        "name": f"IT134 Cust {uuid.uuid4().hex[:6]}", "state": "Andhra Pradesh",
    }, timeout=10)
    r.raise_for_status()
    return r.json()


def _make_trip(cust_id: str, date_iso: str) -> str:
    r = requests.post(f"{API}/trips", headers=_hdr(), json={
        "customer_id": cust_id, "date": date_iso,
        "vehicle_number": "AP16TA0134", "from_location": "A", "to_location": "B",
        "tons": 10, "unloaded_qty": 10,
        "freight_mode": "per_ton", "rate_per_ton": 500,
        "product_name": "Bitumen", "product_rate_per_mt": 40000,
    }, timeout=10)
    r.raise_for_status()
    return r.json()["id"]


# ────────────────────── Numbering / FY ──────────────────────

def test_preview_returns_past_fy_for_march_date():
    """31-Mar-2026 → FY 25-26."""
    r = requests.get(f"{API}/invoices/next-preview", headers=_hdr(),
                     params={"invoice_date": "2026-03-31"}, timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["fy"] == "25-26"
    assert "/25-26/" in j["suggested_number"]


def test_preview_returns_new_fy_for_april_date():
    """01-Apr-2026 → FY 26-27."""
    r = requests.get(f"{API}/invoices/next-preview", headers=_hdr(),
                     params={"invoice_date": "2026-04-01"}, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["fy"] == "26-27"


def test_preview_does_not_reserve_sequence():
    """Two consecutive previews for the same past FY must be identical."""
    r1 = requests.get(f"{API}/invoices/next-preview", headers=_hdr(),
                      params={"invoice_date": "2026-03-15"}, timeout=10).json()
    r2 = requests.get(f"{API}/invoices/next-preview", headers=_hdr(),
                      params={"invoice_date": "2026-03-15"}, timeout=10).json()
    assert r1 == r2
    assert r1["fy"] == "25-26"


def test_preview_rejects_future_date():
    r = requests.get(f"{API}/invoices/next-preview", headers=_hdr(),
                     params={"invoice_date": "2099-01-01"}, timeout=10)
    assert r.status_code == 400


def test_preview_rejects_bad_date():
    r = requests.get(f"{API}/invoices/next-preview", headers=_hdr(),
                     params={"invoice_date": "not-a-date"}, timeout=10)
    assert r.status_code == 400


def test_create_invoice_uses_invoice_date_fy(customer):
    """CRITICAL: invoice_date drives FY, not server clock (server is Sep-2026)."""
    tid = _make_trip(customer["id"], "2026-01-15")
    r = requests.post(f"{API}/invoices", headers=_hdr(_idem := f"it134-{uuid.uuid4().hex[:16]}"), json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-01-15", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
    }, timeout=10)
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["fy_string"] == "25-26"
    assert "/25-26/" in inv["invoice_number"], inv["invoice_number"]


def test_create_invoice_future_date_rejected(customer):
    tid = _make_trip(customer["id"], "2026-01-16")
    r = requests.post(f"{API}/invoices", headers=_hdr(f"it134-{uuid.uuid4().hex[:16]}"), json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2099-01-01", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
    }, timeout=10)
    assert r.status_code == 400
    assert "future" in r.json()["detail"].lower()


def test_cross_fy_date_change_blocked(customer):
    tid = _make_trip(customer["id"], "2026-02-10")
    inv = requests.post(f"{API}/invoices", headers=_hdr(f"it134-{uuid.uuid4().hex[:16]}"), json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-02-10", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
    }, timeout=10).json()
    # Same-FY change allowed
    r = requests.put(f"{API}/invoices/{inv['id']}", headers=_hdr(), json={
        "invoice_date": "2026-02-11", "reason": "typo on invoice date field",
    }, timeout=10)
    assert r.status_code == 200, r.text
    # Cross-FY change blocked
    r = requests.put(f"{API}/invoices/{inv['id']}", headers=_hdr(), json={
        "invoice_date": "2026-04-05", "reason": "attempt cross-FY change on issued invoice",
    }, timeout=10)
    assert r.status_code == 400
    assert "financial year" in r.json()["detail"].lower()


def test_owner_override_and_audit(customer, company):
    tid = _make_trip(customer["id"], "2026-02-12")
    inv = requests.post(f"{API}/invoices", headers=_hdr(f"it134-{uuid.uuid4().hex[:16]}"), json={
        "customer_id": customer["id"], "trip_ids": [tid],
        "invoice_date": "2026-02-12", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
    }, timeout=10).json()
    new_num = f"IT134OVR/{uuid.uuid4().hex[:6].upper()}"
    r = requests.patch(f"{API}/invoices/{inv['id']}/override-number", headers=_hdr(), json={
        "new_number": new_num, "reason": "manual serial correction per audit review",
    }, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["invoice_number"] == new_num
    # Short reason rejected
    r = requests.patch(f"{API}/invoices/{inv['id']}/override-number", headers=_hdr(), json={
        "new_number": f"IT134OVR2/{uuid.uuid4().hex[:6].upper()}", "reason": "short",
    }, timeout=10)
    assert r.status_code == 400


def test_duplicate_override_rejected(customer):
    tid1 = _make_trip(customer["id"], "2026-02-13")
    inv1 = requests.post(f"{API}/invoices", headers=_hdr(f"it134-{uuid.uuid4().hex[:16]}"), json={
        "customer_id": customer["id"], "trip_ids": [tid1],
        "invoice_date": "2026-02-13", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
    }, timeout=10).json()
    tid2 = _make_trip(customer["id"], "2026-02-14")
    inv2 = requests.post(f"{API}/invoices", headers=_hdr(f"it134-{uuid.uuid4().hex[:16]}"), json={
        "customer_id": customer["id"], "trip_ids": [tid2],
        "invoice_date": "2026-02-14", "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
    }, timeout=10).json()
    r = requests.patch(f"{API}/invoices/{inv2['id']}/override-number", headers=_hdr(), json={
        "new_number": inv1["invoice_number"], "reason": "attempt to duplicate invoice number",
    }, timeout=10)
    assert r.status_code == 409


def test_contradictory_system_note_blocked(company):
    doc = dict(company)  # shallow copy
    doc["signature_file_id"] = "file_dummy_iter134"
    doc["system_generated_note"] = "This is computer generated. Signature not required."
    r = requests.put(f"{API}/company", headers=_hdr(), json=doc, timeout=10)
    assert r.status_code == 400
    assert "signature" in r.json()["detail"].lower()
    # Cleanup: clear signature so it doesn't affect the running UAT
    doc["signature_file_id"] = ""
    doc["system_generated_note"] = ""
    requests.put(f"{API}/company", headers=_hdr(), json=doc, timeout=10)


def test_fy_derivation_helper_matches_boundary():
    """Direct helper coverage — no server involvement, just import + call."""
    from services import _fy_from_iso
    assert _fy_from_iso("2027-03-31") == "26-27"
    assert _fy_from_iso("2027-04-01") == "27-28"
    assert _fy_from_iso("2026-04-01") == "26-27"
    assert _fy_from_iso("2026-03-31") == "25-26"
