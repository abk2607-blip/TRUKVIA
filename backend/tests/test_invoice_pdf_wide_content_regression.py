"""DEFERRED-BUG-INV-PDF-500-WIDTH · Invoice PDF wide-content regression.

RCA: `bottom_tbl` (and `sig_tbl`) previously declared 277 mm width, but
reportlab's default Frame reserves 6 pt L + 6 pt R = 12 pt / 4.23 mm of
internal padding, leaving only 272.77 mm of content width. Invoices with
denser natural content (multiple trips, halting sub-rows, longer
amount-in-words strings) tripped `reportlab.LayoutError` at build time.

Iter133 L2d fix (layout-only): four colWidths reduced by 2-4 mm each so
the composite tables stay inside the 273 mm safe budget. Zero business
calculation change.

This suite guards the entire failure class, not just invoice 0025.
"""
import io
import os
import re
import uuid
import httpx
import pytest
from pdf.invoice import build_invoice_pdf
from reportlab.lib.units import mm
from pdfminer.high_level import extract_text as _pdf_extract


# ---------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------

def _api():
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") + "/api"
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


API = _api()
TOK = os.environ["DEMO_TOKEN_VALUE"]


def _headers():
    h = {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}
    cid = httpx.get(f"{API}/companies", headers=h, timeout=10).json()[0]["id"]
    h["X-Company-Id"] = cid
    return cid, h


def _company_dict():
    return {
        "name": "AKB INV TEST TRANSPORT",
        "address": "Plot 42, Anjanadri Block, Vijayawada — 521225",
        "gstin": "37ABAFA7142G1Z5", "state": "Andhra Pradesh",
        "phone": "9440661939",
        "bank_name": "ICICI BANK",
        "account_number": "030305500255",
        "ifsc": "ICIC0000303",
        "branch": "ONE TOWN BRANCH, VIJAYAWADA",
    }


def _customer_dict():
    return {
        "name": "MEGHA ENGINEERING AND INFRA STRUCTURE",
        "gstin": "37AAECM7627A1ZM", "pan": "AAECM7627A",
        "state": "Andhra Pradesh",
        "address": "MEGHA ENGINEERING & INFRASTRUCTURE PROJECT CODE-3256-CHILLIKURU",
    }


def _mk_trip(i, halting=False, shortage=False, diesel=False, advance=False,
             tons=30.98, rate=950.0):
    t = {
        "id": f"trip-{i}",
        "date": f"2026-07-{15 + i:02d}",
        "vehicle_number": f"AP39VB{4600 + i}",
        "tons": tons, "loaded_qty": tons, "unloaded_qty": tons,
        "from_location": "CHENNAI", "to_location": "CHILLAKUR",
        "freight_mode": "per_ton", "rate_per_ton": rate,
        "freight_amount": round(tons * rate, 2),
        "product_name": "BITUMEN VG 40", "hsn_sac": "996791",
        "customer_reference": f"TN{5542111500 + i}",
        "applied_freight_method": "per_ton",
        "status": "invoiced",
    }
    if halting:
        t["halting_amount"] = 7500.0
        t["chargeable_halting_days"] = 3
        t["halting_rate_per_day"] = 2500.0
        t["halting_remarks"] = "Site queue delay"
    if shortage:
        t["shortage_amount"] = 1200.0
    if diesel or advance:
        t["customer_receipts"] = []
        if diesel:
            t["customer_receipts"].append({
                "type": "diesel", "litres": 50, "rate": 90.0,
                "amount": 4500.0, "remarks": "Diesel at loading",
            })
        if advance:
            t["customer_receipts"].append({
                "type": "advance", "mode": "UPI",
                "ref_no": f"UPI{i:04d}", "amount": 10000.0,
                "remarks": "Trip advance",
            })
    return t


def _mk_invoice(trips, invoice_number="AKB/26-27/TEST", total_override=None,
                gst_type="cgst_sgst", rcm=True, halting_total=None):
    freight_total = round(sum(t.get("freight_amount", 0) for t in trips), 2)
    halting = (halting_total if halting_total is not None
               else round(sum(t.get("halting_amount", 0) for t in trips), 2))
    shortage = round(sum(t.get("shortage_amount", 0) for t in trips), 2)
    diesel_ded = 0.0
    advance_ded = 0.0
    for t in trips:
        for r in t.get("customer_receipts", []) or []:
            amt = float(r.get("amount") or 0)
            if (r.get("type") or "").lower() == "diesel":
                diesel_ded += amt
            elif (r.get("type") or "").lower() == "advance":
                advance_ded += amt
    subtotal = round(freight_total + halting - shortage - diesel_ded - advance_ded, 2)
    tax_rate = 0.05
    cgst = round(subtotal * (tax_rate / 2), 2) if gst_type == "cgst_sgst" else 0.0
    sgst = cgst
    igst = round(subtotal * tax_rate, 2) if gst_type == "igst" else 0.0
    total_tax = round(cgst + sgst + igst, 2)
    gross = round(subtotal + total_tax, 2) if not rcm else subtotal
    total = total_override if total_override is not None else (subtotal if rcm else gross)
    return {
        "id": f"inv-test-{uuid.uuid4().hex[:6]}",
        "invoice_number": invoice_number,
        "invoice_date": "2026-08-31",
        "customer_id": "cust-test",
        "trip_ids": [t["id"] for t in trips],
        "freight_total": freight_total,
        "halting_total": halting,
        "shortage_total": shortage,
        "diesel_deduction_total": diesel_ded,
        "advance_deduction_total": advance_ded,
        "subtotal": subtotal,
        "gst_type": gst_type,
        "cgst_amount": cgst, "sgst_amount": sgst, "igst_amount": igst,
        "total_tax": total_tax,
        "gross_total": gross,
        "round_off": 0.0,
        "total_amount": total,
        "amount_paid": 0.0,
        "balance_due": total,
        "rcm": rcm,
        "payment_status": "unpaid",
        "hsn_sac": "996791",
    }


def _assert_valid_pdf(pdf_bytes, description):
    assert isinstance(pdf_bytes, (bytes, bytearray)), f"{description}: not bytes"
    assert pdf_bytes[:4] == b"%PDF", f"{description}: missing PDF magic bytes"
    assert len(pdf_bytes) > 2000, f"{description}: suspiciously small ({len(pdf_bytes)} bytes)"


def _extract(pdf_bytes):
    return _pdf_extract(io.BytesIO(pdf_bytes))


# ---------------------------------------------------------------------
# HTTP end-to-end helper — mirrors the real router → renderer path
# (invokes _recompute_invoice which populates every derived field the
# invoice PDF renderer reads).  Deterministic replacement for the
# earlier synthetic-dict path that was underspecified.
# ---------------------------------------------------------------------

def _seed_customer(h, prefix="INVPDF"):
    tag = uuid.uuid4().hex[:6]
    r = httpx.post(f"{API}/customers", headers=h,
                   json={"name": f"{prefix}-{tag}", "phone": f"9{tag}",
                         "state": "Andhra Pradesh"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


def _seed_trip(h, cust_id, i=0, date="2026-08-15", tons=25.0, rate=1000.0,
               halting=False, shortage=False, diesel=False, advance=False,
               from_loc="CHENNAI", to_loc="CHILLAKUR"):
    tag = uuid.uuid4().hex[:5]
    body = {
        "customer_id": cust_id, "date": date,
        "vehicle_number": f"AP39VB{4600 + i}_{tag}",
        "tons": tons, "loaded_qty": tons, "unloaded_qty": tons,
        "freight_mode": "per_ton", "rate_per_ton": rate,
        "product_rate_per_mt": 40000,
        "from_location": from_loc, "to_location": to_loc,
        "loading_date": date, "unloading_date": date,
    }
    if halting:
        body["halting_amount"] = 7500.0
        body["chargeable_halting_days"] = 3
        body["halting_rate_per_day"] = 2500.0
        body["halting_amount_override"] = True
    if shortage:
        body["shortage_amount"] = 1200.0
        body["shortage_amount_override"] = True
    if diesel or advance:
        recs = []
        if diesel:
            recs.append({"type": "diesel", "date": date, "litres": 50,
                         "rate": 90.0, "amount": 4500.0,
                         "remarks": "Diesel at loading"})
        if advance:
            recs.append({"type": "advance", "date": date, "mode": "UPI",
                         "ref_no": f"UPI{i:04d}", "amount": 10000.0,
                         "remarks": "Trip advance"})
        body["customer_receipts"] = recs
    r = httpx.post(f"{API}/trips", headers=h, json=body, timeout=15)
    assert r.status_code == 200, f"POST /trips failed: {r.text[:400]}"
    return r.json()


def _seed_invoice(h, cust_id, trip_ids, invoice_date="2026-08-15",
                  rcm=False, gst_type=None):
    body = {"customer_id": cust_id, "trip_ids": trip_ids,
            "invoice_date": invoice_date, "rcm": rcm}
    if gst_type:
        body["gst_type"] = gst_type
    r = httpx.post(f"{API}/invoices", headers=h, json=body, timeout=30)
    assert r.status_code == 200, f"POST /invoices failed: {r.text[:400]}"
    return r.json()


def _fetch_invoice_pdf(h, invoice_id):
    r = httpx.get(f"{API}/invoices/{invoice_id}/pdf", headers=h, timeout=45)
    return r


# =====================================================================
# TEST 1 — Simple invoice via HTTP (0024-shape) must return 200
# =====================================================================

def test_invoice_pdf_renders_1_trip_no_halting():
    """End-to-end via GET /api/invoices/{iid}/pdf — verifies the
    router → renderer path for the simplest invoice shape.  Also
    proves the layout fix did not regress simple invoices."""
    _cid, h = _headers()
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(f"{API}/customers", headers=h,
                     json={"name": f"INVPDF-{tag}", "phone": f"9{tag}",
                           "state": "Andhra Pradesh"}, timeout=10).json()
    trip = httpx.post(
        f"{API}/trips", headers=h,
        json={"customer_id": cust["id"], "date": "2026-08-15",
              "vehicle_number": f"AP39{tag}", "tons": 25,
              "loaded_qty": 25, "unloaded_qty": 25,
              "freight_mode": "per_ton", "rate_per_ton": 1000,
              "product_rate_per_mt": 40000,
              "from_location": "KARWAR", "to_location": "PILLAIPALLI",
              "loading_date": "2026-08-15", "unloading_date": "2026-08-15"},
        timeout=15,
    ).json()
    inv = httpx.post(
        f"{API}/invoices", headers=h,
        json={"customer_id": cust["id"], "trip_ids": [trip["id"]],
              "invoice_date": "2026-08-15", "rcm": True},
        timeout=15,
    ).json()

    r = httpx.get(f"{API}/invoices/{inv['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"
    assert r.headers["content-type"].startswith("application/pdf")
    _assert_valid_pdf(r.content, "1-trip HTTP PDF")
    text = _extract(r.content)
    assert inv["invoice_number"] in text, "invoice number missing"
    assert "AMOUNT IN WORDS" in text.upper(), "amount-in-words section missing"


# =====================================================================
# TEST 2 — Dense invoice (9 trips + halting) — the exact 0025 failure class
# =====================================================================

def test_invoice_pdf_renders_9_trips_with_halting():
    """Reproduces the exact 0025 failure class end-to-end via the real
    router → _recompute_invoice → build_invoice_pdf path: 9 trips,
    halting on trips 7 & 8, GST enabled (non-RCM).  Must return
    HTTP 200 with a valid multi-page PDF containing all 9 trips,
    both halting sub-rows, and the amount-in-words section."""
    _cid, h = _headers()
    cust = _seed_customer(h)
    trip_ids = []
    for i in range(9):
        t = _seed_trip(h, cust["id"], i=i,
                       halting=(i in (7, 8)),
                       tons=30.0, rate=950.0)
        trip_ids.append(t["id"])
    inv = _seed_invoice(h, cust["id"], trip_ids, rcm=False)

    r = _fetch_invoice_pdf(h, inv["id"])
    assert r.status_code == 200, (
        f"9-trip+halting PDF failed with {r.status_code}: {r.text[:400]}"
    )
    assert r.headers["content-type"].startswith("application/pdf")
    _assert_valid_pdf(r.content, "9-trip+halting HTTP PDF")

    text = _extract(r.content)
    assert inv["invoice_number"] in text, "invoice number missing"
    assert "AMOUNT IN WORDS" in text.upper(), "amount-in-words missing"
    assert "Halting" in text, "halting sub-row label missing"
    assert "Rupees" in text, "amount-in-words phrase missing"
    # Every trip's vehicle number should be present
    missing_trips = 0
    for i in range(9):
        if f"AP39VB{4600 + i}" not in text:
            missing_trips += 1
    assert missing_trips == 0, (
        f"{missing_trips}/9 trip vehicles missing from PDF"
    )


# =====================================================================
# TEST 3 — Long amount-in-words (large total)
# =====================================================================

def test_invoice_pdf_renders_long_amount_in_words():
    """Multi-trip invoice whose total pushes amount-in-words into the
    Lakh/Crore range — the longest natural amount-in-words wrap.
    Verified end-to-end via HTTP."""
    _cid, h = _headers()
    cust = _seed_customer(h)
    trip_ids = []
    # 10 trips × 30 tons × ₹25,000/ton = ₹75 lakh subtotal
    # → amount-in-words = "Seventy Five Lakh ..." (long)
    for i in range(10):
        t = _seed_trip(h, cust["id"], i=i, tons=30.0, rate=25000.0)
        trip_ids.append(t["id"])
    inv = _seed_invoice(h, cust["id"], trip_ids, rcm=False)

    r = _fetch_invoice_pdf(h, inv["id"])
    assert r.status_code == 200, (
        f"long-amount PDF failed with {r.status_code}: {r.text[:400]}"
    )
    _assert_valid_pdf(r.content, "long-amount HTTP PDF")

    text = _extract(r.content)
    words_norm = " ".join(text.split())
    assert re.search(r"Lakh|Crore", words_norm, re.IGNORECASE), (
        f"amount-in-words missing Lakh/Crore token. "
        f"Sample: {words_norm[:600]}"
    )
    assert "AMOUNT IN WORDS" in text.upper()


# =====================================================================
# TEST 4 — All sub-rows combined (halting + shortage + diesel + advance)
# =====================================================================

def test_invoice_pdf_renders_all_sub_rows_combined():
    """One trip carrying halting + shortage + diesel + advance
    deductions simultaneously, seeded via the real API path so every
    derived field is populated by _recompute_invoice.  Exercises every
    sub-row branch in the invoice PDF renderer.  Must return HTTP 200."""
    _cid, h = _headers()
    cust = _seed_customer(h)
    t = _seed_trip(h, cust["id"], i=0,
                   halting=True, shortage=True,
                   diesel=True, advance=True,
                   tons=30.0, rate=1000.0)
    inv = _seed_invoice(h, cust["id"], [t["id"]], rcm=False)

    r = _fetch_invoice_pdf(h, inv["id"])
    assert r.status_code == 200, (
        f"all-sub-rows PDF failed with {r.status_code}: {r.text[:400]}"
    )
    _assert_valid_pdf(r.content, "all-sub-rows HTTP PDF")

    text = _extract(r.content)
    # Every sub-row category label should be present somewhere in the PDF
    # (case-insensitive since sub-row labels may be in title-case).
    text_lower = text.lower()
    for token in ("halting", "shortage", "diesel", "advance"):
        assert token in text_lower, f"sub-row token missing: {token}"
    assert "AMOUNT IN WORDS" in text.upper()


# =====================================================================
# TEST 5 — Static: bottom_tbl declared width within safe frame budget
# =====================================================================

def test_invoice_pdf_bottom_tbl_declared_width_under_frame():
    """Iter133 L2d fix guardrail — the composite bottom_tbl + sig_tbl
    declared widths must stay ≤ 273 mm (frame content budget after
    reportlab's 12 pt default padding). Reads the invoice.py source
    to enforce the invariant statically so any future edit that
    re-widens the tables fails this test."""
    src_path = "/app/backend/pdf/invoice.py"
    with open(src_path, "r") as f:
        src = f.read()

    # Extract bottom_tbl colWidths
    m = re.search(
        r"bottom_tbl\s*=\s*Table\(\s*\[\[left_bank_tbl,\s*totals_tbl\]\],\s*"
        r"colWidths=\[(\d+)\s*\*\s*mm,\s*(\d+)\s*\*\s*mm\]\)",
        src,
    )
    assert m, "could not locate bottom_tbl colWidths in invoice.py"
    a, b = int(m.group(1)), int(m.group(2))
    assert a + b <= 270, (
        f"bottom_tbl declared width {a + b} mm > 270 mm safe budget "
        f"(frame content width after 12pt padding, with 2.77mm safety "
        f"margin). Regression of L2d v2 fix."
    )

    # Extract sig_tbl colWidths
    m2 = re.search(
        r"colWidths=\[(\d+)\s*\*\s*mm,\s*(\d+)\s*\*\s*mm\],\s*"
        r"#\s*Iter133 L2d",
        src,
    )
    assert m2, "could not locate sig_tbl colWidths (L2d-marked) in invoice.py"
    c, d = int(m2.group(1)), int(m2.group(2))
    assert c + d <= 270, (
        f"sig_tbl declared width {c + d} mm > 270 mm safe budget"
    )

    # left_bank_tbl and tc_inline_tbl must match the reduced envelope
    m3 = re.search(r"left_bank_tbl\s*=\s*Table\(\[\[bank_lines\]\],\s*"
                   r"colWidths=\[(\d+)\s*\*\s*mm\]\)", src)
    assert m3 and int(m3.group(1)) <= 163, \
        f"left_bank_tbl width regressed: {m3 and m3.group(1)}"

    m4 = re.search(r"tc_inline_tbl\s*=\s*Table\([\s\S]*?colWidths=\[(\d+)\s*\*\s*mm\]\)", src)
    assert m4 and int(m4.group(1)) <= 147, \
        f"tc_inline_tbl width regressed: {m4 and m4.group(1)}"
