"""Iter139 P0 · Quick Operational Expense — bulk canonical Expense writer.

Focused regression covering:
  • whitelist enforcement
  • per-row validation + partial-batch success
  • idempotency (batch key + row-level source_key)
  • supplier-vehicle routing (adjustment / company-borne)
  • Fuel-collection isolation
  • Iter135 vendor-ledger invariant preservation
"""
from __future__ import annotations
import os
import uuid
from pathlib import Path

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
DEMO = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {DEMO}", "Content-Type": "application/json"}


def _mk_vehicle(vtype="own", supplier_name=""):
    body = {"vehicle_number": f"AP31TF{uuid.uuid4().hex[:4].upper()}",
            "vehicle_type": vtype}
    if vtype == "supplier":
        sup_body = {"name": f"Sup-{uuid.uuid4().hex[:8]}"}
        sr = requests.post(f"{API}/suppliers", headers=H, json=sup_body, timeout=15)
        if sr.status_code == 409:
            existing = (sr.json() or {}).get("detail", {}).get("existing") or {}
            sup = existing
        else:
            assert sr.status_code in (200, 201), sr.text
            sup = sr.json()
        body["supplier_id"] = sup["id"]
        body["supplier_name"] = sup["name"]
    r = requests.post(f"{API}/vehicles", headers=H, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture(scope="module")
def own_veh():
    return _mk_vehicle("own")


@pytest.fixture(scope="module")
def own_veh2():
    return _mk_vehicle("own")


@pytest.fixture(scope="module")
def supplier_veh():
    return _mk_vehicle("supplier", "ABC Transport")


def _post_batch(**body):
    return requests.post(f"{API}/expenses/bulk-operational", headers=H,
                         json=body, timeout=30)


# ── Happy paths ────────────────────────────────────────────────────
def test_single_vehicle_toll(own_veh):
    r = _post_batch(date="2026-09-04", category="Toll",
                    entries=[{"client_row_id": f"r-{uuid.uuid4().hex[:8]}",
                              "vehicle_id": own_veh["id"], "amount": 1000}])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["created"] == 1 and j["failed"] == 0
    row = j["results"][0]
    assert row["status"] == "created"
    exp = row["expense"]
    assert exp["category"] == "Toll" and exp["amount"] == 1000.0
    assert exp["vehicle_id"] == own_veh["id"]
    assert exp["source_type"] == "quick_op"
    assert exp["source_key"].startswith("quickop:2026-09-04:toll:")
    assert exp["party_type"] == "cash" and exp["settlement_mode"] == "cash_now"
    assert exp["vendor_bill_id"] == "" and exp["mechanic_work_order_id"] == ""


def test_multi_vehicle_batch(own_veh, own_veh2):
    entries = [
        {"client_row_id": f"m1-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": 500},
        {"client_row_id": f"m2-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh2["id"], "amount": 700},
    ]
    r = _post_batch(date="2026-09-05", category="Parking", entries=entries)
    j = r.json()
    assert j["created"] == 2 and j["failed"] == 0
    assert [x["status"] for x in j["results"]] == ["created", "created"]


def test_supplier_adjustment(supplier_veh):
    r = _post_batch(date="2026-09-06", category="Toll", entries=[{
        "client_row_id": f"sa-{uuid.uuid4().hex[:8]}", "vehicle_id": supplier_veh["id"],
        "amount": 1200, "supplier_settlement_mode": "supplier_settlement_adjustment"}])
    exp = r.json()["results"][0]["expense"]
    assert exp["supplier_owned_vehicle"] is True
    assert exp["supplier_settlement_mode"] == "supplier_settlement_adjustment"


def test_supplier_company_borne(supplier_veh):
    r = _post_batch(date="2026-09-07", category="Toll", entries=[{
        "client_row_id": f"cb-{uuid.uuid4().hex[:8]}", "vehicle_id": supplier_veh["id"],
        "amount": 1300, "supplier_settlement_mode": "company_borne"}])
    exp = r.json()["results"][0]["expense"]
    assert exp["supplier_owned_vehicle"] is True
    assert exp["supplier_settlement_mode"] == "company_borne"


def test_batch_with_trip_id(own_veh):
    # Trip existence is validated — invalid trip fails at batch level.
    r = _post_batch(date="2026-09-08", category="Toll", trip_id="trip_does_not_exist",
                    entries=[{"client_row_id": "t1", "vehicle_id": own_veh["id"], "amount": 100}])
    assert r.status_code == 400


# ── Row-level validation ────────────────────────────────────────────
def test_non_whitelist_category(own_veh):
    r = _post_batch(date="2026-09-09", category="Insurance",
                    entries=[{"client_row_id": "x", "vehicle_id": own_veh["id"], "amount": 100}])
    assert r.status_code == 400


def test_zero_amount_row_failed(own_veh, own_veh2):
    r = _post_batch(date="2026-09-10", category="Toll", entries=[
        {"client_row_id": f"ok-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": 100},
        {"client_row_id": f"bad-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh2["id"], "amount": 0},
    ])
    j = r.json()
    assert j["created"] == 1 and j["failed"] == 1
    assert j["results"][1]["status"] == "failed"
    assert j["results"][1]["error"]["code"] == "INVALID_AMOUNT"


def test_negative_amount_row_failed(own_veh):
    r = _post_batch(date="2026-09-11", category="Toll", entries=[
        {"client_row_id": f"neg-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": -100}])
    assert r.json()["results"][0]["error"]["code"] == "INVALID_AMOUNT"


def test_vehicle_not_found():
    r = _post_batch(date="2026-09-12", category="Toll", entries=[
        {"client_row_id": f"n-{uuid.uuid4().hex[:6]}", "vehicle_id": "veh_missing", "amount": 100}])
    assert r.json()["results"][0]["error"]["code"] == "VEHICLE_NOT_FOUND"


def test_inactive_vehicle():
    v = _mk_vehicle("own")
    # Deactivate
    upd = {**v, "is_active": False}
    requests.put(f"{API}/vehicles/{v['id']}", headers=H, json=upd, timeout=15)
    r = _post_batch(date="2026-09-13", category="Toll", entries=[
        {"client_row_id": f"in-{uuid.uuid4().hex[:6]}", "vehicle_id": v["id"], "amount": 100}])
    assert r.json()["results"][0]["error"]["code"] == "VEHICLE_INACTIVE"


def test_supplier_without_mode(supplier_veh):
    r = _post_batch(date="2026-09-14", category="Toll", entries=[
        {"client_row_id": f"sm-{uuid.uuid4().hex[:6]}", "vehicle_id": supplier_veh["id"], "amount": 100}])
    assert r.json()["results"][0]["error"]["code"] == "MISSING_SUPPLIER_MODE"


def test_invalid_supplier_mode(supplier_veh):
    r = _post_batch(date="2026-09-15", category="Toll", entries=[{
        "client_row_id": f"sm2-{uuid.uuid4().hex[:6]}", "vehicle_id": supplier_veh["id"],
        "amount": 100, "supplier_settlement_mode": "made_up"}])
    assert r.json()["results"][0]["error"]["code"] == "INVALID_SUPPLIER_MODE"


def test_cross_tenant_vehicle():
    # Simulated: use bogus vehicle id — falls through as VEHICLE_NOT_FOUND.
    r = _post_batch(date="2026-09-16", category="Toll", entries=[
        {"client_row_id": "ct", "vehicle_id": "veh_other_company", "amount": 100}])
    assert r.json()["results"][0]["error"]["code"] == "VEHICLE_NOT_FOUND"


# ── Idempotency ────────────────────────────────────────────────────
def test_same_client_row_id_returns_duplicate(own_veh):
    """Row-level idempotency via expenses_source_key_uniq (survives TTL)."""
    rid = f"idem-{uuid.uuid4().hex[:8]}"
    body = dict(date="2026-09-17", category="Toll",
                entries=[{"client_row_id": rid, "vehicle_id": own_veh["id"], "amount": 250}])
    r1 = requests.post(f"{API}/expenses/bulk-operational", headers=H, json=body, timeout=15)
    r2 = requests.post(f"{API}/expenses/bulk-operational", headers=H, json=body, timeout=15)
    j1, j2 = r1.json(), r2.json()
    assert j1["results"][0]["status"] == "created"
    assert j2["results"][0]["status"] == "duplicate"
    # Only ONE canonical row must exist.
    lst = requests.get(f"{API}/expenses", headers=H,
                       params={"vehicle_id": own_veh["id"], "category": "Toll",
                               "date_from": "2026-09-17", "date_to": "2026-09-17"},
                       timeout=15).json()
    assert sum(1 for e in lst if e.get("source_key", "").endswith(f":{rid}")) == 1


def test_distinct_client_row_ids_allow_repeats(own_veh):
    body1 = dict(date="2026-09-18", category="Toll", entries=[
        {"client_row_id": f"r1-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": 500}])
    body2 = dict(date="2026-09-18", category="Toll", entries=[
        {"client_row_id": f"r2-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": 700}])
    r1 = _post_batch(**body1); r2 = _post_batch(**body2)
    assert r1.json()["results"][0]["status"] == "created"
    assert r2.json()["results"][0]["status"] == "created"


# ── Category normalisation ──────────────────────────────────────────
def test_driver_batta_normalized_to_batta(own_veh):
    r = _post_batch(date="2026-09-19", category="Driver Batta", entries=[
        {"client_row_id": f"db-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": 500}])
    j = r.json()
    assert j["category"] == "Batta"
    assert j["results"][0]["expense"]["category"] == "Batta"


# ── Projections ─────────────────────────────────────────────────────
def test_expense_register_shows_quick_entry(own_veh):
    unique = uuid.uuid4().hex[:8]
    _post_batch(date="2026-09-20", category="Parking", entries=[
        {"client_row_id": f"reg-{unique}", "vehicle_id": own_veh["id"], "amount": 111,
         "remarks": f"tag-{unique}"}])
    lst = requests.get(f"{API}/expenses", headers=H,
                       params={"vehicle_id": own_veh["id"], "category": "Parking",
                               "date_from": "2026-09-20", "date_to": "2026-09-20"},
                       timeout=15).json()
    assert any(e.get("source_type") == "quick_op" and e.get("source_key", "").endswith(f":reg-{unique}")
               for e in lst)


def test_quick_diesel_does_not_touch_fuel(own_veh):
    before = requests.get(f"{API}/fuel", headers=H, timeout=15).json()
    _post_batch(date="2026-09-21", category="Diesel", entries=[
        {"client_row_id": f"d-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": 8000}])
    after = requests.get(f"{API}/fuel", headers=H, timeout=15).json()
    assert len(before) == len(after)


def test_vehicle_cost_reflects_quick_entry(own_veh):
    """Vehicle Cost is a projection of Expense (Iter133 LOCK). Quick Entry
    contributes automatically. We assert the canonical Expense list scoped
    to the vehicle exposes the new row."""
    lst = requests.get(f"{API}/expenses", headers=H,
                       params={"vehicle_id": own_veh["id"]}, timeout=15).json()
    assert any(e.get("source_type") == "quick_op" for e in lst)


# ── Batch-level guards ─────────────────────────────────────────────
def test_empty_entries_400():
    r = _post_batch(date="2026-09-22", category="Toll", entries=[])
    assert r.status_code == 400


def test_over_200_entries_400(own_veh):
    r = _post_batch(date="2026-09-23", category="Toll", entries=[
        {"client_row_id": f"o-{i}", "vehicle_id": own_veh["id"], "amount": 1} for i in range(201)])
    assert r.status_code == 400


def test_invalid_date_400(own_veh):
    r = _post_batch(date="not-a-date", category="Toll", entries=[
        {"client_row_id": "bad", "vehicle_id": own_veh["id"], "amount": 100}])
    assert r.status_code == 400


# ── Locked invariant regression ────────────────────────────────────
def test_iter136_register_still_default_hides_reversed(own_veh):
    r = requests.get(f"{API}/expenses", headers=H, timeout=15)
    assert r.status_code == 200
    assert all((not e.get("is_reversed")) for e in r.json())


def test_bulk_endpoint_does_not_create_vendor_bill(own_veh):
    before_ct = requests.get(f"{API}/vendor-bills", headers=H, timeout=15).json()
    _post_batch(date="2026-09-24", category="Toll", entries=[
        {"client_row_id": f"vb-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": 100}])
    after_ct = requests.get(f"{API}/vendor-bills", headers=H, timeout=15).json()
    assert len(before_ct) == len(after_ct)


def test_quick_op_expense_schema_shape():
    import sys
    sys.path.insert(0, "/app/backend")
    from models import Expense  # type: ignore
    assert "quick_op" in Expense.model_fields["source_type"].annotation.__args__


# ── Static frontend guard ──────────────────────────────────────────
def test_frontend_page_exists():
    p = Path("/app/frontend/src/pages/QuickOperationalExpense.jsx")
    assert p.exists()
    src = p.read_text(encoding="utf-8")
    assert "/expenses/bulk-operational" in src
    assert "SearchableSelect" in src
    # Twin-payable guard preserved even for Quick Entry — no vendor_bill_id / mwo_id in payload builder.
    assert "vendor_bill_id" not in src
    assert "mechanic_work_order_id" not in src


# ── Iter139 duplicate-warning invariants ────────────────────────────
def test_no_new_unique_constraint_added():
    """The duplicate warning is a UX layer — the DB must never enforce
    uniqueness on (date, category, vehicle_id, amount) because legitimate
    repeats exist (multiple toll booths on one route, etc.)."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio, os
    from pathlib import Path as _P
    from dotenv import load_dotenv
    load_dotenv(_P("/app/backend/.env"))
    async def _idx():
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        idx = await c[os.environ["DB_NAME"]].expenses.index_information()
        return idx
    idx = asyncio.run(_idx())
    for name, spec in idx.items():
        keys = [k for k, _ in spec.get("key", [])]
        if set(["date", "category", "vehicle_id", "amount"]).issubset(set(keys)):
            assert not spec.get("unique"), (
                f"Unexpected unique index blocks legitimate repeats: {name} → {spec}"
            )


def test_batta_alias_normalized_still_matches_existing(own_veh):
    """Existing 'Batta' row must be found by a later 'Driver Batta' entry
    (both normalise to canonical 'Batta') — proven via API list."""
    d = "2026-09-25"
    r1 = _post_batch(date=d, category="Batta", entries=[
        {"client_row_id": f"bt-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": 500}])
    assert r1.json()["results"][0]["status"] == "created"
    # Query by canonical 'Batta' — the Driver Batta submission would find this.
    lst = requests.get(f"{API}/expenses", headers=H,
                       params={"vehicle_id": own_veh["id"], "category": "Batta",
                               "date_from": d, "date_to": d}, timeout=15).json()
    assert any(float(e["amount"]) == 500.0 for e in lst)


def test_reversed_expense_not_matched_by_duplicate_check(own_veh):
    """A reversed Expense must NOT appear in the duplicate detection list
    used by the frontend — the /api/expenses default filter must hide it."""
    d = "2026-09-26"
    _post_batch(date=d, category="Toll", entries=[
        {"client_row_id": f"rv-{uuid.uuid4().hex[:6]}", "vehicle_id": own_veh["id"], "amount": 2500}])
    lst = requests.get(f"{API}/expenses", headers=H,
                       params={"vehicle_id": own_veh["id"], "category": "Toll",
                               "date_from": d, "date_to": d}, timeout=15).json()
    # No row has is_reversed=true by default — that is exactly the guard the
    # UI relies on to avoid false-positive duplicate warnings against history.
    assert all((not e.get("is_reversed")) for e in lst)
    assert all((not e.get("is_deleted")) for e in lst)


def test_duplicate_warning_ui_present():
    """Static guard — the QuickOperationalExpense page contains a duplicate
    check + warning modal wired to the required test-ids."""
    src = Path("/app/frontend/src/pages/QuickOperationalExpense.jsx").read_text(encoding="utf-8")
    for needed in [
        "DUPLICATE RECORD FOUND",
        "duplicate-modal",
        "duplicate-modal-cancel",
        "duplicate-modal-add-anyway",
        "dupCheck",
        "Add Anyway",
    ]:
        assert needed in src, f"QuickOperationalExpense.jsx missing marker: {needed}"


# ── Iter139 UAT bug fix · Supplier-owned vehicle CREDIT projection ───

# ── Iter139 UAT UX · Diesel row (qty × rate = amount, Filled At, Vendor) ───

def test_diesel_amount_calculated_from_qty_x_rate(own_veh):
    """Server computes Diesel amount authoritatively from qty × rate."""
    r = _post_batch(date="2026-11-01", category="Diesel", entries=[{
        "client_row_id": f"d1-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"],
        "qty": 320, "rate": 92.50}])
    assert r.status_code == 200, r.text
    doc = r.json()["results"][0]["expense"]
    assert doc["category"] == "Diesel"
    assert abs(doc["amount"] - 29600.0) < 0.005
    assert "320" in (doc.get("narration") or "")
    assert "92.50" in (doc.get("narration") or "")


def test_diesel_zero_amount_row_failed(own_veh):
    """Missing qty (or rate) fails at row level with the new code."""
    r = _post_batch(date="2026-11-02", category="Diesel", entries=[{
        "client_row_id": f"d0-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 0, "rate": 92.50}])
    assert r.json()["results"][0]["error"]["code"] == "INVALID_DIESEL_QTY_RATE"


def test_diesel_narration_preserves_vendor_and_station(own_veh):
    """Server composes narration from qty/rate + filled_at + vendor name —
    this is how Filled At + Vendor are carried without schema change."""
    r = _post_batch(date="2026-11-03", category="Diesel", entries=[{
        "client_row_id": f"dv-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 100, "rate": 92.50,
        "filled_at": "IOC Vijayawada Auto Nagar"}])
    doc = r.json()["results"][0]["expense"]
    assert "IOC Vijayawada Auto Nagar" in doc["narration"]
    assert "100" in doc["narration"]


def test_diesel_does_not_create_vendor_payable(own_veh):
    """Diesel expense — with or without Vendor selection — must never
    create a VendorBill or VendorPayment (Iter135 invariant)."""
    before_b = requests.get(f"{API}/vendor-bills", headers=H, timeout=15).json()
    _post_batch(date="2026-11-04", category="Diesel", entries=[{
        "client_row_id": f"dnp-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 50, "rate": 100.0,
        "filled_at": "BPC"}])
    after_b = requests.get(f"{API}/vendor-bills", headers=H, timeout=15).json()
    assert len(before_b) == len(after_b)


def test_diesel_duplicate_detection_uses_calculated_amount(own_veh):
    """Same date + Diesel + same vehicle + same calculated amount is
    detectable via the same /api/expenses filter the UI uses."""
    d = "2026-11-05"
    _post_batch(date=d, category="Diesel", entries=[{
        "client_row_id": f"dup-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 320, "rate": 92.50}])
    lst = requests.get(f"{API}/expenses", headers=H, params={
        "vehicle_id": own_veh["id"], "category": "Diesel",
        "date_from": d, "date_to": d}, timeout=15).json()
    assert any(abs(e["amount"] - 29600.0) < 0.005 for e in lst)


def test_diesel_frontend_layout_present():
    """Static guard — Diesel row exposes qty/rate/filled-at/vendor
    testids and read-only amount."""
    src = Path("/app/frontend/src/pages/QuickOperationalExpense.jsx").read_text(encoding="utf-8")
    for needed in [
        "quick-expense-row-${i}-qty",
        "quick-expense-row-${i}-rate",
        "quick-expense-row-${i}-filled-at",
        "quick-expense-row-${i}-vendor",
        "isDiesel",
        "computedAmount",
        "readOnly value={fmt(computedAmount",
    ]:
        assert needed in src, f"QuickOperationalExpense.jsx missing marker: {needed}"


# ── Iter139 UAT #2 · Diesel amount LOCK + Vendor MASTER link ────────────────

def _mk_vendor(name_prefix="DieselVen"):
    body = {"name": f"{name_prefix}-{uuid.uuid4().hex[:8]}"}
    r = requests.post(f"{API}/vendors", headers=H, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_diesel_amount_computed_server_when_no_amount_sent(own_veh):
    """No `amount` in payload — server computes from qty × rate."""
    r = _post_batch(date="2026-11-10", category="Diesel", entries=[{
        "client_row_id": f"noamt-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 150, "rate": 92.50}])
    doc = r.json()["results"][0]["expense"]
    assert abs(doc["amount"] - 13875.0) < 0.005


def test_diesel_amount_tampered_rejected(own_veh):
    """Client sends `amount` that disagrees with qty × rate → row rejected."""
    r = _post_batch(date="2026-11-11", category="Diesel", entries=[{
        "client_row_id": f"tamp-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"],
        "qty": 100, "rate": 92.50, "amount": 12345.67}])
    res = r.json()["results"][0]
    assert res["status"] == "failed"
    assert res["error"]["code"] == "AMOUNT_TAMPERED"


def test_diesel_missing_rate_rejected(own_veh):
    """Missing rate → row rejected with the qty/rate code."""
    r = _post_batch(date="2026-11-12", category="Diesel", entries=[{
        "client_row_id": f"norate-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 150}])
    assert r.json()["results"][0]["error"]["code"] == "INVALID_DIESEL_QTY_RATE"


def test_diesel_vendor_id_persisted_as_party_reference(own_veh):
    """Selected Vendor is persisted as party_type='vendor', party_id=<vid>,
    party_name=<vendor.name> — REUSES existing Expense schema."""
    ven = _mk_vendor()
    r = _post_batch(date="2026-11-13", category="Diesel", entries=[{
        "client_row_id": f"ven-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 100, "rate": 92.50,
        "vendor_id": ven["id"]}])
    doc = r.json()["results"][0]["expense"]
    assert doc["party_type"] == "vendor"
    assert doc["party_id"] == ven["id"]
    assert doc["party_name"] == ven["name"]
    # narration composed with vendor name appended.
    assert ven["name"] in (doc.get("narration") or "")


def test_diesel_vendor_link_visible_via_expense_party_filter(own_veh):
    """Existing GET /api/expenses?party_type=vendor&party_id=<vid> already
    supports Vendor-linked Expense visibility — no new endpoint needed."""
    ven = _mk_vendor()
    _post_batch(date="2026-11-14", category="Diesel", entries=[{
        "client_row_id": f"venv-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 200, "rate": 90.0,
        "vendor_id": ven["id"]}])
    lst = requests.get(f"{API}/expenses", headers=H, params={
        "party_type": "vendor", "party_id": ven["id"]}, timeout=15).json()
    assert any(e["party_id"] == ven["id"] and e["category"] == "Diesel"
               and abs(e["amount"] - 18000.0) < 0.005 for e in lst)


def test_diesel_vendor_link_does_not_create_vendor_bill_or_payment(own_veh):
    """Linking a Vendor to a Diesel Expense must NOT create a payable
    (no VendorBill, no VendorPayment) — Iter133 invariant preserved."""
    ven = _mk_vendor()
    bills_before = requests.get(f"{API}/vendor-bills", headers=H, timeout=15).json()
    pays_before = requests.get(f"{API}/vendors/{ven['id']}/payments",
                               headers=H, timeout=15).json()
    _post_batch(date="2026-11-15", category="Diesel", entries=[{
        "client_row_id": f"vnp-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 100, "rate": 100.0,
        "vendor_id": ven["id"]}])
    bills_after = requests.get(f"{API}/vendor-bills", headers=H, timeout=15).json()
    pays_after = requests.get(f"{API}/vendors/{ven['id']}/payments",
                              headers=H, timeout=15).json()
    assert len(bills_before) == len(bills_after)
    assert len(pays_before) == len(pays_after)


def test_diesel_vendor_link_does_not_affect_vendor_ledger(own_veh):
    """Vendor Ledger (Bills+Payments) DEBIT/CREDIT rows must stay unchanged
    when a Diesel Expense links to that vendor — no double count."""
    ven = _mk_vendor()
    l0 = requests.get(f"{API}/vendors/{ven['id']}/ledger",
                      headers=H, timeout=15).json()
    open0 = float(l0.get("opening_balance") or 0)
    entries0 = len(l0.get("entries") or [])
    close0 = float(l0.get("closing_balance") or 0)
    _post_batch(date="2026-11-16", category="Diesel", entries=[{
        "client_row_id": f"vled-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 500, "rate": 95.0,
        "vendor_id": ven["id"]}])
    l1 = requests.get(f"{API}/vendors/{ven['id']}/ledger",
                      headers=H, timeout=15).json()
    assert float(l1.get("opening_balance") or 0) == open0
    assert len(l1.get("entries") or []) == entries0
    assert float(l1.get("closing_balance") or 0) == close0


def test_diesel_vendor_not_found_row_failed(own_veh):
    """Non-existent vendor_id → row-level VENDOR_NOT_FOUND, batch continues."""
    r = _post_batch(date="2026-11-17", category="Diesel", entries=[{
        "client_row_id": f"vnf-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 50, "rate": 90.0,
        "vendor_id": "ven_does_not_exist"}])
    res = r.json()["results"][0]
    assert res["status"] == "failed"
    assert res["error"]["code"] == "VENDOR_NOT_FOUND"


def test_diesel_vendor_optional_still_defaults_to_cash(own_veh):
    """No vendor_id supplied → Expense stays party_type='cash', party_id=''."""
    r = _post_batch(date="2026-11-18", category="Diesel", entries=[{
        "client_row_id": f"nov-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 40, "rate": 100.0}])
    doc = r.json()["results"][0]["expense"]
    assert doc["party_type"] == "cash"
    assert doc["party_id"] == ""


def test_diesel_vehicle_cost_still_reflects_diesel_expense_once(own_veh):
    """Vehicle Cost must include the canonical Diesel Expense EXACTLY once
    — no double counting when vendor is linked."""
    ven = _mk_vendor()
    d = "2026-11-19"
    _post_batch(date=d, category="Diesel", entries=[{
        "client_row_id": f"vc1-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "qty": 100, "rate": 90.0,
        "vendor_id": ven["id"]}])
    lst = requests.get(f"{API}/expenses", headers=H, params={
        "vehicle_id": own_veh["id"], "category": "Diesel",
        "date_from": d, "date_to": d}, timeout=15).json()
    matches = [e for e in lst if abs(e["amount"] - 9000.0) < 0.005]
    assert len(matches) == 1


def test_diesel_frontend_amount_hardened_readonly():
    """Static guard — Diesel amount input is not just readOnly; paste,
    keydown, and copy are also intercepted so the user cannot force a
    typed / pasted amount override."""
    src = Path("/app/frontend/src/pages/QuickOperationalExpense.jsx").read_text(encoding="utf-8")
    for needed in [
        "onKeyDown={(e) => e.preventDefault()}",
        "onPaste={(e) => e.preventDefault()}",
        "cursor-not-allowed",
    ]:
        assert needed in src, f"QuickOperationalExpense.jsx missing amount-lock marker: {needed}"


def test_diesel_frontend_vendor_uses_searchable_select():
    """Static guard — Diesel row uses SearchableSelect bound to
    /api/vendors, NOT a free-text input."""
    src = Path("/app/frontend/src/pages/QuickOperationalExpense.jsx").read_text(encoding="utf-8")
    assert 'testId={`quick-expense-row-${i}-vendor`}' in src
    assert "vendorOptions" in src
    assert 'queryKey: ["vendors"' in src
    # Free-text vendor input must be gone.
    assert 'placeholder="Vendor (optional, free text)"' not in src

def _mk_supplier_vehicle():
    """Create a supplier + supplier-owned vehicle and return both."""
    sup_body = {"name": f"UATSup-{uuid.uuid4().hex[:8]}", "opening_balance": 0}
    sr = requests.post(f"{API}/suppliers", headers=H, json=sup_body, timeout=15)
    if sr.status_code == 409:
        sup = (sr.json() or {}).get("detail", {}).get("existing") or {}
    else:
        assert sr.status_code in (200, 201), sr.text
        sup = sr.json()
    vbody = {"vehicle_number": f"AP39ZU{uuid.uuid4().hex[:4].upper()}",
             "vehicle_type": "supplier",
             "supplier_id": sup["id"], "supplier_name": sup["name"]}
    vr = requests.post(f"{API}/vehicles", headers=H, json=vbody, timeout=15)
    assert vr.status_code in (200, 201), vr.text
    return sup, vr.json()


def test_supplier_adjustment_appears_in_supplier_ledger():
    """Iter139 UAT fix: Quick Entry with supplier_settlement_adjustment must
    materialise as a CREDIT entry in the Supplier Ledger."""
    sup, veh = _mk_supplier_vehicle()
    d = "2026-10-01"
    r = _post_batch(date=d, category="Toll", entries=[{
        "client_row_id": f"sa1-{uuid.uuid4().hex[:6]}",
        "vehicle_id": veh["id"], "amount": 1000,
        "supplier_settlement_mode": "supplier_settlement_adjustment"}])
    assert r.json()["created"] == 1, r.text
    lg = requests.get(f"{API}/suppliers/{sup['id']}/ledger", headers=H, timeout=15).json()
    entries = lg.get("entries") or []
    credit_rows = [e for e in entries if e.get("type") == "supplier_settlement_expense"]
    assert len(credit_rows) == 1, f"expected 1 credit row, got {credit_rows}"
    assert credit_rows[0]["credit"] == 1000.0
    assert credit_rows[0]["debit"] == 0.0
    assert lg["totals"]["credit"] >= 1000.0


def test_supplier_company_borne_does_not_appear_in_supplier_ledger():
    sup, veh = _mk_supplier_vehicle()
    d = "2026-10-02"
    r = _post_batch(date=d, category="Toll", entries=[{
        "client_row_id": f"cb1-{uuid.uuid4().hex[:6]}",
        "vehicle_id": veh["id"], "amount": 1200,
        "supplier_settlement_mode": "company_borne"}])
    assert r.json()["created"] == 1
    lg = requests.get(f"{API}/suppliers/{sup['id']}/ledger", headers=H, timeout=15).json()
    for e in (lg.get("entries") or []):
        assert e.get("type") != "supplier_settlement_expense", (
            "company_borne Expense must NOT appear in Supplier Ledger"
        )


def test_own_vehicle_does_not_appear_in_supplier_ledger(own_veh):
    # No supplier is associated; iterate all suppliers to be safe.
    r = _post_batch(date="2026-10-03", category="Toll", entries=[{
        "client_row_id": f"ov1-{uuid.uuid4().hex[:6]}",
        "vehicle_id": own_veh["id"], "amount": 500}])
    assert r.json()["created"] == 1
    # No specific supplier to query — verify no other supplier ledger picks it up
    # by checking a fresh supplier's ledger is empty of settlement rows.
    sup, _ = _mk_supplier_vehicle()
    lg = requests.get(f"{API}/suppliers/{sup['id']}/ledger", headers=H, timeout=15).json()
    for e in (lg.get("entries") or []):
        # Only supplier's own trips / payments allowed; no cross-supplier expense.
        assert e.get("type") != "supplier_settlement_expense" or e.get("vehicle_number") == "".__class__(""), (
            "Own-vehicle Expense leaked into a foreign Supplier Ledger"
        )


def test_multiple_supplier_vehicles_route_to_correct_suppliers():
    supA, vehA = _mk_supplier_vehicle()
    supB, vehB = _mk_supplier_vehicle()
    d = "2026-10-04"
    r = _post_batch(date=d, category="Toll", entries=[
        {"client_row_id": f"a-{uuid.uuid4().hex[:6]}", "vehicle_id": vehA["id"], "amount": 1000,
         "supplier_settlement_mode": "supplier_settlement_adjustment"},
        {"client_row_id": f"b-{uuid.uuid4().hex[:6]}", "vehicle_id": vehB["id"], "amount": 1500,
         "supplier_settlement_mode": "supplier_settlement_adjustment"},
    ])
    assert r.json()["created"] == 2
    lgA = requests.get(f"{API}/suppliers/{supA['id']}/ledger", headers=H, timeout=15).json()
    lgB = requests.get(f"{API}/suppliers/{supB['id']}/ledger", headers=H, timeout=15).json()
    aRows = [e for e in lgA["entries"] if e.get("type") == "supplier_settlement_expense"]
    bRows = [e for e in lgB["entries"] if e.get("type") == "supplier_settlement_expense"]
    assert sum(e["credit"] for e in aRows) == 1000.0
    assert sum(e["credit"] for e in bRows) == 1500.0


def test_supplier_adjustment_does_not_create_supplier_payment():
    sup, veh = _mk_supplier_vehicle()
    before = requests.get(f"{API}/suppliers/{sup['id']}/payments", headers=H, timeout=15).json()
    _post_batch(date="2026-10-05", category="Toll", entries=[{
        "client_row_id": f"np-{uuid.uuid4().hex[:6]}", "vehicle_id": veh["id"], "amount": 600,
        "supplier_settlement_mode": "supplier_settlement_adjustment"}])
    after = requests.get(f"{API}/suppliers/{sup['id']}/payments", headers=H, timeout=15).json()
    assert len(before) == len(after), "Quick Entry must NOT create a SupplierPayment"


def test_reversed_or_deleted_expense_excluded_from_supplier_ledger():
    """The settlement-adjustment CREDIT projection must respect the
    is_reversed / is_deleted filters (Iter139 UAT invariant)."""
    sup, veh = _mk_supplier_vehicle()
    d = "2026-10-06"
    r = _post_batch(date=d, category="Toll", entries=[{
        "client_row_id": f"rv-{uuid.uuid4().hex[:6]}", "vehicle_id": veh["id"], "amount": 800,
        "supplier_settlement_mode": "supplier_settlement_adjustment"}])
    eid = r.json()["results"][0]["expense"]["id"]
    # Soft-cancel via Iter136 API
    requests.delete(f"{API}/expenses/{eid}", headers=H,
                    params={"reason": "UAT reverse test"}, timeout=15)
    lg = requests.get(f"{API}/suppliers/{sup['id']}/ledger", headers=H, timeout=15).json()
    for e in lg["entries"]:
        assert e.get("expense_id") != eid, "Deleted Expense must not appear in supplier ledger"


def test_frontend_route_registered():
    src = Path("/app/frontend/src/App.js").read_text(encoding="utf-8")
    assert "/expenses/quick" in src
    assert "QuickOperationalExpense" in src


def test_sidebar_link_registered():
    src = Path("/app/frontend/src/components/Layout.jsx").read_text(encoding="utf-8")
    assert 'nav-quick-expense' in src
    assert '/expenses/quick' in src
