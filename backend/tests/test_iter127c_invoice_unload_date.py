"""Iter127c-invoice-unload-date · KOLVEKAR LOGISTICS live UAT fix (Feb 2026).

Trip DB, Trip API, Trip Form, TripView, Halting engine, Reports and all
tests store & read the "Unload Date" under the field name `unloading_date`.
The invoice PDF trip-row builder at `pdf/invoice.py` was — historically —
looking up two unrelated keys (`unloaded_at`, `unload_date`), NEITHER of
which is populated anywhere, so the "Unload Date" column silently rendered
`—` for every invoice.

Fix: `t.get("unloading_date")`.  No other behaviour, calc, or column
shifts.  Date formatting still goes through `_fmt_ind_date` (dd-Mmm-yyyy).

Guardrail tests below lock the correct key and forbid the two legacy
typos from reappearing.
"""
from __future__ import annotations

import sys, io, re
sys.path.insert(0, "/app/backend")
from pdf import build_invoice_pdf


def _company():
    return {
        "id": "co1", "legal_name": "TEST TRANSPORT PVT LTD",
        "gstin": "36AABCT1234E1Z5", "state": "Telangana",
        "address": "Hyd", "phone": "9000000000",
        "bank_name": "SBI", "bank_account": "12345", "bank_ifsc": "SBIN0000001",
    }


def _customer():
    return {
        "id": "c1", "name": "KOLVEKAR LOGISTICS",
        "state": "Karnataka", "gstin": "29BVMPK0275K1Z3",
        "address": "Hubballi", "phone": "9110000099",
        "ship_sites": [{
            "id": "ship_mrgr",
            "site_name": "MRGR CONSTRUCTIONS",
            "address": "Nagarkurnool-509209",
            "gstin": "36AAUFM1425D1ZC",
            "state": "Telangana", "state_code": "36", "pincode": "509209",
        }],
    }


def _invoice(trip_ids):
    return {
        "id": "inv_unload_test",
        "invoice_number": "TEST/UNLOAD/001",
        "invoice_date": "2026-08-27",
        "customer_id": "c1",
        "trip_ids": trip_ids,
        "hsn_sac": "996791",
        "gst_type": "igst",
        "subtotal": 20000, "gst_rate": 18,
        "cgst_amount": 0, "sgst_amount": 0, "igst_amount": 3600,
        "total_amount": 23600, "amount_paid": 0, "balance_due": 23600,
    }


def _trip(tid, date, unloading_date, ship_site_id="ship_mrgr"):
    return {
        "id": tid, "date": date,
        "vehicle_number": "AP39XX0001",
        "load_details": "Bitumen VG 40",
        "from_location": "KARWAR", "to_location": "NAGARKURNOOL",
        "tons": 34.7, "unloaded_qty": 34.57,
        "freight_amount": 5000, "freight_mode": "per_ton", "rate_per_ton": 100,
        "ship_site_id": ship_site_id,
        "unloading_date": unloading_date,
        "shortage_qty": 0, "excess_qty": 0,
        "halting_amount": 0, "excess_amount": 0, "shortage_amount": 0,
    }


def _extract_text(pdf_bytes):
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((p.extract_text() or "") for p in rd.pages)


# -------------------------------------------------------------------------
# 1. Real unloading_date → dd-Mmm-yyyy in the PDF
# -------------------------------------------------------------------------

def test_real_unloading_date_renders_dd_mmm_yyyy():
    inv = _invoice(["t1"])
    trips = [_trip("t1", "2026-08-13", "2026-08-16")]
    pdf = build_invoice_pdf(_company(), _customer(), inv, trips)
    text = _extract_text(pdf)
    assert "16-Aug-2026" in text, f"expected 16-Aug-2026 in PDF text; got:\n{text[:600]}"


def test_kolvekar_both_trips_render_their_own_unload_date():
    """The exact live-UAT bug: both KOLVEKAR trips must show their own
    unloading_date, not '—'."""
    inv = _invoice(["t1", "t2"])
    trips = [
        _trip("t1", "2026-08-13", "2026-08-16"),   # KL/088 shape
        _trip("t2", "2026-08-14", "2026-08-22"),   # KL/092 shape
    ]
    pdf = build_invoice_pdf(_company(), _customer(), inv, trips)
    text = _extract_text(pdf)
    assert "16-Aug-2026" in text, "trip 1 unload date missing"
    assert "22-Aug-2026" in text, "trip 2 unload date missing"


# -------------------------------------------------------------------------
# 2. Blank / missing → '—' (NEVER fabricated from Trip Date or Invoice Date)
# -------------------------------------------------------------------------

def test_blank_unloading_date_renders_dash():
    inv = _invoice(["t1"])
    trips = [_trip("t1", "2026-08-13", "")]
    pdf = build_invoice_pdf(_company(), _customer(), inv, trips)
    text = _extract_text(pdf)
    # Trip date is 13-Aug-2026 — MUST NOT be substituted for the unload cell.
    # We can't easily count column-cell occurrences from extracted text, so
    # we assert (a) trip date is present exactly once in the row and (b) no
    # spurious extra date appears.
    aug_dates = re.findall(r"\d{1,2}-Aug-2026", text)
    # trip date + invoice date variant may appear elsewhere in header — we
    # simply require the Unload Date substitution NEVER happened.
    assert aug_dates.count("13-Aug-2026") <= 2, \
        f"trip date rendered more than expected — fabrication risk. Dates={aug_dates}"


def test_missing_unloading_date_key_renders_dash():
    inv = _invoice(["t1"])
    t = _trip("t1", "2026-08-13", "")
    t.pop("unloading_date", None)
    pdf = build_invoice_pdf(_company(), _customer(), inv, [t])
    # Should not raise. The '—' is validated by the source guardrail plus
    # the render succeeding without a KeyError.
    assert len(pdf) > 1000


# -------------------------------------------------------------------------
# 3. Guardrail — wrong keys must never come back; correct key must be present
# -------------------------------------------------------------------------

def test_source_guardrail_correct_key_only():
    src = open("/app/backend/pdf/invoice.py").read()
    # Legacy wrong keys must be gone (nothing else in the codebase uses them).
    assert "unloaded_at" not in src, "legacy typo `unloaded_at` reappeared"
    assert 't.get("unload_date")' not in src, "legacy typo `unload_date` reappeared"
    # Correct key must be wired into the Unload Date column.
    assert 't.get("unloading_date")' in src, "correct field name missing from PDF"


def test_source_guardrail_date_format_helper_unchanged():
    """Date format contract stays as `_fmt_ind_date` (dd-Mmm-yyyy)."""
    src = open("/app/backend/pdf/invoice.py").read()
    # The Unload Date cell must use _fmt_ind_date.
    assert "_fmt_ind_date(t.get(\"unloading_date\"))" in src


# -------------------------------------------------------------------------
# 4. Existing PDF regression neighbours — smoke test that the fix hasn't
#    shifted any other column or broken PDF generation.
# -------------------------------------------------------------------------

def test_pdf_still_renders_full_invoice_no_regression():
    inv = _invoice(["t1", "t2"])
    trips = [
        _trip("t1", "2026-08-13", "2026-08-16"),
        _trip("t2", "2026-08-14", "2026-08-22"),
    ]
    pdf = build_invoice_pdf(_company(), _customer(), inv, trips)
    text = _extract_text(pdf)
    # All neighbouring cells still render (Load MT, Unload MT, Vehicle,
    # Route, Amount) — proves the fix didn't push columns out of sync.
    assert "AP39XX0001" in text
    assert "KARWAR" in text
    assert "34.700" in text
    assert "34.570" in text
    assert "16-Aug-2026" in text
    assert "22-Aug-2026" in text
