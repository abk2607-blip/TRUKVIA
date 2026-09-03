"""Iter136 P0 · Expense Register + Non-Trip Expense Operator Workflow.

Regression coverage:
    - POST /api/expenses      — standalone (non-trip) Insurance ₹18,000
    - POST /api/expenses      — vehicle-linked Tyres ₹22,000
    - GET  /api/expenses      — list + filters (category / vehicle_id / party_type)
    - PUT  /api/expenses      — edit (amount + narration)
    - DELETE /api/expenses    — soft-cancel (reason ≥ 3 required)
    - include_reversed flag   — soft-deleted rows never resurface
    - ExpenseForm.jsx contract — payload must NEVER include vendor_bill_id
      or mechanic_work_order_id (twin-payable guard).  Static grep guard.
    - ExpenseRegister.jsx     — vehicle chip deep-links to canonical
      /vehicles/:vid/cost (Iter135A locked route).
    - Zero-schema-change      — Expense pydantic model keeps its shape.

Uses the standard /api/expenses endpoints only.  Does NOT create Bills,
Work Orders, or touch the Vendor / Mechanic Ledger (LOCKED Iter135A).
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
DEMO = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {DEMO}", "Content-Type": "application/json"}


# ── helpers ──────────────────────────────────────────────────────────

def _mk_vehicle(num: str) -> dict:
    r = requests.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": num, "vehicle_type": "own",
    }, timeout=15)
    r.raise_for_status()
    return r.json()


def _mk_expense(**body) -> dict:
    r = requests.post(f"{API}/expenses", headers=H, json=body, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ── shared fixtures ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def vehicle():
    return _mk_vehicle(f"AP31TF{uuid.uuid4().hex[:4].upper()}")


@pytest.fixture(scope="module")
def state():
    """Cross-test scratchpad."""
    return {}


# ═════════════════════════════════════════════════════════════════════
# 1.  Standalone Insurance ₹18,000 — non-trip, vehicle-less
# ═════════════════════════════════════════════════════════════════════

def test_iter136_create_standalone_insurance(state):
    doc = _mk_expense(
        date="2026-02-01", category="Insurance", amount=18000,
        narration="Annual comprehensive insurance",
        party_type="none", settlement_mode="cash_now",
    )
    assert doc["category"] == "Insurance"
    assert float(doc["amount"]) == 18000.0
    assert doc.get("vehicle_id", "") == ""
    assert doc.get("trip_id", "") == ""
    assert doc.get("vendor_bill_id", "") == ""
    assert doc.get("mechanic_work_order_id", "") == ""
    state["insurance_id"] = doc["id"]


def test_iter136_list_filter_by_category(state):
    r = requests.get(f"{API}/expenses", headers=H,
                     params={"category": "Insurance"}, timeout=15)
    assert r.status_code == 200
    rows = r.json()
    assert any(x["id"] == state["insurance_id"] for x in rows)
    assert all(x["category"] == "Insurance" for x in rows)


def test_iter136_edit_insurance(state):
    eid = state["insurance_id"]
    r = requests.put(f"{API}/expenses/{eid}", headers=H, json={
        "date": "2026-02-01", "category": "Insurance", "amount": 18500,
        "narration": "Annual comprehensive insurance (renewed)",
        "party_type": "none", "settlement_mode": "cash_now",
    }, timeout=15)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert float(doc["amount"]) == 18500.0
    assert "renewed" in doc["narration"]
    assert doc.get("is_reversed") is False


def test_iter136_cancel_requires_reason(state):
    eid = state["insurance_id"]
    # No reason
    r = requests.delete(f"{API}/expenses/{eid}", headers=H, timeout=15)
    assert r.status_code == 422
    # Too short
    r = requests.delete(f"{API}/expenses/{eid}", headers=H,
                       params={"reason": "no"}, timeout=15)
    assert r.status_code == 422


def test_iter136_cancel_soft_deletes(state):
    eid = state["insurance_id"]
    r = requests.delete(f"{API}/expenses/{eid}", headers=H,
                       params={"reason": "Duplicate entry"}, timeout=15)
    assert r.status_code == 200, r.text
    # Default list must omit cancelled row
    r2 = requests.get(f"{API}/expenses", headers=H,
                     params={"category": "Insurance"}, timeout=15)
    assert r2.status_code == 200
    assert all(x["id"] != eid for x in r2.json())


# ═════════════════════════════════════════════════════════════════════
# 2.  Vehicle-linked Tyres ₹22,000 — with vendor party
# ═════════════════════════════════════════════════════════════════════

def test_iter136_create_vehicle_tyres(state, vehicle):
    doc = _mk_expense(
        date="2026-02-02", category="Tyres", amount=22000,
        narration="Set of 4 rear tyres",
        vehicle_id=vehicle["id"],
        party_type="vendor", party_name="Local Tyre Co",
        settlement_mode="cash_now",
    )
    assert doc["vehicle_id"] == vehicle["id"]
    assert doc["category"] == "Tyres"
    assert float(doc["amount"]) == 22000.0
    # Never a twin-payable created via this API path.
    assert doc.get("vendor_bill_id", "") == ""
    assert doc.get("mechanic_work_order_id", "") == ""
    state["tyres_id"] = doc["id"]


def test_iter136_filter_by_vehicle_id(state, vehicle):
    r = requests.get(f"{API}/expenses", headers=H,
                     params={"vehicle_id": vehicle["id"]}, timeout=15)
    assert r.status_code == 200
    rows = r.json()
    assert any(x["id"] == state["tyres_id"] for x in rows)
    assert all(x["vehicle_id"] == vehicle["id"] for x in rows)


def test_iter136_filter_by_party_type(state):
    r = requests.get(f"{API}/expenses", headers=H,
                     params={"party_type": "vendor"}, timeout=15)
    assert r.status_code == 200
    rows = r.json()
    assert any(x["id"] == state["tyres_id"] for x in rows)
    assert all(x.get("party_type") == "vendor" for x in rows)


def test_iter136_vehicle_number_denorm(state, vehicle):
    """Register's vehicle chip depends on denormalised vehicle_number."""
    r = requests.get(f"{API}/expenses", headers=H,
                     params={"vehicle_id": vehicle["id"]}, timeout=15)
    row = next(x for x in r.json() if x["id"] == state["tyres_id"])
    assert row.get("vehicle_number"), "Expense row missing vehicle_number denorm"
    assert row["vehicle_number"] == vehicle["vehicle_number"]


# ═════════════════════════════════════════════════════════════════════
# 3.  include_reversed toggle
# ═════════════════════════════════════════════════════════════════════

def test_iter136_include_reversed_toggle(state):
    """Soft-deleted rows must NEVER reappear via include_reversed=true;
    that flag only controls reversed rows (correction chain)."""
    r_def = requests.get(f"{API}/expenses", headers=H, timeout=15)
    r_incl = requests.get(f"{API}/expenses", headers=H,
                         params={"include_reversed": True}, timeout=15)
    assert r_def.status_code == 200 and r_incl.status_code == 200
    default_ids = {x["id"] for x in r_def.json()}
    incl_ids = {x["id"] for x in r_incl.json()}
    assert state["insurance_id"] not in default_ids
    assert state["insurance_id"] not in incl_ids


# ═════════════════════════════════════════════════════════════════════
# 4.  Frontend contract — no twin-payable fields, canonical vehicle route
# ═════════════════════════════════════════════════════════════════════

def _strip_js_comments(src: str) -> str:
    """Remove /* … */ block comments and // line comments so guards
    ignore intentional documentation of hidden fields."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def test_iter136_form_omits_twin_payable_fields():
    raw = Path("/app/frontend/src/pages/ExpenseForm.jsx").read_text(encoding="utf-8")
    code = _strip_js_comments(raw)
    assert "vendor_bill_id" not in code, (
        "ExpenseForm.jsx code must not reference vendor_bill_id — "
        "RepairWorkspace owns the vendor payable twin-write."
    )
    assert "mechanic_work_order_id" not in code, (
        "ExpenseForm.jsx code must not reference mechanic_work_order_id — "
        "RepairWorkspace owns the mechanic payable twin-write."
    )


def test_iter136_register_uses_canonical_vehicle_cost_route():
    src = Path("/app/frontend/src/pages/ExpenseRegister.jsx").read_text(encoding="utf-8")
    assert re.search(r"/vehicles/\$\{[^}]+\}/cost", src), (
        "ExpenseRegister.jsx must route the vehicle chip to /vehicles/:vid/cost"
    )
    # Must NOT link to repair-history (Iter135A locked rule).
    assert "/repair-history" not in src


# ═════════════════════════════════════════════════════════════════════
# 5.  Zero-schema-change guard — Expense model unchanged
# ═════════════════════════════════════════════════════════════════════

def test_iter136_expense_schema_unchanged():
    import sys
    sys.path.insert(0, "/app/backend")
    from models import Expense  # type: ignore
    fields = set(Expense.model_fields.keys())
    required = {
        "id", "date", "category", "amount", "vehicle_id", "trip_id",
        "party_type", "party_id", "party_name", "settlement_mode",
        "vendor_bill_id", "mechanic_work_order_id", "file_ids",
        "is_reversed", "reversal_of",
    }
    missing = required - fields
    assert not missing, f"Expense model missing expected fields: {missing}"


# ═════════════════════════════════════════════════════════════════════
# 6.  Seeded categories — the P0 non-trip list is present
# ═════════════════════════════════════════════════════════════════════

def test_iter136_seeded_categories_include_non_trip():
    import sys
    sys.path.insert(0, "/app/backend")
    from models import DEFAULT_EXPENDITURE_TYPES  # type: ignore
    for c in ["Insurance", "Road Tax", "Permit", "Fitness", "Tyres",
              "Engine Oil", "AdBlue", "Repair", "Spare Parts"]:
        assert c in DEFAULT_EXPENDITURE_TYPES, f"Missing seeded category: {c}"
