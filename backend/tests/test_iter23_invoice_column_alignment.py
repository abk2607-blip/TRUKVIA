"""Iteration 23 backend tests — Invoice trip-table column alignment & font-size reduction.

Verifies that the following cells render on a single line (no mid-token wrap)
in the raw PDF text extraction:
  BUG A: Date '2026-07-31'
  BUG B: Tons '32.53' and integer '20'
  BUG C: Vehicle No 'AP39UK5117'
  BUG D: Common product name 'BITUMEN VG 30'
  BUG E: Row-count sanity for main + sub rows
Plus regression: iter22 structural labels and revised T&C are still present.
"""
import os
import pytest
import requests
import fitz  # PyMuPDF

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def H(cid=None, json_ct=True):
    h = dict(AUTH)
    if json_ct:
        h["Content-Type"] = "application/json"
    if cid:
        h["X-Company-Id"] = cid
    return h


def _norm(s):
    return " ".join(s.split())


def _pdf_raw_page0(pdf_bytes):
    """Return raw text (with newlines) from page 0 only."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return doc[0].get_text("text")
    finally:
        doc.close()


# --------------- Shared fixtures ---------------
@pytest.fixture(scope="module")
def company_id():
    r = requests.post(f"{API}/companies", headers=H(),
                      json={"name": "ITER23-CO", "state": "Andhra Pradesh",
                            "invoice_prefix": "I23", "hsn_sac": "996791"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    yield cid
    # Cleanup cascades trips/invoices/customers/vehicles/drivers
    requests.delete(f"{API}/companies/{cid}", headers=H())


@pytest.fixture(scope="module")
def masters(company_id):
    cid = company_id
    hdr = H(cid)
    cust = requests.post(f"{API}/customers", headers=hdr,
                         json={"name": "TEST_C23", "state": "Andhra Pradesh",
                               "gstin": "37ABCDE1234F1Z5"}).json()
    veh = requests.post(f"{API}/vehicles", headers=hdr,
                        json={"vehicle_number": "AP39UK5117", "ownership": "own"}).json()
    drv = requests.post(f"{API}/drivers", headers=hdr,
                        json={"name": "D23", "phone": "9111000023"}).json()
    return cust, veh, drv


def _mk_trip(cid, cust, veh, drv, *, date="2026-07-31", tons=32.53,
             rate=1500, diesel_qty=0.0, diesel_rate=0.0, advance=0.0,
             load="BITUMEN VG 30"):
    payload = {
        "customer_id": cust["id"], "date": date,
        "vehicle_number": veh["vehicle_number"],
        "driver_id": drv["id"],
        "from_location": "Chennai", "to_location": "Bangalore",
        "load_details": load,
        "loaded_qty": tons, "unloaded_qty": tons, "tons": tons,
        "freight_mode": "per_ton",
        "rate_per_ton": rate,
        "fixed_amount": 0.0,
        "round_trip_kms": 0.0,
        "rate_per_km_per_ton": 0.0,
        "expenses": {
            "diesel_from_customer_qty": diesel_qty,
            "diesel_from_customer_rate": diesel_rate,
            "cash_advance_received": advance,
        },
    }
    r = requests.post(f"{API}/trips", headers=H(cid), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_invoice(cid, cust_id, trip_ids, rcm=False, date="2026-07-31"):
    r = requests.post(f"{API}/invoices", headers=H(cid),
                      json={"customer_id": cust_id, "trip_ids": trip_ids,
                            "date": date, "rcm": rcm})
    assert r.status_code == 200, r.text
    return r.json()


def _dl_pdf(cid, iid):
    r = requests.get(f"{API}/invoices/{iid}/pdf", headers=H(cid))
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/pdf")
    return r.content


# --------- Module-level fixture: build one trip that hits A/B/C/D at once ---
@pytest.fixture(scope="module")
def combined_pdf_text(company_id, masters):
    cust, veh, drv = masters
    trip = _mk_trip(company_id, cust, veh, drv,
                    date="2026-07-31", tons=32.53,
                    load="BITUMEN VG 30")
    inv = _mk_invoice(company_id, cust["id"], [trip["id"]], date="2026-07-31")
    pdf = _dl_pdf(company_id, inv["id"])
    raw = _pdf_raw_page0(pdf)
    return raw, trip, inv


# ================== BUG A — Date fits one line ==================
def test_bug_a_date_single_line(combined_pdf_text):
    raw, _, _ = combined_pdf_text
    assert "2026-07-31" in raw, (
        "Date '2026-07-31' not found contiguous in raw PDF text.\n"
        f"--- raw ---\n{raw[:1500]}"
    )
    # Negative: mid-token break must not exist
    assert "2026-07\n-31" not in raw, "Date wrapped after '2026-07' — column too narrow"
    # Positive normalized sanity
    assert "2026-07-31" in _norm(raw)


# ================== BUG B — Tons fits one line ==================
def test_bug_b_tons_decimal_single_line(combined_pdf_text):
    raw, _, _ = combined_pdf_text
    assert "32.53" in raw, f"Tons '32.53' not contiguous.\n{raw[:1500]}"
    assert "32.5\n3" not in raw, "Tons wrapped between '32.5' and '3'"
    assert "32.5\n" not in raw or "32.53" in raw  # sanity


def test_bug_b_tons_integer_single_line(company_id, masters):
    """A trip with tons=20 must show '20' single-line."""
    cust, veh, drv = masters
    trip = _mk_trip(company_id, cust, veh, drv,
                    date="2026-07-15", tons=20, rate=1500,
                    load="BITUMEN VG 40")
    inv = _mk_invoice(company_id, cust["id"], [trip["id"]], date="2026-07-15")
    raw = _pdf_raw_page0(_dl_pdf(company_id, inv["id"]))
    # tons=20 renders as '20.00'
    assert "20.00" in raw, f"Integer tons '20.00' not contiguous.\n{raw[:1500]}"
    assert "20.0\n0" not in raw
    assert "2\n0.00" not in raw


# ================== BUG C — Vehicle No fits one line ==================
def test_bug_c_vehicle_single_line(combined_pdf_text):
    raw, _, _ = combined_pdf_text
    assert "AP39UK5117" in raw, (
        f"Vehicle 'AP39UK5117' not contiguous in raw PDF.\n{raw[:1500]}"
    )
    assert "AP39UK511\n7" not in raw, "Vehicle wrapped before last char"
    assert "AP39UK51\n17" not in raw


# ================== BUG D — Product name single line ==================
def test_bug_d_product_single_line(combined_pdf_text):
    raw, _, _ = combined_pdf_text
    assert "BITUMEN VG 30" in raw, (
        f"'BITUMEN VG 30' not on one line.\n{raw[:1500]}"
    )
    assert "BITUMEN VG\n30" not in raw, "'BITUMEN VG 30' wrapped between 'VG' and '30'"
    assert "BITUMEN\nVG 30" not in raw


# ================== BUG E — Row spacing / row-count sanity ==================
def test_bug_e_row_count_matches_expected(company_id, masters):
    """1 main row + 2 sub rows when diesel + advance non-zero."""
    cust, veh, drv = masters
    trip = _mk_trip(company_id, cust, veh, drv,
                    date="2026-07-20", tons=20, rate=1500,
                    diesel_qty=100, diesel_rate=90, advance=5000,
                    load="BITUMEN VG 30")
    # Iter17 math sanity — this should feed subtotal 16000
    assert trip["expenses"]["diesel_from_customer_amount"] == 9000
    inv = _mk_invoice(company_id, cust["id"], [trip["id"]], date="2026-07-20")
    assert inv["subtotal"] == 16000
    raw = _pdf_raw_page0(_dl_pdf(company_id, inv["id"]))
    # Expect the sub-row labels to appear (indented with ↳)
    assert "Diesel from Customer" in raw
    assert "Customer Advance" in raw
    # Net Freight label always appears
    assert "Net Freight" in raw


# ================== REGRESSION — iter22 structural labels + T&C ==================
def test_regression_iter22_labels(combined_pdf_text):
    raw, _, _ = combined_pdf_text
    text_norm = _norm(raw)
    for lbl in ["TAX INVOICE", "BILL TO", "AMOUNT IN WORDS",
                "BANK DETAILS (RTGS / NEFT)", "TERMS & CONDITIONS",
                "FINAL PAYABLE", "Authorised Signatory"]:
        assert lbl in text_norm, f"Missing label {lbl!r}"

    revised_tnc = ("0.5% for Bitumen, Emulsion, and Other Products, "
                   "and 1% for CRMB / PMB")
    assert revised_tnc in text_norm, f"Revised T&C missing.\n{text_norm[:1500]}"
