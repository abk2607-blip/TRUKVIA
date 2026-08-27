"""Iter127c-invoice-shipto v3 · Guarded Ship-To resolver tests (Feb 2026).

User-approved rules (see /app/backend/ship_to_resolver.py docstring):
  * Trip with an explicit ship_site_id → authoritative identity (site_id, sid).
  * Trip with EMPTY ship_site_id       → infer a customer ship_site only when
    destination evidence (normalized to_location matches by name, pincode,
    OR whole-word substring of address) picks EXACTLY ONE site.  Ambiguous
    (>1 match) or zero-match ⇒ no inference ⇒ falls through to display
    identity ⇒ typically Mixed.

Locked user directives verified here:
  * Read-only: resolver never mutates the trip dict.
  * No silent inheritance: resolver never falls back to Customer.state /
    Customer.gstin / Customer.pincode when populating a ship_site's blank
    field.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/app/backend")
from ship_to_resolver import (
    resolve_invoice_ship_to,
    infer_site_for_trip,
    _site_matches_trip,
)


# ---- fixtures -------------------------------------------------------------

KOLVEKAR_SITE = {
    "id": "ship_a9c9d06791b84c47",
    "site_name": "MRGR CONSTRUCTIONS",
    "address": "For M/s RKIPL-KMV(JV)-NH167K Project,\t\t\t\nSy No.149/A/1/5, Wanapatla Village,\t\t\t\nNagarkurnool-509209\t\t\t\n",
    "gstin": "GSTIN 36AAUFM1425D1ZC\t\t",
    "state": "", "state_code": "", "pincode": "",
}


def _cust(*sites, state="Karnataka", gstin="29CUSTGST123"):
    return {"name": "Cust", "state": state, "gstin": gstin, "ship_sites": list(sites)}


# ---- KOLVEKAR live scenario ----------------------------------------------

def test_kolvekar_live_scenario_infers_missing_fk():
    """The exact bug the user reported — trip with FK + trip without FK
    both point at the same physical site. Guarded inference by whole-word
    address match resolves them as Common Ship-To (NOT Mixed)."""
    customer = _cust(KOLVEKAR_SITE)
    trips = [
        {"id": "t1", "ship_site_id": "ship_a9c9d06791b84c47", "to_location": "NAGARKURNOOL"},
        {"id": "t2", "ship_site_id": "", "to_location": "NAGARKURNOOL"},
    ]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False
    assert r["common"]["site_name"] == "MRGR CONSTRUCTIONS"
    assert r["per_trip"][1]["inferred"] is True
    assert r["per_trip"][1]["site_id"] == "ship_a9c9d06791b84c47"


# ---- Guardrails -----------------------------------------------------------

def test_no_silent_inheritance_of_customer_state():
    """Site has empty state — resolved header MUST NOT inherit Customer.state."""
    site = {**KOLVEKAR_SITE, "state": "", "gstin": "", "pincode": ""}
    customer = _cust(site, state="Karnataka", gstin="29CUSTGST123")
    trips = [{"id": "t1", "ship_site_id": site["id"], "to_location": "Nagarkurnool"}]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["common"]["state"] == ""     # NOT "Karnataka"
    assert r["common"]["gstin"] == ""     # NOT customer.gstin
    assert r["common"]["pincode"] == ""


def test_resolver_is_read_only_on_trip_dict():
    """Resolver must NOT write ship_site_id back into a trip dict when inferring."""
    trips = [{"id": "t2", "ship_site_id": "", "to_location": "NAGARKURNOOL"}]
    resolve_invoice_ship_to(_cust(KOLVEKAR_SITE), trips)
    assert trips[0]["ship_site_id"] == ""   # original still empty


# ---- Guarded inference rules ---------------------------------------------

def test_rule1_exact_site_name_match():
    site = {"id": "s1", "site_name": "Vijayawada Plant", "address": "Some other addr"}
    trip = {"ship_site_id": "", "to_location": "vijayawada plant"}
    assert _site_matches_trip(site, trip) is True


def test_rule2_pincode_match_via_address_pin():
    site = {"id": "s1", "site_name": "X Plant", "address": "Village Y, PIN 509209"}
    trip = {"ship_site_id": "", "to_location": "Somewhere near 509209"}
    assert _site_matches_trip(site, trip) is True


def test_rule2_pincode_match_via_site_pincode_field():
    site = {"id": "s1", "site_name": "X", "address": "Village Z", "pincode": "500001"}
    trip = {"ship_site_id": "", "to_location": "Depot 500001"}
    assert _site_matches_trip(site, trip) is True


def test_rule3_whole_token_in_address():
    site = {"id": "s1", "site_name": "MRGR CONSTRUCTIONS",
            "address": "Sy No.149, Wanapatla Village, Nagarkurnool-509209"}
    trip = {"ship_site_id": "", "to_location": "NAGARKURNOOL"}
    assert _site_matches_trip(site, trip) is True


def test_rule3_short_token_below_minimum_no_match():
    """Whole-word rule requires >=4 chars to avoid accidental false-positives."""
    site = {"id": "s1", "site_name": "X", "address": "AB CD EF hyd"}
    trip = {"ship_site_id": "", "to_location": "hyd"}   # 3 chars, too short
    assert _site_matches_trip(site, trip) is False


def test_no_evidence_no_inference_result_is_mixed_or_fallback():
    """Trip with no evidence linking to any site → not inferred → fallback identity."""
    site = {"id": "s1", "site_name": "Vijayawada", "address": "V1, V2"}
    customer = _cust(site)
    trips = [
        {"id": "t1", "ship_site_id": "s1", "to_location": "Vijayawada"},
        {"id": "t2", "ship_site_id": "", "to_location": "Chennai"},   # no evidence
    ]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is True
    assert r["per_trip"][1]["inferred"] is False


def test_ambiguous_evidence_multiple_sites_no_inference():
    """>1 site matches the trip's to_location → no inference → Mixed."""
    site_a = {"id": "sA", "site_name": "Depot A", "address": "PIN 509209"}
    site_b = {"id": "sB", "site_name": "Depot B", "address": "509209 something"}
    customer = _cust(site_a, site_b)
    # to_location contains PIN 509209 → matches BOTH sites → ambiguous
    trips = [
        {"id": "t1", "ship_site_id": "sA", "to_location": "Depot A 509209"},
        {"id": "t2", "ship_site_id": "", "to_location": "Somewhere 509209"},
    ]
    inferred = infer_site_for_trip(trips[1], [site_a, site_b])
    assert inferred is None   # ambiguous → no inference
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is True


def test_two_trips_no_fk_both_infer_same_site_common():
    """When BOTH empty-FK trips infer the SAME site → Common Ship-To."""
    site = {"id": "s1", "site_name": "MRGR CONSTRUCTIONS",
            "address": "Village X, Nagarkurnool-509209"}
    customer = _cust(site)
    trips = [
        {"id": "t1", "ship_site_id": "", "to_location": "NAGARKURNOOL"},
        {"id": "t2", "ship_site_id": "", "to_location": "NAGARKURNOOL"},
    ]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False
    assert r["common"]["site_name"] == "MRGR CONSTRUCTIONS"
    assert all(p["inferred"] for p in r["per_trip"])


def test_two_trips_different_explicit_fk_still_mixed():
    """FK vs FK, different sites → Mixed even if inference could pick a match."""
    s1 = {"id": "s1", "site_name": "Site A", "address": "Andhra 500001"}
    s2 = {"id": "s2", "site_name": "Site B", "address": "Telangana 500002"}
    customer = _cust(s1, s2)
    trips = [
        {"id": "t1", "ship_site_id": "s1", "to_location": "anywhere"},
        {"id": "t2", "ship_site_id": "s2", "to_location": "anywhere"},
    ]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is True


def test_single_trip_always_common():
    customer = _cust(KOLVEKAR_SITE)
    trips = [{"id": "t1", "ship_site_id": "", "to_location": "NAGARKURNOOL"}]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False


def test_no_ship_sites_falls_back_to_to_location():
    customer = _cust()   # no sites
    trips = [{"id": "t1", "ship_site_id": "", "to_location": "Chennai"},
             {"id": "t2", "ship_site_id": "", "to_location": "Chennai"}]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False
    assert r["common"]["site_name"] == "Chennai"
    assert r["common"]["linked"] is False


def test_empty_customer_and_no_trips_safe():
    r = resolve_invoice_ship_to(None, [])
    assert r["mixed"] is False
    assert r["common"] is None
    assert r["per_trip"] == []


# ---- Source-level guardrails ---------------------------------------------

def test_source_guardrail_resolver_module_exists():
    src = open("/app/backend/ship_to_resolver.py").read()
    assert "def resolve_invoice_ship_to" in src
    assert "def infer_site_for_trip" in src
    # Ambiguous ⇒ None. Locking the guard.
    assert "matches[0] if len(matches) == 1 else None" in src


def test_source_guardrail_pdf_uses_shared_resolver():
    src = open("/app/backend/pdf/invoice.py").read()
    assert "from ship_to_resolver import resolve_invoice_ship_to" in src
    # Legacy inline helpers must be gone.
    assert "def _resolve_ship_to(" not in src
    assert "def _ship_identity(" not in src


def test_source_guardrail_endpoint_uses_shared_resolver():
    src = open("/app/backend/routers/invoices.py").read()
    assert 'GET /api/invoices/{iid}/ship-to' not in src   # not the string, the wiring:
    assert '@router.get("/invoices/{iid}/ship-to")' in src
    assert "from ship_to_resolver import resolve_invoice_ship_to" in src
