"""Iter46 — Halting = single source of truth at Trip level.

Locks the two entry paths + full downstream flow:
  1. loading_date + unloading_date → auto Total Days
  2. No dates → user-typed Total Days respected
  3. Chargeable = max(Total - Grace, 0); Amount = Chargeable × Rate (unless override)
  4. Multi-trip invoice halting_total = sum of trip halting_amounts
  5. Invoice PDF renders halting sub-row per trip with '↳ Halting — N day(s) × ₹X / day → ₹Y'
"""
import os
import uuid
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Xdist Test Cleanup (approved plan §5b) — per-process unique fixtures so
# concurrent workers on other files cannot mutate this customer's policy
# mid-flight. Matches the pattern already used by test_iter44.
_FIXTURE_NAME = f"TEST_Iter46_{uuid.uuid4().hex[:6]}"
_VEH_SUFFIX = uuid.uuid4().hex[:4].upper()


def _customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c["name"] == _FIXTURE_NAME:
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": _FIXTURE_NAME, "state": "Andhra Pradesh"}).json()["id"]


def test_halting_from_manual_total_days_no_dates():
    """User types Total Days = 10, Grace 4, Rate ₹3,000 → Chargeable 6, Amount ₹18,000."""
    cid = _customer()
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2028-05-01",
        "vehicle_number": f"ITER46-MAN-{_VEH_SUFFIX}", "tons": 20,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "total_halting_days": 10, "grace_days": 4, "halting_rate_per_day": 3000,
    }).json()
    assert t["total_halting_days"] == 10
    assert t["chargeable_halting_days"] == 6
    assert t["halting_amount"] == 18000.0


def test_halting_from_dates():
    """loading_date + unloading_date 12 days apart, Grace 4, Rate ₹3,000 → Chargeable 8, Amount ₹24,000."""
    cid = _customer()
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2028-05-01",
        "vehicle_number": f"ITER46-DATES-{_VEH_SUFFIX}", "tons": 20,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "loading_date": "2028-05-01", "unloading_date": "2028-05-13",
        "grace_days": 4, "halting_rate_per_day": 3000,
    }).json()
    assert t["total_halting_days"] == 12
    assert t["chargeable_halting_days"] == 8
    assert t["halting_amount"] == 24000.0


def test_halting_zero_when_within_grace():
    cid = _customer()
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2028-05-01",
        "vehicle_number": f"ITER46-GRACE-{_VEH_SUFFIX}", "tons": 20,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "total_halting_days": 3, "grace_days": 4, "halting_rate_per_day": 3000,
    }).json()
    assert t["chargeable_halting_days"] == 0
    assert t["halting_amount"] == 0.0


def test_halting_override_preserved():
    cid = _customer()
    t = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2028-05-01",
        "vehicle_number": f"ITER46-OVR-{_VEH_SUFFIX}", "tons": 20,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "total_halting_days": 10, "grace_days": 4, "halting_rate_per_day": 3000,
        "halting_amount": 15000, "halting_amount_override": True,
    }).json()
    assert t["halting_amount"] == 15000.0  # manual override preserved


def test_invoice_halting_flows_from_multiple_trips():
    """Two trips → invoice halting_total sums; PDF text carries both halting rows."""
    import pymupdf
    cid = _customer()
    t1 = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2028-06-01",
        "vehicle_number": f"ITER46-INV1-{_VEH_SUFFIX}", "tons": 30,
        "freight_mode": "per_ton", "rate_per_ton": 1500,
        "total_halting_days": 10, "grace_days": 4, "halting_rate_per_day": 3000,
    }).json()
    t2 = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2028-06-02",
        "vehicle_number": f"ITER46-INV2-{_VEH_SUFFIX}", "tons": 30,
        "freight_mode": "per_ton", "rate_per_ton": 1500,
        "loading_date": "2028-06-02", "unloading_date": "2028-06-14",
        "grace_days": 4, "halting_rate_per_day": 3000,
    }).json()
    assert t1["halting_amount"] == 18000.0
    assert t2["halting_amount"] == 24000.0
    inv = requests.post(f"{API}/invoices", headers=HEADERS, json={
        "customer_id": cid, "trip_ids": [t1["id"], t2["id"]], "gst_type": "cgst_sgst",
    }).json()
    assert inv["halting_total"] == 42000.0
    assert inv["freight_total"] == 90000.0
    assert inv["subtotal"] == 132000.0
    # PDF must show both halting rows
    pdf = requests.get(f"{API}/invoices/{inv['id']}/pdf", headers=HEADERS)
    assert pdf.status_code == 200
    text = "".join(p.get_text() for p in pymupdf.open(stream=pdf.content, filetype="pdf"))
    assert "Halting" in text
    assert "18,000" in text or "18000" in text
    assert "24,000" in text or "24000" in text
    # Auto-recompute: update trip 1 halting, refetch → PDF updates
    requests.put(f"{API}/trips/{t1['id']}", headers=HEADERS, json={
        "customer_id": cid, "date": "2028-06-01",
        "vehicle_number": f"ITER46-INV1-{_VEH_SUFFIX}", "tons": 30,
        "freight_mode": "per_ton", "rate_per_ton": 1500,
        "total_halting_days": 5, "grace_days": 4, "halting_rate_per_day": 3000,
    })
    inv2 = requests.get(f"{API}/invoices/{inv['id']}", headers=HEADERS).json()
    assert inv2["halting_total"] == 3000.0 + 24000.0
