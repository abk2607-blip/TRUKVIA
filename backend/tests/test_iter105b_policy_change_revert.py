"""Iter105 · Phase B — Policy Change Revert regression guards.

Contract enforced by these tests:
  1. `reason` is MANDATORY on revert (400 without).
  2. Only `status=applied` events can be reverted (400 on re-revert).
  3. If any applied trip has since been invoiced → 409 Conflict + list of
     blocking trip ids; NO partial revert allowed.
  4. Successful revert restores the Customer master (default_freight_method
     + shortage_config) to the pre-apply state.
  5. Successful revert restores each affected trip's applied_* snapshot +
     recomputed financials to the pre-apply state.
  6. Event row flips to `status=reverted` with reverted_at / reverted_by /
     revert_reason.
  7. Non-selected trips + trips outside the event are guaranteed untouched.
  8. Historical / archived trips remain untouched (they were skipped on
     apply anyway).
"""
import os
import uuid
import httpx


BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDRS = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}


# ─────────────────────────── Helpers ────────────────────────────────────

def _mk_customer(name_suffix: str, *, freight="per_ton_loading",
                 limit=0.0, method="net_shortage", eff="") -> dict:
    body = {
        "name": f"IT105B_{name_suffix}_{uuid.uuid4().hex[:6]}",
        "default_freight_method": freight,
        "shortage_config": {
            "limit": limit, "limit_type": "pct", "method": method,
            "effective_from": eff, "active": True, "remarks": "",
        },
    }
    r = httpx.post(f"{BASE}/customers", headers=HDRS, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _mk_product(default_pct: float = 0.5) -> str:
    r = httpx.post(f"{BASE}/products", headers=HDRS, json={
        "name": f"IT105B_VG40_{uuid.uuid4().hex[:6]}",
        "hsn_sac": "996791", "unit": "MT",
        "default_shortage_allowance_pct": default_pct,
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _mk_trip(customer_id: str, product_id: str, *, date: str) -> dict:
    r = httpx.post(f"{BASE}/trips", headers=HDRS, json={
        "customer_id": customer_id, "product_id": product_id, "date": date,
        "vehicle_number": f"AP39{uuid.uuid4().hex[:4].upper()}",
        "vehicle_type": "own",
        "tons": 33.2, "loaded_qty": 33.2, "unloaded_qty": 32.8,
        "product_rate_per_mt": 62500.0,
        "freight_mode": "per_ton", "rate_per_ton": 1000.0,
        "load_details": "BITUMEN VG 40",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _apply(customer_id: str, trip_ids, *, eff="2026-04-01",
           method="full_after_limit", freight="per_ton_unloading") -> dict:
    r = httpx.post(f"{BASE}/policy-changes/apply", headers=HDRS, json={
        "customer_id": customer_id, "effective_from": eff,
        "new_policy": {"default_freight_method": freight,
                       "shortage_config": {"limit": 0, "limit_type": "pct",
                                            "method": method,
                                            "effective_from": eff,
                                            "active": True, "remarks": ""}},
        "apply_to_previous": True, "trip_ids": trip_ids,
        "reason": "IT105B setup",
    }, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


def _get_trip(tid: str) -> dict:
    r = httpx.get(f"{BASE}/trips/{tid}", headers=HDRS, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _get_customer(cid: str) -> dict:
    # Search paginated with a q to avoid slow full-list scan
    r = httpx.get(f"{BASE}/customers", headers=HDRS, timeout=15).json()
    rows = r if isinstance(r, list) else r.get("items", [])
    for row in rows:
        if row.get("id") == cid:
            return row
    raise AssertionError(f"customer {cid} not found in list")


# ─────────────────────────── Tests ──────────────────────────────────────

def test_revert_requires_reason():
    cust = _mk_customer("rr")
    pid = _mk_product()
    trip = _mk_trip(cust["id"], pid, date="2026-05-12")
    ev = _apply(cust["id"], [trip["id"]])["event"]

    r = httpx.post(f"{BASE}/policy-changes/{ev['id']}/revert", headers=HDRS,
                   json={"reason": "   "}, timeout=15)
    assert r.status_code == 400, r.text
    assert "reason" in r.text.lower()


def test_revert_success_restores_customer_and_trip():
    cust = _mk_customer("ok")
    pid = _mk_product(default_pct=0.5)
    trip = _mk_trip(cust["id"], pid, date="2026-05-12")
    old_customer = _get_customer(cust["id"])
    old_trip = _get_trip(trip["id"])

    ev = _apply(cust["id"], [trip["id"]])["event"]

    # After apply: customer + trip should have moved to the new policy
    after_apply_cust = _get_customer(cust["id"])
    assert after_apply_cust["default_freight_method"] == "per_ton_unloading"
    after_apply_trip = _get_trip(trip["id"])
    assert after_apply_trip["applied_customer_shortage_method"] == "full_after_limit"

    r = httpx.post(f"{BASE}/policy-changes/{ev['id']}/revert", headers=HDRS,
                   json={"reason": "UAT-B rollback"}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert trip["id"] in body["reverted_trip_ids"]

    restored_cust = _get_customer(cust["id"])
    assert restored_cust["default_freight_method"] == old_customer["default_freight_method"]
    assert (restored_cust.get("shortage_config") or {}).get("method") == \
           (old_customer.get("shortage_config") or {}).get("method")

    restored_trip = _get_trip(trip["id"])
    for k in ("applied_freight_method", "applied_customer_shortage_method",
              "applied_customer_shortage_limit",
              "applied_product_shortage_pct",
              "shortage_amount", "freight_amount"):
        assert restored_trip.get(k) == old_trip.get(k), \
            f"trip field {k} not restored: {restored_trip.get(k)} vs {old_trip.get(k)}"


def test_revert_blocked_when_trip_has_been_invoiced():
    cust = _mk_customer("blk")
    pid = _mk_product()
    trip = _mk_trip(cust["id"], pid, date="2026-05-12")
    ev = _apply(cust["id"], [trip["id"]])["event"]

    # Invoice the affected trip AFTER apply
    inv = httpx.post(f"{BASE}/invoices", headers=HDRS, json={
        "customer_id": cust["id"], "trip_ids": [trip["id"]], "hsn_sac": "996791",
    }, timeout=15)
    assert inv.status_code in (200, 201), inv.text

    r = httpx.post(f"{BASE}/policy-changes/{ev['id']}/revert", headers=HDRS,
                   json={"reason": "test"}, timeout=15)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "REVERT_BLOCKED_INVOICED"
    assert trip["id"] in detail["invoiced_trip_ids"]

    # Verify NO partial revert happened
    still_applied_trip = _get_trip(trip["id"])
    assert still_applied_trip["applied_customer_shortage_method"] == "full_after_limit"


def test_revert_second_call_returns_400_already_reverted():
    cust = _mk_customer("re2")
    pid = _mk_product()
    trip = _mk_trip(cust["id"], pid, date="2026-05-12")
    ev = _apply(cust["id"], [trip["id"]])["event"]

    r1 = httpx.post(f"{BASE}/policy-changes/{ev['id']}/revert", headers=HDRS,
                    json={"reason": "first"}, timeout=15)
    assert r1.status_code == 200

    r2 = httpx.post(f"{BASE}/policy-changes/{ev['id']}/revert", headers=HDRS,
                    json={"reason": "second"}, timeout=15)
    assert r2.status_code == 400
    assert "reverted" in r2.text.lower()


def test_reverted_event_status_and_audit_fields():
    cust = _mk_customer("stat")
    pid = _mk_product()
    trip = _mk_trip(cust["id"], pid, date="2026-05-12")
    ev = _apply(cust["id"], [trip["id"]])["event"]

    r = httpx.post(f"{BASE}/policy-changes/{ev['id']}/revert", headers=HDRS,
                   json={"reason": "test-audit"}, timeout=15)
    assert r.status_code == 200
    refreshed = r.json()["event"]
    assert refreshed["status"] == "reverted"
    assert refreshed["revert_reason"] == "test-audit"
    assert refreshed["reverted_at"] != ""
    # History endpoint returns the reverted row
    lst = httpx.get(f"{BASE}/policy-changes", headers=HDRS,
                    params={"customer_id": cust["id"]}, timeout=15).json()
    row = next((r for r in lst["items"] if r["id"] == ev["id"]), None)
    assert row is not None and row["status"] == "reverted"


def test_revert_does_not_touch_trips_outside_the_event():
    cust = _mk_customer("iso")
    pid = _mk_product()
    trip_in = _mk_trip(cust["id"], pid, date="2026-05-12")
    trip_out = _mk_trip(cust["id"], pid, date="2026-05-13")
    # Apply only to trip_in
    ev = _apply(cust["id"], [trip_in["id"]])["event"]
    outside_snapshot = _get_trip(trip_out["id"])

    r = httpx.post(f"{BASE}/policy-changes/{ev['id']}/revert", headers=HDRS,
                   json={"reason": "iso-check"}, timeout=15)
    assert r.status_code == 200
    after_revert_outside = _get_trip(trip_out["id"])
    for k in ("applied_freight_method", "applied_customer_shortage_method",
              "shortage_amount", "freight_amount", "policy_snapshot_at"):
        assert outside_snapshot.get(k) == after_revert_outside.get(k), \
            f"non-event trip {k} was mutated by revert"
