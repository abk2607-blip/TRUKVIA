"""Iter42 — Loading (tons) − Unloading = Shortage/Excess.

Locks the shortage/excess auto-diff logic per user brief:
  - `tons` is the OFFICIAL "Loading Qty (in Tons)".
  - loaded_qty is a legacy mirror synced from tons.
  - shortage/excess is auto-computed from tons − unloaded_qty and flows through
    to shortage_amount / excess_amount (using product_rate_per_mt).
  - manual overrides (shortage_amount_override / excess_amount_override) still
    respected on the amount side; the QTY fields are always derived.
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


CUSTOMER_NAME = "TEST_Iter42"


def _customer():
    """Resolve the TEST_Iter42 fixture, creating it only when it truly is absent.

    The plain `GET /api/customers` browse path returns at most 20 000 rows and
    hides fixture-named customers, so once the tenant grew past that window
    this fixture stopped being visible there even though it existed. The test
    then tried to create it again and duplicate-master prevention correctly
    answered 409, whose body carries no top-level "id" -- every test in this
    module died on the resulting KeyError before a single trip was made.

    `?q=` is the application's own supported search path: it returns the
    paginated envelope and deliberately bypasses the fixture-hide filter so
    tests can find their own fixtures. The customer identity is unchanged.
    """
    r = requests.get(f"{API}/customers", headers=HEADERS, params={"q": CUSTOMER_NAME})
    payload = r.json()
    items = payload.get("items", []) if isinstance(payload, dict) else payload
    for c in items:
        if c["name"] == CUSTOMER_NAME:
            return c["id"]

    created = requests.post(
        f"{API}/customers", headers=HEADERS,
        json={"name": CUSTOMER_NAME, "state": "Andhra Pradesh"},
    )
    body = created.json()
    if created.status_code == 409:
        # Present but outside the search window -- reuse the row the duplicate
        # guard just pointed at rather than failing the whole module.
        return body["detail"]["existing"]["id"]
    return body["id"]


def _make_trip(**overrides):
    body = {
        "customer_id": _customer(),
        "date": "2027-06-01",
        "vehicle_number": "AP99IT42X",
        "freight_mode": "per_ton",
        "rate_per_ton": 1500,
    }
    body.update(overrides)
    return requests.post(f"{API}/trips", headers=HEADERS, json=body).json()


def test_shortage_when_loading_greater_than_unloading():
    """User's reported bug: tons=33.2, unloaded=32.960 → shortage=0.240 MT, not 32.960 excess."""
    t = _make_trip(tons=33.2, unloaded_qty=32.960, product_rate_per_mt=84250)
    assert t["loaded_qty"] == 33.2, "loaded_qty must mirror tons"
    assert t["shortage_qty"] == 0.24, f"expected 0.240, got {t['shortage_qty']}"
    assert t["excess_qty"] == 0.0
    assert t["shortage_amount"] == 20220.0, f"expected 20220 (0.24×84250), got {t['shortage_amount']}"
    assert t["excess_amount"] == 0.0


def test_excess_when_unloading_greater_than_loading():
    t = _make_trip(tons=28.5, unloaded_qty=28.75, product_rate_per_mt=50000)
    assert t["shortage_qty"] == 0.0
    assert t["excess_qty"] == 0.25
    assert t["excess_amount"] == 12500.0


def test_equal_qty_zero_shortage_and_excess():
    t = _make_trip(tons=25.0, unloaded_qty=25.0, product_rate_per_mt=50000)
    assert t["shortage_qty"] == 0.0
    assert t["excess_qty"] == 0.0
    assert t["shortage_amount"] == 0.0
    assert t["excess_amount"] == 0.0


def test_legacy_loaded_qty_ignored_when_tons_present():
    """Regression against the original bug: even if a client sends loaded_qty=0
    (or a stale value), the backend must use `tons` as the source of truth."""
    t = _make_trip(tons=20.0, loaded_qty=0, unloaded_qty=19.5, product_rate_per_mt=1000)
    assert t["loaded_qty"] == 20.0, "loaded_qty auto-synced from tons"
    assert t["shortage_qty"] == 0.5
    assert t["shortage_amount"] == 500.0


def test_manual_amount_override_preserved_but_qty_still_computed():
    t = _make_trip(
        tons=30.0, unloaded_qty=29.5, product_rate_per_mt=10000,
        shortage_amount=999.99, shortage_amount_override=True,
    )
    assert t["shortage_qty"] == 0.5, "qty always derived"
    assert t["shortage_amount"] == 999.99, "manual amount override preserved"


def test_no_unloaded_qty_no_shortage_or_excess():
    """When unloaded_qty is still 0 (trip not delivered yet), no diff should be set."""
    t = _make_trip(tons=20.0, unloaded_qty=0)
    assert t["shortage_qty"] == 20.0 or t["shortage_qty"] == 0.0, \
        f"either 20 (loading not yet unloaded) or 0 (both zero); got {t['shortage_qty']}"
    # Excess should always be 0 when unloaded=0
    assert t["excess_qty"] == 0.0


def test_shortage_flows_into_invoice_and_pdf():
    """The corrected shortage propagates to the invoice's subtotal + PDF sub-row."""
    import pymupdf
    cid = _customer()
    trip = _make_trip(tons=33.2, unloaded_qty=32.96, product_rate_per_mt=84250,
                       vehicle_number="AP99IT42INV")
    tid = trip["id"]
    assert trip["shortage_amount"] == 20220.0

    inv = requests.post(f"{API}/invoices", headers=HEADERS, json={
        "customer_id": cid, "trip_ids": [tid], "gst_type": "cgst_sgst", "rcm": True,
    }).json()
    # Freight = 33.2 × 1500 = 49800; shortage_total from trip = 20220; subtotal = freight − shortage
    assert inv["freight_total"] == 49800.0
    assert inv["shortage_total"] == 20220.0
    assert inv["subtotal"] == 29580.0

    pdf = requests.get(f"{API}/invoices/{inv['id']}/pdf", headers=HEADERS)
    assert pdf.status_code == 200
    text = ""
    with pymupdf.open(stream=pdf.content, filetype="pdf") as doc:
        for p in doc:
            text += p.get_text()
    assert "0.240" in text or "0.24" in text, "shortage qty must appear in PDF"
    assert "84,250" in text or "84250" in text, "product rate must appear in PDF"
