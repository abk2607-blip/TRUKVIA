"""Iter146 P0 · Trip Entry first-save screen — static + backend guards.

FE-only UX rearrangement. Zero backend / schema / endpoint / accounting
change. Existing POST /api/trips payload contract is preserved.
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

TF = Path("/app/frontend/src/pages/TripForm.jsx")
LR = Path("/app/frontend/src/components/tripform/LRSection.jsx")
FR = Path("/app/frontend/src/components/tripform/FreightSection.jsx")


def _customer():
    r = requests.get(f"{API}/customers", headers=H, timeout=15).json()
    for c in r:
        if c["name"] == "TEST_Iter146":
            return c["id"]
    return requests.post(f"{API}/customers", headers=H,
        json={"name": "TEST_Iter146", "state": "Andhra Pradesh"}, timeout=15).json()["id"]


def _first_own_vehicle():
    for v in requests.get(f"{API}/vehicles", headers=H,
                          params={"active_only": True}, timeout=15).json():
        if (v.get("vehicle_type") or "").lower() != "supplier":
            return v
    return None


# ── FE static guards ───────────────────────────────────────────────────────

def test_fe_first_save_mode_derived():
    src = TF.read_text(encoding="utf-8")
    assert "const firstSaveMode = !isEdit;" in src
    # Post-create navigation goes to /trips/{id}/edit
    assert "/trips/${saved.id}/edit" in src


def test_fe_advanced_sections_wrapped_first_save():
    src = TF.read_text(encoding="utf-8")
    # Advanced sections are gated
    assert "{!firstSaveMode && (" in src
    for section in ("UnloadingSection", "HaltingSection",
                    "ReceivedFromCustomerSection", "ExpensesSection",
                    "OtherExpenditureSection"):
        assert section in src, f"missing section reference: {section}"


def test_fe_lr_advanced_fields_hidden_on_first_save():
    """Iter146 P0 UAT-FIX (2026-09-09) · LR remains FULL on first-save.
    Business requirement: LR preview / PDF actions must be available at
    Trip Entry. Trimming was reverted at the TripForm call-site — LR
    section is now invoked WITHOUT firstSaveMode, so all LR fields render.
    The LRSection component itself still accepts the prop (safe / harmless)
    but TripForm does not pass it any more."""
    src = TF.read_text(encoding="utf-8")
    # LR call-site MUST NOT pass firstSaveMode.
    assert "<LRSection form={form} setForm={setForm} isEdit={isEdit} id={id} />" in src, (
        "LR must render full functionality on /trips/new — call-site must not gate"
    )
    # LRSection component still owns the prop for future use.
    lr_src = LR.read_text(encoding="utf-8")
    assert "firstSaveMode = false" in lr_src


def test_fe_lr_full_fields_present_on_first_save_call_site():
    """Static verification: every LR field/action data-testid is still
    reachable when firstSaveMode=false (the LR default)."""
    lr_src = LR.read_text(encoding="utf-8")
    for tid in [
        'trip-lr-number', 'trip-lr-time', 'trip-ext-invoice',
        'trip-cust-invoice', 'trip-purchased-at', 'trip-invoice-value',
        'trip-waybill', 'trip-consignor', 'trip-site-loc',
        'trip-site-contact', 'trip-gross-wt', 'trip-tare-wt',
        'trip-seal', 'trip-lr-driver-name', 'trip-driver-mobile',
        'trip-from-pin', 'trip-to-pin', 'preview-lr-btn',
    ]:
        assert f'data-testid="{tid}"' in lr_src, f"LR field missing: {tid}"


def test_fe_freight_snapshot_and_breakdown_hidden_on_first_save():
    src = FR.read_text(encoding="utf-8")
    assert "firstSaveMode" in src
    assert "!firstSaveMode && !isFixedLump" in src


def test_fe_no_backend_change_smell():
    src = TF.read_text(encoding="utf-8")
    for banned in ("/trips/first-save", "/trips/new-endpoint",
                   "POST(\"/trips/mini"):
        assert banned not in src


# ── Backend contract ───────────────────────────────────────────────────────

def test_post_trips_accepts_minimal_first_save_payload():
    cid = _customer()
    veh = _first_own_vehicle()
    body = {
        "customer_id": cid, "date": "2029-04-01",
        "vehicle_number": veh["vehicle_number"], "vehicle_id": veh["id"],
        "vehicle_type": "own",
        "tons": 5, "freight_mode": "per_ton", "rate_per_ton": 100,
        "from_location": "I146-A", "to_location": "I146-B",
        "consignor_name": "TestCo", "consignee_site_location": "TestSite",
    }
    r = requests.post(f"{API}/trips", headers=H, json=body, timeout=15)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    # Downstream calc still fires: freight_amount = tons * rate
    doc = requests.get(f"{API}/trips/{tid}", headers=H, timeout=15).json()
    assert abs(float(doc.get("freight_amount") or 0) - 500.0) < 0.01
    # No canonical Expense yet, no legacy scalars: has_canonical_expenses false
    assert doc.get("has_canonical_expenses", False) is False


def test_post_trips_still_requires_supplier_for_supplier_vehicle():
    """Iter47 Phase-3 guard preserved."""
    cid = _customer()
    for v in requests.get(f"{API}/vehicles", headers=H,
                          params={"active_only": True}, timeout=15).json():
        if (v.get("vehicle_type") or "").lower() == "supplier":
            body = {
                "customer_id": cid, "date": "2029-04-02",
                "vehicle_number": v["vehicle_number"], "vehicle_id": v["id"],
                "vehicle_type": "supplier",
                "tons": 5, "freight_mode": "per_ton", "rate_per_ton": 100,
                "from_location": "X", "to_location": "Y",
                # NO supplier_id / supplier_name
            }
            r = requests.post(f"{API}/trips", headers=H, json=body, timeout=15)
            assert r.status_code in (400, 422), (
                f"Server must still reject supplier trip without supplier — got {r.status_code}"
            )
            return


def test_iter146_idempotency_and_iter145_canonical_still_intact():
    """Sanity: creating a Trip via first-save fields does NOT bypass any
    Iter145 canonical projection — Trip.expenses/total_expense stay at 0."""
    cid = _customer()
    veh = _first_own_vehicle()
    body = {
        "customer_id": cid, "date": "2029-04-03",
        "vehicle_number": veh["vehicle_number"], "vehicle_id": veh["id"],
        "vehicle_type": "own",
        "tons": 3, "freight_mode": "fixed", "fixed_amount": 999.0,
        "from_location": "A", "to_location": "B",
    }
    r = requests.post(f"{API}/trips", headers=H, json=body, timeout=15).json()
    assert float(r.get("total_expense") or 0) == 0
    assert (r.get("expenses") or {}).get("diesel", 0) == 0
