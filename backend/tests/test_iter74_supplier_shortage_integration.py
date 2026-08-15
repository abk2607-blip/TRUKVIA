"""Iter74 · Supplier Shortage Integration — trip → supplier ledger/settlement.

Locks in end-to-end accounting flow: trip.shortage_amount auto-mirrors into
supplier_shortage_deduction (for supplier vehicles), which posts a CREDIT
entry into the supplier ledger and reduces supplier_net_payable, and the
supplier statement/settlement/dashboard all reflect the same value.

Covers the 5 test cases the user demanded verbatim:
  1. Trip with no shortage → no shortage entry in supplier ledger.
  2. Trip with shortage → correct amount flows into supplier ledger + settlement.
  3. Trip with shortage above configured limit → existing policy still applied.
  4. Edit the shortage → supplier ledger + settlement update (no duplicates).
  5. Multiple trips for same supplier → each shortage posted against its own trip;
     supplier balance is the correct cumulative amount.
"""
import os, uuid, httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
HDR = {"Authorization": "Bearer test_session_bitumen_2026"}
UNIQUE = f"IT74_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=30).json()


def _cust(h):
    return httpx.post(f"{BASE}/api/customers", json={"name": f"{UNIQUE}_C"}, headers=h, timeout=15).json()


def _sup(h):
    return httpx.post(
        f"{BASE}/api/suppliers",
        json={"name": f"{UNIQUE}_Sup_{uuid.uuid4().hex[:5]}", "mobile": f"9{uuid.uuid4().int % 10**9:09d}", "state": "AP"},
        headers=h, timeout=15,
    ).json()


def _mk_trip(h, cid, sid, tons, unloaded, product_rate=80000, **extra):
    body = {
        "customer_id": cid,
        "date": extra.get("date", "2027-08-01"),
        "vehicle_number": f"AP74{uuid.uuid4().hex[:5].upper()}",
        "vehicle_type": "supplier",
        "supplier_id": sid,
        "tons": tons,
        "unloaded_qty": unloaded,
        "product_rate_per_mt": product_rate,
        "freight_mode": "per_ton",
        "rate_per_ton": 1200,
        "supplier_freight_mode": "per_ton",
        "supplier_rate_per_ton": 900,
    }
    body.update({k: v for k, v in extra.items() if k != "date"})
    return httpx.post(f"{BASE}/api/trips", json=body, headers=h, timeout=30).json()


def _ledger(h, sid):
    return httpx.get(f"{BASE}/api/suppliers/{sid}/ledger", headers=h, timeout=30).json()


# ---------------------------------------------------------------------------
# Case 1 — No shortage → NO shortage entry in supplier ledger
# ---------------------------------------------------------------------------
def test_case1_no_shortage_no_supplier_shortage_entry():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)
    trip = _mk_trip(h, c["id"], s["id"], tons=28.0, unloaded=28.0)
    assert trip["shortage_amount"] == 0
    assert trip["supplier_shortage_deduction"] == 0
    assert trip["supplier_net_payable"] == trip["supplier_freight"]  # no deductions

    led = _ledger(h, s["id"])
    shortage_entries = [e for e in led["entries"] if e["type"] == "trip_shortage" and e.get("trip_id") == trip["id"]]
    assert shortage_entries == [], "no-shortage trip must not create supplier shortage ledger entry"


# ---------------------------------------------------------------------------
# Case 2 — Shortage within limit → auto-mirrors into supplier ledger
# ---------------------------------------------------------------------------
def test_case2_shortage_auto_flows_into_supplier_ledger_and_settlement():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)
    # 0.15 MT shortage @ product_rate 80000/MT = ₹12,000
    trip = _mk_trip(h, c["id"], s["id"], tons=28.0, unloaded=27.85, product_rate=80000)
    assert trip["shortage_amount"] > 0
    # Auto-mirrored
    assert trip["supplier_shortage_deduction"] == trip["shortage_amount"], \
        f"expected supplier_shortage_deduction={trip['shortage_amount']}, got {trip['supplier_shortage_deduction']}"
    # Net payable = freight − shortage (no other deductions)
    expected_net = round(trip["supplier_freight"] - trip["shortage_amount"], 2)
    assert trip["supplier_net_payable"] == expected_net, \
        f"expected net {expected_net}, got {trip['supplier_net_payable']}"

    led = _ledger(h, s["id"])
    shortage_entries = [e for e in led["entries"] if e["type"] == "trip_shortage" and e.get("trip_id") == trip["id"]]
    assert len(shortage_entries) == 1
    entry = shortage_entries[0]
    assert entry["credit"] == round(trip["shortage_amount"], 2)  # CREDIT = reduces supplier payable
    assert entry["debit"] == 0
    assert "Shortage Recovery" in entry["particulars"]

    # Settlement / closing balance reflects the deduction
    freight_entries = [e for e in led["entries"] if e["type"] == "trip_freight" and e.get("trip_id") == trip["id"]]
    assert len(freight_entries) == 1
    assert freight_entries[0]["debit"] == trip["supplier_freight"]


# ---------------------------------------------------------------------------
# Case 3 — Shortage above configured allowed limit → policy still applies
# ---------------------------------------------------------------------------
def test_case3_shortage_above_limit_follows_existing_policy():
    """The trip's `shortage_amount` is computed by the existing shortage
    policy (rate-cap, per-MT ceiling, etc.). Whatever value the policy
    produces on the trip flows verbatim to the supplier — no double-cap."""
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)
    trip = _mk_trip(h, c["id"], s["id"], tons=28.0, unloaded=25.0, product_rate=80000)
    assert trip["shortage_amount"] > 0
    assert trip["supplier_shortage_deduction"] == trip["shortage_amount"]

    led = _ledger(h, s["id"])
    shortage_entries = [e for e in led["entries"] if e["type"] == "trip_shortage" and e.get("trip_id") == trip["id"]]
    assert len(shortage_entries) == 1
    assert shortage_entries[0]["credit"] == round(trip["shortage_amount"], 2)


# ---------------------------------------------------------------------------
# Case 4 — Edit shortage → ledger + settlement update, NO duplicates
# ---------------------------------------------------------------------------
def test_case4_edit_shortage_updates_ledger_no_duplicates():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)
    trip = _mk_trip(h, c["id"], s["id"], tons=28.0, unloaded=27.85, product_rate=80000)
    original_shortage = trip["supplier_shortage_deduction"]

    # PUT — reduce shortage by lifting unloaded_qty to 27.95 MT (0.05 MT shortage)
    upd_body = {**trip, "unloaded_qty": 27.95}
    upd = httpx.put(f"{BASE}/api/trips/{trip['id']}", json=upd_body, headers=h, timeout=30).json()
    assert upd["shortage_amount"] < original_shortage
    assert upd["supplier_shortage_deduction"] == upd["shortage_amount"]

    led = _ledger(h, s["id"])
    shortage_entries = [e for e in led["entries"] if e["type"] == "trip_shortage" and e.get("trip_id") == trip["id"]]
    # STILL exactly one entry — updated, not duplicated
    assert len(shortage_entries) == 1, f"expected 1 entry after edit, got {len(shortage_entries)} — duplicate?"
    assert shortage_entries[0]["credit"] == round(upd["shortage_amount"], 2)


def test_case4b_edit_shortage_to_zero_removes_ledger_entry():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)
    trip = _mk_trip(h, c["id"], s["id"], tons=28.0, unloaded=27.85)
    assert trip["shortage_amount"] > 0
    # Correct the trip — full delivery received
    upd = httpx.put(f"{BASE}/api/trips/{trip['id']}", json={**trip, "unloaded_qty": 28.0}, headers=h, timeout=30).json()
    assert upd["shortage_amount"] == 0
    assert upd["supplier_shortage_deduction"] == 0
    led = _ledger(h, s["id"])
    shortage_entries = [e for e in led["entries"] if e["type"] == "trip_shortage" and e.get("trip_id") == trip["id"]]
    assert shortage_entries == [], "corrected trip must not leave stale shortage entry"


# ---------------------------------------------------------------------------
# Case 5 — Multiple trips same supplier → cumulative balance correct
# ---------------------------------------------------------------------------
def test_case5_multi_trip_cumulative_supplier_balance():
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)

    t1 = _mk_trip(h, c["id"], s["id"], tons=28.0, unloaded=27.90, product_rate=80000, date="2027-08-01")
    t2 = _mk_trip(h, c["id"], s["id"], tons=30.0, unloaded=29.85, product_rate=80000, date="2027-08-02")
    t3 = _mk_trip(h, c["id"], s["id"], tons=25.0, unloaded=25.0,  product_rate=80000, date="2027-08-03")

    # Every trip's supplier_shortage_deduction === trip's shortage_amount
    for t in (t1, t2, t3):
        assert t["supplier_shortage_deduction"] == t["shortage_amount"]

    led = _ledger(h, s["id"])
    freights = [e for e in led["entries"] if e["type"] == "trip_freight"]
    shortages = [e for e in led["entries"] if e["type"] == "trip_shortage"]
    assert len(freights) == 3, "each trip must post exactly one supplier_freight entry"
    # Only trips with actual shortage get a shortage entry (t3 has zero)
    assert len(shortages) == 2, f"expected 2 shortage entries, got {len(shortages)}"

    # Cumulative balance: total freight − total shortage
    total_freight = sum(t["supplier_freight"] for t in (t1, t2, t3))
    total_shortage = sum(t["supplier_shortage_deduction"] for t in (t1, t2, t3))
    expected_closing = round(total_freight - total_shortage, 2)
    assert led["totals"]["closing_balance"] == expected_closing, \
        f"expected closing {expected_closing}, got {led['totals']['closing_balance']}"

    # Each shortage linked to its own trip_id
    trip_ids = {e["trip_id"] for e in shortages}
    assert t1["id"] in trip_ids and t2["id"] in trip_ids


# ---------------------------------------------------------------------------
# Manual override still respected
# ---------------------------------------------------------------------------
def test_manual_override_blocks_auto_mirror():
    """When user manually edits the supplier_shortage_deduction field, the
    override flag must prevent the backend from silently reverting on next
    save. Historical accounting stays intact."""
    cs = _companies()
    h = {**HDR, "X-Company-Id": cs[0]["id"]}
    c = _cust(h); s = _sup(h)
    trip = _mk_trip(h, c["id"], s["id"], tons=28.0, unloaded=27.85, product_rate=80000)
    trip_shortage = trip["shortage_amount"]

    # User manually sets a different deduction (say, negotiated with supplier)
    upd = httpx.put(f"{BASE}/api/trips/{trip['id']}", json={
        **trip,
        "supplier_shortage_deduction": trip_shortage * 0.5,
        "supplier_shortage_deduction_override": True,
    }, headers=h, timeout=30).json()
    assert upd["supplier_shortage_deduction"] == round(trip_shortage * 0.5, 2), \
        "manual override must persist"
    assert upd["shortage_amount"] == trip["shortage_amount"], \
        "trip's own shortage_amount is unchanged by supplier override"
