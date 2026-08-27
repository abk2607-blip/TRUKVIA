"""Iter127c-invoice-shipto v2 · KOLVEKAR LOGISTICS PDF-Preview parity — v3 update.

v2 locked an inline heal inside pdf/invoice.py. v3 (Feb 2026 · user-
approved guarded resolver) moved that logic into the shared module
`/app/backend/ship_to_resolver.py`, so this file now re-asserts the
identical parity guarantees through the shared resolver instead of the
removed inline helper. Behaviour contract is unchanged for the two
scenarios locked below (name-match still resolves; unrelated to_location
still falls back safely).
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/app/backend")
from ship_to_resolver import resolve_invoice_ship_to


SITE_MRGR = {
    "id": "ship_mrgr",
    "site_name": "MRGR CONSTRUCTIONS",
    "address": "For M/s RKIPL-KMV(JV)-NH167K Project, Nagarkurnool-509209",
    "gstin": "36AAUFM1425D1ZC",
    "state": "Telangana",
    "pincode": "509209",
}


def _cust(*sites, state="Karnataka", gstin="29X"):
    return {"name": "C", "state": state, "gstin": gstin, "ship_sites": list(sites)}


def test_kolvekar_scenario_one_fk_one_fallback_now_common():
    """UAT bug: 2 trips, one with FK, one to_location='MRGR CONSTRUCTIONS'."""
    customer = _cust(SITE_MRGR)
    trips = [
        {"ship_site_id": "ship_mrgr", "to_location": "NAGARKURNOOL"},
        {"ship_site_id": "",           "to_location": "MRGR CONSTRUCTIONS"},
    ]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False
    assert r["common"]["site_name"] == "MRGR CONSTRUCTIONS"
    assert r["common"]["gstin"] == "36AAUFM1425D1ZC"
    assert r["common"]["state"] == "Telangana"
    assert r["per_trip"][1]["inferred"] is True


def test_no_fk_and_no_matching_site_still_falls_back_to_to_location():
    """Trip without FK and to_location that doesn't match any site → safe fallback."""
    customer = _cust(SITE_MRGR)
    trips = [{"ship_site_id": "", "to_location": "Kadapa Junction"}]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False
    assert r["common"]["linked"] is False
    assert r["common"]["site_name"] == "Kadapa Junction"
    assert r["common"]["state"] == ""     # NO customer-state inheritance


def test_case_insensitive_matching_across_whitespace():
    customer = _cust(SITE_MRGR)
    trips = [
        {"ship_site_id": "ship_mrgr", "to_location": "anything"},
        {"ship_site_id": "",           "to_location": "  mrgr constructions  "},
    ]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False
    assert r["common"]["state"] == "Telangana"


def test_source_guardrail_shared_resolver_is_used_by_pdf():
    src = open("/app/backend/pdf/invoice.py").read()
    assert "from ship_to_resolver import resolve_invoice_ship_to" in src
    # v3 marker on the delegation site.
    assert "Iter127c-invoice-shipto v3" in src
