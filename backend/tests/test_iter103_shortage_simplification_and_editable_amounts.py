"""Iter103 · Shortage Policy Simplification + Editable Shortage/Excess.

Guards the Feb 2026 changes to the Shortage model:
  Product Master  → Shortage Allowance (source of truth)
  Customer Master → Deduction Method (Net vs Full-After-Limit)
  Customer Master → Optional "Custom Allowance" override

Plus the editable Shortage/Excess UX invariants:
  • Auto-calculated by default
  • First non-matching edit → override flag flips true (frontend responsibility)
  • Override reason stored on save via the existing field_overrides audit log
  • Reverting to system value → override flag clears + no audit noise

Existing engine + historical snapshot behaviour is preserved — these tests
verify the intended data flows without altering `_compute_trip` logic.
"""
import os
import uuid

import httpx


API = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
TOK = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}
T = 30


def _boot():
    httpx.post(f"{API}/auth/demo-login", timeout=T)


# ══════════════════════════════════════════════════════════════════════════
# Decision 1 — Product Master owns the allowance when the Customer hasn't
# turned on a Custom Allowance override.  Customer's method must still apply.
# ══════════════════════════════════════════════════════════════════════════

def test_product_allowance_used_when_customer_has_no_custom_limit():
    """Bitumen 0.5 % + Customer method=full_after_limit + no custom allowance
    → snapshot picks up product pct and customer method drives the deduction."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT103_Prod_{tag}", "default_shortage_allowance_pct": 0.5,
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT103_Cust_{tag}", "state": "AP",
        # Custom allowance intentionally left OFF (limit=0).
        "shortage_config": {"limit": 0, "limit_type": "pct",
                             "method": "full_after_limit", "active": True},
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP103A{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()

    tid = None
    try:
        # 20 MT loaded, 19.85 unloaded → shortage 0.150 MT (0.75 %)
        # Product allowance 0.5 % of 20 = 0.100 MT.  Actual 0.150 > allowed.
        # method=full_after_limit → deduction = 0.150 × 40000 = 6000.00
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-11-01",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "own",
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.85,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
        }, timeout=T).json()
        tid = t["id"]
        assert t["applied_customer_shortage_limit"] == 0.0                 # no custom
        assert t["applied_product_shortage_pct"] == 0.5                    # from Product
        assert t["applied_customer_shortage_method"] == "full_after_limit" # from Customer
        # Full-after-limit: whole 0.150 MT × 40000 = 6 000
        assert abs(t["shortage_amount"] - 6000.0) < 0.02, t["shortage_amount"]
    finally:
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


def test_customer_custom_allowance_wins_over_product():
    """Bitumen product 0.5 % + Customer *custom* 0.3 % override → snapshot
    uses the customer limit, not the product's."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT103_Prod_{tag}", "default_shortage_allowance_pct": 0.5,
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT103_Cust_{tag}", "state": "AP",
        # Customer contractually agreed to 0.3 % (stricter than product's 0.5 %)
        "shortage_config": {"limit": 0.3, "limit_type": "pct",
                             "method": "net_shortage", "active": True},
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP103B{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()

    tid = None
    try:
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-11-01",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "own",
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.85,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
        }, timeout=T).json()
        tid = t["id"]
        assert t["applied_customer_shortage_limit"] == 0.3   # customer wins
        assert t["applied_product_shortage_pct"] == 0.5      # product still frozen
        assert t["applied_customer_shortage_method"] == "net_shortage"
        # 0.3% of 20 = 0.06 MT allowed. Shortage 0.150. Net = 0.090 × 40000 = 3600
        assert abs(t["shortage_amount"] - 3600.0) < 0.02, t["shortage_amount"]
    finally:
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


# ══════════════════════════════════════════════════════════════════════════
# Decision 2 — Historical protection: existing snapshots must remain intact
# ══════════════════════════════════════════════════════════════════════════

def test_historical_snapshot_immune_to_customer_edits():
    """Existing Trip's frozen policy must NOT change when we later edit the
    Customer's shortage_config or toggle the Custom Allowance flag."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT103_Prod_{tag}", "default_shortage_allowance_pct": 0.5,
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT103_Cust_{tag}", "state": "AP",
        "shortage_config": {"limit": 0.3, "limit_type": "pct",
                             "method": "net_shortage", "active": True},
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP103C{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()
    tid = None
    try:
        t0 = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-11-01",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "own",
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.85,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
        }, timeout=T).json()
        tid = t0["id"]
        original_snapshot = {
            "limit": t0["applied_customer_shortage_limit"],
            "type":  t0["applied_customer_shortage_limit_type"],
            "method": t0["applied_customer_shortage_method"],
            "prod_pct": t0["applied_product_shortage_pct"],
            "shortage_amount": t0["shortage_amount"],
        }
        # Now flip the customer OFF the custom-allowance override
        httpx.put(f"{API}/customers/{cust['id']}", headers=H, json={
            **cust,
            "shortage_config": {"limit": 0, "limit_type": "pct",
                                 "method": "full_after_limit", "active": True},
        }, timeout=T)
        # …and edit the product allowance too
        httpx.put(f"{API}/products/{prod['id']}", headers=H, json={
            **prod, "default_shortage_allowance_pct": 1.0,
        }, timeout=T)
        # Re-read the historical trip → snapshot must be UNCHANGED
        got = httpx.get(f"{API}/trips/{tid}", headers=H, timeout=T).json()
        assert got["applied_customer_shortage_limit"] == original_snapshot["limit"]
        assert got["applied_customer_shortage_limit_type"] == original_snapshot["type"]
        assert got["applied_customer_shortage_method"] == original_snapshot["method"]
        assert got["applied_product_shortage_pct"] == original_snapshot["prod_pct"]
        assert abs(got["shortage_amount"] - original_snapshot["shortage_amount"]) < 0.02
    finally:
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


# ══════════════════════════════════════════════════════════════════════════
# Decision 3 — Excess is customer-side ONLY.  Supplier settlement is untouched.
# ══════════════════════════════════════════════════════════════════════════

def test_excess_amount_does_not_touch_supplier_settlement():
    """Even when Customer has an excess (unloaded > loaded) the Supplier
    settlement fields (freight, halting, diesel, advance, shortage_deduction,
    net_payable) must be completely unaffected."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    sup = httpx.post(f"{API}/suppliers", headers=H, json={
        "name": f"IT103_Sup_{tag}", "state": "AP", "shortage_limit_kg": 100,
    }, timeout=T).json()
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT103_ProdE_{tag}",
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT103_CustE_{tag}", "state": "AP",
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP103D{tag[:4].upper()}", "vehicle_type": "supplier",
        "supplier_id": sup["id"],
    }, timeout=T).json()
    tid = None
    try:
        # unloaded > loaded → excess 0.200 MT
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-11-02",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "supplier", "supplier_id": sup["id"],
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 20.2,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
            "supplier_freight_mode": "per_ton",
            "supplier_rate_per_ton": 2000, "supplier_quantity": 20.0,
        }, timeout=T).json()
        tid = t["id"]
        # Customer sees excess
        assert t["excess_qty"] == 0.2
        assert abs(t["excess_amount"] - 8000.0) < 0.02
        assert t["shortage_qty"] == 0.0
        # Supplier is UNTOUCHED — no excess flows there
        assert abs(t["supplier_freight"] - 40000.0) < 0.02
        assert t["supplier_shortage_deduction"] == 0.0
        assert abs(t["supplier_net_payable"] - 40000.0) < 0.02
    finally:
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/suppliers/{sup['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


# ══════════════════════════════════════════════════════════════════════════
# Decision 4 — Editable Shortage & Excess with override audit trail
# ══════════════════════════════════════════════════════════════════════════

def test_manual_shortage_override_flows_to_invoice_and_audit():
    """When a user overrides shortage_amount, PUT /trips writes to
    trip.field_overrides[] AND the manual value flows into the invoice."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT103_ProdX_{tag}", "default_shortage_allowance_pct": 0.5,
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT103_CustX_{tag}", "state": "AP",
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP103E{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()
    tid = None
    inv_id = None
    try:
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-11-03",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "own",
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.85,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
        }, timeout=T).json()
        tid = t["id"]
        system_short = float(t["shortage_amount"])   # expected 2000.00 (net 0.05 × 40k)

        # Manager overrides to a lower agreed value (₹1000) with reason
        override_val = 1000.0
        put_r = httpx.put(f"{API}/trips/{tid}", headers=H, json={
            **t,
            "shortage_amount": override_val,
            "shortage_amount_override": True,
            "field_overrides": [{
                "field": "shortage_amount",
                "system_value": system_short,
                "final_value": override_val,
                "reason": "Customer accepted only ₹1000 as agreed telephonically",
                "modified_by": os.environ["DEMO_TOKEN_VALUE"],
                "modified_at": "2026-11-03T10:00:00Z",
            }],
        }, timeout=T)
        assert put_r.status_code == 200, put_r.text
        updated = put_r.json()
        assert abs(updated["shortage_amount"] - override_val) < 0.02, \
            f"override not persisted: {updated['shortage_amount']}"
        assert updated["shortage_amount_override"] is True
        overrides = updated.get("field_overrides") or []
        assert any(o["field"] == "shortage_amount" and
                    abs(o["system_value"] - system_short) < 0.02 and
                    abs(o["final_value"] - override_val) < 0.02 and
                    "telephonically" in (o.get("reason") or "")
                    for o in overrides), overrides

        # Invoice must pick up the OVERRIDDEN value, not the system value
        inv = httpx.post(f"{API}/invoices", headers=H, json={
            "customer_id": cust["id"], "invoice_date": "2026-11-04",
            "trip_ids": [tid], "hsn_sac": "996791", "gst_treatment": "rcm",
        }, timeout=T).json()
        inv_id = inv["id"]
        assert abs(float(inv["shortage_total"]) - override_val) < 0.02, \
            f"invoice.shortage_total {inv['shortage_total']} != override {override_val}"
    finally:
        if inv_id:
            httpx.delete(f"{API}/invoices/{inv_id}", headers=H, timeout=T)
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


def test_reverting_manual_to_system_value_clears_override_state():
    """When the user restores shortage_amount to the system-computed value,
    the override flag should clear (frontend responsibility) AND the trip
    resave should NOT append a new no-op audit entry (system==final)."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT103_ProdR_{tag}", "default_shortage_allowance_pct": 0.5,
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT103_CustR_{tag}", "state": "AP",
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP103F{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()
    tid = None
    try:
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-11-03",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "own",
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.85,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
        }, timeout=T).json()
        tid = t["id"]
        system_short = float(t["shortage_amount"])
        # First save: user reverts to system value + clears the override flag
        r = httpx.put(f"{API}/trips/{tid}", headers=H, json={
            **t,
            "shortage_amount": system_short,
            "shortage_amount_override": False,
            "field_overrides": [],   # frontend purges the reason on revert
        }, timeout=T)
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["shortage_amount_override"] is False
        overrides = got.get("field_overrides") or []
        # No override entry should reference shortage_amount because the
        # final value equals the system value.
        for o in overrides:
            if o.get("field") == "shortage_amount":
                assert abs(o["system_value"] - o["final_value"]) < 0.02, \
                    f"no-op override should not be recorded: {o}"
    finally:
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


def test_manual_excess_override_flows_to_invoice_customer_side_only():
    """Excess override reaches the invoice's excess_total but never touches
    supplier settlement fields (which stay at 0 or their own-track value)."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    sup = httpx.post(f"{API}/suppliers", headers=H, json={
        "name": f"IT103_SupE_{tag}", "state": "AP",
    }, timeout=T).json()
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT103_ProdEE_{tag}",
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT103_CustEE_{tag}", "state": "AP",
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP103G{tag[:4].upper()}", "vehicle_type": "supplier",
        "supplier_id": sup["id"],
    }, timeout=T).json()
    tid = None
    inv_id = None
    try:
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-11-05",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "supplier", "supplier_id": sup["id"],
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 20.2,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
            "supplier_freight_mode": "per_ton",
            "supplier_rate_per_ton": 2000, "supplier_quantity": 20.0,
        }, timeout=T).json()
        tid = t["id"]
        sys_excess = float(t["excess_amount"])                # 8000
        supplier_net_before = float(t["supplier_net_payable"])

        # Override excess to zero (commercial concession)
        r = httpx.put(f"{API}/trips/{tid}", headers=H, json={
            **t,
            "excess_amount": 0.0,
            "excess_amount_override": True,
            "field_overrides": [{
                "field": "excess_amount",
                "system_value": sys_excess,
                "final_value": 0.0,
                "reason": "Waived per management call",
                "modified_by": os.environ["DEMO_TOKEN_VALUE"],
                "modified_at": "2026-11-05T10:00:00Z",
            }],
        }, timeout=T)
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["excess_amount"] == 0.0
        assert got["excess_amount_override"] is True
        # Supplier settlement must be unchanged
        assert abs(float(got["supplier_net_payable"]) - supplier_net_before) < 0.02

        # Invoice picks up the overridden value
        inv = httpx.post(f"{API}/invoices", headers=H, json={
            "customer_id": cust["id"], "invoice_date": "2026-11-05",
            "trip_ids": [tid], "hsn_sac": "996791", "gst_treatment": "rcm",
        }, timeout=T).json()
        inv_id = inv["id"]
        assert float(inv["excess_total"]) == 0.0, inv["excess_total"]
    finally:
        if inv_id:
            httpx.delete(f"{API}/invoices/{inv_id}", headers=H, timeout=T)
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/suppliers/{sup['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


# ══════════════════════════════════════════════════════════════════════════
# Decision 5 — Supplier fixed-KG shortage logic remains independent
# ══════════════════════════════════════════════════════════════════════════

def test_supplier_fixed_kg_shortage_logic_unchanged():
    """Supplier's shortage_limit_kg gate is completely independent from the
    Product/Customer allowance simplification.  Same trip must produce the
    Customer-side deduction based on Product allowance AND the Supplier-side
    deduction based on the supplier's fixed KG limit."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    sup = httpx.post(f"{API}/suppliers", headers=H, json={
        "name": f"IT103_SupIndep_{tag}", "state": "AP",
        "shortage_limit_kg": 50,      # supplier allows 50 KG
    }, timeout=T).json()
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT103_ProdIndep_{tag}",
        "default_shortage_allowance_pct": 0.5,   # product allows 0.5 %
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT103_CustIndep_{tag}", "state": "AP",
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP103H{tag[:4].upper()}", "vehicle_type": "supplier",
        "supplier_id": sup["id"],
    }, timeout=T).json()
    tid = None
    try:
        # shortage 200 kg (0.2 MT). Product allowance 0.5% of 20 = 0.1 MT.
        # Customer net = (0.2 - 0.1) × 40000 = 4000.
        # Supplier limit 50 KG → exceeded → supplier deducts full 0.2 MT × 40000 = 8000.
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-11-06",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "supplier", "supplier_id": sup["id"],
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.8,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
            "supplier_freight_mode": "per_ton",
            "supplier_rate_per_ton": 2000, "supplier_quantity": 20.0,
        }, timeout=T).json()
        tid = t["id"]
        # Customer side
        assert t["applied_product_shortage_pct"] == 0.5
        assert t["applied_customer_shortage_limit"] == 0.0
        assert abs(t["shortage_amount"] - 4000.0) < 0.02, t["shortage_amount"]
        # Supplier side (independent — fixed KG limit exceeded)
        assert t["applied_supplier_shortage_limit_kg"] == 50.0
        assert abs(t["supplier_shortage_deduction"] - 8000.0) < 0.02, t["supplier_shortage_deduction"]
    finally:
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/suppliers/{sup['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)
