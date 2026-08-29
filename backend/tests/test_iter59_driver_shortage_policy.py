"""Iter59 · Phase A — Driver Shortage Policy Engine tests.

Covers ALL the scenarios in the user's audit checklist:
 1. Policy CRUD + soft delete
 2. Effective-date lookup: trip-date wins over current-date
 3. Historical snapshot on Trip CREATE
 4. Trip UPDATE preserves original snapshot (never re-resolves)
 5. Policy change AFTER old trip exists → old trip unchanged
 6. Editing an OLD trip → its historical policy stays
 7. Shortage below limit → no recovery
 8. Shortage above limit → only beyond limit is recoverable
 9. Recovery amount = recoverable_kg × product_rate
10. Manual override with mandatory reason + audit trail
11. Multi-company isolation
Plus the four numeric examples from the requirement.
"""
import os, uuid, pytest, httpx, asyncio
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}
UNIQUE = f"IT59_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=60).json()


def _h(cid=None):
    return {**HDR, "X-Company-Id": cid or _companies()[0]["id"]}


def _make_policy(cid, name, limit_kg, eff_from, eff_to=None, active=True, category=None):
    # Iter59 — Bind policies to a unique product_category so tests don't
    # pollute each other via the catch-all fallback.
    return httpx.post(f"{BASE}/api/driver-shortage-policies", headers=_h(cid), json={
        "name": name, "shortage_limit_kg": limit_kg, "unit": "KG",
        "effective_from": eff_from, "effective_to": eff_to,
        "product_category": category or UNIQUE, "active": active,
    }, timeout=60).json()


def _make_driver(cid):
    return httpx.post(f"{BASE}/api/drivers", headers=_h(cid), json={
        "name": f"DRV_{UNIQUE}_{uuid.uuid4().hex[:4]}", "phone": "9998887777",
    }, timeout=60).json()


def _make_customer(cid):
    return httpx.post(f"{BASE}/api/customers", headers=_h(cid), json={
        "name": f"CUST_{UNIQUE}", "phone": "9111111111", "state": "AP",
    }, timeout=60).json()


def _make_vehicle(cid):
    return httpx.post(f"{BASE}/api/vehicles", headers=_h(cid), json={
        "vehicle_number": f"AP59{UNIQUE[:4]}{uuid.uuid4().hex[:2].upper()}", "vehicle_type": "own",
    }, timeout=60).json()


def _make_trip(cid, driver_id, customer_id, vehicle_id, vehicle_number,
               date, shortage_mt, product_rate=100.0):
    return httpx.post(f"{BASE}/api/trips", headers=_h(cid), json={
        "customer_id": customer_id, "date": date,
        "vehicle_id": vehicle_id, "vehicle_number": vehicle_number,
        "driver_id": driver_id, "driver_name": "test",
        "tons": 20.0, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "loaded_qty": 20.0, "unloaded_qty": round(20.0 - shortage_mt, 3),
        "product_rate_per_mt": product_rate,
        "product_category": UNIQUE,
        "from_location": "Kondapalli", "to_location": "Vijayawada",
    }, timeout=60).json()


@pytest.fixture(scope="module")
def env():
    cid = _companies()[0]["id"]
    driver = _make_driver(cid)
    cust = _make_customer(cid)
    veh = _make_vehicle(cid)
    return {"cid": cid, "driver": driver, "customer": cust, "vehicle": veh}


# 1 — CRUD
def test_policy_crud(env):
    p = _make_policy(env["cid"], f"CRUD_{UNIQUE}", 100, "2026-01-01")
    assert p["id"].startswith("dsp")
    assert p["version"] == 1
    assert p["shortage_limit_kg"] == 100
    # Update → version bumps
    r = httpx.put(f"{BASE}/api/driver-shortage-policies/{p['id']}", headers=_h(env["cid"]), json={
        "name": p["name"], "shortage_limit_kg": 120, "unit": "KG",
        "effective_from": p["effective_from"], "active": True,
    }, timeout=60).json()
    assert r["shortage_limit_kg"] == 120
    assert r["version"] == 2
    # Soft delete (Iter60 — reason mandatory)
    d = httpx.request("DELETE", f"{BASE}/api/driver-shortage-policies/{p['id']}",
                      headers=_h(env["cid"]), json={"reason": "test cleanup iter59"},
                      timeout=60).json()
    assert d["ok"] is True and d.get("deactivated") is True


# 2 — Effective-date lookup uses TRIP DATE not current date
def test_resolve_uses_trip_date(env):
    _make_policy(env["cid"], f"HistOld_{UNIQUE}", 100, "2026-01-01", eff_to="2026-06-30")
    _make_policy(env["cid"], f"HistNew_{UNIQUE}", 150, "2026-07-01")
    # Trip on 15-Jun-2026 → old policy applies (100 KG)
    r1 = httpx.get(f"{BASE}/api/driver-shortage-policies/resolve",
                   headers=_h(env["cid"]), params={"trip_date": "2026-06-15", "product_category": UNIQUE}, timeout=60).json()
    assert r1["policy"] is not None
    assert r1["policy"]["shortage_limit_kg"] == 100
    # Trip on 15-Aug-2026 → new policy applies (150 KG)
    r2 = httpx.get(f"{BASE}/api/driver-shortage-policies/resolve",
                   headers=_h(env["cid"]), params={"trip_date": "2026-08-15", "product_category": UNIQUE}, timeout=60).json()
    assert r2["policy"]["shortage_limit_kg"] == 150


# 3 + 7 — Shortage BELOW limit → no recovery
def test_shortage_below_limit_no_recovery(env):
    t = _make_trip(env["cid"], env["driver"]["id"], env["customer"]["id"],
                   env["vehicle"]["id"], env["vehicle"]["vehicle_number"],
                   "2026-06-15", shortage_mt=0.08, product_rate=104.24)  # 80 KG
    dr = t.get("driver_recovery")
    assert dr is not None, "snapshot missing"
    assert dr["allowed_limit_kg"] == 100
    assert dr["actual_shortage_kg"] == pytest.approx(80, abs=0.5)
    assert dr["system_recoverable_shortage_kg"] == 0
    assert dr["system_recovery_amount"] == 0
    assert dr["final_recovery_amount"] == 0


# 8 — Shortage EQUAL to limit → no recovery
def test_shortage_equal_limit_no_recovery(env):
    t = _make_trip(env["cid"], env["driver"]["id"], env["customer"]["id"],
                   env["vehicle"]["id"], env["vehicle"]["vehicle_number"],
                   "2026-06-15", shortage_mt=0.100, product_rate=104.24)  # 100 KG
    dr = t["driver_recovery"]
    assert dr["system_recoverable_shortage_kg"] == 0
    assert dr["final_recovery_amount"] == 0


# 8 + 9 — Shortage ABOVE limit → excess is recoverable × rate
def test_shortage_above_limit_recovery(env):
    t = _make_trip(env["cid"], env["driver"]["id"], env["customer"]["id"],
                   env["vehicle"]["id"], env["vehicle"]["vehicle_number"],
                   "2026-06-15", shortage_mt=0.150, product_rate=104.24)  # 150 KG
    dr = t["driver_recovery"]
    assert dr["allowed_limit_kg"] == 100
    assert dr["system_recoverable_shortage_kg"] == pytest.approx(50, abs=0.5)
    # 50 KG × 104.24 = 5212.00
    assert dr["system_recovery_amount"] == pytest.approx(5212.0, abs=0.5)


# New limit ≥ shortage → no recovery
def test_shortage_150_limit_150_no_recovery(env):
    t = _make_trip(env["cid"], env["driver"]["id"], env["customer"]["id"],
                   env["vehicle"]["id"], env["vehicle"]["vehicle_number"],
                   "2026-08-15", shortage_mt=0.150, product_rate=104.24)
    dr = t["driver_recovery"]
    assert dr["allowed_limit_kg"] == 150
    assert dr["system_recoverable_shortage_kg"] == 0
    assert dr["system_recovery_amount"] == 0


# 4 — Trip UPDATE preserves the original policy snapshot
def test_trip_update_preserves_snapshot(env):
    t = _make_trip(env["cid"], env["driver"]["id"], env["customer"]["id"],
                   env["vehicle"]["id"], env["vehicle"]["vehicle_number"],
                   "2026-06-15", shortage_mt=0.150, product_rate=104.24)
    original_policy_id = t["driver_recovery"]["policy_id"]
    original_limit = t["driver_recovery"]["allowed_limit_kg"]
    # Add a BRAND NEW policy that would apply to the trip date IF re-resolved
    _make_policy(env["cid"], f"NewerJun_{UNIQUE}", 200, "2026-06-01")
    # Update the trip (just change from_location — nothing that should trigger policy re-resolve)
    updated = httpx.put(f"{BASE}/api/trips/{t['id']}", headers=_h(env["cid"]), json={
        **t, "from_location": "UpdatedFrom",
    }, timeout=60).json()
    # Snapshot MUST remain the original
    assert updated["driver_recovery"]["policy_id"] == original_policy_id, "snapshot policy_id changed on update!"
    assert updated["driver_recovery"]["allowed_limit_kg"] == original_limit, "snapshot limit changed on update!"


# 5 — Policy change AFTER old trip exists → old trip unchanged
def test_policy_change_does_not_recalc_old_trips(env):
    # Create Trip under 100-KG policy period
    t = _make_trip(env["cid"], env["driver"]["id"], env["customer"]["id"],
                   env["vehicle"]["id"], env["vehicle"]["vehicle_number"],
                   "2026-06-20", shortage_mt=0.150, product_rate=104.24)
    original = dict(t["driver_recovery"])
    # Now bump the OLD policy limit dramatically
    old_resp = httpx.get(f"{BASE}/api/driver-shortage-policies", headers=_h(env["cid"]),
                         params={"q": f"HistOld_{UNIQUE}", "limit": 100}, timeout=60).json()
    old_policies = old_resp.get("items", old_resp) if isinstance(old_resp, dict) else old_resp
    hist_old = next(p for p in old_policies if p["name"] == f"HistOld_{UNIQUE}")
    httpx.put(f"{BASE}/api/driver-shortage-policies/{hist_old['id']}", headers=_h(env["cid"]), json={
        "name": hist_old["name"], "shortage_limit_kg": 999, "unit": "KG",
        "effective_from": hist_old["effective_from"], "effective_to": hist_old.get("effective_to"),
        "active": True,
    }, timeout=60)
    # Fetch the trip — snapshot must NOT change
    got = httpx.get(f"{BASE}/api/trips/{t['id']}", headers=_h(env["cid"]), timeout=60).json()
    assert got["driver_recovery"]["allowed_limit_kg"] == original["allowed_limit_kg"], \
        f"policy edit retroactively changed old trip: {got['driver_recovery']}"
    assert got["driver_recovery"]["system_recovery_amount"] == original["system_recovery_amount"]


# 10 — Manual override with mandatory reason + audit
def test_manual_override(env):
    # Create a fresh isolated policy for this test's specific date
    _make_policy(env["cid"], f"OverrideTest_{UNIQUE}", 100, "2026-05-01", eff_to="2026-05-31")
    t = _make_trip(env["cid"], env["driver"]["id"], env["customer"]["id"],
                   env["vehicle"]["id"], env["vehicle"]["vehicle_number"],
                   "2026-05-15", shortage_mt=0.150, product_rate=104.24)
    assert t["driver_recovery"]["allowed_limit_kg"] == 100, t["driver_recovery"]
    # Reject missing reason
    r = httpx.post(f"{BASE}/api/trips/{t['id']}/driver-recovery/override",
                   headers=_h(env["cid"]), json={"override_amount": 1000, "reason": ""}, timeout=60)
    assert r.status_code in (400, 422)
    # Apply override
    r = httpx.post(f"{BASE}/api/trips/{t['id']}/driver-recovery/override",
                   headers=_h(env["cid"]),
                   json={"override_amount": 1000, "reason": "Driver accepted 1000 flat"},
                   timeout=60).json()
    assert r["ok"] is True
    dr = r["driver_recovery"]
    assert dr["override"]["amount"] == 1000
    assert dr["override"]["reason"] == "Driver accepted 1000 flat"
    assert dr["override"]["by"]
    assert dr["override"]["at"]
    assert dr["final_recovery_amount"] == 1000
    # SYSTEM values PRESERVED alongside override
    assert dr["system_recovery_amount"] == pytest.approx(5212.0, abs=0.5)
    assert dr["actual_shortage_kg"] == pytest.approx(150, abs=0.5)
    # Audit history has the entry
    assert any(h["action"] == "override" and h["amount"] == 1000 for h in r["history"])
    # Clear override → reverts to system calc
    r2 = httpx.post(f"{BASE}/api/trips/{t['id']}/driver-recovery/override",
                    headers=_h(env["cid"]),
                    json={"override_amount": None, "reason": "cleared"}, timeout=60).json()
    assert r2["driver_recovery"]["override"] is None
    assert r2["driver_recovery"]["final_recovery_amount"] == pytest.approx(5212.0, abs=0.5)


# 11 — Multi-company isolation
def test_multi_company_isolation():
    comps = _companies()
    if len(comps) < 2:
        pytest.skip("need 2+ companies")
    cid_a, cid_b = comps[0]["id"], comps[1]["id"]
    p_a = _make_policy(cid_a, f"IsolA_{UNIQUE}", 100, "2026-01-01")
    # Policy from A must NOT appear in B's list
    b_resp = httpx.get(f"{BASE}/api/driver-shortage-policies", headers=_h(cid_b), timeout=60).json()
    b_list = b_resp.get("items") if isinstance(b_resp, dict) else b_resp
    assert not any(x["id"] == p_a["id"] for x in b_list), "policy leaked across companies"
    # Resolve in B must NOT return A's policy
    b_resolve = httpx.get(f"{BASE}/api/driver-shortage-policies/resolve",
                          headers=_h(cid_b), params={"trip_date": "2026-06-15"}, timeout=60).json()
    if b_resolve["policy"]:
        assert b_resolve["policy"]["id"] != p_a["id"]
    # B cannot update A's policy
    upd = httpx.put(f"{BASE}/api/driver-shortage-policies/{p_a['id']}", headers=_h(cid_b), json={
        "name": "hijacked", "shortage_limit_kg": 999, "unit": "KG",
        "effective_from": "2026-01-01", "active": True,
    }, timeout=60)
    assert upd.status_code == 404
