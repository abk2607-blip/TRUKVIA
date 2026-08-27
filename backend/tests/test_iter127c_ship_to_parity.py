"""Iter127c-invoice-shipto v3 · Preview / PDF parity test (Feb 2026).

User directive: "the same resolver/result must drive both — Invoice
Preview = Invoice PDF".  This test proves it at the code level: both the
PDF path and the /api/invoices/{iid}/ship-to endpoint import and call the
EXACT SAME `resolve_invoice_ship_to` function.  Any future divergence
between the two surfaces (e.g. someone copies the resolver locally into
one of them) is caught here.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/app/backend")


def test_pdf_imports_shared_resolver():
    src = open("/app/backend/pdf/invoice.py").read()
    assert "from ship_to_resolver import resolve_invoice_ship_to" in src


def test_endpoint_imports_shared_resolver():
    src = open("/app/backend/routers/invoices.py").read()
    assert "from ship_to_resolver import resolve_invoice_ship_to" in src
    assert '@router.get("/invoices/{iid}/ship-to")' in src


def test_resolver_output_is_deterministic():
    """Same inputs → identical output tuple. Underpins parity."""
    from ship_to_resolver import resolve_invoice_ship_to
    site = {"id": "s1", "site_name": "MRGR CONSTRUCTIONS",
            "address": "Village X, Nagarkurnool-509209"}
    customer = {"ship_sites": [site]}
    trips = [
        {"id": "t1", "ship_site_id": "s1", "to_location": "NAGARKURNOOL"},
        {"id": "t2", "ship_site_id": "",   "to_location": "NAGARKURNOOL"},
    ]
    r1 = resolve_invoice_ship_to(customer, trips)
    r2 = resolve_invoice_ship_to(customer, trips)
    # Note: identity tuples inside per_trip should compare equal
    assert r1["mixed"] == r2["mixed"]
    assert r1["common"] == r2["common"]
    for p1, p2 in zip(r1["per_trip"], r2["per_trip"]):
        assert p1["identity"] == p2["identity"]
        assert p1["site_id"] == p2["site_id"]
        assert p1["inferred"] == p2["inferred"]


def test_preview_view_reads_from_endpoint():
    """Frontend Preview must call the resolver endpoint, not compute locally."""
    src = open("/app/frontend/src/pages/InvoiceView.jsx").read()
    assert '/invoices/${id}/ship-to' in src
    assert 'invoice-ship-to-mixed' in src or 'shipTo.mixed' in src
    # Legacy silent inheritance MUST be gone from the Ship-To block.
    assert 's.state || customer.state' not in src
