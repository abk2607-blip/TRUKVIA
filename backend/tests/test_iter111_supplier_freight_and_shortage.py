"""Iter111 · Supplier Freight & Shortage — final requirements regression.

Contract pinned:
  A. Supplier Freight MIRRORS the trip's applied_freight_method:
       per_ton_loading   → uses loading tons
       per_ton_unloading → uses unloading tons
       per_ton_higher_of → uses max(loading, unloading)
       fixed             → supplier_fixed_amount / RT
     Supplier's own supplier_rate_per_ton stays separate from customer rate.

  B. Supplier Shortage threshold (independent of customer policy):
       actual <= limit           → ZERO deduction
       actual  > limit           → FULL actual × product_rate_per_mt
       limit <= 0 (unconfigured) → FULL actual × product_rate_per_mt (Iter111)
                                   (was: mirror customer shortage_amount — removed)

  C. Manual override:
       • supplier_shortage_deduction is editable via PUT /trips/{id}.
       • When the new value != system-computed → override=True, reason mandatory,
         actor + timestamp stamped. Original system value preserved.
       • Restoring the value back to the system-computed number → override
         cleared, reason cleared, NO extra audit crumb.
"""
import os
import uuid
import httpx


BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDRS = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}


# ─────────────────────────── helpers ────────────────────────────────────

def _customer(*, freight="per_ton_loading") -> str:
    body = {
        "name": f"IT111_C_{uuid.uuid4().hex[:6]}",
        "default_freight_method": freight,
        "shortage_config": {"limit": 0, "limit_type": "pct", "method": "net_shortage",
                             "effective_from": "", "active": True, "remarks": ""},
    }
    r = httpx.post(f"{BASE}/customers", headers=HDRS, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _product() -> str:
    r = httpx.post(f"{BASE}/products", headers=HDRS, json={
        "name": f"IT111_P_{uuid.uuid4().hex[:6]}", "hsn_sac": "996791", "unit": "MT",
        "default_shortage_allowance_pct": 0.0,
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _supplier(*, limit_kg: float = 0.0) -> str:
    r = httpx.post(f"{BASE}/suppliers", headers=HDRS, json={
        "name": f"IT111_S_{uuid.uuid4().hex[:6]}",
        "phone": "9999999999",
        "shortage_limit_kg": limit_kg,
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _mk_supplier_trip(cid, pid, sid, *, loaded=33.2, unloaded=32.8,
                     rate_per_ton=1000.0, rate_per_mt=62500.0,
                     freight_mode="per_ton",
                     supplier_rate=None,
                     supplier_freight_mode="per_ton",
                     supplier_fixed=0.0) -> dict:
    body = {
        "customer_id": cid, "product_id": pid, "supplier_id": sid,
        "date": "2026-05-12",
        "vehicle_number": f"AP39{uuid.uuid4().hex[:4].upper()}",
        "vehicle_type": "supplier",
        "tons": loaded, "loaded_qty": loaded, "unloaded_qty": unloaded,
        "product_rate_per_mt": rate_per_mt,
        "freight_mode": freight_mode, "rate_per_ton": rate_per_ton,
        "supplier_freight_mode": supplier_freight_mode,
        "supplier_rate_per_ton": supplier_rate if supplier_rate is not None else rate_per_ton,
        "supplier_fixed_amount": supplier_fixed,
        "load_details": "BITUMEN VG 40",
    }
    r = httpx.post(f"{BASE}/trips", headers=HDRS, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _get(tid: str) -> dict:
    r = httpx.get(f"{BASE}/trips/{tid}", headers=HDRS, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _put(tid: str, patch: dict) -> httpx.Response:
    cur = _get(tid)
    cur.update(patch)
    return httpx.put(f"{BASE}/trips/{tid}", headers=HDRS, json=cur, timeout=15)


# ═════════════════ A. Supplier Freight — quantity basis ═════════════════

def test_freight_per_ton_loading_uses_loading_tons():
    cid = _customer(freight="per_ton_loading")
    pid = _product(); sid = _supplier()
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.2, unloaded=32.8, rate_per_ton=1000)
    assert t["applied_freight_method"] == "per_ton_loading"
    assert t["supplier_quantity"] == 33.2
    assert t["supplier_freight"] == 33200.00


def test_freight_per_ton_unloading_uses_unloading_tons():
    """The exact case the user flagged. Supplier freight MUST use unloading."""
    cid = _customer(freight="per_ton_unloading")
    pid = _product(); sid = _supplier()
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.2, unloaded=32.8, rate_per_ton=1000)
    assert t["applied_freight_method"] == "per_ton_unloading"
    assert t["supplier_quantity"] == 32.8, f"expected 32.8 got {t['supplier_quantity']}"
    assert t["supplier_freight"] == 32800.00


def test_freight_higher_of_uses_max_loading_unloading():
    cid = _customer(freight="per_ton_higher_of")
    pid = _product(); sid = _supplier()
    # Unloading > loading → higher-of picks unloading
    t = _mk_supplier_trip(cid, pid, sid, loaded=30.0, unloaded=32.5, rate_per_ton=1000)
    assert t["supplier_quantity"] == 32.5
    assert t["supplier_freight"] == 32500.00


def test_freight_fixed_uses_supplier_fixed_amount():
    cid = _customer(freight="fixed")
    pid = _product(); sid = _supplier()
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.2, unloaded=32.8,
                          freight_mode="fixed",
                          supplier_freight_mode="fixed",
                          supplier_fixed=45000.0,
                          supplier_rate=0.0)
    assert t["supplier_freight"] == 45000.00


# ═════════════════ B. Supplier Shortage — threshold logic ═════════════════

def test_shortage_below_limit_zero_deduction():
    cid = _customer(); pid = _product(); sid = _supplier(limit_kg=100)
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.280, unloaded=33.200,
                          rate_per_ton=1000, rate_per_mt=62500)
    assert round(t["shortage_qty"] * 1000) == 80
    assert t["supplier_shortage_deduction"] == 0.0
    assert t["supplier_shortage_original_amount"] == 0.0


def test_shortage_equal_to_limit_zero_deduction():
    cid = _customer(); pid = _product(); sid = _supplier(limit_kg=100)
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.300, unloaded=33.200,
                          rate_per_ton=1000, rate_per_mt=62500)
    assert round(t["shortage_qty"] * 1000) == 100
    assert t["supplier_shortage_deduction"] == 0.0


def test_shortage_above_limit_full_actual_deduction():
    cid = _customer(); pid = _product(); sid = _supplier(limit_kg=100)
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.340, unloaded=33.200,
                          rate_per_ton=1000, rate_per_mt=62500)
    assert round(t["shortage_qty"] * 1000) == 140
    # FULL 0.140 × ₹62500 = ₹8750
    assert t["supplier_shortage_deduction"] == 8750.00
    assert t["supplier_shortage_original_amount"] == 8750.00


def test_no_supplier_limit_uses_full_actual_deduction_not_customer_mirror():
    """Iter111 rule #4 — no supplier limit configured → FULL deduction.
    Previous behaviour mirrored trip.shortage_amount (customer side); must
    NOT do that anymore."""
    cid = _customer(); pid = _product(); sid = _supplier(limit_kg=0)
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.340, unloaded=33.200,
                          rate_per_ton=1000, rate_per_mt=62500)
    # Even though customer has no shortage_config (shortage_amount = ₹25000
    # via legacy full-fallback in customer engine), supplier side MUST use
    # its OWN full-actual × product_rate rule → 0.14 × 62500 = ₹8750.
    assert t["supplier_shortage_deduction"] == 8750.00


# ═════════════════ C. Manual override — reason / audit / restore ═════════

def test_override_calculated_shortage_is_editable():
    cid = _customer(); pid = _product(); sid = _supplier(limit_kg=100)
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.340, unloaded=33.200,
                          rate_per_mt=62500)
    r = _put(t["id"], {
        "supplier_shortage_deduction": 5000.0,
        "supplier_shortage_deduction_override": True,
        "supplier_shortage_override_reason": "Negotiated write-down with driver",
    })
    assert r.status_code == 200, r.text
    updated = _get(t["id"])
    assert updated["supplier_shortage_deduction"] == 5000.0
    assert updated["supplier_shortage_deduction_override"] is True
    assert updated["supplier_shortage_original_amount"] == 8750.00
    assert updated["supplier_shortage_override_reason"] == "Negotiated write-down with driver"
    assert updated["supplier_shortage_override_by"] != ""
    assert updated["supplier_shortage_override_at"] != ""


def test_override_edit_flips_auto_to_manual_and_requires_reason():
    cid = _customer(); pid = _product(); sid = _supplier(limit_kg=100)
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.340, unloaded=33.200,
                          rate_per_mt=62500)
    r = _put(t["id"], {
        "supplier_shortage_deduction": 5000.0,
        "supplier_shortage_deduction_override": True,
        "supplier_shortage_override_reason": "",   # missing
    })
    assert r.status_code == 400, r.text
    assert "reason" in r.text.lower()


def test_override_manual_value_flows_to_supplier_settlement():
    cid = _customer(); pid = _product(); sid = _supplier(limit_kg=100)
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.340, unloaded=33.200,
                          rate_per_ton=1000, rate_per_mt=62500)
    net_before = t["supplier_net_payable"]     # freight - 8750 - ...
    r = _put(t["id"], {
        "supplier_shortage_deduction": 2000.0,
        "supplier_shortage_deduction_override": True,
        "supplier_shortage_override_reason": "Half write-off",
    })
    assert r.status_code == 200, r.text
    updated = _get(t["id"])
    # Net payable increases by (8750 - 2000) = 6750 because the deduction shrank.
    assert round(updated["supplier_net_payable"] - net_before, 2) == 6750.00


def test_restore_to_system_value_returns_to_auto_no_audit_noise():
    """Bringing the value back to the exact system-calculated number clears
    the override flag + reason WITHOUT creating a new audit row for the
    restored value (per user rule #6 — no audit noise)."""
    cid = _customer(); pid = _product(); sid = _supplier(limit_kg=100)
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.340, unloaded=33.200,
                          rate_per_mt=62500)
    # Manual override first
    r = _put(t["id"], {
        "supplier_shortage_deduction": 5000.0,
        "supplier_shortage_deduction_override": True,
        "supplier_shortage_override_reason": "Trial",
    })
    assert r.status_code == 200
    # Restore to system value (8750.00). No reason required this time.
    r = _put(t["id"], {
        "supplier_shortage_deduction": 8750.00,
        "supplier_shortage_deduction_override": False,
        "supplier_shortage_override_reason": "",
    })
    assert r.status_code == 200, r.text
    restored = _get(t["id"])
    assert restored["supplier_shortage_deduction"] == 8750.00
    assert restored["supplier_shortage_deduction_override"] is False
    assert restored["supplier_shortage_override_reason"] == ""
    assert restored["supplier_shortage_override_by"] == ""
    assert restored["supplier_shortage_override_at"] == ""


def test_override_captures_full_audit_metadata():
    cid = _customer(); pid = _product(); sid = _supplier(limit_kg=100)
    t = _mk_supplier_trip(cid, pid, sid, loaded=33.340, unloaded=33.200,
                          rate_per_mt=62500)
    r = _put(t["id"], {
        "supplier_shortage_deduction": 3333.0,
        "supplier_shortage_deduction_override": True,
        "supplier_shortage_override_reason": "Damaged bag write-off",
    })
    assert r.status_code == 200
    d = _get(t["id"])
    # All 4 audit fields populated
    assert d["supplier_shortage_original_amount"] == 8750.00     # original
    assert d["supplier_shortage_deduction"] == 3333.00           # final
    assert d["supplier_shortage_override_reason"] == "Damaged bag write-off"
    assert d["supplier_shortage_override_by"], "missing actor"
    assert d["supplier_shortage_override_at"], "missing timestamp"
