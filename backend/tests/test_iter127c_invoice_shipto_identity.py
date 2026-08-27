"""Iter127c-invoice-shipto v3 · KOLVEKAR LOGISTICS UAT — Ship-To identity contract.

This is the legacy identity-contract test suite, rewritten to exercise the
NEW guarded resolver at `/app/backend/ship_to_resolver.py`.  All cases now
run through `resolve_invoice_ship_to(customer, trips)` so the assertions
match what the PDF *and* the Preview endpoint will actually render.

Key rule shift from v2 → v3 (user-approved, Feb 2026):
  * v2 said: "trip with FK + trip without FK ⇒ always Mixed."
  * v3 says: "trip with FK + trip without FK ⇒ Mixed UNLESS destination
    evidence (name / pincode / whole-word address token) unambiguously
    infers the missing FK to the SAME site."

Detailed guarded rules and the ambiguity guard live in the resolver's
docstring and are exhaustively covered by
`test_iter127c_ship_to_resolver_guarded.py`.  This file is the
higher-level invariant lock (identity ⇒ Mixed?) for the six original
scenarios.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/app/backend")
from ship_to_resolver import resolve_invoice_ship_to


def _site(sid, name, address="", state="", gstin="", pincode=""):
    return {"id": sid, "site_name": name, "address": address,
            "state": state, "gstin": gstin, "pincode": pincode}


def _customer(*sites):
    return {"name": "C", "state": "Karnataka", "gstin": "29X", "ship_sites": list(sites)}


def test_case1_single_trip_never_mixed():
    r = resolve_invoice_ship_to(
        _customer(_site("ship_1", "MRGR", "For M/s RKIPL", "", "36AAUFM1425D1ZC")),
        [{"ship_site_id": "ship_1", "to_location": "NAGARKURNOOL"}],
    )
    assert r["mixed"] is False


def test_case2_two_trips_same_site_id_common():
    """Both trips carry the same explicit FK → always Common."""
    r = resolve_invoice_ship_to(
        _customer(_site("ship_mrgr", "MRGR CONSTRUCTIONS", "Site addr")),
        [
            {"ship_site_id": "ship_mrgr", "to_location": "NAGARKURNOOL"},
            {"ship_site_id": "ship_mrgr", "to_location": "somewhere else"},
        ],
    )
    assert r["mixed"] is False
    assert r["common"]["site_name"] == "MRGR CONSTRUCTIONS"


def test_case3_two_trips_different_site_id_mixed():
    r = resolve_invoice_ship_to(
        _customer(_site("ship_a", "Site A", "Addr A"), _site("ship_b", "Site B", "Addr B")),
        [
            {"ship_site_id": "ship_a", "to_location": "A"},
            {"ship_site_id": "ship_b", "to_location": "B"},
        ],
    )
    assert r["mixed"] is True


def test_case4_same_name_different_address_no_fk_is_mixed():
    """Both trips lack FK; no ship_sites on customer → fallback identity
    (name, address, gstin). Same name but different addresses ⇒ Mixed."""
    r = resolve_invoice_ship_to(
        _customer(),   # no sites → nothing to infer
        [
            {"ship_site_id": "", "to_location": "Depot"},
            {"ship_site_id": "", "to_location": "Depot2"},
        ],
    )
    assert r["mixed"] is True


def test_case5_three_trips_same_fk_common():
    r = resolve_invoice_ship_to(
        _customer(_site("ship_x", "X Plant", "Addr X")),
        [
            {"ship_site_id": "ship_x", "date": "2026-08-01"},
            {"ship_site_id": "ship_x", "date": "2026-08-05"},
            {"ship_site_id": "ship_x", "date": "2026-08-12"},
        ],
    )
    assert r["mixed"] is False


def test_case6_fk_plus_no_fk_common_when_evidence_matches():
    """UPDATED CONTRACT (v3): a trip with FK + a trip without FK is
    Common when destination evidence unambiguously infers the missing FK.
    (This is the exact KOLVEKAR live scenario.)"""
    r = resolve_invoice_ship_to(
        _customer(_site("ship_x", "MRGR CONSTRUCTIONS",
                        "Village Y, Nagarkurnool-509209")),
        [
            {"ship_site_id": "ship_x", "to_location": "NAGARKURNOOL"},
            {"ship_site_id": "",       "to_location": "NAGARKURNOOL"},
        ],
    )
    assert r["mixed"] is False
    assert r["common"]["site_name"] == "MRGR CONSTRUCTIONS"


def test_case6b_fk_plus_no_fk_still_mixed_when_no_evidence():
    """If evidence does NOT link the FK-less trip to the sole customer site,
    the resolver falls back and Mixed is the correct answer — the guard
    exists precisely to prevent silent misgrouping."""
    r = resolve_invoice_ship_to(
        _customer(_site("ship_x", "X Plant", "Village Y, Nagarkurnool-509209")),
        [
            {"ship_site_id": "ship_x", "to_location": "NAGARKURNOOL"},
            {"ship_site_id": "",       "to_location": "Chennai"},   # no evidence
        ],
    )
    assert r["mixed"] is True


def test_case7_gstin_case_insensitivity_in_fallback_identity():
    """Both trips lack FK. Same normalised name + address + GSTIN
    (differing only in case/whitespace) → Common fallback identity."""
    r = resolve_invoice_ship_to(
        _customer(),
        [
            {"ship_site_id": "", "to_location": "Depot"},
            {"ship_site_id": "", "to_location": " DEPOT "},
        ],
    )
    assert r["mixed"] is False


def test_source_guardrail_resolver_is_the_one_source_of_truth():
    """Enforce that the legacy inline helpers are gone from pdf/invoice.py
    and both surfaces import the shared resolver."""
    pdf_src = open("/app/backend/pdf/invoice.py").read()
    api_src = open("/app/backend/routers/invoices.py").read()
    assert "from ship_to_resolver import resolve_invoice_ship_to" in pdf_src
    assert "from ship_to_resolver import resolve_invoice_ship_to" in api_src
    assert "def _ship_identity(" not in pdf_src
    assert "def _resolve_ship_to(" not in pdf_src
