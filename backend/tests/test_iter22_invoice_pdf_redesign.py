"""Iteration 22 backend tests — Invoice PDF redesign + revised T&C clause #2.

Covers:
- BUG 1: Structural labels present, legacy column headers absent
- BUG 1b: Per-ton trip w/ diesel + advance renders correctly
- BUG 1c: Fixed / round-trip mode renders without error
- BUG 2: Revised T&C clause verbatim; old wording gone
- REGRESSION: Iter17 diesel/advance math still intact
- REGRESSION: Iter21 MSME/Udyam still renders / suppressed when blank
- REGRESSION: Iter19 multi-company w/ logos still produce distinct PDFs
"""
import io
import os
import base64
import struct
import zlib

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
TOKEN = "test_session_bitumen_2026"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def H(cid=None, json_ct=True):
    h = dict(AUTH)
    if json_ct:
        h["Content-Type"] = "application/json"
    if cid:
        h["X-Company-Id"] = cid
    return h


def _png(color):
    r, g, b = color
    def chunk(t, d):
        c = zlib.crc32(t + d) & 0xffffffff
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", c)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" + bytes([r, g, b]))
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _pdf_text(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(p.get_text() for p in doc)


# --------------- Shared fixtures ---------------
@pytest.fixture(scope="module")
def companies():
    coA = requests.post(f"{API}/companies", headers=H(),
                       json={"name": "ITER22-CO-A", "state": "Andhra Pradesh",
                             "invoice_prefix": "I22A", "hsn_sac": "996791"}).json()
    coB = requests.post(f"{API}/companies", headers=H(),
                       json={"name": "ITER22-CO-B", "state": "Telangana",
                             "invoice_prefix": "I22B", "hsn_sac": "996791"}).json()
    # Upload a logo on each
    requests.post(f"{API}/company/logo", headers=H(coA["id"], json_ct=False),
                  files={"file": ("A.png", _png((255, 0, 0)), "image/png")})
    requests.post(f"{API}/company/logo", headers=H(coB["id"], json_ct=False),
                  files={"file": ("B.png", _png((0, 0, 255)), "image/png")})
    yield coA["id"], coB["id"]
    requests.delete(f"{API}/companies/{coA['id']}", headers=H())
    requests.delete(f"{API}/companies/{coB['id']}", headers=H())


def _mk_master(cid, tag):
    hdr = H(cid)
    cust = requests.post(f"{API}/customers", headers=hdr,
                        json={"name": f"TEST_C22_{tag}", "state": "Andhra Pradesh",
                              "gstin": "37ABCDE1234F1Z5"}).json()
    veh = requests.post(f"{API}/vehicles", headers=hdr,
                       json={"vehicle_number": f"AP01{tag}22", "ownership": "own"}).json()
    drv = requests.post(f"{API}/drivers", headers=hdr,
                       json={"name": f"D22_{tag}", "phone": "9111000022"}).json()
    return cust, veh, drv


def _mk_trip(cid, cust, veh, drv, *, mode="per_ton", tons=20, rate=1500,
             fixed_amount=0.0, round_trip_kms=0.0, rate_per_km_per_ton=0.0,
             diesel_qty=0.0, diesel_rate=0.0, advance=0.0,
             load="Bitumen VG 40"):
    payload = {
        "customer_id": cust["id"], "date": "2026-02-15",
        "vehicle_number": veh["vehicle_number"],
        "driver_id": drv["id"],
        "from_location": "Chennai", "to_location": "Bangalore",
        "load_details": load,
        "loaded_qty": tons, "unloaded_qty": tons, "tons": tons,
        "freight_mode": mode,
        "rate_per_ton": rate if mode == "per_ton" else 0,
        "fixed_amount": fixed_amount,
        "round_trip_kms": round_trip_kms,
        "rate_per_km_per_ton": rate_per_km_per_ton,
        "expenses": {
            "diesel_from_customer_qty": diesel_qty,
            "diesel_from_customer_rate": diesel_rate,
            "cash_advance_received": advance,
        },
    }
    r = requests.post(f"{API}/trips", headers=H(cid), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_invoice(cid, cust_id, trip_ids, rcm=False):
    r = requests.post(f"{API}/invoices", headers=H(cid),
                      json={"customer_id": cust_id, "trip_ids": trip_ids,
                            "date": "2026-02-15", "rcm": rcm})
    assert r.status_code == 200, r.text
    return r.json()


def _dl_pdf(cid, iid):
    r = requests.get(f"{API}/invoices/{iid}/pdf", headers=H(cid))
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/pdf"), r.headers
    assert len(r.content) > 5000, f"PDF suspiciously small: {len(r.content)} bytes"
    return r.content


# ================== BUG 1: Structural labels ==================
def test_01_structural_labels_present_and_legacy_absent(companies):
    cidA, _ = companies
    cust, veh, drv = _mk_master(cidA, "STRUC")
    trip = _mk_trip(cidA, cust, veh, drv, mode="per_ton", tons=10, rate=1000)
    inv = _mk_invoice(cidA, cust["id"], [trip["id"]])
    pdf = _dl_pdf(cidA, inv["id"])
    text = _pdf_text(pdf)

    required = [
        "TAX INVOICE", "BILL TO", "Invoice No", "HSN/SAC", "GST Type",
        "Rate", "Amount", "AMOUNT IN WORDS", "BANK DETAILS (RTGS / NEFT)",
        "TERMS & CONDITIONS", "FINAL PAYABLE", "Authorised Signatory",
    ]
    missing = [k for k in required if k not in text]
    assert not missing, f"Missing labels: {missing}\n--- TEXT ---\n{text[:2000]}"

    # Legacy column headers must not exist as headers
    # 'Cust Inv:' inline label under Route is allowed; but standalone 'Cust Inv'
    # header column should not exist.  We rely on the specific old strings.
    forbidden = ["Rate Mode", "Rate/KMs"]
    present = [k for k in forbidden if k in text]
    assert not present, f"Legacy headers still present: {present}"


# ================== BUG 1b: Per-ton + diesel + advance ==================
def test_02_per_ton_with_diesel_and_advance(companies):
    cidA, _ = companies
    cust, veh, drv = _mk_master(cidA, "PT")
    trip = _mk_trip(cidA, cust, veh, drv, mode="per_ton", tons=20, rate=1500,
                   diesel_qty=100, diesel_rate=90, advance=5000)
    assert trip["expenses"]["diesel_from_customer_amount"] == 9000
    inv = _mk_invoice(cidA, cust["id"], [trip["id"]], rcm=True)
    # Iter17 math regression
    assert inv["subtotal"] == 16000, inv
    assert inv["total_amount"] == 16000, inv  # RCM: no tax
    pdf = _dl_pdf(cidA, inv["id"])
    text = _pdf_text(pdf)
    # Normalize whitespace to tolerate PDF column wrap (e.g., "Bitumen VG\n40")
    text_norm = _normalize(text)
    for needle in [veh["vehicle_number"], trip["load_details"], "→",
                   "Per Ton", "Less: Diesel from Customer",
                   "Less: Customer Advance", "Net Freight (Taxable)"]:
        assert _normalize(needle) in text_norm, f"Missing {needle!r} in PDF\n{text[:1500]}"


# ================== BUG 1c: Fixed mode renders ==================
def test_03_fixed_mode_renders(companies):
    cidA, _ = companies
    cust, veh, drv = _mk_master(cidA, "FIX")
    trip = _mk_trip(cidA, cust, veh, drv, mode="fixed",
                   fixed_amount=25000, tons=15)
    inv = _mk_invoice(cidA, cust["id"], [trip["id"]], rcm=True)
    pdf = _dl_pdf(cidA, inv["id"])
    text = _pdf_text(pdf)
    assert "Fixed" in text, f"'Fixed' label missing.\n{text[:1500]}"
    assert inv["subtotal"] == 25000, inv


# ================== BUG 2: Revised T&C clause verbatim ==================
REVISED_TNC = (
    "Shortage or excess in quantity will be accounted for only beyond "
    "a permissible variation of 0.5% for Bitumen, Emulsion, and Other Products, "
    "and 1% for CRMB / PMB."
)


def _normalize(s):
    return " ".join(s.split())


def test_04_revised_tnc_present_and_old_absent(companies):
    cidA, _ = companies
    cust, veh, drv = _mk_master(cidA, "TNC")
    trip = _mk_trip(cidA, cust, veh, drv, mode="per_ton", tons=5, rate=1000)
    inv = _mk_invoice(cidA, cust["id"], [trip["id"]])
    pdf = _dl_pdf(cidA, inv["id"])
    text_norm = _normalize(_pdf_text(pdf))

    assert _normalize(REVISED_TNC) in text_norm, \
        f"Revised T&C missing.\n--- normalized text ---\n{text_norm[:2500]}"

    # Old standalone bullet phrasing must be gone.
    old_bullet = "Shortage or excess in Bitumen quantity will be accounted for " \
                 "only beyond a permissible variation of 1%."
    assert _normalize(old_bullet) not in text_norm, "Old T&C wording still present"


# ================== REGRESSION: Iter21 MSME/Udyam ==================
def test_05_udyam_appears_when_set(companies):
    cidA, _ = companies
    # Set udyam on company A
    cA = requests.get(f"{API}/company", headers=H(cidA)).json()
    cA["udyam_registration"] = "UDYAM-AP-01-COMPANY-TEST"
    cA.pop("is_default", None)
    r = requests.put(f"{API}/company", headers=H(cidA), json=cA)
    assert r.status_code == 200, r.text

    cust, veh, drv = _mk_master(cidA, "UDY")
    trip = _mk_trip(cidA, cust, veh, drv, mode="per_ton", tons=5, rate=1000)
    inv = _mk_invoice(cidA, cust["id"], [trip["id"]])
    pdf = _dl_pdf(cidA, inv["id"])
    text = _pdf_text(pdf)
    assert "MSME / Udyam Registration No: UDYAM-AP-01-COMPANY-TEST" in text, \
        f"MSME/Udyam clause missing.\n{text[:2000]}"


def test_06_udyam_absent_when_blank(companies):
    _, cidB = companies
    # Ensure B has blank udyam
    cB = requests.get(f"{API}/company", headers=H(cidB)).json()
    cB["udyam_registration"] = ""
    cB.pop("is_default", None)
    r = requests.put(f"{API}/company", headers=H(cidB), json=cB)
    assert r.status_code == 200, r.text

    cust, veh, drv = _mk_master(cidB, "NOUDY")
    trip = _mk_trip(cidB, cust, veh, drv, mode="per_ton", tons=5, rate=1000)
    inv = _mk_invoice(cidB, cust["id"], [trip["id"]])
    pdf = _dl_pdf(cidB, inv["id"])
    text = _pdf_text(pdf)
    assert "MSME / Udyam" not in text, f"MSME/Udyam should be absent.\n{text[:800]}"


# ================== REGRESSION: Iter19 multi-company w/ logos ==================
def test_07_multi_company_pdfs_generate_and_differ(companies):
    cidA, cidB = companies
    custA, vA, dA = _mk_master(cidA, "MCA")
    custB, vB, dB = _mk_master(cidB, "MCB")
    tA = _mk_trip(cidA, custA, vA, dA, mode="per_ton", tons=5, rate=1000)
    tB = _mk_trip(cidB, custB, vB, dB, mode="per_ton", tons=5, rate=1000)
    iA = _mk_invoice(cidA, custA["id"], [tA["id"]])
    iB = _mk_invoice(cidB, custB["id"], [tB["id"]])
    pA = _dl_pdf(cidA, iA["id"])
    pB = _dl_pdf(cidB, iB["id"])
    assert pA != pB, "Multi-company PDFs must differ"
    # Content-level: each PDF should reference its own company
    tA_txt = _pdf_text(pA)
    tB_txt = _pdf_text(pB)
    assert "ITER22-CO-A" in tA_txt
    assert "ITER22-CO-B" in tB_txt
    assert "ITER22-CO-B" not in tA_txt
    assert "ITER22-CO-A" not in tB_txt
