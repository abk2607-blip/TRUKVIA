"""Iter127b · Invoice PDF pagination — "Page X of Y" footer (Feb 2026, user-approved Option A).

Contract locked here (uniform behaviour across all invoices):
  * 1-page invoice → "Page 1 of 1"
  * 2-page invoice → "Page 1 of 2" + "Page 2 of 2"
  * 3+ page invoice → every page correctly numbered

Guardrails:
  * Existing invoice content unchanged.
  * No changes to totals / freight / shortage / tax / IGST / CGST / SGST /
    LR / Ship-To / GSTIN / Unload Date / any Iter127c logic.
  * Existing margins, orientation, fonts and signature placement unchanged.
  * Signature block appears only on the LAST page (natural Platypus flow).
  * Footer sits bottom-right in the 8 mm bottom margin — no overlap with
    any flowable.
"""
from __future__ import annotations

import io
import sys
sys.path.insert(0, "/app/backend")
from pdf import build_invoice_pdf
from models import Trip
from services import _compute_trip


def _company():
    return {"id": "co", "legal_name": "TEST TRANSPORT PVT LTD",
            "gstin": "36AABCT1234E1Z5", "state": "Telangana",
            "address": "Hyd", "phone": "9000000000",
            "bank_name": "SBI", "account_number": "12345", "ifsc": "SBIN0000001",
            "branch": "Hyd Branch"}


def _customer():
    return {"id": "c", "name": "TEST CUST", "state": "Karnataka",
            "gstin": "29BVMPK0275K1Z3", "address": "Hubli", "phone": "9110000099",
            "ship_sites": []}


def _invoice(trip_ids):
    return {"id": "inv", "invoice_number": "TEST/PAGES/001",
            "invoice_date": "2026-08-27", "customer_id": "c", "trip_ids": trip_ids,
            "hsn_sac": "996791", "gst_type": "igst",
            "subtotal": 0, "gst_rate": 18,
            "cgst_amount": 0, "sgst_amount": 0, "igst_amount": 0,
            "total_amount": 0, "amount_paid": 0, "balance_due": 0}


def _trip(idx):
    t = Trip(id=f"t{idx}", user_id="u", customer_id="c", vehicle_number=f"AP39XX{idx:04}",
             date="2026-08-27", tons=30.0, unloaded_qty=29.85, unloading_date="2026-08-30",
             load_details="Bitumen VG 40", from_location="KARWAR", to_location="NAGARKURNOOL",
             freight_mode="per_ton", rate_per_ton=100.0,
             applied_freight_method="per_ton_loading",
             product_rate_per_mt=50000.0,
             applied_customer_shortage_limit=0.5,
             applied_customer_shortage_limit_type="pct",
             applied_customer_shortage_method="net_shortage")
    _compute_trip(t)
    return t.model_dump()


def _extract_pages(pdf_bytes):
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(pdf_bytes))
    return [(p.extract_text() or "") for p in rd.pages]


def _make_pdf(n_trips):
    trips = [_trip(i) for i in range(n_trips)]
    inv = _invoice([t["id"] for t in trips])
    return build_invoice_pdf(_company(), _customer(), inv, trips)


# -------------------------------------------------------------------------
# Contract locks
# -------------------------------------------------------------------------

def test_1_single_page_shows_page_1_of_1():
    pages = _extract_pages(_make_pdf(1))
    assert len(pages) == 1
    assert "Page 1 of 1" in pages[0]


def test_2_two_page_invoice_numbered_correctly():
    """Enough trips to spill into a 2nd page. 20 trips fills the trip table
    beyond the page height in landscape A4."""
    pdf = _make_pdf(20)
    pages = _extract_pages(pdf)
    assert len(pages) >= 2, f"Expected ≥2 pages, got {len(pages)}"
    y = len(pages)
    for i, txt in enumerate(pages, start=1):
        assert f"Page {i} of {y}" in txt, f"Page {i} missing correct footer. Got:\n{txt[-200:]}"


def test_3_three_or_more_page_invoice_numbered_correctly():
    """60 trips guarantees 3+ pages."""
    pdf = _make_pdf(60)
    pages = _extract_pages(pdf)
    assert len(pages) >= 3, f"Expected ≥3 pages, got {len(pages)}"
    y = len(pages)
    for i, txt in enumerate(pages, start=1):
        assert f"Page {i} of {y}" in txt


def test_4_signature_block_only_on_last_page():
    """Iter114 signature block must appear on the last page only — never
    repeated on earlier pages when the invoice spans multiple pages."""
    pages = _extract_pages(_make_pdf(20))
    if len(pages) < 2:
        return  # single page — nothing to compare
    for i, txt in enumerate(pages[:-1]):
        assert "Authorised Signatory" not in txt, f"signature leaked onto page {i+1}"
    assert "Authorised Signatory" in pages[-1]


def test_5_footer_never_appears_inside_trip_rows():
    """Guardrail — 'Page X of Y' must not appear as part of any trip cell
    text. It's drawn on the canvas below the frame."""
    pages = _extract_pages(_make_pdf(20))
    import re
    for i, txt in enumerate(pages):
        # count occurrences of any "Page N of Y" pattern per page — must be
        # exactly 1 (from the canvas footer).
        matches = re.findall(r"Page \d+ of \d+", txt)
        assert len(matches) == 1, f"page {i+1} has {len(matches)} footer glyphs: {matches}"


def test_6_deterministic_page_count_two_pass():
    """Two-pass render must produce the same page count on repeated calls."""
    n1 = len(_extract_pages(_make_pdf(20)))
    n2 = len(_extract_pages(_make_pdf(20)))
    assert n1 == n2


def test_7_source_guardrail_footer_font_and_position():
    src = open("/app/backend/pdf/invoice.py").read()
    assert "def _invoice_page_footer_factory" in src
    assert "setFont(_UNI_FONT, 7.5)" in src
    assert '#64748B' in src            # C_MUTED
    assert "drawRightString(page_size[0] - 10 * mm, 5 * mm" in src


def test_8_source_guardrail_two_pass_wiring():
    src = open("/app/backend/pdf/invoice.py").read()
    # Two-pass render present — accept either the original inline pattern
    # or the Iter133 L2d v3 fresh-story-per-pass pattern (fresh flowables
    # per build eliminate reportlab state pollution on dense invoices).
    assert (
        "_count_doc.build(list(story))" in src
        or "_count_doc.build(_make_story())" in src
    ), "two-pass count build missing"
    # Final build uses footer callbacks (accept both story shapes).
    assert (
        "doc.build(story, onFirstPage=_footer_cb, onLaterPages=_footer_cb)" in src
        or "doc.build(_make_story(), onFirstPage=_footer_cb, onLaterPages=_footer_cb)" in src
    ), "two-pass render build with footer callbacks missing"
    # Old single-call form must be gone.
    assert "\n    doc.build(story)\n" not in src


def test_9_kolvekar_regression_unchanged():
    """Iter127c LOCKED — KOLVEKAR-style trips still produce identical
    business content. Only new addition is the 'Page X of Y' glyph."""
    cust = {"id":"c","name":"KOLVEKAR LOGISTICS","state":"Karnataka",
            "gstin":"29BVMPK0275K1Z3","address":"Hubli","phone":"9110000099",
            "ship_sites":[{"id":"ship_x","site_name":"MRGR CONSTRUCTIONS",
                          "address":"Nagarkurnool-509209","gstin":"36AAUFM1425D1ZC",
                          "state":"Telangana","state_code":"36","pincode":"509209"}]}
    def _kt(load, unload, ud):
        t = Trip(id="t", user_id="u", customer_id="c", vehicle_number="V",
                 date="2026-08-13", tons=load, unloaded_qty=unload, unloading_date=ud,
                 ship_site_id="ship_x", to_location="NAGARKURNOOL",
                 freight_mode="per_ton", rate_per_ton=100.0,
                 applied_freight_method="per_ton_loading",
                 product_rate_per_mt=50000.0,
                 applied_customer_shortage_limit=0.5,
                 applied_customer_shortage_limit_type="pct",
                 applied_customer_shortage_method="net_shortage")
        _compute_trip(t)
        return t.model_dump()
    trips = [_kt(29.5, 29.44, "2026-08-16"), _kt(34.7, 34.57, "2026-08-22")]
    inv = _invoice([t["id"] for t in trips])
    pdf = build_invoice_pdf(_company(), cust, inv, trips)
    text = "\n".join(_extract_pages(pdf))
    assert "MRGR CONSTRUCTIONS" in text
    assert "16-Aug-2026" in text
    assert "22-Aug-2026" in text
    assert "Page 1 of" in text                    # footer present


def test_10_raghava_pre_unload_regression_unchanged():
    """Iter127c LOCKED — pre-unload invoice still shows — for shortage cells
    and preserves freight. Only new addition is the footer."""
    t = Trip(id="t", user_id="u", customer_id="c", vehicle_number="V",
             date="2026-08-27", tons=29.670, unloaded_qty=0, unloading_date="",
             freight_mode="per_ton", rate_per_ton=100.0,
             applied_freight_method="per_ton_loading",
             product_rate_per_mt=50000.0,
             applied_customer_shortage_limit=0.5,
             applied_customer_shortage_limit_type="pct",
             applied_customer_shortage_method="net_shortage")
    _compute_trip(t)
    pdf = build_invoice_pdf(_company(), _customer(), _invoice(["t"]), [t.model_dump()])
    text = "\n".join(_extract_pages(pdf))
    assert text.count("29.670") == 1              # Load MT cell only, no fabricated shortage
    assert "2,967" in text                        # freight preserved
    assert "Page 1 of 1" in text


def test_11_no_overlap_first_page_content_versus_footer():
    """Footer sits below the story frame's y-range (8 mm bottom margin)
    so no flowable can render at y < 8 mm. We assert the extracted
    story text doesn't share a line with the footer glyph — pypdf's
    line-based extract keeps them on separate 'lines'."""
    pages = _extract_pages(_make_pdf(1))
    lines = pages[0].splitlines()
    footer_lines = [i for i, l in enumerate(lines) if "Page 1 of 1" in l]
    assert len(footer_lines) == 1
    # Any signature/trip content line preceding the footer must not itself
    # contain 'Page 1 of 1'.
    for l in lines[:footer_lines[0]]:
        assert "Page 1 of 1" not in l


def test_12_footer_present_on_every_page():
    """Bruter-force lock: for a 20-trip multi-page invoice, EACH extracted
    page must contain exactly one 'Page N of Y' line."""
    pages = _extract_pages(_make_pdf(20))
    import re
    for i, txt in enumerate(pages):
        found = re.findall(r"Page \d+ of \d+", txt)
        assert len(found) == 1, f"page {i+1}: expected 1 footer, got {found}"
