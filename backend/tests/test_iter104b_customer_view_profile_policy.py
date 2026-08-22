"""Iter104b · Customer View — Profile + Policy panel + Edit round-trip.

Guards the small enhancement to the Customer View screen:
- Read-only Customer Profile card (name/GSTIN/state/pincode/phone/email/address)
- Read-only Current Billing Policy card (freight method, shortage method,
  custom vs product-fallback allowance, effective from, active status)
- Edit button (`customer-view-edit-btn`) navigates to
  /customers?edit={id}&returnTo=history — Customers.jsx auto-opens the modal
  on mount and, on save, returns to the Customer View screen.

Products, Drivers, Vehicles View screens are NOT changed by this iteration.
"""
from pathlib import Path


def _read(p):
    return (Path("/app/frontend/src/pages") / p).read_text()


def test_customer_view_has_profile_card():
    src = _read("CustomerHistory.jsx")
    assert 'data-testid="customer-view-profile-policy"' in src
    assert 'data-testid="customer-view-profile"' in src
    for k in ["cvp-name", "cvp-gstin", "cvp-state", "cvp-pincode",
              "cvp-phone", "cvp-email", "cvp-address"]:
        assert f'testid="{k}"' in src, f"missing testid={k}"


def test_customer_view_has_policy_card_with_fallback_indicator():
    src = _read("CustomerHistory.jsx")
    assert 'data-testid="customer-view-policy"' in src
    assert 'testid="cvp-freight-method"' in src
    assert 'testid="cvp-shortage-method"' in src
    # Both branches — custom vs product-fallback — must exist
    assert 'data-testid="cvp-custom-allowance"' in src
    assert 'data-testid="cvp-product-fallback"' in src
    assert 'testid="cvp-effective-from"' in src
    assert 'testid="cvp-policy-status"' in src


def test_customer_view_edit_button_deeplinks_to_customers_form():
    src = _read("CustomerHistory.jsx")
    assert 'data-testid="customer-view-edit-btn"' in src
    assert "returnTo=history" in src
    assert "/customers?edit=" in src


def test_customers_page_handles_deeplink_edit_and_returns_to_view():
    src = _read("Customers.jsx")
    # Reads ?edit={id}&returnTo=history from URL, opens modal automatically
    assert 'searchParams.get("edit")' in src
    assert 'searchParams.get("returnTo")' in src
    # On save it must navigate back to /customers/history/{id} when returnTo=history
    assert '`/customers/history/${editIdFromUrl}`' in src
    # Existing modal + save flow untouched
    assert "saveWithReturn.mutate" in src


def test_products_and_vehicles_and_drivers_untouched():
    """Iter104b is Customers-only. Testids/functions must exist untouched."""
    for pg in ("Products.jsx", "Vehicles.jsx", "Drivers.jsx"):
        src = _read(pg)
        # Their entity-view testids from Iter104 still present
        assert "view-" in src, f"{pg} lost its Iter104 view testid"
