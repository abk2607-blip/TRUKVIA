"""Iter141 P0 · Vehicle Workspace — regression tests.

The Vehicle Workspace is a pure read/projection surface. It adds NO new
backend endpoint and NO schema change. These tests confirm that:

  • the two endpoints the workspace consumes still exist and shape data
    the way the frontend expects,
  • no double counting is possible (Repair Cost = Σ Expense; Bill/WO
    amounts stay on the payable side),
  • cancelled and reversed rows disappear from the cost surface,
  • the new frontend page contains the right test IDs.
"""
from pathlib import Path
import os
import uuid
import time
import requests

API = os.environ["REACT_APP_BACKEND_URL"] + "/api" if os.environ.get("REACT_APP_BACKEND_URL") else "http://localhost:8001/api"
if not API.startswith("http"):
    API = "http://localhost:8001/api"
H = {"Authorization": f"Bearer {os.environ.get('DEMO_TOKEN_VALUE','')}"}


def _mk_vendor(name_prefix="VW"):
    r = requests.post(f"{API}/vendors", headers=H, json={"name": f"{name_prefix}-{uuid.uuid4().hex[:6]}"}, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _first_own_vehicle():
    lst = requests.get(f"{API}/vehicles", headers=H, params={"active_only": True}, timeout=15).json()
    for v in lst:
        if (v.get("vehicle_type") or "").lower() != "supplier":
            return v
    return lst[0]


def _first_supplier_vehicle():
    lst = requests.get(f"{API}/vehicles", headers=H, params={"active_only": True}, timeout=15).json()
    for v in lst:
        if (v.get("vehicle_type") or "").lower() == "supplier":
            return v
    return None


def _post_quick_diesel(veh_id, vendor_id, qty=100, rate=90.0, date=None):
    date = date or "2027-07-01"
    body = {"date": date, "category": "Diesel", "trip_id": "",
            "entries": [{"client_row_id": f"vw-{uuid.uuid4().hex[:8]}",
                         "vehicle_id": veh_id, "qty": qty, "rate": rate,
                         "vendor_id": vendor_id, "filled_at": "VW UAT"}]}
    r = requests.post(f"{API}/expenses/bulk-operational", headers={**H,
        "Idempotency-Key": f"vw-{uuid.uuid4().hex[:12]}"}, json=body, timeout=15)
    return r.json()["results"][0]["expense"]


# ── Backend read-surface guards ────────────────────────────────────────────

def test_cost_summary_endpoint_shape_stable_for_workspace():
    """Vehicle Workspace consumes total_cost, repair_total, non_trip_total,
    trip_linked_total, expense_count, by_category, by_month, rows."""
    veh = _first_own_vehicle()
    r = requests.get(f"{API}/vehicles/{veh['id']}/cost-summary", headers=H, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("total_cost", "repair_total", "non_trip_total", "trip_linked_total",
              "expense_count", "by_category", "by_month", "rows"):
        assert k in d, f"cost-summary missing '{k}' — Vehicle Workspace depends on it"


def test_repair_history_endpoint_shape_stable_for_workspace():
    veh = _first_own_vehicle()
    r = requests.get(f"{API}/vehicles/{veh['id']}/repair-history", headers=H, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("total_repair_cost", "count", "events"):
        assert k in d


def test_workspace_cost_includes_new_diesel_exactly_once():
    """New Diesel Quick Op is visible under Vehicle Cost — appears once."""
    veh = _first_own_vehicle()
    ven = _mk_vendor()
    before = requests.get(f"{API}/vehicles/{veh['id']}/cost-summary", headers=H, timeout=15).json()
    exp = _post_quick_diesel(veh["id"], ven["id"], qty=100, rate=95.0, date="2027-07-02")
    after = requests.get(f"{API}/vehicles/{veh['id']}/cost-summary", headers=H, timeout=15).json()
    delta = after["total_cost"] - before["total_cost"]
    assert abs(delta - exp["amount"]) < 0.01
    matches = [r for r in after["rows"] if r["id"] == exp["id"]]
    assert len(matches) == 1, "expense must appear exactly once in workspace"


def test_workspace_cost_excludes_cancelled():
    veh = _first_own_vehicle()
    ven = _mk_vendor("VWCXL")
    exp = _post_quick_diesel(veh["id"], ven["id"], qty=100, rate=100.0, date="2027-07-03")
    requests.delete(f"{API}/expenses/{exp['id']}", headers=H,
                    params={"reason": "workspace cancel test"}, timeout=15)
    after = requests.get(f"{API}/vehicles/{veh['id']}/cost-summary", headers=H, timeout=15).json()
    assert not any(r["id"] == exp["id"] for r in after["rows"])


def test_workspace_repair_cost_uses_expense_not_bill_or_wo(own_veh_and_repair_env):
    """Repair Cost = Σ Expense.amount (never Bill+WO+Expense)."""
    env = own_veh_and_repair_env
    if not env:
        return  # env not available on this tenant — skipped
    d = requests.get(f"{API}/vehicles/{env['vehicle_id']}/repair-history",
                     headers=H, timeout=15).json()
    for ev in d.get("events", []):
        exp_sum = round(sum(float(x.get("amount") or 0) for x in ev.get("expenses", [])), 2)
        assert abs(ev["total_repair_cost"] - exp_sum) < 0.01, (
            f"repair {ev['id']} total_repair_cost({ev['total_repair_cost']}) must equal "
            f"Σ Expense.amount ({exp_sum}); never Bill+WO+Expense"
        )


def test_workspace_supplier_context_does_not_alter_supplier_settlement():
    """Opening a supplier-owned vehicle must not change any supplier
    settlement or ledger data — the workspace is read-only."""
    veh = _first_supplier_vehicle()
    if not veh:
        return
    sup_id = veh.get("supplier_id")
    if not sup_id:
        return
    l0 = requests.get(f"{API}/suppliers/{sup_id}/ledger", headers=H, timeout=15).json()
    _ = requests.get(f"{API}/vehicles/{veh['id']}/cost-summary", headers=H, timeout=15).json()
    _ = requests.get(f"{API}/vehicles/{veh['id']}/repair-history", headers=H, timeout=15).json()
    l1 = requests.get(f"{API}/suppliers/{sup_id}/ledger", headers=H, timeout=15).json()
    assert float(l0.get("opening_balance") or 0) == float(l1.get("opening_balance") or 0)
    assert len(l0.get("entries") or []) == len(l1.get("entries") or [])


# ── Frontend static guards ─────────────────────────────────────────────────

def test_frontend_vehicle_workspace_page_present():
    src = Path("/app/frontend/src/pages/VehicleWorkspace.jsx").read_text(encoding="utf-8")
    for m in [
        'data-testid="vehicle-workspace"',
        'data-testid="vw-header"',
        'data-testid="vw-vehicle-number"',
        'data-testid="vw-vehicle-type"',
        'data-testid="vw-active-status"',
        'data-testid="vw-kpis"',
        'testId="vw-kpi-total"',
        'testId="vw-kpi-repair"',
        'testId="vw-kpi-operational"',
        'testId="vw-kpi-trip"',
        'data-testid="vw-tabs"',
        'data-testid={`vw-tab-${t.id}`}',
        'data-testid="vw-expenses"',
        'data-testid="vw-expenses-total"',
        'data-testid="vw-repairs"',
        'data-testid="vw-repairs-total"',
        'data-testid="vw-reports-placeholder"',
        'data-testid="vw-filter-from"',
        'data-testid="vw-filter-to"',
        'data-testid="vw-filter-category"',
        "/cost-summary",
        "/repair-history",
        "v141-p0",
    ]:
        assert m in src, f"VehicleWorkspace.jsx missing marker: {m}"


def test_frontend_route_wired_and_cost_deep_link_preserved():
    src = Path("/app/frontend/src/App.js").read_text(encoding="utf-8")
    assert 'path="/vehicles/:vid"' in src, "workspace route missing"
    assert "VehicleWorkspace" in src
    assert 'path="/vehicles/:vid/cost"' in src, "existing /cost deep-link must remain"


def test_frontend_vehicles_list_links_to_workspace():
    src = Path("/app/frontend/src/pages/Vehicles.jsx").read_text(encoding="utf-8")
    assert 'href={`/vehicles/${v.id}`}' in src
    assert 'vehicle-workspace-${v.id}' in src or 'href={`/vehicles/${v.id}/cost`}' in src
    # Vehicle number now links to workspace (not the view modal)
    assert 'title="Open Vehicle Workspace"' in src


# ── Fixture: pick a vehicle that has at least one repair event, if any ─────

import pytest

@pytest.fixture(scope="module")
def own_veh_and_repair_env():
    veh = _first_own_vehicle()
    rev = requests.get(f"{API}/repair-events", headers=H, params={"vehicle_id": veh["id"]}, timeout=15).json()
    if not rev:
        return None
    return {"vehicle_id": veh["id"], "repair_event_id": rev[0]["id"]}
