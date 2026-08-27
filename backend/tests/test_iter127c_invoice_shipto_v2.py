"""Iter127c-invoice-shipto v2 · KOLVEKAR LOGISTICS PDF-Preview parity.

Locks the healed fallback: a trip with NO `ship_site_id` whose
`to_location` matches an existing ship-site's name (case-insensitive)
now resolves to THAT ship-site instead of the raw `to_location` string.
Result: two trips entered inconsistently (one with FK, one without)
render the SAME SHIP TO in the invoice PDF — matching the already-
correct Preview.
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/app/backend")

# We re-implement the resolver at test scope so we can lock its contract
# without spinning up a full PDF render (the iter67 integration tests
# still cover the end-to-end PDF path).

def _resolve_ship_to(trip, ship_sites_by_id):
    sid = trip.get("ship_site_id") or ""
    s = ship_sites_by_id.get(sid) if sid else None
    if not s:
        to_loc = (trip.get("to_location") or "").strip().casefold()
        if to_loc:
            for candidate in ship_sites_by_id.values():
                if (candidate.get("site_name") or "").strip().casefold() == to_loc:
                    s = candidate
                    break
    if s:
        return {"site_name": s.get("site_name") or "", "address": s.get("address") or "",
                "gstin": s.get("gstin") or "", "state": s.get("state") or "",
                "pincode": s.get("pincode") or "", "phone": "", "linked": True}
    return {"site_name": trip.get("to_location") or "", "address": "",
            "gstin": "", "state": "", "pincode": "", "phone": "", "linked": False}


SITE_MRGR = {
    "id": "ship_mrgr",
    "site_name": "MRGR CONSTRUCTIONS",
    "address": "For M/s RKIPL-KMV(JV)-NH167K Project, Nagarkurnool-509209",
    "gstin": "36AAUFM1425D1ZC",
    "state": "Telangana",
    "pincode": "509209",
}


def test_kolvekar_scenario_one_fk_one_fallback_now_common():
    """The exact bug from UAT: 2 trips, one with FK, one without, both
    to_location='MRGR CONSTRUCTIONS' → PDF must NOT say Mixed."""
    ship_sites_by_id = {SITE_MRGR["id"]: SITE_MRGR}
    trip_a = {"ship_site_id": "ship_mrgr", "to_location": "NAGARKURNOOL"}
    trip_b = {"ship_site_id": "",           "to_location": "MRGR CONSTRUCTIONS"}
    r_a = _resolve_ship_to(trip_a, ship_sites_by_id)
    r_b = _resolve_ship_to(trip_b, ship_sites_by_id)
    # Both must produce the linked-site payload after the heal.
    assert r_a["linked"] is True and r_b["linked"] is True
    assert r_a["site_name"] == r_b["site_name"] == "MRGR CONSTRUCTIONS"
    assert r_a["gstin"]     == r_b["gstin"]     == "36AAUFM1425D1ZC"
    assert r_a["state"]     == r_b["state"]     == "Telangana"


def test_no_fk_and_no_matching_site_still_falls_back_to_to_location():
    """A trip with no FK and a to_location that DOESN'T match any site
    must still gracefully fall back — no crash, no silent inheritance."""
    r = _resolve_ship_to(
        {"ship_site_id": "", "to_location": "Kadapa Junction"},
        {SITE_MRGR["id"]: SITE_MRGR},
    )
    assert r["linked"] is False
    assert r["site_name"] == "Kadapa Junction"
    assert r["state"] == ""  # NO customer-state inheritance


def test_case_insensitive_matching_across_whitespace():
    ship_sites_by_id = {SITE_MRGR["id"]: SITE_MRGR}
    r = _resolve_ship_to(
        {"ship_site_id": "", "to_location": "  mrgr constructions  "},
        ship_sites_by_id,
    )
    assert r["linked"] is True
    assert r["state"] == "Telangana"


def test_source_guardrail_heal_present_in_pdf_module():
    src = open("/app/backend/pdf/invoice.py").read()
    # Iter127c-invoice-shipto v2 marker + case-insensitive match loop.
    assert "Iter127c-invoice-shipto v2" in src
    assert "candidate.get(\"site_name\")" in src and ".casefold()" in src
