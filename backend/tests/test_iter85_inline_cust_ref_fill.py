"""Iter85 — One-Click Cust Ref Fill from the Missing Cust Ref view.

New PATCH endpoint `/api/trips/{id}/customer-ref` updates ONLY the trip's
`customer_reference_number` field (no duplicate field, no side-effects on
freight/halting/expenses/invoice linkage). After a save, the trip must
disappear from the `missing_cust_ref=true` filter list. The value must also
be reflected in a subsequent GET /api/trips/{id} and in the Invoice PDF for
that trip.
"""
import os, uuid, io, httpx
import pytest
from pypdf import PdfReader

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
TOK = "test_session_bitumen_2026"
HA = {"Authorization": f"Bearer {TOK}"}


@pytest.fixture(scope="module")
def blank_trip():
    httpx.post(f"{BASE}/api/auth/demo-login", timeout=60)
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(
        f"{BASE}/api/customers", headers=HA,
        json={"name": f"IT85_Cust_{tag}", "phone": "9998887777", "state": "AP"},
        timeout=60,
    ).json()
    veh = httpx.post(
        f"{BASE}/api/vehicles", headers=HA,
        json={"vehicle_number": f"AP99IT85{tag[:4].upper()}", "vehicle_type": "own"},
        timeout=60,
    ).json()
    trip = httpx.post(
        f"{BASE}/api/trips", headers=HA,
        json={
            "customer_id": cust["id"], "date": "2026-10-01",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1000,
            "from_location": "K", "to_location": "V",
            # no customer_reference_number
        },
        timeout=60,
    ).json()
    return {"trip": trip, "cust": cust, "tag": tag}


def test_patch_sets_customer_reference_number(blank_trip):
    """The PATCH endpoint sets ONLY the customer_reference_number field."""
    tid = blank_trip["trip"]["id"]
    new_ref = f"CINV-INLINE-{blank_trip['tag']}"
    r = httpx.patch(
        f"{BASE}/api/trips/{tid}/customer-ref",
        headers=HA,
        json={"customer_reference_number": new_ref},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    assert r.json()["customer_reference_number"] == new_ref
    # verify persisted
    fresh = httpx.get(f"{BASE}/api/trips/{tid}", headers=HA, timeout=30).json()
    assert fresh["customer_reference_number"] == new_ref


def test_trip_disappears_from_missing_filter_after_save(blank_trip):
    """Once saved, the trip must no longer appear under missing_cust_ref=true."""
    tid = blank_trip["trip"]["id"]
    cid = blank_trip["cust"]["id"]
    trips = httpx.get(
        f"{BASE}/api/trips?missing_cust_ref=true&customer_id={cid}",
        headers=HA, timeout=30,
    ).json()
    ids = {t["id"] for t in trips}
    assert tid not in ids, "trip with a ref must not appear under missing_cust_ref=true"


def test_patch_does_not_alter_other_trip_fields(blank_trip):
    """Freight, tons, dates, halting must be untouched by the ref patch."""
    tid = blank_trip["trip"]["id"]
    original = blank_trip["trip"]
    fresh = httpx.get(f"{BASE}/api/trips/{tid}", headers=HA, timeout=30).json()
    for k in ("date", "vehicle_id", "tons", "freight_mode", "rate_per_ton",
              "from_location", "to_location", "freight_amount"):
        assert fresh.get(k) == original.get(k), f"field {k} was altered by the ref PATCH"


def test_blank_patch_clears_ref_and_returns_to_missing_list(blank_trip):
    """Sending an empty ref must clear the field and return the trip to the
    missing list — matches the user's expectation of a symmetric flow."""
    tid = blank_trip["trip"]["id"]
    cid = blank_trip["cust"]["id"]
    r = httpx.patch(
        f"{BASE}/api/trips/{tid}/customer-ref",
        headers=HA,
        json={"customer_reference_number": ""},
        timeout=30,
    )
    assert r.status_code == 200
    assert r.json()["customer_reference_number"] == ""
    trips = httpx.get(
        f"{BASE}/api/trips?missing_cust_ref=true&customer_id={cid}",
        headers=HA, timeout=30,
    ).json()
    ids = {t["id"] for t in trips}
    assert tid in ids


def test_inline_ref_reflects_in_invoice_pdf(blank_trip):
    """Set a ref inline, generate an invoice for that trip, and confirm the
    ref appears in the PDF's Cust Ref column."""
    tid = blank_trip["trip"]["id"]
    cid = blank_trip["cust"]["id"]
    new_ref = f"CINV-PDF-{blank_trip['tag']}"
    httpx.patch(
        f"{BASE}/api/trips/{tid}/customer-ref",
        headers=HA, json={"customer_reference_number": new_ref}, timeout=30,
    ).raise_for_status()
    inv = httpx.post(
        f"{BASE}/api/invoices", headers=HA,
        json={
            "customer_id": cid, "invoice_date": "2026-10-02",
            "trip_ids": [tid], "hsn_sac": "996791",
            "gst_treatment": "rcm", "due_date": "2026-11-01",
        },
        timeout=60,
    ).json()
    r = httpx.get(f"{BASE}/api/invoices/{inv['id']}/pdf", headers=HA, timeout=60)
    assert r.status_code == 200
    reader = PdfReader(io.BytesIO(r.content))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    # Allow for pypdf wrapping — check that the significant token exists.
    assert "CINV-PDF" in text, "Cust Ref set inline must appear in the Invoice PDF"


def test_patch_404_on_unknown_trip():
    r = httpx.patch(
        f"{BASE}/api/trips/nope-does-not-exist/customer-ref",
        headers=HA, json={"customer_reference_number": "X"}, timeout=30,
    )
    assert r.status_code == 404
