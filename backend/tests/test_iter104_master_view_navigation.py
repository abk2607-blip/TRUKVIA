"""Iter104 · Option A — Master List row Name → View click navigation guard.

Confirms the four masters (Customers, Drivers, Products, Vehicles) expose a
`view-<entity>-<id>` clickable trigger on each row that routes to the
existing details/history screen (Customers, Drivers) or opens the Edit
modal in read-only View mode (Products, Vehicles). Nothing else about the
row (Edit/Delete/History/Ledger) should regress.

This is a lightweight structural test — it just asserts each masters page
returns the expected DOM markers via the served bundle. Playwright covers
the actual click-through flows.
"""
import re
from pathlib import Path

FE = Path("/app/frontend/src/pages")


def _read(p):
    return (FE / p).read_text()


def test_customers_row_name_is_a_link_to_history():
    src = _read("Customers.jsx")
    assert "to={`/customers/history/${c.id}`}" in src, \
        "Customer row name must link to /customers/history/:id"
    assert 'data-testid={`view-customer-${c.id}`}' in src
    # Edit / Delete / History / Ship-To buttons must still exist
    assert 'data-testid={`edit-customer-${c.id}`}' in src
    assert 'data-testid={`delete-customer-${c.id}`}' in src
    assert 'data-testid={`history-customer-${c.id}`}' in src
    assert 'data-testid={`ship-sites-customer-${c.id}`}' in src


def test_drivers_row_name_is_a_link_to_history():
    src = _read("Drivers.jsx")
    assert "to={`/drivers/${d.id}/history`}" in src
    assert 'data-testid={`view-driver-${d.id}`}' in src
    # Existing actions preserved
    assert 'data-testid={`history-driver-${d.id}`}' in src
    assert 'data-testid={`ledger-driver-${d.id}`}' in src
    assert 'data-testid={`edit-driver-${d.id}`}' in src
    assert 'data-testid={`delete-driver-${d.id}`}' in src


def test_products_row_name_opens_view_mode():
    src = _read("Products.jsx")
    assert "const openView = " in src, "Products must expose openView(p)"
    assert 'data-testid={`view-product-${p.id}`}' in src
    assert "setViewMode(true)" in src
    assert "setViewMode(false)" in src
    # Modal renames itself + surfaces Switch to Edit + hides Save
    assert 'data-testid="product-modal-title"' in src
    assert 'data-testid="product-switch-to-edit"' in src
    # Edit / Delete still wired
    assert 'data-testid={`edit-product-${p.id}`}' in src
    assert 'data-testid={`delete-product-${p.id}`}' in src


def test_vehicles_row_number_opens_view_mode():
    src = _read("Vehicles.jsx")
    assert "const openView = " in src, "Vehicles must expose openView(v)"
    assert 'data-testid={`view-vehicle-${v.id}`}' in src
    assert 'data-testid="vehicle-modal-title"' in src
    assert 'data-testid="vehicle-switch-to-edit"' in src
    # Edit / Delete still wired
    assert 'data-testid={`edit-vehicle-${v.id}`}' in src
    assert 'data-testid={`delete-vehicle-${v.id}`}' in src


def test_app_routes_backing_the_view_links_exist():
    src = (Path("/app/frontend/src") / "App.js").read_text()
    assert 'path="/customers/history/:id"' in src
    assert 'path="/drivers/:id/history"' in src
    # Products & Vehicles route to themselves — modal opens in-page.
    assert 'path="/products"' in src
    assert 'path="/vehicles"' in src
