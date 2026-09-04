"""Iter137A · Searchable Vehicle + Category selectors.

Backend guardrails (payload compatibility with Iter136 P0):
  - POST /api/expenses accepts the same body as before.
  - PUT  /api/expenses/{eid} accepts the same body as before.
  - vehicle_id round-trips exactly as submitted.
  - custom category round-trips exactly as submitted.

Frontend static guards:
  - ExpenseForm.jsx still hides vendor_bill_id / mechanic_work_order_id.
  - The reusable SearchableSelect component exists and is imported by
    ExpenseForm.jsx.
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


@pytest.fixture(scope="module")
def vehicle():
    vnum = f"AP39WC{uuid.uuid4().hex[:4].upper()}"
    r = requests.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": vnum, "vehicle_type": "own",
    }, timeout=15)
    r.raise_for_status()
    return r.json()


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ── payload compatibility ────────────────────────────────────────────

def test_iter137a_payload_shape_unchanged(vehicle):
    """Create + edit path exercises the exact fields the new UI submits."""
    payload = {
        "date": "2026-02-05", "category": "Tyres", "amount": 5555,
        "narration": "Iter137A round-trip", "vehicle_id": vehicle["id"],
        "party_type": "vendor", "party_name": "Combo-Test Vendor",
        "settlement_mode": "cash_now",
    }
    r = requests.post(f"{API}/expenses", headers=H, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["vehicle_id"] == vehicle["id"]
    assert doc["category"] == "Tyres"
    assert doc["party_name"] == "Combo-Test Vendor"
    eid = doc["id"]
    # Edit — change category and clear vehicle
    payload2 = {**payload, "category": "Parking", "amount": 200,
                "vehicle_id": "", "party_type": "none", "party_name": ""}
    r2 = requests.put(f"{API}/expenses/{eid}", headers=H, json=payload2, timeout=15)
    assert r2.status_code == 200, r2.text
    doc2 = r2.json()
    assert doc2["category"] == "Parking"
    assert doc2.get("vehicle_id", "") == ""


def test_iter137a_custom_category_round_trip(vehicle):
    """Category selector's 'Other…' escape hatch must accept free text."""
    body = {
        "date": "2026-02-05", "category": "Bell Crank Rework",
        "amount": 777, "narration": "custom",
        "vehicle_id": vehicle["id"],
        "party_type": "none", "settlement_mode": "cash_now",
    }
    r = requests.post(f"{API}/expenses", headers=H, json=body, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "Bell Crank Rework"


# ── frontend static guards ───────────────────────────────────────────

def test_iter137a_searchable_component_present():
    p = Path("/app/frontend/src/components/ui/searchable-select.jsx")
    assert p.exists(), "SearchableSelect reusable component missing"
    src = p.read_text(encoding="utf-8")
    # Must be built on shadcn Command + Popover primitives.
    assert "from \"@/components/ui/command\"" in src
    assert "from \"@/components/ui/popover\"" in src
    # Search input receives focus via CommandInput.
    assert "CommandInput" in src
    # No third-party combobox library sneaked in.
    assert "react-select" not in src
    assert "downshift" not in src


def test_iter137a_form_uses_searchable_select():
    p = Path("/app/frontend/src/pages/ExpenseForm.jsx")
    src = p.read_text(encoding="utf-8")
    assert "SearchableSelect" in src, (
        "ExpenseForm.jsx must import and use the SearchableSelect combobox"
    )
    code = _strip_js_comments(src)
    # Two SearchableSelect usages — one for vehicle, one for category —
    # each wired to the historical Iter136 test-ids via the `testId` prop.
    assert code.count('testId="field-vehicle"') == 1
    assert code.count('testId="field-category"') == 1
    # Twin-payable guard (Iter136) MUST remain intact.
    assert "vendor_bill_id" not in code
    assert "mechanic_work_order_id" not in code


def test_iter137a_expenditure_types_api_reachable():
    """The expenditure-types API is the preferred source; the form merges
    it with a hard-coded fallback so historical companies (seeded before
    Iter136 added Insurance/Tyres/AdBlue/…) still see the full list."""
    r = requests.get(f"{API}/expenditure-types", headers=H, timeout=15)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and len(rows) > 0
    # Every row must at least have a non-empty name.
    for row in rows:
        assert (row.get("name") or "").strip(), f"Empty category name: {row}"


# ── register-side guards (Iter136 P0 remains locked) ─────────────────

def test_iter137a_register_filter_unchanged():
    """Iter136 Register category filter is a free-text input, not a
    combobox — must stay that way (per user's explicit instruction)."""
    p = Path("/app/frontend/src/pages/ExpenseRegister.jsx")
    src = p.read_text(encoding="utf-8")
    # Look for the testid substring — greedy regex fails on '=>' inside handlers.
    assert 'data-testid="filter-category"' in src
    idx = src.index('data-testid="filter-category"')
    # Locate the nearest opening tag before this attribute — must be <input.
    prefix = src.rfind("<", 0, idx)
    tag_open = src[prefix:idx].split()[0].lower()
    assert tag_open == "<input", (
        f"Register category filter must remain a free-text input, got tag {tag_open!r}"
    )
    # Register must NOT import SearchableSelect (locked scope).
    assert "SearchableSelect" not in src


def test_iter137a_register_vehicle_filter_unchanged():
    """Register vehicle filter stays a native <select> — searchable
    upgrade is intentionally form-only per Iter137A scope."""
    p = Path("/app/frontend/src/pages/ExpenseRegister.jsx")
    src = p.read_text(encoding="utf-8")
    assert 'data-testid="filter-vehicle"' in src
    idx = src.index('data-testid="filter-vehicle"')
    prefix = src.rfind("<", 0, idx)
    tag_open = src[prefix:idx].split()[0].lower()
    assert tag_open == "<select", (
        f"Register vehicle filter must remain a native select, got tag {tag_open!r}"
    )


# ── zero backend schema drift ────────────────────────────────────────

def test_iter137a_expense_schema_unchanged():
    import sys
    sys.path.insert(0, "/app/backend")
    from models import Expense  # type: ignore
    fields = set(Expense.model_fields.keys())
    required = {
        "id", "date", "category", "amount", "vehicle_id", "trip_id",
        "party_type", "party_id", "party_name", "settlement_mode",
        "vendor_bill_id", "mechanic_work_order_id", "file_ids",
        "is_reversed", "reversal_of", "supplier_owned_vehicle",
        "supplier_settlement_mode",
    }
    assert not (required - fields), (
        f"Expense model missing expected fields: {required - fields}"
    )
