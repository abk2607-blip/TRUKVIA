"""Iter127c-invoice-shipto v3.1 · GSTIN normalization (Feb 2026, user-approved).

Two-phase cleanup for dirty ShipSite GSTIN values in the wild (e.g.
KOLVEKAR's site stored `"GSTIN 36AAUFM1425D1ZC\t\t"`).

  * ON SAVE (POST/PUT ship-site)   → `normalize_gstin` cleans the value
    before storage; future edits produce canonical form.
  * ON RENDER (resolver output)    → `_display_from_site` runs the same
    cleaner so existing dirty records display cleanly TODAY without any
    DB write.

Strictly a display/input-hygiene fix. Zero impact on tax calc, LR,
customer, supplier, or freight/shortage logic. No auto-migration.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/app/backend")
from ship_to_resolver import normalize_gstin, resolve_invoice_ship_to


# ----------------------------------------------------------------------
# 1. Pure normalizer contract
# ----------------------------------------------------------------------

def test_norm_strips_leading_gstin_uppercase():
    assert normalize_gstin("GSTIN 36AAUFM1425D1ZC") == "36AAUFM1425D1ZC"


def test_norm_strips_leading_gst_uppercase():
    assert normalize_gstin("GST 36AAUFM1425D1ZC") == "36AAUFM1425D1ZC"


def test_norm_strips_leading_gstn_uppercase():
    assert normalize_gstin("GSTN 36AAUFM1425D1ZC") == "36AAUFM1425D1ZC"


def test_norm_strips_leading_gstin_lowercase():
    assert normalize_gstin("gstin 36aaufm1425d1zc") == "36AAUFM1425D1ZC"


def test_norm_strips_mixed_case_prefix():
    assert normalize_gstin("Gstin  36AAUFM1425D1ZC") == "36AAUFM1425D1ZC"
    assert normalize_gstin("gST 36AAUFM1425D1ZC") == "36AAUFM1425D1ZC"


def test_norm_handles_tabs_and_newlines_and_trailing_ws():
    # KOLVEKAR's exact stored value.
    assert normalize_gstin("GSTIN 36AAUFM1425D1ZC\t\t") == "36AAUFM1425D1ZC"
    assert normalize_gstin("\tGSTIN 36AAUFM1425D1ZC\n") == "36AAUFM1425D1ZC"
    assert normalize_gstin("  GSTIN  36AAUFM1425D1ZC  ") == "36AAUFM1425D1ZC"


def test_norm_leaves_already_clean_value_unchanged():
    assert normalize_gstin("36AAUFM1425D1ZC") == "36AAUFM1425D1ZC"


def test_norm_blank_stays_blank():
    assert normalize_gstin("") == ""
    assert normalize_gstin(None) == ""
    assert normalize_gstin("   ") == ""
    assert normalize_gstin("\t\n") == ""


def test_norm_uppercases_result():
    assert normalize_gstin("36aaufm1425d1zc") == "36AAUFM1425D1ZC"


def test_norm_handles_colon_separator_after_prefix():
    assert normalize_gstin("GSTIN: 36AAUFM1425D1ZC") == "36AAUFM1425D1ZC"
    assert normalize_gstin("GSTIN:36AAUFM1425D1ZC")   == "36AAUFM1425D1ZC"


def test_norm_does_not_strip_prefix_that_is_not_a_word_boundary():
    """`GSTINX...` is NOT a valid prefix removal — the regex uses \\b."""
    assert normalize_gstin("GSTINX36AAUFM1425D1ZC") == "GSTINX36AAUFM1425D1ZC"


# ----------------------------------------------------------------------
# 2. Render-time cleanup does NOT mutate the underlying record
# ----------------------------------------------------------------------

def test_resolver_renders_clean_gstin_from_dirty_stored_value():
    """The exact KOLVEKAR-style dirty record → resolver returns cleaned GSTIN."""
    dirty_site = {
        "id": "ship_a9c9d06791b84c47",
        "site_name": "MRGR CONSTRUCTIONS",
        "address": "Village Y, Nagarkurnool-509209",
        "gstin": "GSTIN 36AAUFM1425D1ZC\t\t",          # dirty in DB
        "state": "", "state_code": "", "pincode": "",
    }
    customer = {"name": "KOLVEKAR", "ship_sites": [dirty_site]}
    trips = [
        {"id": "t1", "ship_site_id": "ship_a9c9d06791b84c47", "to_location": "NAGARKURNOOL"},
        {"id": "t2", "ship_site_id": "", "to_location": "NAGARKURNOOL"},
    ]

    # Snapshot dirty value BEFORE resolve.
    dirty_before = dirty_site["gstin"]

    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False
    assert r["common"]["gstin"] == "36AAUFM1425D1ZC"    # clean OUT
    assert "GSTIN GSTIN" not in r["common"]["gstin"]

    # And the underlying record must NOT have been mutated.
    assert dirty_site["gstin"] == dirty_before          # DB view still dirty
    assert customer["ship_sites"][0]["gstin"] == dirty_before


def test_resolver_render_leaves_blank_gstin_blank():
    site = {"id": "s1", "site_name": "X", "address": "some addr", "gstin": ""}
    customer = {"ship_sites": [site]}
    trips = [{"id": "t1", "ship_site_id": "s1", "to_location": "anywhere"}]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["common"]["gstin"] == ""


# ----------------------------------------------------------------------
# 3. Source-level guardrails — save-path & render-path both use the helper
# ----------------------------------------------------------------------

def test_source_guardrail_save_path_normalizes_gstin_on_create():
    src = open("/app/backend/routers/customers.py").read()
    # The create_ship_site body must call normalize_gstin on payload.gstin.
    assert "async def create_ship_site(" in src
    idx = src.index("async def create_ship_site(")
    body = src[idx:src.index("async def update_ship_site(", idx)]
    assert "normalize_gstin(payload.gstin)" in body


def test_source_guardrail_save_path_normalizes_gstin_on_update():
    src = open("/app/backend/routers/customers.py").read()
    idx = src.index("async def update_ship_site(")
    body = src[idx:src.index("async def delete_ship_site(", idx)]
    assert 'normalize_gstin(updated.get("gstin"))' in body


def test_source_guardrail_resolver_uses_normalize_gstin_on_render():
    src = open("/app/backend/ship_to_resolver.py").read()
    assert "def normalize_gstin" in src
    # The display helper must call normalize_gstin on the site's raw gstin.
    idx = src.index("def _display_from_site(")
    body = src[idx:src.index("def _display_fallback(", idx)]
    assert "normalize_gstin(site.get(\"gstin\"))" in body


# ----------------------------------------------------------------------
# 4. Full-file KOLVEKAR contract (resolver only — PDF grep proven at
#    integration level in the smoke script during shipping).
# ----------------------------------------------------------------------

def test_kolvekar_resolver_output_shows_clean_gstin():
    """Resolver output for KOLVEKAR must contain exactly
    `gstin == "36AAUFM1425D1ZC"`. Regression lock for the UAT bug."""
    customer = {
        "name": "KOLVEKAR LOGISTICS",
        "state": "Karnataka",
        "gstin": "29BVMPK0275K1Z3",
        "ship_sites": [{
            "id": "ship_a9c9d06791b84c47",
            "site_name": "MRGR CONSTRUCTIONS",
            "address": "For M/s RKIPL-KMV(JV)-NH167K Project, Nagarkurnool-509209",
            "gstin": "GSTIN 36AAUFM1425D1ZC\t\t",
            "state": "", "state_code": "", "pincode": "",
        }],
    }
    trips = [
        {"id": "t1", "ship_site_id": "ship_a9c9d06791b84c47", "to_location": "NAGARKURNOOL"},
        {"id": "t2", "ship_site_id": "", "to_location": "NAGARKURNOOL"},
    ]
    r = resolve_invoice_ship_to(customer, trips)
    assert r["mixed"] is False
    assert r["common"]["site_name"] == "MRGR CONSTRUCTIONS"
    assert r["common"]["gstin"] == "36AAUFM1425D1ZC"    # locked expectation
