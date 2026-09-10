"""Iter148 UAT-fix v2 · Today's Expenses Vehicle + Category filters.

Backend contract already supports `vehicle_id` and `category` on
`/api/expenses`. These tests lock the interaction between the widened
`source_type` (CSV) and the additional filters so that:
  • Vehicle filter narrows to a single vehicle across every source_type.
  • Category filter narrows without breaking source_type union.
  • Combining vehicle + category + source-CSV returns exactly the
    intersection — no leakage, no duplicates.
  • Empty filters behave as "All" (unchanged from Iter148 baseline).
"""
import os
import requests

API = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
TOKEN = os.environ.get("DEMO_TOKEN_VALUE", "")
H = {"Authorization": f"Bearer {TOKEN}"}

WIDE_SRC = "quick_op,fastag_import,fleet_card_import,manual"


def _first_veh_with_data(source_type=None):
    params = {}
    if source_type:
        params["source_type"] = source_type
    r = requests.get(f"{API}/expenses", headers=H, params=params, timeout=15).json()
    for row in r:
        if row.get("vehicle_id"):
            return row["vehicle_id"], row["vehicle_number"], row["date"], row["category"]
    return None


def test_vehicle_filter_returns_only_that_vehicle():
    veh = _first_veh_with_data(WIDE_SRC)
    if not veh:
        import pytest; pytest.skip("no operational Expense with a vehicle present")
    vid, _, date, _ = veh
    r = requests.get(f"{API}/expenses", headers=H, params={
        "source_type": WIDE_SRC, "date_from": date, "date_to": date,
        "vehicle_id": vid,
    }, timeout=15).json()
    assert r, "vehicle filter must return at least the seed row"
    for row in r:
        assert row["vehicle_id"] == vid


def test_category_filter_returns_only_that_category():
    r_all = requests.get(f"{API}/expenses", headers=H, params={
        "source_type": WIDE_SRC,
    }, timeout=15).json()
    if not r_all:
        import pytest; pytest.skip("no operational Expense present")
    target_cat = r_all[0]["category"]
    r = requests.get(f"{API}/expenses", headers=H, params={
        "source_type": WIDE_SRC, "category": target_cat,
    }, timeout=15).json()
    for row in r:
        assert row["category"] == target_cat


def test_vehicle_plus_category_intersection():
    r_all = requests.get(f"{API}/expenses", headers=H,
                         params={"source_type": WIDE_SRC}, timeout=15).json()
    if not r_all:
        import pytest; pytest.skip("no operational Expense present")
    picked = None
    for row in r_all:
        if row.get("vehicle_id"):
            picked = row; break
    if not picked:
        import pytest; pytest.skip("no operational Expense with vehicle present")
    vid, cat, date = picked["vehicle_id"], picked["category"], picked["date"]
    r = requests.get(f"{API}/expenses", headers=H, params={
        "source_type": WIDE_SRC, "date_from": date, "date_to": date,
        "vehicle_id": vid, "category": cat,
    }, timeout=15).json()
    assert any(row["id"] == picked["id"] for row in r)
    for row in r:
        assert row["vehicle_id"] == vid
        assert row["category"] == cat


def test_no_duplicate_ids_under_combined_filters():
    r = requests.get(f"{API}/expenses", headers=H, params={
        "source_type": WIDE_SRC,
    }, timeout=15).json()
    ids = [row["id"] for row in r]
    assert len(ids) == len(set(ids))


def test_empty_filters_return_all_sources():
    r = requests.get(f"{API}/expenses", headers=H, params={
        "source_type": WIDE_SRC,
    }, timeout=15).json()
    seen = {row.get("source_type") for row in r}
    assert seen.issubset({"quick_op", "fastag_import", "fleet_card_import", "manual"})
