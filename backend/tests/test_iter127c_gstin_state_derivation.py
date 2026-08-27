"""Iter127c-invoice-shipto v3.2 · GSTIN → State / State Code auto-derivation.

User-approved (Feb 2026) small isolated UX enhancement:
  * A valid ShipSite GSTIN's first 2 digits carry the Indian State Code.
  * On save, blank `state_code` / `state` are auto-filled from GSTIN.
  * Never guesses when GSTIN is blank or ill-formed.
  * Never silently overwrites a manually-entered conflicting value — the
    FE surfaces a warning; the backend refuses to overwrite. Historical
    records are safe.
  * No auto-migration of existing ship-sites.
  * No changes to tax calc, IGST/CGST/SGST, freight, shortage, LR, invoice,
    customer or supplier logic.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/app/backend")
from ship_to_resolver import (
    derive_state_from_gstin,
    apply_gstin_state_derivation,
    normalize_gstin,
)


# -------------------------------------------------------------------------
# 1. Pure derivation contract — first 2 digits of a well-formed GSTIN pick
#    a canonical Indian state name.
# -------------------------------------------------------------------------

def test_derive_telangana_state_code_36():
    r = derive_state_from_gstin("36AAUFM1425D1ZC")
    assert r == {"state_code": "36", "state": "Telangana"}


def test_derive_karnataka_state_code_29():
    r = derive_state_from_gstin("29BVMPK0275K1Z3")
    assert r == {"state_code": "29", "state": "Karnataka"}


def test_derive_andhra_pradesh_state_code_37():
    r = derive_state_from_gstin("37AAECR5210P2Z2")
    assert r == {"state_code": "37", "state": "Andhra Pradesh"}


def test_derive_maharashtra_state_code_27():
    r = derive_state_from_gstin("27AAACR5055K1Z7")
    assert r == {"state_code": "27", "state": "Maharashtra"}


def test_derive_delhi_state_code_07():
    r = derive_state_from_gstin("07AABCU9603R1ZM")
    assert r == {"state_code": "07", "state": "Delhi"}


def test_derive_tamil_nadu_state_code_33():
    r = derive_state_from_gstin("33AABCT3518Q1ZW")
    assert r == {"state_code": "33", "state": "Tamil Nadu"}


def test_blank_gstin_no_derivation():
    for candidate in ("", None, "   ", "\t"):
        assert derive_state_from_gstin(candidate) == {"state_code": "", "state": ""}


def test_invalid_gstin_no_derivation():
    for candidate in (
        "BADGSTIN",
        "99AAECR5210P2Z2",        # unknown state code (99)
        "1AAAA1234A1Z1",          # too short
        "36AAECR5210P2Z2X",       # too long
        "36aa$c$5210P2Z2",        # illegal chars
        "3EAAECR5210P2Z2",        # non-digit state code
        "36AAECR5210P1YY",        # missing 'Z' at position 13
    ):
        assert derive_state_from_gstin(candidate) == {"state_code": "", "state": ""}, candidate


def test_derivation_survives_gstin_prefix_and_whitespace():
    """Combined with normalizer: 'GSTIN 36AAUFM1425D1ZC\\t\\t' still derives Telangana."""
    assert derive_state_from_gstin("GSTIN 36AAUFM1425D1ZC\t\t") == {"state_code": "36", "state": "Telangana"}
    assert derive_state_from_gstin("gst 29BVMPK0275K1Z3") == {"state_code": "29", "state": "Karnataka"}
    assert derive_state_from_gstin("  gstin:36AAUFM1425D1ZC  ") == {"state_code": "36", "state": "Telangana"}


# -------------------------------------------------------------------------
# 2. Payload mutator contract — apply_gstin_state_derivation
# -------------------------------------------------------------------------

def test_apply_fills_blank_state_and_state_code():
    p = {"gstin": "36AAUFM1425D1ZC", "state": "", "state_code": ""}
    apply_gstin_state_derivation(p)
    assert p["state"] == "Telangana"
    assert p["state_code"] == "36"


def test_apply_never_overwrites_manual_state():
    """Manually-entered value that CONFLICTS with GSTIN is kept (safety)."""
    p = {"gstin": "36AAUFM1425D1ZC", "state": "Karnataka", "state_code": "29"}
    apply_gstin_state_derivation(p)
    assert p["state"] == "Karnataka"
    assert p["state_code"] == "29"


def test_apply_keeps_manual_when_matches():
    p = {"gstin": "36AAUFM1425D1ZC", "state": "Telangana", "state_code": "36"}
    apply_gstin_state_derivation(p)
    assert p == {"gstin": "36AAUFM1425D1ZC", "state": "Telangana", "state_code": "36"}


def test_apply_blank_gstin_leaves_state_untouched():
    p = {"gstin": "", "state": "", "state_code": ""}
    apply_gstin_state_derivation(p)
    assert p["state"] == ""
    assert p["state_code"] == ""


def test_apply_invalid_gstin_leaves_state_untouched():
    p = {"gstin": "BADGSTIN", "state": "", "state_code": ""}
    apply_gstin_state_derivation(p)
    assert p["state"] == ""
    assert p["state_code"] == ""


def test_apply_fills_only_blank_field_when_partial_manual():
    """If ONLY state_code was entered manually and matches derivation,
    state name still gets auto-filled."""
    p = {"gstin": "36AAUFM1425D1ZC", "state": "", "state_code": "36"}
    apply_gstin_state_derivation(p)
    assert p["state_code"] == "36"
    assert p["state"] == "Telangana"


def test_apply_dirty_gstin_still_derives_after_normalization():
    p = {"gstin": normalize_gstin("GSTIN 36AAUFM1425D1ZC\t\t"), "state": "", "state_code": ""}
    apply_gstin_state_derivation(p)
    assert p["state"] == "Telangana"
    assert p["state_code"] == "36"


# -------------------------------------------------------------------------
# 3. Source-level guardrails — save-time integration
# -------------------------------------------------------------------------

def test_source_guardrail_create_endpoint_applies_derivation():
    src = open("/app/backend/routers/customers.py").read()
    idx = src.index("async def create_ship_site(")
    body = src[idx:src.index("async def update_ship_site(", idx)]
    assert "apply_gstin_state_derivation" in body


def test_source_guardrail_update_endpoint_applies_derivation():
    src = open("/app/backend/routers/customers.py").read()
    idx = src.index("async def update_ship_site(")
    body = src[idx:src.index("async def delete_ship_site(", idx)]
    assert "apply_gstin_state_derivation" in body


def test_source_guardrail_frontend_modal_has_derivation_helper():
    src = open("/app/frontend/src/components/ShipSitesModal.jsx").read()
    assert "deriveStateFromGstin" in src
    assert "site-gstin-derived" in src            # success UX marker
    assert "site-gstin-state-conflict" in src     # conflict warning UX
    assert "site-gstin-invalid" in src            # invalid GSTIN UX


# -------------------------------------------------------------------------
# 4. Resolver still renders whatever state the ShipSite carries — the
#    derived state persists into Preview / PDF via the same code path as
#    manually-entered state. No inheritance from Customer.
# -------------------------------------------------------------------------

def test_derived_state_flows_into_resolver_output():
    """After derivation, the ShipSite's state is what Preview + PDF render."""
    from ship_to_resolver import resolve_invoice_ship_to
    # Simulate what save-time does — payload starts blank, GSTIN drives it.
    site = {"id": "s1", "site_name": "MRGR CONSTRUCTIONS",
            "address": "Village Y, Nagarkurnool-509209",
            "gstin": "GSTIN 36AAUFM1425D1ZC\t\t"}
    site["gstin"] = normalize_gstin(site["gstin"])
    apply_gstin_state_derivation(site)
    customer = {"name": "KOLVEKAR", "state": "Karnataka", "ship_sites": [site]}
    trips = [{"id": "t1", "ship_site_id": "s1", "to_location": "NAGARKURNOOL"}]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False
    assert r["common"]["state"] == "Telangana"          # from GSTIN, NOT customer.state
    assert r["common"]["state_code"] == "36"
    assert r["common"]["gstin"] == "36AAUFM1425D1ZC"


def test_no_inheritance_when_gstin_invalid_and_state_blank():
    """Guardrail: invalid GSTIN + blank manual state ⇒ still blank, never
    falls back to customer.state."""
    from ship_to_resolver import resolve_invoice_ship_to
    site = {"id": "s1", "site_name": "X", "address": "addr", "gstin": "BADGSTIN",
            "state": "", "state_code": ""}
    site["gstin"] = normalize_gstin(site["gstin"])   # 'BADGSTIN' — unchanged, still invalid
    apply_gstin_state_derivation(site)                # no-op
    assert site.get("state", "") == "" and site.get("state_code", "") == ""
    customer = {"state": "Karnataka", "ship_sites": [site]}
    trips = [{"id": "t1", "ship_site_id": "s1", "to_location": "anywhere"}]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["common"]["state"] == ""                # NOT 'Karnataka'
