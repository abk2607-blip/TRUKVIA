"""Iteration 21 backend tests — Per-company Logo isolation + MSME/Udyam field
persistence and rendering in Invoice PDF T&C.

Covers:
- Logo upload/delete scoped by X-Company-Id (no leak / overwrite)
- Logo appears in each company's invoice PDF (different bytes)
- udyam_registration save/load per company via PUT/GET /company
- MSME/Udyam string appears in invoice PDF T&C when set; absent when blank
"""
import io
import os
import base64
import struct
import zlib

import pytest
import requests

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


def _png_bytes(color_rgb):
    """Build a valid 1x1 PNG with given color to make L1/L2 differ."""
    r, g, b = color_rgb
    def chunk(t, d):
        c = zlib.crc32(t + d) & 0xffffffff
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", c)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00" + bytes([r, g, b])
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.fixture(scope="module")
def companies():
    coA = requests.post(f"{API}/companies", headers=H(),
                        json={"name": "ISO-LOGO-A", "state": "Andhra Pradesh",
                              "invoice_prefix": "LGA", "hsn_sac": "996791"}).json()
    coB = requests.post(f"{API}/companies", headers=H(),
                        json={"name": "ISO-LOGO-B", "state": "Telangana",
                              "invoice_prefix": "LGB", "hsn_sac": "996791"}).json()
    yield coA["id"], coB["id"]
    requests.delete(f"{API}/companies/{coA['id']}", headers=H())
    requests.delete(f"{API}/companies/{coB['id']}", headers=H())


# ---------------- BUG 1: per-company logo isolation ----------------
def test_01_logo_upload_scoped_per_company(companies):
    cidA, cidB = companies
    L1 = _png_bytes((255, 0, 0))
    L2 = _png_bytes((0, 0, 255))

    rA = requests.post(f"{API}/company/logo", headers=H(cidA, json_ct=False),
                       files={"file": ("A.png", L1, "image/png")})
    assert rA.status_code == 200, rA.text
    rB = requests.post(f"{API}/company/logo", headers=H(cidB, json_ct=False),
                       files={"file": ("B.png", L2, "image/png")})
    assert rB.status_code == 200, rB.text

    gA = requests.get(f"{API}/company", headers=H(cidA)).json()
    gB = requests.get(f"{API}/company", headers=H(cidB)).json()

    assert gA["logo"], "Company A logo empty"
    assert gB["logo"], "Company B logo empty"
    assert gA["logo"] != gB["logo"], "LEAK: Company A and B share the same logo"

    # sanity — the data URLs should decode back to our exact bytes
    b64A = gA["logo"].split(",", 1)[1]
    b64B = gB["logo"].split(",", 1)[1]
    assert base64.b64decode(b64A) == L1
    assert base64.b64decode(b64B) == L2

    # GET /companies must return distinct logos too
    all_cos = requests.get(f"{API}/companies", headers=H()).json()
    by_id = {c["id"]: c for c in all_cos}
    assert by_id[cidA]["logo"] == gA["logo"]
    assert by_id[cidB]["logo"] == gB["logo"]
    assert by_id[cidA]["logo"] != by_id[cidB]["logo"]


def test_02_delete_logo_scoped(companies):
    cidA, cidB = companies
    # Delete A's logo
    r = requests.delete(f"{API}/company/logo", headers=H(cidA))
    assert r.status_code == 200, r.text

    gA = requests.get(f"{API}/company", headers=H(cidA)).json()
    gB = requests.get(f"{API}/company", headers=H(cidB)).json()
    assert gA["logo"] == "", f"Company A logo not cleared: {gA['logo'][:60]}"
    assert gB["logo"] != "", "Company B logo unexpectedly cleared (leak)"

    # Re-upload A for downstream test
    L1 = _png_bytes((255, 0, 0))
    r = requests.post(f"{API}/company/logo", headers=H(cidA, json_ct=False),
                      files={"file": ("A.png", L1, "image/png")})
    assert r.status_code == 200


# ---------------- BUG 2: udyam save/load per company ----------------
def test_03_udyam_save_and_load_per_company(companies):
    cidA, cidB = companies
    # Fetch current then patch fields
    cA = requests.get(f"{API}/company", headers=H(cidA)).json()
    cB = requests.get(f"{API}/company", headers=H(cidB)).json()
    cA["udyam_registration"] = "UDYAM-AP-01-COMPANY-A"
    cB["udyam_registration"] = "UDYAM-TS-05-COMPANY-B"
    # strip fields the Company model may not want on write
    for d in (cA, cB):
        d.pop("is_default", None)

    rA = requests.put(f"{API}/company", headers=H(cidA), json=cA)
    rB = requests.put(f"{API}/company", headers=H(cidB), json=cB)
    assert rA.status_code == 200, rA.text
    assert rB.status_code == 200, rB.text

    gA = requests.get(f"{API}/company", headers=H(cidA)).json()
    gB = requests.get(f"{API}/company", headers=H(cidB)).json()
    assert gA["udyam_registration"] == "UDYAM-AP-01-COMPANY-A"
    assert gB["udyam_registration"] == "UDYAM-TS-05-COMPANY-B"
    # And logos still isolated (regression)
    assert gA["logo"] != gB["logo"]


# ---------------- Helpers to build an invoice ----------------
def _make_invoice(cid, name_suffix):
    hdr = H(cid)
    cust = requests.post(f"{API}/customers", headers=hdr,
                         json={"name": f"TEST_C_{name_suffix}", "state": "Andhra Pradesh",
                               "gstin": "37ABCDE1234F1Z5"}).json()
    veh = requests.post(f"{API}/vehicles", headers=hdr,
                        json={"vehicle_number": f"AP01{name_suffix}0001", "ownership": "own"}).json()
    drv = requests.post(f"{API}/drivers", headers=hdr,
                        json={"name": f"D_{name_suffix}", "phone": "9111000001"}).json()
    trip = requests.post(f"{API}/trips", headers=hdr, json={
        "customer_id": cust["id"], "date": "2026-02-11",
        "trip_no": f"T-{name_suffix}",
        "vehicle_number": veh["vehicle_number"],
        "driver_id": drv["id"],
        "from_location": "A", "to_location": "B",
        "loaded_qty": 10, "unloaded_qty": 10, "tons": 10,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
    })
    assert trip.status_code == 200, trip.text
    trip = trip.json()
    inv = requests.post(f"{API}/invoices", headers=hdr,
                        json={"customer_id": cust["id"], "trip_ids": [trip["id"]],
                              "date": "2026-02-11"})
    assert inv.status_code == 200, inv.text
    return inv.json(), trip, cust


def _pdf_text(pdf_bytes):
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(p.get_text() for p in doc)


# ---------------- BUG 1c: Logo appears in PDF for correct company ----------------
def test_04_invoice_pdfs_differ_between_companies(companies):
    cidA, cidB = companies
    invA, _, _ = _make_invoice(cidA, "AA")
    invB, _, _ = _make_invoice(cidB, "BB")

    rA = requests.get(f"{API}/invoices/{invA['id']}/pdf", headers=H(cidA))
    rB = requests.get(f"{API}/invoices/{invB['id']}/pdf", headers=H(cidB))
    assert rA.status_code == 200 and rA.headers.get("content-type", "").startswith("application/pdf")
    assert rB.status_code == 200 and rB.headers.get("content-type", "").startswith("application/pdf")
    assert len(rA.content) > 5000, f"PDF A too small: {len(rA.content)}"
    assert len(rB.content) > 5000, f"PDF B too small: {len(rB.content)}"
    # save for downstream tests
    pytest._pdfA = rA.content
    pytest._pdfB = rB.content
    pytest._invA = invA["id"]
    pytest._invB = invB["id"]


# ---------------- BUG 2b: Udyam string appears in PDF T&C ----------------
def test_05_udyam_appears_in_pdf_tnc(companies):
    textA = _pdf_text(pytest._pdfA)
    textB = _pdf_text(pytest._pdfB)
    assert "MSME / Udyam Registration No: UDYAM-AP-01-COMPANY-A" in textA, \
        f"Company A PDF missing Udyam. First 800 chars:\n{textA[:800]}"
    assert "MSME / Udyam Registration No: UDYAM-TS-05-COMPANY-B" in textB, \
        f"Company B PDF missing Udyam. First 800 chars:\n{textB[:800]}"
    # And no cross-contamination
    assert "COMPANY-B" not in textA
    assert "COMPANY-A" not in textB


def test_06_no_udyam_line_when_blank(companies):
    cidA, _ = companies
    # Clear A's udyam
    cA = requests.get(f"{API}/company", headers=H(cidA)).json()
    cA["udyam_registration"] = ""
    cA.pop("is_default", None)
    r = requests.put(f"{API}/company", headers=H(cidA), json=cA)
    assert r.status_code == 200

    invA, _, _ = _make_invoice(cidA, "NB")
    rp = requests.get(f"{API}/invoices/{invA['id']}/pdf", headers=H(cidA))
    assert rp.status_code == 200
    text = _pdf_text(rp.content)
    assert "MSME / Udyam" not in text, f"Blank udyam should not produce line. Got:\n{text[:500]}"

    # Restore for other tests
    cA["udyam_registration"] = "UDYAM-AP-01-COMPANY-A"
    requests.put(f"{API}/company", headers=H(cidA), json=cA)


# ---------------- Regression: master isolation still holds ----------------
def test_07_master_isolation_regression(companies):
    cidA, cidB = companies
    # Quick smoke: customers created under A must not appear for B
    listA = requests.get(f"{API}/customers", headers=H(cidA)).json()
    listB = requests.get(f"{API}/customers", headers=H(cidB)).json()
    a_names = {c.get("name") for c in listA}
    b_names = {c.get("name") for c in listB}
    # There must be at least one A-scoped test customer and B-scoped test customer,
    # and they must not overlap.
    assert a_names.isdisjoint(b_names), f"Master leak: intersection {a_names & b_names}"
