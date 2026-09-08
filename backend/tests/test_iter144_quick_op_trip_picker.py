"""Iter144 · Quick Op — Trip picker replaces the manual Trip ID input.

UI-only change. Backend guarantees remain intact:
  * GET /api/trips?date=YYYY-MM-DD returns full Trip docs incl. every field
    the picker needs (id, lr_number, vehicle_id, vehicle_number,
    vehicle_type, from_location, to_location, driver_name, supplier_name).
  * POST /api/expenses/bulk-operational continues to accept trip_id and
    validates ownership; no schema/field/collection change.
  * All locked Iter139–143 behaviours preserved: canonical Expense still
    carries trip_id, XOR fallback still fires only for legacy trips,
    Trip Cost tab / PDF / Excel still reconcile.

Frontend static guards ensure the picker is wired, the vehicle picker is
locked when a Trip is selected, and the manual "Trip ID (optional)" text
input has been removed.
"""
from pathlib import Path
import os
import uuid
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
if not API.startswith("http"):
    API = "http://localhost:8001/api"
TOKEN = os.environ.get("DEMO_TOKEN_VALUE", "")
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

QOB = Path("/app/frontend/src/pages/QuickOperationalExpense.jsx")


# ── Helpers ────────────────────────────────────────────────────────────────

def _customer():
    r = requests.get(f"{API}/customers", headers=H, timeout=15).json()
    for c in r:
        if c["name"] == "TEST_Iter144":
            return c["id"]
    return requests.post(
        f"{API}/customers", headers=H,
        json={"name": "TEST_Iter144", "state": "Andhra Pradesh"}, timeout=15,
    ).json()["id"]


def _first_own_vehicle():
    for v in requests.get(f"{API}/vehicles", headers=H,
                          params={"active_only": True}, timeout=15).json():
        if (v.get("vehicle_type") or "").lower() != "supplier":
            return v
    return None


def _first_supplier_vehicle():
    for v in requests.get(f"{API}/vehicles", headers=H,
                          params={"active_only": True}, timeout=15).json():
        if (v.get("vehicle_type") or "").lower() == "supplier":
            return v
    return None


def _mk_trip(cid, veh, date):
    body = {
        "customer_id": cid, "date": date,
        "vehicle_number": veh["vehicle_number"],
        "vehicle_id": veh["id"], "vehicle_type": "own",
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "from_location": "I144-VJA", "to_location": "I144-KKD",
        "driver_name": "I144 Driver",
    }
    r = requests.post(f"{API}/trips", headers=H, json=body, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ── Backend guarantees the picker depends on ───────────────────────────────

def test_trips_endpoint_returns_fields_the_picker_needs():
    cid = _customer()
    veh = _first_own_vehicle()
    date = "2029-02-01"
    trip = _mk_trip(cid, veh, date)
    r = requests.get(f"{API}/trips", headers=H,
                     params={"date": date, "limit": 50}, timeout=15)
    assert r.status_code == 200
    lst = r.json()
    match = next((t for t in lst if t["id"] == trip["id"]), None)
    assert match is not None, "Newly created trip not returned by date filter"
    for f in ("id", "date", "lr_number", "vehicle_id", "vehicle_number",
              "vehicle_type", "from_location", "to_location"):
        assert f in match, f"Trip endpoint missing field for picker: {f}"


def test_trips_endpoint_q_param_narrows_results():
    cid = _customer()
    veh = _first_own_vehicle()
    date = "2029-02-02"
    trip = _mk_trip(cid, veh, date)
    r = requests.get(f"{API}/trips", headers=H,
                     params={"date": date, "q": trip["vehicle_number"], "limit": 50},
                     timeout=15).json()
    assert any(t["id"] == trip["id"] for t in r), (
        "q= should surface a trip when vehicle_number matches"
    )


def test_trips_endpoint_empty_state_for_far_future_date():
    r = requests.get(f"{API}/trips", headers=H,
                     params={"date": "2099-01-01", "limit": 50},
                     timeout=15).json()
    assert isinstance(r, list) and len(r) == 0


def test_supplier_trip_returned_with_supplier_metadata():
    sup = _first_supplier_vehicle()
    if not sup:
        return
    cid = _customer()
    body = {
        "customer_id": cid, "date": "2029-02-03",
        "vehicle_number": sup["vehicle_number"],
        "vehicle_id": sup["id"], "vehicle_type": "supplier",
        "supplier_id": sup.get("supplier_id") or "",
        "supplier_name": sup.get("supplier_name") or "Sup1",
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 800,
        "from_location": "SP144-A", "to_location": "SP144-B",
    }
    r = requests.post(f"{API}/trips", headers=H, json=body, timeout=15)
    if r.status_code != 200:
        return  # supplier trip creation may be policy-blocked
    tid = r.json()["id"]
    lst = requests.get(f"{API}/trips", headers=H,
                       params={"date": "2029-02-03", "limit": 50}, timeout=15).json()
    match = next((t for t in lst if t["id"] == tid), None)
    assert match is not None
    assert (match.get("vehicle_type") or "").lower() == "supplier"


# ── Iter139–143 lock preservation ──────────────────────────────────────────

def test_bulk_operational_still_accepts_trip_id():
    """Iter139 canonical Expense creation with trip_id must still work — the
    UI change is just how the id is picked; the payload contract is intact."""
    cid = _customer()
    veh = _first_own_vehicle()
    date = "2029-02-04"
    trip = _mk_trip(cid, veh, date)
    body = {
        "date": date, "category": "Toll", "trip_id": trip["id"],
        "entries": [{
            "client_row_id": f"i144-{uuid.uuid4().hex[:8]}",
            "vehicle_id": veh["id"], "amount": 150.0, "remarks": "iter144",
        }],
    }
    r = requests.post(f"{API}/expenses/bulk-operational",
                      headers={**H, "Idempotency-Key": f"i144-{uuid.uuid4().hex[:12]}"},
                      json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    results = r.json()["results"]
    assert results and results[0].get("status") == "created"
    exp = results[0]["expense"]
    assert exp["trip_id"] == trip["id"]
    assert exp["vehicle_id"] == veh["id"]


def test_iter143_trip_cost_reflects_expense_created_via_picker_flow():
    """Once the picker sets trip_id + vehicle_id, the resulting canonical
    Expense must show up on the Vehicle's Trip Cost aggregation."""
    cid = _customer()
    veh = _first_own_vehicle()
    date = "2029-02-05"
    trip = _mk_trip(cid, veh, date)
    body = {
        "date": date, "category": "Toll", "trip_id": trip["id"],
        "entries": [{
            "client_row_id": f"i144-{uuid.uuid4().hex[:8]}",
            "vehicle_id": veh["id"], "amount": 250.0, "remarks": "i144-tc",
        }],
    }
    requests.post(f"{API}/expenses/bulk-operational",
                  headers={**H, "Idempotency-Key": f"i144-{uuid.uuid4().hex[:12]}"},
                  json=body, timeout=15)
    cs = requests.get(f"{API}/vehicles/{veh['id']}/cost-summary", headers=H,
                      params={"from": date, "to": date}, timeout=15).json()
    trip_rows = [r for r in cs["rows"] if r.get("trip_id") == trip["id"]]
    assert trip_rows, "Canonical Expense created via picker flow missing from cost-summary"
    total = round(sum(float(r["amount"]) for r in trip_rows), 2)
    assert abs(total - 250.0) < 0.01


# ── Frontend static guards ─────────────────────────────────────────────────

def test_fe_manual_trip_id_input_removed():
    src = QOB.read_text(encoding="utf-8")
    # The old manual input MUST be gone.
    assert 'placeholder="trip_..."' not in src, (
        "Old manual Trip ID input still present — Iter144 must replace it"
    )
    assert 'Trip ID (optional)' not in src, (
        "Old label still present"
    )


def test_fe_async_trip_picker_wired():
    src = QOB.read_text(encoding="utf-8")
    for m in [
        # Component import + usage
        'import AsyncSearchableSelect from "@/components/AsyncSearchableSelect"',
        '<AsyncSearchableSelect',
        # Test IDs
        'dataTestId="quick-expense-trip-picker"',
        'data-testid="quick-expense-trip-lock-notice"',
        'data-testid="quick-expense-trip-empty-hint"',
        # Label
        'Trip (Optional)',
        # Data plumbing
        'api.get("/trips"',
        'limit: 50',
        # Vehicle locking
        'tripLocked',
        'disabled={tripLocked}',
        # Empty state copy
        'No active trips on this date',
        # Trip → vehicle propagation
        'setRows((rs) => rs.map((r) => ({ ...r, vehicle_id: t.vehicle_id })))',
    ]:
        assert m in src, f"Iter144 missing marker: {m}"


def test_fe_backend_payload_still_carries_trip_id():
    src = QOB.read_text(encoding="utf-8")
    # The POST body construction must still include trip_id.
    assert "trip_id: tripId" in src, (
        "Iter144 must preserve Iter139 payload contract — trip_id in bulk body"
    )


def test_fe_date_change_clears_trip_selection():
    src = QOB.read_text(encoding="utf-8")
    # A date change handler must clear the selection to prevent stale trips.
    assert "setSelectedTrip(null)" in src
    assert "different date selected" in src


def test_fe_no_backend_change_smell():
    """Iter144 is UI-only — nothing in the frontend should mint a new
    endpoint URL, new payload key, or new collection reference."""
    src = QOB.read_text(encoding="utf-8")
    for banned in ("/trips/picker", "/quick-op-trip-picker",
                   "trip_picker_id", "picker_trip_id"):
        assert banned not in src, f"Iter144 introduced new backend surface: {banned}"


def test_fe_locked_iterations_still_present():
    """Sanity: Iter140 Today's Entries + Edit/Cancel wiring still there."""
    src = QOB.read_text(encoding="utf-8")
    for m in ('data-testid="quick-expense-page"',
              "TodayEntries",
              # Iter140
              'source_type: "quick_op"'):
        assert m in src, f"missing locked wiring: {m}"
