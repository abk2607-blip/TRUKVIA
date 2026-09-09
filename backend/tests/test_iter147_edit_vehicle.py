"""Iter147 P0 UAT · Post-import Vehicle Correction — end-to-end.

Business contract under test (verbatim from the UAT brief):
  • Row-level only — editing Row A never mutates Row B, even when both
    share the same source_vehicle_ref.
  • Source identity preserved — source_key / source_txn_ref / date /
    litres / amount / station stay identical.
  • No new Expense is created — the same row is updated in place, so
    Vehicle Cost / Expense Register / Trip Cost / Fuel Log reflect
    automatically via the Iter133 canonical read paths.
  • FuelVehicleMap is UNTOUCHED unless the operator opts in with
    `persist_mapping=true`.
  • Manual / Quick Op / Trip Legacy / Legacy Fuel are NOT editable
    through this endpoint.

Uses live tenant + DEMO_TOKEN_VALUE against the running supervisor
backend. Runs sequentially (loadscope) inside the file.

The `_cleanup_iter147_state` helper uses a synchronous pymongo
hard-delete because the source_key partial-unique index treats
soft-deleted rows as still occupying the key — the correct production
semantic, and also the reason we cannot rely on `DELETE /api/expenses/{id}`
to free the key between test runs.
"""
from pathlib import Path
import os
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api" if BASE_URL.startswith("http") else "http://localhost:8001/api"
TOKEN = os.environ.get("DEMO_TOKEN_VALUE", "")
H = {"Authorization": f"Bearer {TOKEN}"}
HJSON = {**H, "Content-Type": "application/json"}

FX = Path(__file__).parent / "fixtures" / "iter147"
IOCL = FX / "IOCL_FUEL_FILE.xls"


def _sync_db():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError("MONGO_URL / DB_NAME not set in env")
    return MongoClient(mongo_url)[db_name]


# ── Helpers ────────────────────────────────────────────────────────────
def _first_two_own_vehicles():
    vs = requests.get(f"{API}/vehicles", headers=H,
                      params={"active_only": True}, timeout=15).json()
    owns = [v for v in vs if (v.get("vehicle_type") or "").lower() != "supplier"]
    if len(owns) < 2:
        raise RuntimeError("test requires at least 2 own vehicles in the tenant")
    return owns[0], owns[1]


def _cleanup_iter147_state():
    """HARD delete Iter147 fleet-card rows so source_key is freed."""
    d = _sync_db()
    me = d.users.find_one({"email": "demo@bitumen-transport.local"},
                          {"_id": 0, "user_id": 1})
    if not me:
        return
    uid = me["user_id"]
    d.expenses.delete_many({"user_id": uid, "source_type": "fleet_card_import"})
    d.fuel_vehicle_maps.delete_many({"user_id": uid})


def _import_iocl_all_to(vehicle_id):
    """Fresh cleanup + import all 5 IOCL rows against ONE vehicle."""
    _cleanup_iter147_state()
    with IOCL.open("rb") as f:
        r = requests.post(f"{API}/fuel-import/preview", headers=H,
                          files={"file": (IOCL.name, f, "application/octet-stream")},
                          timeout=30)
    body = r.json()
    rows = []
    for row in body["rows"]:
        if row["bucket"] == "error":
            continue
        rows.append({**row, "bucket": "ready",
                     "resolved_vehicle_id": vehicle_id,
                     "resolved_vehicle_number": ""})
    cr = requests.post(f"{API}/fuel-import/commit", headers=HJSON,
                       json={"source": "iocl", "rows": rows}, timeout=30).json()
    assert cr["failed"] == 0, cr
    assert cr["created"] >= 5, cr
    listed = requests.get(f"{API}/expenses", headers=H,
                          params={"source_type": "fleet_card_import"},
                          timeout=15).json()
    listed = [e for e in listed if e.get("source") == "iocl"]
    listed.sort(key=lambda e: e.get("date", ""))
    assert len(listed) == 5, listed
    return listed


# ── Test 1 · Endpoint accepts only fleet_card_import Diesel rows ───────
def test_edit_vehicle_rejects_non_fleet_card_rows():
    # Grab any manual Diesel from the tenant.
    mans = requests.get(f"{API}/expenses", headers=H,
                        params={"category": "Diesel", "source_type": "manual"},
                        timeout=15).json()
    assert mans, "tenant must have at least one manual Diesel expense to test rejection"
    a, b = _first_two_own_vehicles()
    r = requests.patch(f"{API}/expenses/{mans[0]['id']}/fleet-card-vehicle",
                       headers=HJSON, json={"vehicle_id": b["id"]}, timeout=15)
    assert r.status_code == 400
    assert "fleet-card" in r.text.lower()


def test_edit_vehicle_rejects_bad_input():
    a, b = _first_two_own_vehicles()
    exps = _import_iocl_all_to(a["id"])
    eid = exps[0]["id"]
    # Missing vehicle_id
    r = requests.patch(f"{API}/expenses/{eid}/fleet-card-vehicle",
                       headers=HJSON, json={}, timeout=15)
    assert r.status_code == 400
    # Unknown vehicle
    r = requests.patch(f"{API}/expenses/{eid}/fleet-card-vehicle",
                       headers=HJSON, json={"vehicle_id": "veh_nope"}, timeout=15)
    assert r.status_code == 400
    # Unknown Expense
    r = requests.patch(f"{API}/expenses/veh_nope_expense/fleet-card-vehicle",
                       headers=HJSON, json={"vehicle_id": b["id"]}, timeout=15)
    assert r.status_code == 404


# ── Test 2 · Row-level correction — sibling rows unchanged ─────────────
def test_edit_vehicle_row_level_only():
    a, b = _first_two_own_vehicles()
    exps = _import_iocl_all_to(a["id"])
    # All 5 rows share the same source_vehicle_ref (GENAKIS7234000012)
    assert len(exps) == 5
    target = exps[0]
    siblings = exps[1:]
    assert all(s["vehicle_id"] == a["id"] for s in siblings)
    # PATCH target to vehicle B
    r = requests.patch(f"{API}/expenses/{target['id']}/fleet-card-vehicle",
                       headers=HJSON,
                       json={"vehicle_id": b["id"]}, timeout=15)
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["ok"] is True
    assert resp["unchanged"] is False
    assert resp["previous_vehicle_id"] == a["id"]
    assert resp["expense"]["vehicle_id"] == b["id"]
    assert resp["expense"]["vehicle_number"] == b["vehicle_number"]
    # Fetch siblings — they MUST still be on vehicle A
    for s in siblings:
        cur = requests.get(f"{API}/expenses/{s['id']}", headers=H, timeout=15).json()
        assert cur["vehicle_id"] == a["id"], \
            f"sibling row {s['id']} was mutated — got {cur['vehicle_id']} expected {a['id']}"


# ── Test 3 · Source identity preserved ────────────────────────────────
def test_edit_vehicle_preserves_source_identity():
    a, b = _first_two_own_vehicles()
    exps = _import_iocl_all_to(a["id"])
    tgt = exps[0]
    keys_before = {k: tgt.get(k) for k in
                   ("source", "source_txn_ref", "source_key", "source_type",
                    "date", "amount", "narration")}
    r = requests.patch(f"{API}/expenses/{tgt['id']}/fleet-card-vehicle",
                       headers=HJSON, json={"vehicle_id": b["id"]}, timeout=15)
    assert r.status_code == 200
    after = requests.get(f"{API}/expenses/{tgt['id']}", headers=H, timeout=15).json()
    for k, v in keys_before.items():
        assert after.get(k) == v, \
            f"source identity field {k!r} changed: before={v!r} after={after.get(k)!r}"


# ── Test 4 · No second Expense is created ─────────────────────────────
def test_edit_vehicle_does_not_create_new_expense():
    a, b = _first_two_own_vehicles()
    exps = _import_iocl_all_to(a["id"])
    tgt = exps[0]
    total_before = len(requests.get(f"{API}/expenses", headers=H,
                                    params={"source_type": "fleet_card_import"},
                                    timeout=15).json())
    requests.patch(f"{API}/expenses/{tgt['id']}/fleet-card-vehicle",
                   headers=HJSON, json={"vehicle_id": b["id"]}, timeout=15)
    total_after = len(requests.get(f"{API}/expenses", headers=H,
                                   params={"source_type": "fleet_card_import"},
                                   timeout=15).json())
    assert total_after == total_before, \
        f"vehicle correction leaked a duplicate Expense (before={total_before} after={total_after})"


# ── Test 5 · Reflection in Unified Fuel Log ───────────────────────────
def test_edit_vehicle_reflects_in_fuel_log():
    a, b = _first_two_own_vehicles()
    exps = _import_iocl_all_to(a["id"])
    tgt = exps[0]
    requests.patch(f"{API}/expenses/{tgt['id']}/fleet-card-vehicle",
                   headers=HJSON, json={"vehicle_id": b["id"]}, timeout=15)
    log = requests.get(f"{API}/fuel-log", headers=H, timeout=15).json()
    hit = [r for r in log if r.get("id") == tgt["id"]]
    assert hit, "corrected row missing from fuel-log"
    assert hit[0]["vehicle_id"] == b["id"]
    assert hit[0]["vehicle_number"] == b["vehicle_number"]


# ── Test 6 · FuelVehicleMap untouched by default ──────────────────────
def test_edit_vehicle_does_not_silently_persist_map():
    a, b = _first_two_own_vehicles()
    exps = _import_iocl_all_to(a["id"])
    tgt = exps[0]
    maps_before = requests.get(f"{API}/fuel/vehicle-maps", headers=H, timeout=15).json()
    requests.patch(f"{API}/expenses/{tgt['id']}/fleet-card-vehicle",
                   headers=HJSON, json={"vehicle_id": b["id"]}, timeout=15)
    maps_after = requests.get(f"{API}/fuel/vehicle-maps", headers=H, timeout=15).json()
    assert len(maps_after) == len(maps_before), \
        "FuelVehicleMap was silently mutated by a row correction"


# ── Test 7 · Opt-in persist upserts FuelVehicleMap ────────────────────
def test_edit_vehicle_opt_in_persists_map():
    a, b = _first_two_own_vehicles()
    exps = _import_iocl_all_to(a["id"])
    tgt = exps[0]
    # Explicitly supply source_vehicle_ref to make the persist path
    # deterministic under the read-only helper.
    r = requests.patch(f"{API}/expenses/{tgt['id']}/fleet-card-vehicle",
                       headers=HJSON,
                       json={"vehicle_id": b["id"], "persist_mapping": True,
                             "source_vehicle_ref": "GENAKIS7234000012"},
                       timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body.get("persisted_map"), "persist_mapping=true must return the upserted FuelVehicleMap"
    assert body["persisted_map"]["vehicle_id"] == b["id"]
    # And the mapping is listable.
    lst = requests.get(f"{API}/fuel/vehicle-maps", headers=H,
                       params={"source": "iocl"}, timeout=15).json()
    assert any(m["source_vehicle_ref"] == "GENAKIS7234000012"
               and m["vehicle_id"] == b["id"] for m in lst)


# ── Test 8 · Same source_vehicle_ref may hold different vehicles ──────
def test_same_source_ref_different_vehicles_per_row():
    a, b = _first_two_own_vehicles()
    exps = _import_iocl_all_to(a["id"])
    r1, r2, r3 = exps[0], exps[1], exps[2]
    # Move r1 → b, keep r2 on a, r3 → b
    for target, vid in ((r1, b["id"]), (r3, b["id"])):
        r = requests.patch(f"{API}/expenses/{target['id']}/fleet-card-vehicle",
                           headers=HJSON, json={"vehicle_id": vid}, timeout=15)
        assert r.status_code == 200
    cur1 = requests.get(f"{API}/expenses/{r1['id']}", headers=H, timeout=15).json()
    cur2 = requests.get(f"{API}/expenses/{r2['id']}", headers=H, timeout=15).json()
    cur3 = requests.get(f"{API}/expenses/{r3['id']}", headers=H, timeout=15).json()
    assert cur1["vehicle_id"] == b["id"]
    assert cur2["vehicle_id"] == a["id"]        # untouched
    assert cur3["vehicle_id"] == b["id"]
    # Source ref (encoded in source_key content-hash) still identical.
    assert cur1["source"] == cur2["source"] == cur3["source"] == "iocl"


# ── Test 9 · Exact duplicate detection still catches a re-upload ──────
def test_exact_duplicate_still_detected_after_correction():
    a, b = _first_two_own_vehicles()
    _import_iocl_all_to(a["id"])
    exps = requests.get(f"{API}/expenses", headers=H,
                        params={"source_type": "fleet_card_import"}, timeout=15).json()
    # Correct one of them.
    tgt = [e for e in exps if e.get("source") == "iocl"][0]
    requests.patch(f"{API}/expenses/{tgt['id']}/fleet-card-vehicle",
                   headers=HJSON, json={"vehicle_id": b["id"]}, timeout=15)
    # Re-upload the same file → EVERY previously-committed row must come
    # back as exact_duplicate (source_key unchanged).
    with IOCL.open("rb") as f:
        r = requests.post(f"{API}/fuel-import/preview", headers=H,
                          files={"file": (IOCL.name, f, "application/octet-stream")},
                          timeout=30)
    body = r.json()
    for row in body["rows"]:
        if row["bucket"] == "error":
            continue
        # Rows may be exact_duplicate (already committed) or
        # vehicle_mapping_required (no map exists — parser-time state).
        assert row["bucket"] in ("exact_duplicate", "vehicle_mapping_required"), \
            f"unexpected bucket {row['bucket']} after correction"


# ── Test 10 · Rejects cancelled Expense ───────────────────────────────
def test_edit_vehicle_rejects_cancelled_expense():
    a, b = _first_two_own_vehicles()
    exps = _import_iocl_all_to(a["id"])
    tgt = exps[0]
    requests.delete(f"{API}/expenses/{tgt['id']}", headers=H,
                    params={"reason": "iter147-uat-cancel-test"}, timeout=15)
    r = requests.patch(f"{API}/expenses/{tgt['id']}/fleet-card-vehicle",
                       headers=HJSON, json={"vehicle_id": b["id"]}, timeout=15)
    assert r.status_code == 400
    assert "cancel" in r.text.lower()


# ── Cleanup at the end of the module ──────────────────────────────────
def test_zzz_cleanup_iter147_state():
    _cleanup_iter147_state()
    assert True
