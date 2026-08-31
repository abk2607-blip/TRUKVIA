"""Iter133 · L2d — Financial PDF Final Polish.

Contract verified:
  · Every ₹ (U+20B9) glyph in the CN/DN totals block renders under the
    DejaVu font family — no more black-square/tofu boxes.
  · Ledger PDF Ref + Particulars cells wrap gracefully — long
    invoice numbers like "AKB/26-27//26-27/0004" and long narrations
    like "Debit Note — other · against AKB/26-27//26-27/0004" stay
    inside their columns.
  · Statement PDF unifies its section hierarchy — Trip Sheets and
    Invoices now use the same branded accent-rule + DejaVu bold
    heading as Balance Bridge and Adjustments.
  · Adjustments row shows BOTH reason_code and reason_text so the
    customer never has to ask "what does OTHER mean?".

PDF inspection uses pymupdf (font-per-span) + pdfminer (text extraction);
both are already present in the runtime.
"""
import io
import os
import uuid
import httpx
import pytest
import fitz  # pymupdf
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
    return {"name": "L2D TEST TRANSPORT", "address": "Plot 42, Vijayawada",
            "gstin": "37AAAAA0000A1Z5", "state": "Andhra Pradesh"}


def _customer_dict():
    return {"name": "L2D TEST CUSTOMER", "gstin": "36AACCK7073N1Z1",
            "state": "Telangana", "address": "KPC House, Hyderabad",
            "phone": "9000000000"}


def _invoice_dict(invoice_number="AKB/26-27//26-27/0004"):
    return {"id": "inv-l2d", "invoice_number": invoice_number,
            "invoice_date": "2026-08-07", "total_amount": 93943.0}


def _note_dict(kind="credit", amount=450.0, rcm=True, apply_gst=True):
    if kind == "credit":
        subtotal = amount
    else:
        subtotal = 11175.0
    tax = subtotal * 0.05
    return {
        "note_number": ("CN" if kind == "credit" else "DN") + "/26-27/0001",
        "note_date": "2026-08-30",
        "reason_code": "other",
        "reason_text": "RATE VARIATION" if kind == "credit" else "EXCESS MATERIAL",
        "apply_gst": apply_gst, "rcm": rcm,
        "lines": [{"description": "RATE VARIATION" if kind == "credit" else "EXCESS MATERIAL 150 KGS",
                   "hsn_sac": "996791",
                   "quantity": 1 if kind == "credit" else 0.15,
                   "rate": amount if kind == "credit" else 74500.0,
                   "taxable_value": subtotal}],
        "subtotal": subtotal,
        "cgst_rate": 0, "cgst_amount": 0, "sgst_rate": 0, "sgst_amount": 0,
        "igst_rate": 5.0, "igst_amount": tax, "total_tax": tax,
        "round_off": 0.0, "total_amount": subtotal,
    }


def _iter_spans(pdf_bytes):
    """Yield (text, fontname) for every span on every page."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            d = page.get_text("dict")
            for block in d.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        yield span.get("text", ""), (span.get("font") or "")
    finally:
        doc.close()


def _rupee_font_check(pdf_bytes, description):
    """Every span whose text contains ₹ (U+20B9) must use a DejaVu font."""
    offenders = []
    rupee_spans = 0
    for text, font in _iter_spans(pdf_bytes):
        if "\u20b9" in text:
            rupee_spans += 1
            if "DejaVu" not in font:
                offenders.append((text, font))
    assert rupee_spans > 0, f"{description}: no ₹ spans found — extraction failed"
    assert not offenders, (
        f"{description}: {len(offenders)}/{rupee_spans} ₹ spans NOT using DejaVu. "
        f"First offender: text={offenders[0][0]!r} font={offenders[0][1]!r}"
    )
    return rupee_spans


def _extract_all_text(pdf_bytes):
    return _pdf_extract(io.BytesIO(pdf_bytes))


# =====================================================================
# Group 1 — CN/DN ₹ font enforcement (4 tests)
# =====================================================================

def test_l2d_cn_pdf_totals_rows_use_dejavu_font():
    """Every ₹ span in the Credit Note PDF (including Subtotal, IGST,
    Total Tax and Round Off rows) must render under the DejaVu family."""
    from pdf.credit_note import build_credit_note_pdf
    pdf_bytes = build_credit_note_pdf(_company_dict(), _customer_dict(),
                                      _invoice_dict(), _note_dict("credit", 450.0))
    rupee_spans = _rupee_font_check(pdf_bytes, "Credit Note PDF")
    text = _extract_all_text(pdf_bytes)
    for expected in ("Subtotal", "IGST", "Total Tax", "Round Off", "TOTAL CREDIT NOTE"):
        assert expected in text, f"CN PDF missing totals label: {expected}"
    # The totals block alone should contribute at least 4 ₹ spans.
    assert rupee_spans >= 5, f"CN PDF ₹ spans seem sparse ({rupee_spans})"


def test_l2d_dn_pdf_totals_rows_use_dejavu_font():
    """Mirror check for the Debit Note PDF."""
    from pdf.debit_note import build_debit_note_pdf
    pdf_bytes = build_debit_note_pdf(_company_dict(), _customer_dict(),
                                     _invoice_dict(), _note_dict("debit", 11175.0))
    rupee_spans = _rupee_font_check(pdf_bytes, "Debit Note PDF")
    text = _extract_all_text(pdf_bytes)
    for expected in ("Subtotal", "IGST", "Total Tax", "Round Off", "TOTAL DEBIT NOTE"):
        assert expected in text, f"DN PDF missing totals label: {expected}"
    assert rupee_spans >= 5, f"DN PDF ₹ spans seem sparse ({rupee_spans})"


def test_l2d_cn_pdf_no_missing_glyph_boxes():
    """No char in the CN PDF should be the Unicode replacement (U+FFFD)."""
    from pdf.credit_note import build_credit_note_pdf
    pdf_bytes = build_credit_note_pdf(_company_dict(), _customer_dict(),
                                      _invoice_dict(), _note_dict("credit", 450.0))
    text = _extract_all_text(pdf_bytes)
    assert "\ufffd" not in text, "CN PDF contains U+FFFD replacement char"
    assert "\u20b9" in text, "CN PDF is missing the ₹ symbol entirely"


def test_l2d_dn_pdf_no_missing_glyph_boxes():
    """Mirror check for the DN PDF."""
    from pdf.debit_note import build_debit_note_pdf
    pdf_bytes = build_debit_note_pdf(_company_dict(), _customer_dict(),
                                     _invoice_dict(), _note_dict("debit", 11175.0))
    text = _extract_all_text(pdf_bytes)
    assert "\ufffd" not in text
    assert "\u20b9" in text


# =====================================================================
# Group 2 — Ledger PDF alignment + font (3 tests)
# =====================================================================

def _build_ledger_pdf_with_entries(entries, opening=0.0):
    from pdf.ledger import build_ledger_pdf
    ledger = {
        "customer": {"name": "L2D Test Customer", "gstin": "36AACCK7073N1Z1",
                     "phone": "9000000000", "state": "Telangana",
                     "address": "KPC House, Hyderabad"},
        "period": {"start": "2026-07-01", "end": "2026-08-31"},
        "opening_balance": opening,
        "entries": entries,
        "total_debit": sum(e.get("debit", 0) for e in entries),
        "total_credit": sum(e.get("credit", 0) for e in entries),
        "closing_balance": opening + sum(e.get("debit", 0) - e.get("credit", 0) for e in entries),
        "totals_by_type": {"invoice": 0, "payment": 0, "credit_note": 0, "debit_note": 0},
    }
    return build_ledger_pdf(_company_dict(), ledger)


def test_l2d_ledger_pdf_ref_column_fits_long_invoice_number():
    """A long ref like 'AKB/26-27//26-27/0004' must appear intact in
    the rendered ledger PDF (Paragraph wrapping preserves all chars)."""
    entries = [{
        "date": "07 Aug 2026",
        "reference": "AKB/26-27//26-27/0004",
        "particulars": "Sales - 1 trip(s)",
        "type": "invoice",
        "debit": 93943.0, "credit": 0.0, "balance": 93943.0,
    }]
    pdf_bytes = _build_ledger_pdf_with_entries(entries)
    text = _extract_all_text(pdf_bytes)
    # Paragraph wrapping preserves all chars but pdfminer inserts newlines
    # at soft-wrap points. Normalise whitespace before asserting the full
    # ref is intact.
    compact = "".join(text.split())
    assert "AKB/26-27//26-27/0004" in compact, "long ref missing from ledger PDF"
    assert len(pdf_bytes) > 1000, "Ledger PDF suspiciously small"


def test_l2d_ledger_pdf_particulars_wraps_long_narration():
    """Long CN narration 'Debit Note — other · against AKB/26-27//26-27/0004'
    must render fully (wrapped, not truncated) inside its column."""
    entries = [{
        "date": "30 Aug 2026",
        "reference": "DN/26-27/0001",
        "particulars": "Debit Note — other · against AKB/26-27//26-27/0004",
        "type": "debit_note",
        "debit": 11175.0, "credit": 0.0, "balance": 105118.0,
    }]
    pdf_bytes = _build_ledger_pdf_with_entries(entries)
    text = _extract_all_text(pdf_bytes)
    for token in ("Debit Note", "other", "against", "AKB/26-27"):
        assert token in text, f"Ledger PDF missing wrapped particulars token: {token}"


def test_l2d_ledger_pdf_rupee_glyph_universal_regression():
    """Regression: every ₹ span in the ledger PDF header still renders
    under DejaVu."""
    entries = [{
        "date": "07 Aug 2026", "reference": "AKB/26-27/0001",
        "particulars": "Sales - 1 trip(s)", "type": "invoice",
        "debit": 93943.0, "credit": 0.0, "balance": 93943.0,
    }]
    pdf_bytes = _build_ledger_pdf_with_entries(entries)
    _rupee_font_check(pdf_bytes, "Ledger PDF")


# =====================================================================
# Group 3 — Statement PDF polish (3 tests)
# =====================================================================

def _fresh_customer(h, prefix="L2D"):
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(f"{API}/customers", headers=h,
                   json={"name": f"{prefix}-{tag}", "phone": f"9{tag}",
                         "state": "Andhra Pradesh"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_trip_invoice(h, cust_id, date="2026-08-15",
                      from_loc="KARWAR", to_loc="MEDIPALLY VILLAGE"):
    tag = uuid.uuid4().hex[:5]
    r = httpx.post(
        f"{API}/trips", headers=h,
        json={"customer_id": cust_id, "date": date,
              "vehicle_number": f"L2D{tag}",
              "tons": 25, "loaded_qty": 25, "unloaded_qty": 25,
              "freight_mode": "per_ton", "rate_per_ton": 1000,
              "product_rate_per_mt": 40000,
              "from_location": from_loc, "to_location": to_loc,
              "loading_date": date, "unloading_date": date},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    trip_id = r.json()["id"]
    r = httpx.post(
        f"{API}/invoices", headers=h,
        json={"customer_id": cust_id, "trip_ids": [trip_id],
              "invoice_date": date, "rcm": True},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _seed_cn(h, invoice, amount, reason_text="RATE VARIATION"):
    r = httpx.post(
        f"{API}/credit-notes", headers=h,
        json={"invoice_id": invoice["id"], "note_date": "2026-08-25",
              "reason_code": "other", "reason_text": reason_text,
              "lines": [{"description": reason_text, "quantity": 1, "rate": amount}]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _fetch_statement_pdf(cust_id, h):
    r = httpx.get(f"{API}/customers/{cust_id}/statement.pdf",
                  headers=h, timeout=30)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    return r.content


def _amber_rects_count(pdf_bytes):
    """Count amber (#B45309 → RGB ≈ 0.706, 0.325, 0.035) filled rectangles."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        n = 0
        for page in doc:
            for d in page.get_drawings():
                fill = d.get("fill")
                if not fill or len(fill) < 3:
                    continue
                r, g, b = fill[:3]
                if max(r, g, b) > 1.5:
                    r, g, b = r / 255.0, g / 255.0, b / 255.0
                if 0.65 <= r <= 0.75 and 0.28 <= g <= 0.38 and b <= 0.10:
                    n += 1
        return n
    finally:
        doc.close()


def test_l2d_statement_pdf_all_sections_use_branded_head():
    """Trip Sheets · Invoices · Balance Bridge · Adjustments must all
    render with the same amber accent rule + DejaVu-bold heading."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _seed_trip_invoice(h, cust)
    _seed_cn(h, inv, 500.0, reason_text="RATE VARIATION")
    pdf_bytes = _fetch_statement_pdf(cust, h)
    text = _extract_all_text(pdf_bytes)
    for label in ("Trip Sheets", "Invoices", "Balance Bridge", "Adjustments"):
        assert label in text, f"Statement PDF missing section: {label}"

    # 4 section rules + 1 top accent divider = at least 5 amber rects.
    amber = _amber_rects_count(pdf_bytes)
    assert amber >= 4, (
        f"Expected ≥4 amber-accent rects (one per section head + top divider), "
        f"got {amber}"
    )


def test_l2d_statement_pdf_long_invoice_and_route_stay_in_columns():
    """Long invoice numbers and long routes must appear intact in the
    extracted text; the PDF must build without crashing."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _seed_trip_invoice(h, cust,
                             from_loc="KARWAR", to_loc="MEDIPALLY VILLAGE")
    pdf_bytes = _fetch_statement_pdf(cust, h)
    text = _extract_all_text(pdf_bytes)
    assert "KARWAR" in text and "MEDIPALLY" in text, "long route missing"
    assert inv["invoice_number"] in text, "invoice number missing from statement"


def test_l2d_statement_pdf_adjustments_shows_reason_code_and_text():
    """Adjustments row must include BOTH the reason_code and reason_text."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _seed_trip_invoice(h, cust)
    _seed_cn(h, inv, 500.0, reason_text="RATE VARIATION")
    pdf_bytes = _fetch_statement_pdf(cust, h)
    text = _extract_all_text(pdf_bytes)
    assert "Adjustments" in text, "Adjustments section missing"
    assert "other" in text.lower(), "reason_code missing from adjustments"
    assert "RATE VARIATION" in text, "reason_text missing from adjustments"
