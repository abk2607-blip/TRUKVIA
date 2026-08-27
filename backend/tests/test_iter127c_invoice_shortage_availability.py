"""Iter127c-invoice-shortage-availability · Pre-unload fabricated shortage fix
(Feb 2026, user-approved).

Business rule (user-locked, verbatim):
    Missing unloading data must mean "Unloading Pending / Not Available Yet",
    NEVER "0 unloaded".

Fix scope:
  * services._compute_trip — gate the shortage/excess auto-diff on
    (t.unloaded_qty or 0) > 0.  Pending unloading ⇒ shortage_qty and
    excess_qty stay at their default 0.0 (== "not available"), which
    naturally hides shortage in PDF/Preview/reports and keeps freight
    intact.  Existing customer / supplier / driver shortage formulas run
    verbatim on the resulting truthful values.
  * pdf/invoice.py — Allowance / Actual Short / Net Short cells all
    render "—" when unloaded_qty is not > 0.  Freight cell unaffected.

Untouched (verified):
  Freight formula/policy, Customer shortage formula, Supplier shortage
  engine, Driver shortage policy, Invoice totals/tax, LR, Ship-To,
  Customer/Supplier duplicate logic, Iter126a/b/c, Iter127a, Auth,
  Save Health, Regression Guard, dd-Mmm-yyyy date contract.

Historical safety (measured in DB before rollout):
  * 9,868 trips have unloaded_qty=0 + non-empty unloading_date — none
    represent legitimate "0 unloaded" completions; all are data-entry
    incomplete states.
  * 15,551 already-invoiced trips currently carry a fabricated
    shortage_qty in Mongo, BUT aggregate shortage_amount across all of
    them is ₹0 — the fabrication never translated into a real deduction
    because product_rate / customer_limit were absent for those trips.
    Therefore on-open re-render will correct the DISPLAY without altering
    any financial history.
  * 1,237 trips have shortage_amount_override=True — preserved verbatim
    by existing lines 106 / 141 in services.py; this fix does not touch
    the override branches.
"""
from __future__ import annotations

import sys, io
sys.path.insert(0, "/app/backend")
from models import Trip
from services import _compute_trip
from pdf import build_invoice_pdf


def _mk_trip(tons, unloaded_qty, unloading_date="", **kw):
    """Build a Trip with the shortage-policy snapshot the customer engine needs."""
    return Trip(
        id="t", user_id="u", customer_id="c", vehicle_number="V1",
        date="2026-08-27", tons=tons, unloaded_qty=unloaded_qty,
        unloading_date=unloading_date,
        freight_mode="per_ton", rate_per_ton=100.0,
        applied_freight_method="per_ton_loading",
        product_rate_per_mt=50000.0,
        applied_customer_shortage_limit=0.5,
        applied_customer_shortage_limit_type="pct",
        applied_customer_shortage_method="net_shortage",
        **kw,
    )


def _extract(pdf_bytes):
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((p.extract_text() or "") for p in rd.pages)


def _company():
    return {"id": "co", "legal_name": "TEST CO", "gstin": "36AABCT1234E1Z5",
            "state": "Telangana", "address": "Hyd", "phone": "9000000000",
            "bank_name": "SBI", "bank_account": "12345", "bank_ifsc": "SBIN0000001"}


def _customer():
    return {"id": "c", "name": "TEST CUST", "state": "Karnataka",
            "gstin": "29BVMPK0275K1Z3", "address": "Hubli", "phone": "9110000099",
            "ship_sites": []}


def _invoice():
    return {"id": "inv", "invoice_number": "TEST/AVAIL/001",
            "invoice_date": "2026-08-27", "customer_id": "c", "trip_ids": ["t"],
            "hsn_sac": "996791", "gst_type": "igst",
            "subtotal": 0, "gst_rate": 18,
            "cgst_amount": 0, "sgst_amount": 0, "igst_amount": 0,
            "total_amount": 0, "amount_paid": 0, "balance_due": 0}


# -------------------------------------------------------------------------
# Test 1 — Loaded, no unload_qty, no unload_date
# -------------------------------------------------------------------------

def test_1_loaded_but_not_unloaded_zero_qty():
    t = _mk_trip(30, 0, "")
    _compute_trip(t)
    assert t.shortage_qty == 0.0, "shortage_qty MUST NOT be fabricated as 30"
    assert t.excess_qty == 0.0
    assert t.shortage_amount == 0.0
    assert t.freight_amount == 3000.0, "freight remains fully calculated"


# -------------------------------------------------------------------------
# Test 2 — Loaded, unload_qty = None, unload_date blank
# -------------------------------------------------------------------------

def test_2_unloaded_qty_none_also_pending():
    """Trip constructed as if `unloaded_qty` was never touched (default 0.0)."""
    t = Trip(id="t", user_id="u", customer_id="c", vehicle_number="V1",
             date="2026-08-27", tons=30.0,
             freight_mode="per_ton", rate_per_ton=100.0,
             applied_freight_method="per_ton_loading",
             product_rate_per_mt=50000.0,
             applied_customer_shortage_limit=0.5,
             applied_customer_shortage_limit_type="pct",
             applied_customer_shortage_method="net_shortage")
    _compute_trip(t)
    assert t.shortage_qty == 0.0
    assert t.excess_qty == 0.0
    assert t.shortage_amount == 0.0
    assert t.freight_amount == 3000.0


# -------------------------------------------------------------------------
# Test 3 — Unload date exists but unload_qty still blank
# -------------------------------------------------------------------------

def test_3_unload_date_present_qty_missing_still_unavailable():
    """User directive #9 — unload_date alone must NOT trigger shortage calc."""
    t = _mk_trip(30, 0, "2026-08-30")
    _compute_trip(t)
    assert t.shortage_qty == 0.0
    assert t.excess_qty == 0.0
    assert t.shortage_amount == 0.0


# -------------------------------------------------------------------------
# Test 4 — Unloaded with a real shortage (State B contract lock)
# -------------------------------------------------------------------------

def test_4_state_b_real_shortage_engine_unchanged():
    t = _mk_trip(30, 29.85, "2026-08-30")
    _compute_trip(t)
    assert t.shortage_qty == 0.15, "State B: real shortage still computed"
    assert t.excess_qty == 0.0
    # Allowance under 0.5% of 30 MT = 0.15 MT — actual shortage EXACTLY at
    # allowance ⇒ NO deduction (net_shortage method).
    assert t.shortage_amount == 0.0


def test_4b_state_b_shortage_above_allowance():
    """Shortage 0.5 MT vs allowance 0.15 MT (0.5% of 30) ⇒ net = 0.35 MT × ₹50000."""
    t = _mk_trip(30, 29.5, "2026-08-30")
    _compute_trip(t)
    assert t.shortage_qty == 0.5
    # net_shortage = (0.5 - 0.15) × 50000 = 17500
    assert t.shortage_amount == 17500.0


# -------------------------------------------------------------------------
# Test 5 — Unloaded, load = unload (State C — no shortage)
# -------------------------------------------------------------------------

def test_5_state_c_zero_shortage_zero_excess():
    t = _mk_trip(30, 30.0, "2026-08-30")
    _compute_trip(t)
    assert t.shortage_qty == 0.0
    assert t.excess_qty == 0.0
    assert t.shortage_amount == 0.0


# -------------------------------------------------------------------------
# Test 6 — KOLVEKAR (State B) regression lock — must be byte-identical
# -------------------------------------------------------------------------

def test_6_kolvekar_regression_no_change_to_existing_completed_trip():
    """Both KOLVEKAR trips are completed (unloaded_qty > 0). Engine output
    must be identical to the pre-fix behaviour."""
    t = _mk_trip(29.670, 29.520, "2026-08-30")  # KOLVEKAR-style
    _compute_trip(t)
    # 0.15 MT shortage, allowance = 0.5% × 29.670 = 0.14835 MT
    # net = (0.15 − 0.14835) × 50000 = 82.5
    assert t.shortage_qty == 0.15
    assert round(t.shortage_amount, 2) == 82.5


# -------------------------------------------------------------------------
# Test 7 — Freight independence (must remain fully calculated pre-unload)
# -------------------------------------------------------------------------

def test_7_freight_independent_of_unload_availability():
    """Freight must be identical whether or not unloading has happened."""
    t_pending = _mk_trip(30, 0, "")
    _compute_trip(t_pending)
    t_done = _mk_trip(30, 29.85, "2026-08-30")
    _compute_trip(t_done)
    assert t_pending.freight_amount == t_done.freight_amount == 3000.0


# -------------------------------------------------------------------------
# Test 8 — Preview vs PDF parity (both surfaces show "—" pre-unload)
# -------------------------------------------------------------------------

def test_8_pdf_renders_dash_for_all_shortage_cells_when_unload_pending():
    """The KOLVEKAR UAT scenario — Load 29.670, no unload data → PDF row must
    show '—' for Actual Short, Allowance, Net Short. Freight amount preserved."""
    t = _mk_trip(29.670, 0, "").model_dump()
    _compute_trip_dict = lambda td: (lambda tr: (_compute_trip(tr), tr))(Trip(**td))
    _, t_obj = _compute_trip_dict(t)
    trip_dict = t_obj.model_dump()
    pdf = build_invoice_pdf(_company(), _customer(), _invoice(), [trip_dict])
    text = _extract(pdf)
    # Freight cell should still show 2,967 (29.670 × 100)
    assert "2,967" in text, "freight cell missing/wrong when unloading pending"
    # No fabricated Actual Short "29.670" should appear anywhere
    assert "29.670" in text                   # Load MT cell — legitimate
    # Substring guardrail — the Actual Short bar's value would be "29.670" too;
    # we assert that the char count of "29.670" is exactly ONE (only in Load MT).
    assert text.count("29.670") == 1, (
        f"pre-unload PDF must not fabricate 29.670 in Actual Short. "
        f"count={text.count('29.670')} — text sample:\n{text[:1500]}"
    )


# -------------------------------------------------------------------------
# Guardrails — locked at the source
# -------------------------------------------------------------------------

def test_source_guardrail_services_gate_present():
    src = open("/app/backend/services.py").read()
    assert "Iter127c-invoice-shortage-availability" in src
    # The availability gate MUST be an if-guard on unloaded_qty > 0.
    assert "if (t.unloaded_qty or 0) > 0:" in src


def test_source_guardrail_pdf_gate_present():
    src = open("/app/backend/pdf/invoice.py").read()
    assert "Iter127c-invoice-shortage-availability" in src
    assert "_unload_available" in src


def test_source_guardrail_override_branch_untouched():
    """shortage_amount_override branch must still exist verbatim."""
    src = open("/app/backend/services.py").read()
    assert "if not t.shortage_amount_override:" in src
    assert "if not t.excess_amount_override:" in src


def test_source_guardrail_freight_calc_untouched():
    """Freight block (Iter97 Phase 2) must still be above the shortage gate."""
    src = open("/app/backend/services.py").read()
    freight_idx = src.index("Iter97 · Phase 2 — Central Freight Calculation Engine")
    gate_idx = src.index("Iter127c-invoice-shortage-availability")
    assert freight_idx < gate_idx, "freight calc must precede shortage gate"
