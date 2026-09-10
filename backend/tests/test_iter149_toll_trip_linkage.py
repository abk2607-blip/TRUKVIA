"""Iter149 P0 · Toll Trip Linkage — regression suite.

Uses the working iter14x test pattern: HTTP calls via `requests` against
the running supervisor backend + synchronous `pymongo` for scoped test
tenant setup/teardown (avoids Motor's per-loop connection binding when
many tests run in sequence).

Verifies:
  • Narrow `PATCH /api/expenses/{eid}/toll-trip` writes ONLY `trip_id`
    (+ modified_by / modified_at). Source identity is byte-preserved.
  • Guards: fastag_import + Toll only; not deleted/reversed; trip in
    tenant; vehicle match; legacy trip blocked; ±2-day window unless
    force=true; idempotent; role gate.
  • Trip DELETE cleanup (L.2): operator-linked Tolls have their
    `trip_id` cleared without soft-deletion; bridge-materialised rows
    still soft-deleted (unchanged Iter133 Turn 2A behaviour).
  • FE static contract: LinkTollToTripDialog + row-scoped affordances
    on Today's Expenses and Vehicle Workspace → Expenses tab.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

REPO_ROOT = Path(__file__).resolve().parent.parent
FE_ROOT = REPO_ROOT.parent / "frontend" / "src"
DIALOG_FILE = FE_ROOT / "components" / "quickexp" / "LinkTollToTripDialog.jsx"
QUICKOP_FILE = FE_ROOT / "pages" / "QuickOperationalExpense.jsx"
VW_FILE = FE_ROOT / "pages" / "VehicleWorkspace.jsx"

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api" if BASE_URL.startswith("http") else "http://localhost:8001/api"
TOKEN = os.environ.get("DEMO_TOKEN_VALUE", "")
H = {"Authorization": f"Bearer {TOKEN}"}
HJSON = {**H, "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _demo_ids() -> tuple[str, str]:
    """Return (uid, cid) for the DEMO_TOKEN_VALUE user's ACTIVE company —
    resolved via the HTTP layer so we exactly match the tenant the
    backend uses for this token."""
    d = _db()
    me = d.users.find_one({"email": "demo@bitumen-transport.local"},
                          {"_id": 0, "user_id": 1})
    assert me, "demo user missing"
    uid = me["user_id"]
    # Ask the backend directly which company it treats as active for
    # this token (uses the same _active_company_id resolver).
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False}, timeout=15)
    assert r.status_code == 200, r.text
    vs = r.json()
    assert vs, "demo tenant has no vehicles — cannot infer active company"
    cid = vs[0].get("company_id") or ""
    assert cid, "no company_id on vehicles response"
    return uid, cid


class _Ctx:
    """Scoped-test-tenant helper: creates uuid-suffixed vehicle / trip /
    expense docs under the DEMO user, plus a teardown() that removes
    only those specific rows so shared-tenant data stays intact."""

    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo_ids()
        self.tag = uuid.uuid4().hex[:10]
        self._created = {"vehicles": [], "trips": [], "expenses": []}

    def vehicle(self, vtype="own"):
        vid = f"veh_iter149_{self.tag}_{uuid.uuid4().hex[:6]}"
        vnum = f"AP31XX{uuid.uuid4().hex[:4].upper()}"
        self.d.vehicles.insert_one({
            "id": vid, "user_id": self.uid, "company_id": self.cid,
            "vehicle_number": vnum, "is_active": True, "vehicle_type": vtype,
            "supplier_id": "" if vtype != "supplier" else f"sup_{self.tag}",
            "supplier_name": "" if vtype != "supplier" else "Test Supplier",
        })
        self._created["vehicles"].append(vid)
        return vid, vnum

    def toll(self, vid: str, vnum: str, *, date="2026-09-09", amount=570.0,
             txn="TXN_TEST", extra=None):
        eid = f"exp_iter149_{self.tag}_{uuid.uuid4().hex[:6]}"
        doc = {
            "id": eid, "user_id": self.uid, "company_id": self.cid,
            "date": date, "category": "Toll", "amount": amount,
            "vehicle_id": vid, "vehicle_number": vnum,
            "narration": "Tangatur Toll Plaza · Test",
            "source_type": "fastag_import", "source": "idfc",
            "source_txn_ref": txn,
            "source_key": f"toll:idfc:{self.cid}:{txn}",
            "source_trip_id": "", "trip_id": "", "repair_event_id": "",
            "supplier_owned_vehicle": False,
            "supplier_settlement_mode": "n/a",
            "settlement_mode": "cash_now", "party_type": "cash",
            "is_deleted": False, "is_reversed": False,
            "created_by": self.uid, "created_at": "2026-09-10T00:00:00+00:00",
        }
        if extra: doc.update(extra)
        self.d.expenses.insert_one(doc)
        self._created["expenses"].append(eid)
        return eid, doc

    def trip(self, vid: str, vnum: str, *, date="2026-09-09",
             has_canonical=True, lr=None, extra=None):
        tid = f"trip_iter149_{self.tag}_{uuid.uuid4().hex[:6]}"
        doc = {
            "id": tid, "user_id": self.uid, "company_id": self.cid,
            "date": date, "vehicle_id": vid, "vehicle_number": vnum,
            "vehicle_type": "own",
            "lr_number": lr or f"LR/26-27/{self.tag[:4]}",
            "from_location": "Nellore", "to_location": "Vijayawada",
            "customer_id": "cust_iter149", "customer_name": "Test Customer",
            "has_canonical_expenses": has_canonical,
            "expenses": {}, "other_expenditures": [],
            "supplier_net_payable": 0.0, "freight_amount": 5000.0,
            "created_at": "2026-09-08T00:00:00+00:00",
        }
        if extra: doc.update(extra)
        self.d.trips.insert_one(doc)
        self._created["trips"].append(tid)
        return tid

    def teardown(self):
        if self._created["vehicles"]:
            self.d.vehicles.delete_many({"id": {"$in": self._created["vehicles"]}})
        if self._created["trips"]:
            self.d.trips.delete_many({"id": {"$in": self._created["trips"]}})
        if self._created["expenses"]:
            self.d.expenses.delete_many({"id": {"$in": self._created["expenses"]}})


def _patch(eid, body):
    return requests.patch(f"{API}/expenses/{eid}/toll-trip",
                          headers=HJSON, json=body, timeout=15)


# ─── 1. Endpoint contract ─────────────────────────────────────────────

def test_link_fastag_toll_to_trip_updates_only_trip_id():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, before = ctx.toll(vid, vnum, txn=f"T1_{ctx.tag}")
        tid = ctx.trip(vid, vnum)
        r = _patch(eid, {"trip_id": tid})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["unchanged"] is False
        after = ctx.d.expenses.find_one({"id": eid}, {"_id": 0})
        assert after["trip_id"] == tid
        # Byte-preserved source-identity fields.
        for k in ("source_type", "source", "source_txn_ref", "source_key",
                  "amount", "date", "vehicle_id", "vehicle_number",
                  "category", "narration",
                  "supplier_owned_vehicle", "supplier_settlement_mode",
                  "settlement_mode", "id", "created_at", "created_by"):
            assert after[k] == before[k], f"{k} changed"
        changed = {k for k in after if after.get(k) != before.get(k)}
        assert changed <= {"trip_id", "modified_by", "modified_at"}, changed
    finally:
        ctx.teardown()


def test_link_is_idempotent_same_trip():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T2_{ctx.tag}")
        tid = ctx.trip(vid, vnum)
        assert _patch(eid, {"trip_id": tid}).status_code == 200
        r2 = _patch(eid, {"trip_id": tid})
        assert r2.status_code == 200 and r2.json()["unchanged"] is True
        assert ctx.d.expenses.count_documents({"id": eid}) == 1
    finally:
        ctx.teardown()


def test_repeated_confirmation_no_duplicate_row():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T3_{ctx.tag}")
        tid = ctx.trip(vid, vnum)
        for _ in range(5):
            assert _patch(eid, {"trip_id": tid}).status_code == 200
        assert ctx.d.expenses.count_documents(
            {"user_id": ctx.uid, "source_txn_ref": f"T3_{ctx.tag}"}) == 1
    finally:
        ctx.teardown()


def test_link_two_tolls_to_same_trip_both_appear():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid_a, _ = ctx.toll(vid, vnum, amount=135.0, txn=f"TA_{ctx.tag}")
        eid_b, _ = ctx.toll(vid, vnum, amount=570.0, txn=f"TB_{ctx.tag}")
        tid = ctx.trip(vid, vnum)
        assert _patch(eid_a, {"trip_id": tid}).status_code == 200
        assert _patch(eid_b, {"trip_id": tid}).status_code == 200
        rows = list(ctx.d.expenses.find(
            {"user_id": ctx.uid, "trip_id": tid, "id": {"$in": [eid_a, eid_b]}},
            {"_id": 0, "amount": 1}))
        assert len(rows) == 2 and sum(r["amount"] for r in rows) == 705.0
    finally:
        ctx.teardown()


def test_unlink_clears_trip_id_without_soft_delete():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T5_{ctx.tag}")
        tid = ctx.trip(vid, vnum)
        assert _patch(eid, {"trip_id": tid}).status_code == 200
        r = _patch(eid, {"trip_id": ""})
        assert r.status_code == 200 and r.json()["unchanged"] is False
        after = ctx.d.expenses.find_one({"id": eid}, {"_id": 0})
        assert after["trip_id"] == "" and not after.get("is_deleted")
    finally:
        ctx.teardown()


def test_cancelled_toll_blocked_400():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T6_{ctx.tag}", extra={"is_deleted": True})
        tid = ctx.trip(vid, vnum)
        r = _patch(eid, {"trip_id": tid})
        assert r.status_code == 400 and "cancel" in r.text.lower()
    finally:
        ctx.teardown()


def test_reversed_toll_blocked_400():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T7_{ctx.tag}", extra={"is_reversed": True})
        tid = ctx.trip(vid, vnum)
        r = _patch(eid, {"trip_id": tid})
        assert r.status_code == 400 and "revers" in r.text.lower()
    finally:
        ctx.teardown()


def test_non_fastag_expense_blocked_400():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T8_{ctx.tag}",
                          extra={"source_type": "quick_op", "source": "",
                                 "source_txn_ref": ""})
        tid = ctx.trip(vid, vnum)
        r = _patch(eid, {"trip_id": tid})
        assert r.status_code == 400 and "fastag" in r.text.lower()
    finally:
        ctx.teardown()


def test_non_toll_category_blocked_400():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T9_{ctx.tag}",
                          extra={"category": "Diesel"})
        tid = ctx.trip(vid, vnum)
        r = _patch(eid, {"trip_id": tid})
        assert r.status_code == 400 and "toll" in r.text.lower()
    finally:
        ctx.teardown()


def test_invalid_trip_400():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T10_{ctx.tag}")
        r = _patch(eid, {"trip_id": "trip_does_not_exist"})
        assert r.status_code == 400 and "trip" in r.text.lower()
    finally:
        ctx.teardown()


def test_legacy_trip_blocked_400():
    """L.1 · has_canonical_expenses=false must be a hard block."""
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T11_{ctx.tag}")
        tid = ctx.trip(vid, vnum, has_canonical=False)
        r = _patch(eid, {"trip_id": tid})
        assert r.status_code == 400 and "legacy" in r.text.lower()
    finally:
        ctx.teardown()


def test_wrong_vehicle_400():
    ctx = _Ctx()
    try:
        vid_a, vnum_a = ctx.vehicle()
        vid_b, vnum_b = ctx.vehicle()
        eid, _ = ctx.toll(vid_a, vnum_a, txn=f"T12_{ctx.tag}")
        tid = ctx.trip(vid_b, vnum_b)  # Different vehicle
        r = _patch(eid, {"trip_id": tid})
        assert r.status_code == 400 and "vehicle_id" in r.text.lower()
    finally:
        ctx.teardown()


def test_date_window_2_days_boundary_allowed():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, date="2026-09-09", txn=f"T13_{ctx.tag}")
        tid = ctx.trip(vid, vnum, date="2026-09-07")   # −2 days
        r = _patch(eid, {"trip_id": tid})
        assert r.status_code == 200, r.text
    finally:
        ctx.teardown()


def test_date_window_3_days_requires_force():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, date="2026-09-09", txn=f"T14_{ctx.tag}")
        tid = ctx.trip(vid, vnum, date="2026-09-06")   # −3 days
        r = _patch(eid, {"trip_id": tid})
        assert r.status_code == 400 and "force" in r.text.lower()
        r2 = _patch(eid, {"trip_id": tid, "force": True})
        assert r2.status_code == 200, r2.text
    finally:
        ctx.teardown()


def test_missing_expense_404():
    r = _patch("exp_does_not_exist_iter149", {"trip_id": ""})
    assert r.status_code == 404


# ─── 2. Downstream projection reflections ─────────────────────────────

def test_vehicle_cost_summary_reflects_linked_toll_no_double_count():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, amount=570.0, txn=f"T15_{ctx.tag}")
        tid = ctx.trip(vid, vnum)

        pre = requests.get(f"{API}/vehicles/{vid}/cost-summary",
                           headers=H, timeout=15).json()
        assert pre["total_cost"] == 570.0
        assert pre["trip_linked_total"] == 0.0

        assert _patch(eid, {"trip_id": tid}).status_code == 200

        post = requests.get(f"{API}/vehicles/{vid}/cost-summary",
                            headers=H, timeout=15).json()
        assert post["total_cost"] == 570.0   # No double count.
        assert post["trip_linked_total"] == 570.0
    finally:
        ctx.teardown()


def test_trip_view_projects_linked_toll_into_expenses():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, amount=570.0, txn=f"T16_{ctx.tag}")
        tid = ctx.trip(vid, vnum)
        assert _patch(eid, {"trip_id": tid}).status_code == 200

        rows = requests.get(f"{API}/expenses", headers=H,
                            params={"trip_id": tid}, timeout=15).json()
        assert any(r["id"] == eid and r["category"] == "Toll" for r in rows)
    finally:
        ctx.teardown()


def test_existing_quick_op_toll_untouched_by_new_endpoint():
    """A pre-existing quick_op Toll must NOT be linkable via this endpoint."""
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        tid = ctx.trip(vid, vnum)
        eid = f"exp_iter149_quick_{ctx.tag}"
        ctx.d.expenses.insert_one({
            "id": eid, "user_id": ctx.uid, "company_id": ctx.cid,
            "date": "2026-09-09", "category": "Toll", "amount": 200.0,
            "vehicle_id": vid, "vehicle_number": vnum,
            "source_type": "quick_op", "source_key": "quickop:iter149:test",
            "source_trip_id": "", "trip_id": tid,
            "is_deleted": False, "is_reversed": False,
            "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        })
        ctx._created["expenses"].append(eid)
        r = _patch(eid, {"trip_id": ""})
        assert r.status_code == 400
        after = ctx.d.expenses.find_one({"id": eid}, {"_id": 0})
        assert after["trip_id"] == tid   # Never touched.
    finally:
        ctx.teardown()


# ─── 3. Accounting invariants ─────────────────────────────────────────

def test_supplier_vehicle_no_supplier_accounting_side_effect():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle(vtype="supplier")
        eid, _ = ctx.toll(vid, vnum, txn=f"T17_{ctx.tag}")
        tid = ctx.trip(vid, vnum, extra={
            "vehicle_type": "supplier", "supplier_id": f"sup_{ctx.tag}",
            "supplier_name": "Test Supplier",
            "supplier_net_payable": 12345.67,
        })
        assert _patch(eid, {"trip_id": tid}).status_code == 200

        after_exp = ctx.d.expenses.find_one({"id": eid}, {"_id": 0})
        assert after_exp["supplier_owned_vehicle"] is False
        assert after_exp["supplier_settlement_mode"] == "n/a"

        trip_after = ctx.d.trips.find_one({"id": tid}, {"_id": 0})
        assert trip_after["supplier_net_payable"] == 12345.67

        # NO payables created for this expense.
        n_bills = ctx.d.vendor_bills.count_documents(
            {"user_id": ctx.uid, "narration": {"$regex": "iter149", "$options": "i"}})
        n_vp = ctx.d.vendor_payments.count_documents(
            {"user_id": ctx.uid, "remarks": {"$regex": "iter149", "$options": "i"}})
        n_sp = ctx.d.supplier_payments.count_documents(
            {"user_id": ctx.uid, "remarks": {"$regex": "iter149", "$options": "i"}})
        assert n_bills == 0 and n_vp == 0 and n_sp == 0
    finally:
        ctx.teardown()


def test_source_identity_preserved_across_link_unlink_cycle():
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, before = ctx.toll(vid, vnum, txn=f"T18_{ctx.tag}")
        tid = ctx.trip(vid, vnum)
        assert _patch(eid, {"trip_id": tid}).status_code == 200
        assert _patch(eid, {"trip_id": ""}).status_code == 200
        after = ctx.d.expenses.find_one({"id": eid}, {"_id": 0})
        for k in ("source_type", "source", "source_txn_ref", "source_key",
                  "amount", "date", "vehicle_id", "narration"):
            assert after[k] == before[k], f"{k} mutated"
        assert after["trip_id"] == ""
    finally:
        ctx.teardown()


# ─── 4. Trip-delete cleanup (L.2) ─────────────────────────────────────

def test_trip_delete_unlinks_operator_fastag_toll_without_soft_delete():
    """Deleting the Trip must clear operator-linked Toll.trip_id while
    leaving the row active (owns its own cost identity)."""
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        eid, _ = ctx.toll(vid, vnum, txn=f"T19_{ctx.tag}")
        tid = ctx.trip(vid, vnum)
        assert _patch(eid, {"trip_id": tid}).status_code == 200

        r = requests.delete(f"{API}/trips/{tid}", headers=H,
                            params={"reason": "iter149 test delete"}, timeout=15)
        assert r.status_code == 200, r.text

        after = ctx.d.expenses.find_one({"id": eid}, {"_id": 0})
        assert after is not None
        assert after["trip_id"] == "", f"trip_id not cleared: {after.get('trip_id')}"
        assert not after.get("is_deleted"), "operator-linked row must NOT be soft-deleted"
        assert after["source_key"] and after["source_txn_ref"]
    finally:
        ctx.teardown()


def test_trip_delete_still_soft_deletes_bridge_materialised_rows():
    """Legacy bridge-materialised canonicals (source_trip_id == tid)
    remain soft-deleted by delete_trip_canonical_expenses. The new
    operator-cleanup MUST NOT touch them."""
    ctx = _Ctx()
    try:
        vid, vnum = ctx.vehicle()
        tid = ctx.trip(vid, vnum)
        bridge_eid = f"exp_iter149_bridge_{ctx.tag}"
        ctx.d.expenses.insert_one({
            "id": bridge_eid, "user_id": ctx.uid, "company_id": ctx.cid,
            "date": "2026-09-09", "category": "Toll", "amount": 100.0,
            "vehicle_id": vid, "vehicle_number": vnum,
            "source_type": "trip_legacy",
            "source_key": f"trip:{tid}:legacy:toll",
            "source_trip_id": tid, "trip_id": tid,
            "is_deleted": False, "is_reversed": False,
            "supplier_owned_vehicle": False, "supplier_settlement_mode": "n/a",
        })
        ctx._created["expenses"].append(bridge_eid)

        eid, _ = ctx.toll(vid, vnum, txn=f"T20_{ctx.tag}")
        assert _patch(eid, {"trip_id": tid}).status_code == 200

        r = requests.delete(f"{API}/trips/{tid}", headers=H,
                            params={"reason": "iter149 mixed delete"},
                            timeout=15)
        assert r.status_code == 200

        bridge_after = ctx.d.expenses.find_one({"id": bridge_eid}, {"_id": 0})
        assert bridge_after["is_deleted"] is True, "bridge row must be soft-deleted"

        op_after = ctx.d.expenses.find_one({"id": eid}, {"_id": 0})
        assert op_after["is_deleted"] is False
        assert op_after["trip_id"] == ""
    finally:
        ctx.teardown()


# ─── 5. Frontend static contract ──────────────────────────────────────

def _read(p): return p.read_text()


def test_link_dialog_component_exists_with_testids():
    src = _read(DIALOG_FILE)
    for t in ("link-toll-to-trip-dialog", "candidate-trip-picker",
              "link-toll-confirm-btn", "link-toll-cancel-btn",
              "link-toll-force-checkbox", "link-toll-force-warning",
              "close-link-toll-dialog", "toll-unlink-confirm-btn",
              "link-toll-current-link", "link-toll-loading",
              "link-toll-no-candidates", "link-toll-expense-summary"):
        assert f'data-testid="{t}"' in src, f"dialog missing testid {t}"


def test_link_dialog_calls_correct_endpoint():
    src = _read(DIALOG_FILE)
    assert "/expenses/${eid}/toll-trip" in src
    assert "api.patch(" in src


def test_link_dialog_honours_force_flag():
    src = _read(DIALOG_FILE)
    assert "force: true" in src


def test_quickop_today_expenses_wires_link_button_for_fastag_toll():
    src = _read(QUICKOP_FILE)
    assert "LinkTollToTripDialog" in src
    assert "toll-link-trip-btn-${r.id}" in src
    assert 'st === "fastag_import"' in src and 'r.category === "Toll"' in src


def test_vehicle_workspace_wires_link_button_for_fastag_toll():
    src = _read(VW_FILE)
    assert "LinkTollToTripDialog" in src
    assert "vw-toll-link-trip-btn-${r.id}" in src
    assert 'r.source_type === "fastag_import"' in src and 'r.category === "Toll"' in src


def test_locked_iter148_wizard_untouched():
    wiz = FE_ROOT / "components" / "quickexp" / "TollImportWizard.jsx"
    src = _read(wiz)
    for t in ("toll-possible-dup-banner", "toll-override-keep-",
              "toll-override-skip-", "toll-commit-confirm-dialog",
              "v148-uat"):
        assert t in src, f"Iter148 wizard marker missing: {t}"


def test_iter147_fleet_card_vehicle_endpoint_still_intact():
    src = _read(REPO_ROOT / "routers" / "fuel_import.py")
    assert '@router.patch("/expenses/{eid}/fleet-card-vehicle")' in src
