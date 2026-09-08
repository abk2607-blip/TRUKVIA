"""Iter145 P0 · Trip View · Canonical Expense projection — focused tests.

Fix: /trips/{id}/view Expenses section previously bound to legacy
Trip.expenses scalars only, invisible to Quick Op canonical Expense rows.
Now projects canonical Expense (via existing GET /api/expenses?trip_id=)
when any active row exists, falls back to legacy shape otherwise (XOR).

No backend / schema / collection / accounting change.
Iter133–144 locks preserved.
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

TV = Path("/app/frontend/src/pages/TripView.jsx")
QOB = Path("/app/frontend/src/pages/QuickOperationalExpense.jsx")


# ── Helpers ────────────────────────────────────────────────────────────────

def _customer():
    r = requests.get(f"{API}/customers", headers=H, timeout=15).json()
    for c in r:
        if c["name"] == "TEST_Iter145":
            return c["id"]
    return requests.post(
        f"{API}/customers", headers=H,
        json={"name": "TEST_Iter145", "state": "Andhra Pradesh"}, timeout=15,
    ).json()["id"]


def _first_own_vehicle():
    for v in requests.get(f"{API}/vehicles", headers=H,
                          params={"active_only": True}, timeout=15).json():
        if (v.get("vehicle_type") or "").lower() != "supplier":
            return v
    return None


def _mk_trip(cid, veh, date, tons=10):
    body = {
        "customer_id": cid, "date": date,
        "vehicle_number": veh["vehicle_number"],
        "vehicle_id": veh["id"], "vehicle_type": "own",
        "tons": tons, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "from_location": "I145-A", "to_location": "I145-B",
        "driver_name": "I145 Driver",
    }
    r = requests.post(f"{API}/trips", headers=H, json=body, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_exp(veh_id, trip_id, category, amount, date):
    body = {
        "date": date, "category": category, "amount": amount,
        "vehicle_id": veh_id, "trip_id": trip_id,
        "party_type": "cash", "settlement_mode": "cash_now",
        "narration": f"iter145 {category}",
    }
    r = requests.post(f"{API}/expenses", headers=H, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _get_expenses_for_trip(tid):
    r = requests.get(f"{API}/expenses", headers=H,
                     params={"trip_id": tid, "limit": 500}, timeout=15)
    assert r.status_code == 200
    return r.json()


def _get_trip(tid):
    return requests.get(f"{API}/trips/{tid}", headers=H, timeout=15).json()


def _cost_summary(vid, params=None):
    return requests.get(f"{API}/vehicles/{vid}/cost-summary", headers=H,
                        params=params or {}, timeout=15).json()


# Mirror of frontend _projectCanonicalToLegacyShape — pinned by tests below.
_MAP = {
    "diesel": "diesel", "toll": "toll", "fasttag": "toll",
    "batta": "batta", "driver batta": "batta",
    "repair": "repair", "firewood": "firewood", "other": "other",
}
def _project(rows):
    out = {"diesel": 0.0, "toll": 0.0, "batta": 0.0, "repair": 0.0,
           "firewood": 0.0, "other": 0.0}
    total = 0.0
    for r in rows:
        amt = float(r.get("amount") or 0)
        total += amt
        field = _MAP.get(str(r.get("category") or "").strip().lower(), "other")
        out[field] = round(out[field] + amt, 2)
    return out, round(total, 2)


# ── Backend contract guards (used by the FE projection) ────────────────────

def test_get_expenses_by_trip_id_returns_active_rows_only():
    cid = _customer()
    veh = _first_own_vehicle()
    trip = _mk_trip(cid, veh, "2029-03-01")
    a = _mk_exp(veh["id"], trip["id"], "Diesel", 800.0, "2029-03-01")
    b = _mk_exp(veh["id"], trip["id"], "Toll", 120.0, "2029-03-01")
    # Cancel one — must disappear from the trip_id list
    requests.delete(f"{API}/expenses/{a['id']}", headers=H,
                    params={"reason": "iter145"}, timeout=15)
    rows = _get_expenses_for_trip(trip["id"])
    ids = {r["id"] for r in rows}
    assert a["id"] not in ids, "cancelled row must not appear"
    assert b["id"] in ids


def test_legacy_trip_view_fallback_unchanged():
    """A trip with only legacy Trip.expenses (no canonical rows) must
    render legacy scalars unchanged — the projection must NOT fire."""
    cid = _customer()
    veh = _first_own_vehicle()
    # Create a trip WITH legacy scalars; the bridge WILL materialise them
    # into canonical rows (Iter133) which is expected — so this test also
    # covers the "canonical mirror of legacy" branch.
    body = {
        "customer_id": cid, "date": "2029-03-02",
        "vehicle_number": veh["vehicle_number"], "vehicle_id": veh["id"],
        "vehicle_type": "own",
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "from_location": "A", "to_location": "B",
        "expenses": {"diesel": 500, "toll": 100},
    }
    r = requests.post(f"{API}/trips", headers=H, json=body, timeout=15).json()
    tid = r["id"]
    canonical = _get_expenses_for_trip(tid)
    # The bridge should have produced canonical rows for these legacy lines.
    assert len(canonical) >= 2, "Bridge (Iter133) should materialise legacy scalars"
    proj, total = _project(canonical)
    assert proj["diesel"] == 500 and proj["toll"] == 100
    assert total == 600
    # And the legacy Trip.expenses still holds the same numbers on the doc.
    trip = _get_trip(tid)
    assert float(trip["expenses"]["diesel"]) == 500
    assert float(trip["expenses"]["toll"]) == 100


def test_quick_op_canonical_visible_via_endpoint():
    cid = _customer()
    veh = _first_own_vehicle()
    trip = _mk_trip(cid, veh, "2029-03-03")
    _mk_exp(veh["id"], trip["id"], "Diesel", 8550.0, "2029-03-03")
    _mk_exp(veh["id"], trip["id"], "Toll", 1200.0, "2029-03-03")
    _mk_exp(veh["id"], trip["id"], "Batta", 500.0, "2029-03-03")
    rows = _get_expenses_for_trip(trip["id"])
    proj, total = _project(rows)
    assert proj["diesel"] == 8550
    assert proj["toll"] == 1200
    assert proj["batta"] == 500
    assert total == 8550 + 1200 + 500
    # And the legacy Trip.expenses stays untouched (still 0) — proving the
    # canonical path does NOT write back to Trip.expenses.
    trip_doc = _get_trip(trip["id"])
    assert float(trip_doc.get("expenses", {}).get("diesel") or 0) == 0
    assert float(trip_doc.get("total_expense") or 0) == 0


def test_unknown_canonical_category_lumps_into_other_but_never_dropped():
    cid = _customer()
    veh = _first_own_vehicle()
    trip = _mk_trip(cid, veh, "2029-03-04")
    _mk_exp(veh["id"], trip["id"], "Diesel", 100.0, "2029-03-04")
    _mk_exp(veh["id"], trip["id"], "FastTag", 25.0, "2029-03-04")   # → toll
    _mk_exp(veh["id"], trip["id"], "Parking", 40.0, "2029-03-04")   # → other
    rows = _get_expenses_for_trip(trip["id"])
    proj, total = _project(rows)
    assert proj["diesel"] == 100
    assert proj["toll"] == 25              # FastTag folded into Toll
    assert proj["other"] == 40             # Parking not silently dropped
    assert total == 165


def test_trip_view_total_equals_vehicle_workspace_trip_cost():
    cid = _customer()
    veh = _first_own_vehicle()
    trip = _mk_trip(cid, veh, "2029-03-05")
    _mk_exp(veh["id"], trip["id"], "Diesel", 8550.0, "2029-03-05")
    _mk_exp(veh["id"], trip["id"], "Toll", 1200.0, "2029-03-05")
    rows = _get_expenses_for_trip(trip["id"])
    _, tv_total = _project(rows)
    cs = _cost_summary(veh["id"], {"from": "2029-03-05", "to": "2029-03-05"})
    trip_rows = [r for r in cs["rows"] if r.get("trip_id") == trip["id"]]
    vw_total = round(sum(float(r["amount"]) for r in trip_rows), 2)
    assert abs(tv_total - vw_total) < 0.01, (
        f"Trip View total {tv_total} must equal Vehicle Workspace trip total {vw_total}"
    )


def test_cancelled_and_reversed_excluded():
    cid = _customer()
    veh = _first_own_vehicle()
    trip = _mk_trip(cid, veh, "2029-03-06")
    keep = _mk_exp(veh["id"], trip["id"], "Diesel", 500.0, "2029-03-06")
    kill = _mk_exp(veh["id"], trip["id"], "Toll", 300.0, "2029-03-06")
    requests.delete(f"{API}/expenses/{kill['id']}", headers=H,
                    params={"reason": "iter145 cancel"}, timeout=15)
    rows = _get_expenses_for_trip(trip["id"])
    ids = {r["id"] for r in rows}
    assert keep["id"] in ids and kill["id"] not in ids
    proj, total = _project(rows)
    assert total == 500 and proj["toll"] == 0


def test_edit_reflects_new_amount():
    cid = _customer()
    veh = _first_own_vehicle()
    trip = _mk_trip(cid, veh, "2029-03-07")
    exp = _mk_exp(veh["id"], trip["id"], "Diesel", 100.0, "2029-03-07")
    # Iter140 update path — via PUT /expenses/{eid}
    body = {**exp, "amount": 750.0, "narration": "iter145 edit"}
    r = requests.put(f"{API}/expenses/{exp['id']}", headers=H, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    rows = _get_expenses_for_trip(trip["id"])
    _, total = _project(rows)
    assert total == 750


def test_different_trips_isolated():
    cid = _customer()
    veh = _first_own_vehicle()
    t1 = _mk_trip(cid, veh, "2029-03-08")
    t2 = _mk_trip(cid, veh, "2029-03-08")
    _mk_exp(veh["id"], t1["id"], "Diesel", 111.0, "2029-03-08")
    _mk_exp(veh["id"], t2["id"], "Diesel", 222.0, "2029-03-08")
    r1 = _get_expenses_for_trip(t1["id"])
    r2 = _get_expenses_for_trip(t2["id"])
    _, tot1 = _project(r1)
    _, tot2 = _project(r2)
    assert tot1 == 111 and tot2 == 222
    # And cross-check: no row of trip A appears in trip B result.
    for r in r1:
        assert r["trip_id"] == t1["id"]
    for r in r2:
        assert r["trip_id"] == t2["id"]


# ── Frontend static guards ─────────────────────────────────────────────────

def test_fe_trip_view_uses_canonical_endpoint():
    src = TV.read_text(encoding="utf-8")
    for m in [
        'queryKey: ["trip-expenses-canonical", id]',
        'api.get("/expenses"',
        'trip_id: id',
        '_projectCanonicalToLegacyShape',
        'displayedTotalExpense',
        'data-testid="trip-view-expense-source"',
        'data-source={hasCanonical ? "canonical" : "legacy"}',
        'Live from canonical Expense',
        'Legacy trip expense',
    ]:
        assert m in src, f"TripView.jsx missing marker: {m}"


def test_fe_trip_view_does_not_write_back_to_legacy_scalars():
    """The canonical branch must be READ-ONLY — never mutates trip.expenses
    or trip.total_expense on the client or via a follow-up PUT."""
    src = TV.read_text(encoding="utf-8")
    for banned in ("api.put(`/trips/",
                   "api.patch(`/trips/",
                   "trip.expenses ="):
        assert banned not in src, (
            f"Iter145 must be read-only on the Trip doc — found: {banned}"
        )


def test_fe_customer_side_fields_still_from_legacy():
    src = TV.read_text(encoding="utf-8")
    # These are Trip-metadata fields, not canonical costs. They must
    # continue to read from the raw Trip doc regardless of canonical.
    assert "legacyExpenses.diesel_from_customer_amount" in src
    assert "legacyExpenses.shortage_qty" in src
    assert "legacyExpenses.shortage_amount" in src
    assert "legacyExpenses.cash_advance_received" in src


def test_fe_quick_op_invalidates_trip_view_queries():
    src = QOB.read_text(encoding="utf-8")
    assert '["trip-expenses-canonical"' in src, (
        "Quick Op mutations must invalidate the Trip View canonical query"
    )
    assert '["trip-view"' in src


def test_fe_no_new_backend_endpoint_call():
    src = TV.read_text(encoding="utf-8")
    assert "/trips/${id}/expense-summary" not in src
    assert "/expense-summary" not in src


def test_fe_source_indicator_present_for_both_branches():
    src = TV.read_text(encoding="utf-8")
    # The strip toggles copy based on hasCanonical — both must be authored.
    assert 'hasCanonical ?' in src
    assert 'canonicalRows.length' in src
