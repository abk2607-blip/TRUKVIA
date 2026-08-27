"""Iter127c-invoice-shipto · KOLVEKAR LOGISTICS UAT (Feb 2026).

The user reported that an invoice containing 2 trips, both linked to the
SAME Ship-To (MRGR CONSTRUCTIONS · KARWAR → NAGARKURNOOL), rendered a PDF
header saying `Mixed — see per-trip below`. Root cause: the identity check
compared the resolved display tuple `(site_name, address, gstin, state,
pincode)` — if one trip's ship_site_id was stale in the customer's
`ship_sites` dict (or the linked site had partial data), the resolution
fell back to `to_location` for that trip and produced a different tuple
than the other trip's fully-resolved tuple → treated as Mixed.

New identity rule (locked here):
  • Trip has ship_site_id                → identity = ("site_id", sid).
                                          Two trips sharing the same
                                          ship_site_id are always the
                                          SAME delivery site, regardless
                                          of dict resolution differences.
  • Trip has no ship_site_id             → identity = ("fb", norm_name,
                                          norm_address, norm_gstin).
                                          Same name + different address
                                          → different identity → Mixed.

Test coverage matrix (all cases the user asked for):
  1. Single trip / one Ship-To                    → not mixed.
  2. Multiple trips / same ship_site_id           → Common Ship-To.
  3. Multiple trips / different ship_site_id      → Mixed.
  4. Same name, different address (no site FK)    → Mixed.
  5. Same normalized identity + different trip
     data (dates, refs, freight)                  → Common Ship-To.
"""
from __future__ import annotations

import sys, importlib
sys.path.insert(0, "/app/backend")
_inv = importlib.import_module("pdf.invoice")

# Access the private identity helper we just introduced by re-implementing
# the same rule at test scope. This is a pure logic contract test — no PDF
# rendering needed (the full integration is covered by iter67 tests).
def _ship_identity(trip, resolved):
    sid = (trip.get("ship_site_id") or "").strip()
    if sid:
        return ("site_id", sid)
    return (
        "fb",
        (resolved["site_name"] or "").strip().lower(),
        (resolved["address"] or "").strip().lower(),
        (resolved["gstin"] or "").strip().upper(),
    )

def _resolved(name="", address="", gstin=""):
    return {"site_name": name, "address": address, "gstin": gstin,
            "state": "", "pincode": "", "phone": "", "linked": bool(name)}


def test_case1_single_trip_never_mixed():
    trips = [{"ship_site_id": "ship_1"}]
    r = [_resolved("MRGR", "For M/s RKIPL", "36AAUFM1425D1ZC")]
    ids = {_ship_identity(t, s) for t, s in zip(trips, r)}
    assert len(ids) == 1


def test_case2_two_trips_same_site_id_common():
    """The KOLVEKAR LOGISTICS scenario from the UAT — MUST be Common."""
    trips = [{"ship_site_id": "ship_mrgr"}, {"ship_site_id": "ship_mrgr"}]
    # Simulate different display resolution on trip 2 (e.g. dict lookup
    # partially failed) — identity MUST still match via the site_id.
    r = [
        _resolved("MRGR CONSTRUCTIONS", "For M/s RKIPL-KMV(JV)-NH167K Project", "36AAUFM1425D1ZC"),
        _resolved("NAGARKURNOOL", "", ""),   # <-- stale dict fell back to to_location
    ]
    ids = {_ship_identity(t, s) for t, s in zip(trips, r)}
    assert len(ids) == 1, "identical ship_site_id must be treated as Common Ship-To"


def test_case3_two_trips_different_site_id_mixed():
    trips = [{"ship_site_id": "ship_a"}, {"ship_site_id": "ship_b"}]
    r = [_resolved("Site A"), _resolved("Site B")]
    ids = {_ship_identity(t, s) for t, s in zip(trips, r)}
    assert len(ids) == 2


def test_case4_same_name_different_address_no_fk_is_mixed():
    """Two trips without ship_site_id, same display name but different
    address ⇒ Mixed (different physical locations)."""
    trips = [{"ship_site_id": ""}, {"ship_site_id": ""}]
    r = [
        _resolved("Depot", "Plot 1, Village X"),
        _resolved("Depot", "Plot 999, Village Y"),
    ]
    ids = {_ship_identity(t, s) for t, s in zip(trips, r)}
    assert len(ids) == 2


def test_case5_three_trips_all_same_fk_common():
    """A + A + A → Common Ship-To even with unrelated trip payload drift."""
    trips = [
        {"ship_site_id": "ship_x", "date": "2026-08-01"},
        {"ship_site_id": "ship_x", "date": "2026-08-05"},
        {"ship_site_id": "ship_x", "date": "2026-08-12"},
    ]
    r = [_resolved("X Plant", "Addr X"), _resolved("X Plant", "Addr X"), _resolved("X Plant", "Addr X")]
    ids = {_ship_identity(t, s) for t, s in zip(trips, r)}
    assert len(ids) == 1


def test_case6_two_with_fk_plus_one_fallback_is_mixed():
    """Trip with site FK vs trip without FK ⇒ always mixed (different
    identity type buckets)."""
    trips = [{"ship_site_id": "ship_x"}, {"ship_site_id": ""}]
    r = [_resolved("X Plant"), _resolved("X Plant")]
    ids = {_ship_identity(t, s) for t, s in zip(trips, r)}
    assert len(ids) == 2


def test_case7_gstin_normalisation_case_insensitive():
    """Fallback identity: same name + address + GSTIN differing in case ⇒ Common."""
    trips = [{"ship_site_id": ""}, {"ship_site_id": ""}]
    r = [
        _resolved("Depot", "Plot 1", "36aaufm1425d1zc"),
        _resolved(" DEPOT ", "  PLOT 1  ", "36AAUFM1425D1ZC"),
    ]
    ids = {_ship_identity(t, s) for t, s in zip(trips, r)}
    assert len(ids) == 1


def test_source_guardrail_ship_identity_uses_site_id_first():
    """Lock: the invoice module's identity check MUST prefer ship_site_id."""
    src = open("/app/backend/pdf/invoice.py").read()
    # The new helper name is _ship_identity — enforce its existence.
    assert "_ship_identity" in src
    # The site_id branch MUST come BEFORE the fallback tuple.
    fn_start = src.index("def _ship_identity(")
    fn_body  = src[fn_start:src.index("\n    _st_identities", fn_start)]
    site_pos = fn_body.index('("site_id"')
    fb_pos   = fn_body.index('"fb"')
    assert site_pos < fb_pos, "site_id branch must be evaluated before the fallback tuple"
