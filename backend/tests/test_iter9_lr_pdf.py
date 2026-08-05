"""Iteration 9 backend tests: LR PDF changes.
(1) Remove 'Freight Basis' and 'Freight Amount' fields from LR page 1.
(2) 'Unloading Details by Site Officials' rendered column-wise with headers.
(3) Site Officer signature strip rendered column-wise with headers.
(4) Regression: 2-page PDF; operational data only on page 1; T&C on page 2.
"""
import os
import re
import pytest
import requests

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}

BASE_EXP = {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0,
            "firewood": 0, "shortage_amount": 0, "diesel_from_customer_qty": 0,
            "diesel_from_customer_rate": 0, "diesel_from_customer_amount": 0,
            "cash_advance_received": 0}


@pytest.fixture(scope="module")
def customer_id():
    r = requests.post(f"{API}/customers",
                      headers=JSON_HEADERS,
                      json={"name": "TEST_iter9_Customer", "gstin": "29ABCDE1234F1Z5",
                            "state": "Karnataka", "address": "Test Addr",
                            "pincode": "560001"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    yield cid
    try:
        requests.delete(f"{API}/customers/{cid}", headers=HEADERS,
                        params={"reason": "cleanup"})
    except Exception:
        pass


@pytest.fixture(scope="module")
def lr_pdf_pages(customer_id):
    """Create a trip, fetch LR PDF, return (page1_text, page2_text, page_count)."""
    if fitz is None:
        pytest.skip("PyMuPDF not installed")
    body = {
        "customer_id": customer_id,
        "date": "2026-01-15",
        "vehicle_number": "TS09LR909",
        "vehicle_type": "own",
        "tons": 18,
        "freight_mode": "per_ton",
        "rate_per_ton": 1500,
        "expenses": BASE_EXP,
        "lr_number": "LR-TEST-9-001",
        "lr_time": "11:45",
        "consignor_name": "TEST Consignor 9",
        "driver_name": "TEST Driver Nine",
        "driver_mobile": "8888888888",
        "waybill_no": "EWB999888",
        "gross_weight": 30.0,
        "tare_weight": 12.0,
        "from_location": "Chennai",
        "to_location": "Bengaluru",
        "load_details": "Bitumen VG30",
    }
    r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json=body)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    try:
        pdf_resp = requests.get(f"{API}/trips/{tid}/lr", headers=HEADERS)
        assert pdf_resp.status_code == 200, pdf_resp.text
        assert "pdf" in pdf_resp.headers.get("content-type", "").lower()
        doc = fitz.open(stream=pdf_resp.content, filetype="pdf")
        page_count = doc.page_count
        p1 = doc.load_page(0).get_text() if page_count >= 1 else ""
        p2 = doc.load_page(1).get_text() if page_count >= 2 else ""
        yield p1, p2, page_count
    finally:
        try:
            requests.delete(f"{API}/trips/{tid}", headers=HEADERS,
                            params={"reason": "cleanup"})
        except Exception:
            pass


def _norm(s: str) -> str:
    """Collapse whitespace for robust substring matches (handles <br/> line-splits in PDF)."""
    return re.sub(r"\s+", " ", s).strip()


class TestLRPdfFreightRemoved:
    """Feature 1: Freight Basis & Freight Amount removed from LR page 1."""

    def test_freight_basis_not_on_page1(self, lr_pdf_pages):
        p1, _, _ = lr_pdf_pages
        assert "Freight Basis" not in p1, "'Freight Basis' should NOT appear on LR page 1"

    def test_freight_amount_not_on_page1(self, lr_pdf_pages):
        p1, _, _ = lr_pdf_pages
        assert "Freight Amount" not in p1, "'Freight Amount' should NOT appear on LR page 1"


class TestUnloadingDetailsColumnWise:
    """Feature 2: Column-wise 'UNLOADING DETAILS BY SITE OFFICIALS' block."""

    def test_unloading_section_title(self, lr_pdf_pages):
        p1, _, _ = lr_pdf_pages
        assert "UNLOADING DETAILS BY SITE OFFICIALS" in _norm(p1).upper()

    @pytest.mark.parametrize("header", [
        "Date of Arrival",
        "Arrival Time",
        "Unloading Start",
        "Unloading End",
        "Date of Departure",
        "Extra KM",
        "Shortage",   # 'Shortage / Excess (MT)' — search 'Shortage'
        "Temp",
        "Seal",       # 'Seal Status'
        "Remarks",
    ])
    def test_unloading_column_header_present(self, lr_pdf_pages, header):
        p1, _, _ = lr_pdf_pages
        norm = _norm(p1)
        assert header in norm, f"Unloading column header '{header}' missing on page 1"


class TestSiteOfficerSignatureColumnWise:
    """Feature 3: Column-wise Site Officer signature strip."""

    @pytest.mark.parametrize("header", [
        "Site Officer Name",
        "Designation",
        "Mobile",
        "Signature",   # 'Signature & Stamp'
        "Date",        # 'Date & Time' — 'Date' will match; combined check below
    ])
    def test_site_officer_header_present(self, lr_pdf_pages, header):
        p1, _, _ = lr_pdf_pages
        norm = _norm(p1)
        assert header in norm, f"Site Officer signature header '{header}' missing"

    def test_signature_stamp_and_date_time_combined(self, lr_pdf_pages):
        p1, _, _ = lr_pdf_pages
        norm = _norm(p1)
        assert "Signature & Stamp" in norm or "Signature &amp; Stamp" in norm
        assert "Date & Time" in norm or "Date &amp; Time" in norm


class TestLRPdfRegression:
    """Regression: PDF still 2 pages; operational data on page 1; T&C only on page 2."""

    def test_two_pages(self, lr_pdf_pages):
        _, _, pc = lr_pdf_pages
        assert pc == 2, f"Expected 2 pages, got {pc}"

    def test_page1_operational_data(self, lr_pdf_pages):
        p1, _, _ = lr_pdf_pages
        assert "LR-TEST-9-001" in p1
        assert "TS09LR909" in p1
        assert "TEST Driver Nine" in p1
        assert "EWB999888" in p1
        assert "Chennai" in p1
        assert "Bengaluru" in p1
        assert "Bitumen VG30" in p1

    def test_page2_terms_only(self, lr_pdf_pages):
        _, p2, _ = lr_pdf_pages
        assert "TERMS" in p2.upper() and "CONDITIONS" in p2.upper()
        # Operational data must NOT be on T&C page
        assert "TS09LR909" not in p2
        assert "TEST Driver Nine" not in p2
        assert "EWB999888" not in p2
        # Freight Amount / Basis must not appear anywhere either
        assert "Freight Basis" not in p2
        assert "Freight Amount" not in p2
        # Unloading column table must NOT be on page 2
        assert "UNLOADING DETAILS BY SITE OFFICIALS" not in _norm(p2).upper()
