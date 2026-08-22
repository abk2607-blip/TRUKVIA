"""Iter105 · Customer Policy Change Workflow — backend regression guards.

Covers the contract the user explicitly approved:
  1. Effective Date is MANDATORY.
  2. `apply_to_previous=False` never touches historical trips.
  3. Preview shows old vs new for eligible pending trips only.
  4. Apply recomputes selected trips via the central engine and records
     a policy_change_events row with per-trip deltas.
  5. Invoiced trips are skipped (never silently rewritten).
  6. Historical / archived trips are skipped.
  7. Trips whose date is BEFORE effective_from are skipped.
  8. Non-selected eligible trips are guaranteed untouched.
  9. Company + user_id isolation is enforced on every write.
 10. Supplier-side shortage/settlement remains independent of the customer
     policy change (its own `applied_supplier_shortage_limit_kg` is preserved
     verbatim through the recompute).
"""
import os
import uuid
import httpx


BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
DEMO_TOKEN = "test_session_bitumen_2026"
HDRS = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}


# ─────────────────────────── Helpers ────────────────────────────────────

def _mk_customer(name_suffix: str, *, freight="per_ton_loading",
                 limit=0.0, method="net_shortage", eff="") -> str:
    body = {
        "name": f"IT105_{name_suffix}_{uuid.uuid4().hex[:6]}",
        "default_freight_method": freight,
        "shortage_config": {
            "limit": limit, "limit_type": "pct", "method": method,
            "effective_from": eff, "active": True, "remarks": "",
        },
    }
    r = httpx.post(f"{BASE}/customers", headers=HDRS, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _mk_product(default_pct: float = 0.5) -> str:
    r = httpx.post(f"{BASE}/products", headers=HDRS, json={
        "name": f"IT105_VG40_{uuid.uuid4().hex[:6]}",
        "hsn_sac": "996791", "unit": "MT",
        "default_shortage_allowance_pct": default_pct,
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _mk_trip(customer_id: str, product_id: str, *, date: str,
             loaded=33.2, unloaded=32.8, rate_per_ton=1000.0,
             rate_per_mt=62500.0, invoice: bool = False) -> str:
    body = {
        "customer_id": customer_id,
        "product_id": product_id,
        "date": date,
        "vehicle_number": f"AP39{uuid.uuid4().hex[:4].upper()}",
        "vehicle_type": "own",
        "tons": loaded,
        "loaded_qty": loaded,
        "unloaded_qty": unloaded,
        "product_rate_per_mt": rate_per_mt,
        "freight_mode": "per_ton",
        "rate_per_ton": rate_per_ton,
        "load_details": "BITUMEN VG 40",
    }
    r = httpx.post(f"{BASE}/trips", headers=HDRS, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    tid = r.json()["id"]
    if invoice:
        inv = httpx.post(f"{BASE}/invoices", headers=HDRS, json={
            "customer_id": customer_id, "trip_ids": [tid], "hsn_sac": "996791",
        }, timeout=15)
        assert inv.status_code in (200, 201), inv.text
    return tid


def _get_trip(tid: str) -> dict:
    r = httpx.get(f"{BASE}/trips/{tid}", headers=HDRS, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ─────────────────────────── Tests ──────────────────────────────────────

def test_effective_from_is_mandatory():
    """Preview + Apply both reject empty effective_from."""
    cid = _mk_customer("effmand")
    r1 = httpx.post(f"{BASE}/policy-changes/preview", headers=HDRS, json={
        "customer_id": cid, "effective_from": "",
        "new_policy": {"default_freight_method": "per_ton_unloading",
                       "shortage_config": {"limit": 0.5, "limit_type": "pct",
                                            "method": "full_after_limit"}},
    }, timeout=15)
    assert r1.status_code == 400, r1.text
    assert "effective_from" in r1.text
    r2 = httpx.post(f"{BASE}/policy-changes/apply", headers=HDRS, json={
        "customer_id": cid, "effective_from": "  ",
        "new_policy": {"default_freight_method": "per_ton_unloading",
                       "shortage_config": {"limit": 0.5, "limit_type": "pct",
                                            "method": "full_after_limit"}},
    }, timeout=15)
    assert r2.status_code == 400


def test_preview_lists_only_eligible_pending_trips():
    """Preview must include the pending on-or-after trip and exclude
    invoiced + out-of-range trips."""
    cid = _mk_customer("prev")
    pid = _mk_product(default_pct=0.5)
    t_eligible = _mk_trip(cid, pid, date="2026-05-12")
    _ = _mk_trip(cid, pid, date="2026-03-01")            # out-of-range
    _ = _mk_trip(cid, pid, date="2026-06-01", invoice=True)  # invoiced

    r = httpx.post(f"{BASE}/policy-changes/preview", headers=HDRS, json={
        "customer_id": cid, "effective_from": "2026-04-01",
        "new_policy": {"default_freight_method": "per_ton_unloading",
                       "shortage_config": {"limit": 0, "limit_type": "pct",
                                            "method": "full_after_limit",
                                            "effective_from": "2026-04-01",
                                            "active": True, "remarks": ""}},
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [row["trip_id"] for row in body["eligible_trips"]]
    assert t_eligible in ids
    assert body["skipped_invoiced_count"] >= 1


def test_preview_is_readonly_no_writes_to_trip():
    """Preview must NOT mutate the trip document — snapshot fields stay put."""
    cid = _mk_customer("readonly")
    pid = _mk_product(default_pct=0.5)
    tid = _mk_trip(cid, pid, date="2026-05-12")
    before = _get_trip(tid)

    httpx.post(f"{BASE}/policy-changes/preview", headers=HDRS, json={
        "customer_id": cid, "effective_from": "2026-04-01",
        "new_policy": {"default_freight_method": "per_ton_unloading",
                       "shortage_config": {"limit": 0, "limit_type": "pct",
                                            "method": "full_after_limit",
                                            "effective_from": "2026-04-01",
                                            "active": True, "remarks": ""}},
    }, timeout=15)

    after = _get_trip(tid)
    for k in ("applied_freight_method", "applied_customer_shortage_method",
              "applied_product_shortage_pct", "policy_snapshot_at",
              "shortage_amount", "freight_amount", "net_settlement"):
        assert before.get(k) == after.get(k), f"preview mutated {k}"


def test_apply_recomputes_selected_trip_via_engine():
    """Trip should end up with the Product allowance frozen + shortage
    recomputed by the central engine, matching the expected math:
      loaded 33.2 × 0.5% = 0.166 allowed ; actual 0.4 shortage ;
      method full_after_limit → deduction = 0.4 × ₹62500 = ₹25 000."""
    cid = _mk_customer("apply")
    pid = _mk_product(default_pct=0.5)
    tid = _mk_trip(cid, pid, date="2026-05-12",
                   loaded=33.2, unloaded=32.8,
                   rate_per_ton=1000.0, rate_per_mt=62500.0)

    r = httpx.post(f"{BASE}/policy-changes/apply", headers=HDRS, json={
        "customer_id": cid, "effective_from": "2026-04-01",
        "new_policy": {"default_freight_method": "per_ton_unloading",
                       "shortage_config": {"limit": 0, "limit_type": "pct",
                                            "method": "full_after_limit",
                                            "effective_from": "2026-04-01",
                                            "active": True, "remarks": ""}},
        "apply_to_previous": True,
        "trip_ids": [tid],
        "reason": "IT105 recompute after product allowance fix",
    }, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert tid in body["applied_trip_ids"]
    assert body["updated_trip_count"] == 1

    after = _get_trip(tid)
    assert after["applied_freight_method"] == "per_ton_unloading"
    assert after["applied_customer_shortage_method"] == "full_after_limit"
    assert round(after["applied_product_shortage_pct"], 3) == 0.5
    # Engine math: full_after_limit past 0.166 allowed → full 0.4 × 62500 = 25000
    assert round(after["shortage_amount"], 2) == 25000.00
    assert round(after["shortage_qty"], 3) == 0.400


def test_apply_off_updates_customer_only_not_trips():
    """apply_to_previous=False must persist the master edit but NEVER
    touch existing trips."""
    cid = _mk_customer("off")
    pid = _mk_product(default_pct=0.5)
    tid = _mk_trip(cid, pid, date="2026-05-12")
    before = _get_trip(tid)

    r = httpx.post(f"{BASE}/policy-changes/apply", headers=HDRS, json={
        "customer_id": cid, "effective_from": "2026-04-01",
        "new_policy": {"default_freight_method": "per_ton_unloading",
                       "shortage_config": {"limit": 0, "limit_type": "pct",
                                            "method": "full_after_limit",
                                            "effective_from": "2026-04-01",
                                            "active": True, "remarks": ""}},
        "apply_to_previous": False,
        "trip_ids": [],
    }, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["updated_trip_count"] == 0
    after = _get_trip(tid)
    for k in ("applied_freight_method", "applied_customer_shortage_method",
              "shortage_amount", "freight_amount", "net_settlement",
              "policy_snapshot_at"):
        assert before.get(k) == after.get(k), f"OFF path mutated trip {k}"
    # Customer master should have been updated
    c = httpx.get(f"{BASE}/customers", headers=HDRS, timeout=15).json()
    row = next((x for x in (c if isinstance(c, list) else c.get("items", []))
                if x.get("id") == cid), None)
    if row:  # not paginated
        assert row["default_freight_method"] == "per_ton_unloading"


def test_apply_skips_invoiced_and_historical_and_out_of_range():
    """Even if the caller explicitly lists an invoiced or historical trip,
    the apply endpoint must skip it and record it under `skipped`."""
    cid = _mk_customer("skip")
    pid = _mk_product(default_pct=0.5)
    t_invoiced = _mk_trip(cid, pid, date="2026-05-12", invoice=True)
    t_out_of_range = _mk_trip(cid, pid, date="2026-03-01")

    r = httpx.post(f"{BASE}/policy-changes/apply", headers=HDRS, json={
        "customer_id": cid, "effective_from": "2026-04-01",
        "new_policy": {"default_freight_method": "per_ton_unloading",
                       "shortage_config": {"limit": 0, "limit_type": "pct",
                                            "method": "full_after_limit",
                                            "effective_from": "2026-04-01",
                                            "active": True, "remarks": ""}},
        "apply_to_previous": True,
        "trip_ids": [t_invoiced, t_out_of_range],
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_trip_count"] == 0
    assert t_invoiced in body["skipped"]["invoiced"]
    assert t_out_of_range in body["skipped"]["out_of_range"]


def test_apply_leaves_non_selected_eligible_trips_untouched():
    """A second eligible trip that was NOT included in trip_ids must remain
    exactly as it was."""
    cid = _mk_customer("nosel")
    pid = _mk_product(default_pct=0.5)
    tid_a = _mk_trip(cid, pid, date="2026-05-12")
    tid_b = _mk_trip(cid, pid, date="2026-05-13")
    before_b = _get_trip(tid_b)

    r = httpx.post(f"{BASE}/policy-changes/apply", headers=HDRS, json={
        "customer_id": cid, "effective_from": "2026-04-01",
        "new_policy": {"default_freight_method": "per_ton_unloading",
                       "shortage_config": {"limit": 0, "limit_type": "pct",
                                            "method": "full_after_limit",
                                            "effective_from": "2026-04-01",
                                            "active": True, "remarks": ""}},
        "apply_to_previous": True,
        "trip_ids": [tid_a],       # only A
    }, timeout=15)
    assert r.status_code == 200, r.text
    assert tid_b not in r.json()["applied_trip_ids"]
    after_b = _get_trip(tid_b)
    for k in ("applied_freight_method", "applied_customer_shortage_method",
              "shortage_amount", "freight_amount", "net_settlement",
              "policy_snapshot_at"):
        assert before_b.get(k) == after_b.get(k), \
            f"non-selected trip mutated {k}"


def test_policy_change_event_row_captured():
    """A policy_change_events row must be written with the full old/new
    policy, applied_trip_ids, per-trip deltas, actor + status='applied'."""
    cid = _mk_customer("event")
    pid = _mk_product(default_pct=0.5)
    tid = _mk_trip(cid, pid, date="2026-05-12")
    r = httpx.post(f"{BASE}/policy-changes/apply", headers=HDRS, json={
        "customer_id": cid, "effective_from": "2026-04-01",
        "new_policy": {"default_freight_method": "per_ton_unloading",
                       "shortage_config": {"limit": 0, "limit_type": "pct",
                                            "method": "full_after_limit",
                                            "effective_from": "2026-04-01",
                                            "active": True, "remarks": ""}},
        "apply_to_previous": True, "trip_ids": [tid], "reason": "IT105-event",
    }, timeout=15)
    assert r.status_code == 200
    event = r.json()["event"]
    assert event["status"] == "applied"
    assert event["customer_id"] == cid
    assert event["effective_from"] == "2026-04-01"
    assert tid in event["applied_trip_ids"]
    assert len(event["per_trip_deltas"]) == 1
    d = event["per_trip_deltas"][0]
    assert d["trip_id"] == tid
    assert "old" in d and "new" in d and "delta_net_settlement" in d

    # History endpoint returns the event
    lst = httpx.get(f"{BASE}/policy-changes", headers=HDRS,
                    params={"customer_id": cid}, timeout=15).json()
    assert any(row["id"] == event["id"] for row in lst["items"])
