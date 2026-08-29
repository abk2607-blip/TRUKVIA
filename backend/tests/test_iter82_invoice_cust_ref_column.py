"""Iter82 — Customer Ref Number per-trip in Invoice PDF + on-screen view.

The user reported that although each Trip stores its own Customer Invoice /
Reference Number, the generated Invoice only shows it inline in the Route cell
(as a small subtitle) and doesn't have a dedicated column. This suite locks:
  1. Each trip's `customer_reference_number` is preserved by the trips API.
  2. The Invoice PDF renders a dedicated "Cust Ref" column with each trip's
     own value (never inherited across trips).
  3. Blank Cust Ref stays blank on that trip and doesn't inherit.
"""
import os, uuid, httpx, io
import pytest
from pypdf import PdfReader

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
TOK = os.environ["DEMO_TOKEN_VALUE"]
HA = {"Authorization": f"Bearer {TOK}"}


@pytest.fixture(scope="module")
def invoice_with_mixed_refs():
    """Create 3 trips with different Customer Ref Numbers + 1 with blank ref,
    then group them into one invoice."""
    httpx.post(f"{BASE}/api/auth/demo-login", timeout=30)
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(
        f"{BASE}/api/customers", headers=HA,
        json={"name": f"IT82_Cust_{tag}", "phone": "9998887777", "state": "AP"},
        timeout=30,
    ).json()
    veh = httpx.post(
        f"{BASE}/api/vehicles", headers=HA,
        json={"vehicle_number": f"AP99IT82{tag[:4].upper()}", "vehicle_type": "own"},
        timeout=30,
    ).json()

    trip_refs = [
        ("2026-08-01", "CINV-101"),
        ("2026-08-02", "CINV-102"),
        ("2026-08-03", "CINV-103"),
        ("2026-08-04", ""),  # blank — must stay blank
    ]
    trip_ids = []
    for d, ref in trip_refs:
        trip = httpx.post(
            f"{BASE}/api/trips", headers=HA,
            json={
                "customer_id": cust["id"], "date": d,
                "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
                "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1000,
                "from_location": "K", "to_location": "V",
                "customer_reference_number": ref,
            },
            timeout=30,
        ).json()
        assert trip["customer_reference_number"] == ref
        trip_ids.append(trip["id"])

    inv = httpx.post(
        f"{BASE}/api/invoices", headers=HA,
        json={
            "customer_id": cust["id"], "invoice_date": "2026-08-05",
            "trip_ids": trip_ids, "hsn_sac": "996791",
            "gst_treatment": "rcm", "due_date": "2026-09-04",
        },
        timeout=30,
    ).json()
    return {"invoice": inv, "trip_ids": trip_ids, "refs": [r for _, r in trip_refs]}


def test_trips_api_preserves_per_trip_customer_ref(invoice_with_mixed_refs):
    """The trips-by-ids API used by InvoiceView returns each trip's own ref, never inherited."""
    ids = ",".join(invoice_with_mixed_refs["trip_ids"])
    trips = httpx.get(f"{BASE}/api/trips?ids={ids}", headers=HA, timeout=30).json()
    # Order isn't guaranteed — map by id
    by_id = {t["id"]: t for t in trips}
    for tid, expected_ref in zip(invoice_with_mixed_refs["trip_ids"], invoice_with_mixed_refs["refs"]):
        assert by_id[tid]["customer_reference_number"] == expected_ref, \
            f"trip {tid} expected ref='{expected_ref}' got '{by_id[tid].get('customer_reference_number')}'"


def test_invoice_pdf_shows_all_customer_refs_per_trip(invoice_with_mixed_refs):
    """The Invoice PDF must contain EVERY non-blank Customer Ref, one per trip."""
    inv_id = invoice_with_mixed_refs["invoice"]["id"]
    r = httpx.get(f"{BASE}/api/invoices/{inv_id}/pdf", headers=HA, timeout=60)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    reader = PdfReader(io.BytesIO(r.content))
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    # Every non-blank ref must appear in the PDF text
    for ref in ("CINV-101", "CINV-102", "CINV-103"):
        assert ref in full_text, f"Customer Ref '{ref}' missing from Invoice PDF"
    # The column header must exist too
    assert "Cust Ref" in full_text, "Invoice PDF must include the 'Cust Ref' column header"


def test_blank_ref_does_not_inherit(invoice_with_mixed_refs):
    """Trip 4 has blank customer_reference_number — it MUST NOT show CINV-103 (previous trip's ref)."""
    ids = ",".join(invoke := invoice_with_mixed_refs["trip_ids"])
    trips = httpx.get(f"{BASE}/api/trips?ids={ids}", headers=HA, timeout=30).json()
    by_id = {t["id"]: t for t in trips}
    blank_trip = by_id[invoke[3]]
    assert blank_trip["customer_reference_number"] == "", \
        f"blank trip must have empty customer_reference_number, got '{blank_trip.get('customer_reference_number')}'"
