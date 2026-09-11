"""Iter133 · Turn 2A — Trip → canonical Expense materialisation.

MASTER PRINCIPLE: ENTER ONCE → CALCULATE ONCE → REFLECT EVERYWHERE.

`sync_trip_expenses_to_canonical()` is invoked from routers/trips.py after
every successful create / update (and paired with a cleanup pass on delete).
It converts legacy Trip.expenses.* scalars and Trip.other_expenditures[]
rows into canonical Expense documents with deterministic source-line
identity so:
  * Same trip saved twice → same canonical rows (no duplication).
  * Editing an expense field → same canonical row updated in place.
  * Removing an expense field → canonical row soft-deleted.
  * Two other_expenditure rows with identical amount/date/category still
    map to distinct canonical rows (because their row `id` differs).

Identity contract (never heuristic):
    trip:{trip_id}:legacy:{diesel|toll|batta|repair|other|firewood}
    trip:{trip_id}:oe:{row_id}
"""
from __future__ import annotations
import logging
from db import db
from models import now_utc, new_id
# Iter150A-2 Phase 3B-ii-a · service-level Expense hook (Trip bridge path).
from services_fin_txn_hooks import hook_after_source_write

logger = logging.getLogger(__name__)

_LEGACY_CATEGORY_MAP: dict[str, str] = {
    "diesel":   "Diesel",
    "toll":     "Toll",
    "batta":    "Batta",
    "repair":   "Repair",
    "other":    "Other",
    "firewood": "Firewood",
}


def is_legacy_conflicting_toll_trip(trip: dict) -> bool:
    """Iter149 P0 · L.1 REVISED (2026-09-10) · Authoritative predicate.

    Returns True iff attaching a canonical FASTag Toll to this trip
    would cause a Toll double-count against the legacy XOR fallback
    in vehicle_reports.

    Rule:
      • If `has_canonical_expenses == True`, the bridge has already
        materialised every legacy `Trip.expenses.*` + `other_expenditures[]`
        scalar into canonical Expenses — nothing to conflict with.
        Return False.
      • Else check ONLY the Toll surface (Diesel/Batta/Repair etc are
        irrelevant to Toll linkage):
          – `Trip.expenses.toll > 0`
          – any `Trip.other_expenditures[]` item where
            `type` (case-insensitive strip) equals "toll" AND
            `amount > 0`

    Empty / modern trips (all-zero legacy scalars, no Toll-typed OE
    row, has_canonical_expenses may be False because operators use
    Quick Op / Fuel Import / FASTag Import to write canonical directly)
    are ELIGIBLE for operator-confirmed FASTag Toll linkage.
    """
    if trip.get("has_canonical_expenses") is True:
        return False
    exp = trip.get("expenses") or {}
    try:
        if float(exp.get("toll") or 0) > 0:
            return True
    except Exception:
        pass
    for oe in (trip.get("other_expenditures") or []):
        try:
            amt = float(oe.get("amount") or 0)
        except Exception:
            amt = 0.0
        if amt <= 0:
            continue
        t = (oe.get("type") or "").strip().lower()
        if t == "toll":
            return True
    return False


def _build_desired_rows(trip_dict: dict) -> dict[str, dict]:
    """Return {source_key: partial_expense_fields} for the current trip state."""
    tid = trip_dict.get("id") or ""
    tdate = trip_dict.get("date") or ""
    vehicle_id = trip_dict.get("vehicle_id") or ""
    vehicle_number = trip_dict.get("vehicle_number") or ""

    desired: dict[str, dict] = {}
    e = trip_dict.get("expenses") or {}
    for field, category in _LEGACY_CATEGORY_MAP.items():
        try:
            amt = float(e.get(field) or 0)
        except Exception:
            amt = 0.0
        if amt <= 0:
            continue
        key = f"trip:{tid}:legacy:{field}"
        narration = e.get("other_desc", "") if field == "other" else ""
        remarks = e.get("other_remarks", "") if field == "other" else ""
        desired[key] = {
            "date": tdate,
            "category": category,
            "subcategory": "",
            "amount": round(amt, 2),
            "narration": str(narration or ""),
            "remarks": str(remarks or ""),
            "vehicle_id": vehicle_id,
            "vehicle_number": vehicle_number,
            "trip_id": tid,
            "repair_event_id": "",
            "party_type": "cash",
            "party_id": "",
            "party_name": "",
            "vendor_bill_id": "",
            "mechanic_work_order_id": "",
            "supplier_owned_vehicle": False,
            "supplier_settlement_mode": "n/a",
            "settlement_mode": "cash_now",
            "reversal_of": "",
            "is_reversed": False,
            "file_ids": [],
            "source_type": "trip_legacy",
            "source_key": key,
            "source_trip_id": tid,
        }

    for oe in (trip_dict.get("other_expenditures") or []):
        try:
            amt = float(oe.get("amount") or 0)
        except Exception:
            amt = 0.0
        if amt <= 0:
            continue
        row_id = oe.get("id") or ""
        if not row_id:
            # Skip rows without stable identity; safer than heuristic dedup.
            continue
        key = f"trip:{tid}:oe:{row_id}"
        cat = (oe.get("type") or "Other").strip() or "Other"
        desired[key] = {
            "date": oe.get("date") or tdate,
            "category": cat,
            "subcategory": "",
            "amount": round(amt, 2),
            "narration": "",
            "remarks": str(oe.get("remarks") or ""),
            "vehicle_id": vehicle_id,
            "vehicle_number": vehicle_number,
            "trip_id": tid,
            "repair_event_id": "",
            "party_type": "cash",
            "party_id": "",
            "party_name": "",
            "vendor_bill_id": "",
            "mechanic_work_order_id": "",
            "supplier_owned_vehicle": False,
            "supplier_settlement_mode": "n/a",
            "settlement_mode": "cash_now",
            "reversal_of": "",
            "is_reversed": False,
            "file_ids": [],
            "source_type": "trip_other_expenditure",
            "source_key": key,
            "source_trip_id": tid,
        }
    return desired


async def sync_trip_expenses_to_canonical(uid: str, cid: str, trip_dict: dict) -> bool:
    """Materialise legacy trip expense data → canonical Expense rows.

    Returns True iff there is at least one ACTIVE canonical row for this trip
    after the sync (drives Trip.has_canonical_expenses flag).
    Idempotent by source_key. Never double-counts.
    """
    tid = trip_dict.get("id")
    if not tid:
        return False

    desired = _build_desired_rows(trip_dict)

    existing_rows = await db.expenses.find(
        {"user_id": uid, "company_id": cid, "source_trip_id": tid},
        {"_id": 0, "id": 1, "source_key": 1, "is_deleted": 1},
    ).to_list(2000)
    existing_by_key: dict[str, dict] = {
        r["source_key"]: r for r in existing_rows if r.get("source_key")
    }

    now_iso = now_utc().isoformat()

    # Upsert each desired row (resurrect if soft-deleted).
    for key, fields in desired.items():
        prev = existing_by_key.get(key)
        if prev:
            patch = {
                **fields,
                "modified_by": uid,
                "modified_at": now_iso,
                "is_deleted": False,
                "deleted_by": "",
                "deleted_at": "",
                "deletion_reason": "",
            }
            await db.expenses.update_one({"id": prev["id"]}, {"$set": patch})
            # Iter150A-2 Phase 3B-ii-a · fire hook after authoritative
            # update / resurrection. Non-raising; failures land in
            # fin_hook_failures.
            await hook_after_source_write(uid, cid, "expense", prev["id"])
        else:
            new_doc = {
                **fields,
                "id": new_id("exp_"),
                "user_id": uid,
                "company_id": cid,
                "created_by": uid,
                "created_at": now_iso,
                "modified_by": "",
                "modified_at": "",
                "is_deleted": False,
                "deleted_by": "",
                "deleted_at": "",
                "deletion_reason": "",
                "is_historical": False,
            }
            await db.expenses.insert_one(new_doc)
            # Iter150A-2 Phase 3B-ii-a · fire hook after authoritative insert.
            await hook_after_source_write(uid, cid, "expense", new_doc["id"])

    # Soft-delete rows the trip no longer contains.
    for key, prev in existing_by_key.items():
        if key in desired:
            continue
        if prev.get("is_deleted"):
            continue
        await db.expenses.update_one(
            {"id": prev["id"]},
            {"$set": {
                "is_deleted": True,
                "deleted_by": uid,
                "deleted_at": now_iso,
                "deletion_reason": "trip_line_removed",
                "modified_by": uid,
                "modified_at": now_iso,
            }},
        )
        # Iter150A-2 Phase 3B-ii-a · fire hook after authoritative
        # soft-delete; A-1 short-circuits on is_deleted and legs vanish.
        await hook_after_source_write(uid, cid, "expense", prev["id"])

    active_count = len(desired)
    await db.trips.update_one(
        {"id": tid, "user_id": uid, "company_id": cid},
        {"$set": {"has_canonical_expenses": active_count > 0}},
    )
    return active_count > 0


async def delete_trip_canonical_expenses(uid: str, cid: str, tid: str, reason: str = "trip_deleted") -> int:
    """Soft-delete every canonical Expense linked to a trip. Called on Trip DELETE.

    Iter150A-2 Phase 3B-ii-b · B3 — after the authoritative `update_many`,
    fires `hook_after_source_write` for every affected Expense so the A-1
    projection layer clears their active FinTxn legs. Filter and mutation
    semantics are unchanged; only projection dispatch is added.

    Set-safety: this function targets `source_trip_id == tid` (bridge-
    materialised rows). Set B (operator-linked, `source_trip_id != tid`
    AND `trip_id == tid`) is disjoint by filter. A local per-call `set()`
    dedupe on collected IDs guards against any accidental duplicate hook
    dispatch. No global cache / TTL / scheduler.
    """
    if not tid:
        return 0
    now_iso = now_utc().isoformat()
    b3_filter = {"user_id": uid, "company_id": cid,
                 "source_trip_id": tid, "is_deleted": {"$ne": True}}

    # 1. Pre-collect affected active Expense IDs (LOCAL, per-call dedupe).
    affected_rows = await db.expenses.find(
        b3_filter, {"_id": 0, "id": 1}
    ).to_list(10000)
    affected_ids: set[str] = {r["id"] for r in affected_rows if r.get("id")}

    # 2. Execute the existing update_many unchanged.
    r = await db.expenses.update_many(
        b3_filter,
        {"$set": {
            "is_deleted": True,
            "deleted_by": uid,
            "deleted_at": now_iso,
            "deletion_reason": reason or "trip_deleted",
            "modified_by": uid,
            "modified_at": now_iso,
        }},
    )

    # 3. Fire hook after each authoritative soft-delete. A-1 short-circuits
    #    on is_deleted → legs vanish. Non-raising; failures land in
    #    fin_hook_failures.
    for eid in affected_ids:
        await hook_after_source_write(uid, cid, "expense", eid)

    return int(r.modified_count or 0)


async def unlink_operator_expenses_on_trip_delete(uid: str, cid: str, tid: str) -> int:
    """Iter149 P0 · L.2 · Clear `trip_id` on operator-linked canonical
    Expenses when the Trip is deleted.

    These rows (currently: FASTag-imported Tolls linked via
    `PATCH /api/expenses/{eid}/toll-trip`) OWN their own cost identity —
    they must NOT be soft-deleted (unlike bridge-materialised legacy
    Trip.expenses rows that `delete_trip_canonical_expenses` handles).

    Identified by `trip_id == tid` AND `source_trip_id != tid` (bridge-
    materialised rows have `source_trip_id == tid` and are handled by
    the sibling function). Idempotent, tenant-scoped, active rows only.

    Iter150A-2 Phase 3B-ii-b · B4 — after the authoritative `update_many`,
    fires `hook_after_source_write` for every affected Expense so the A-1
    projection layer refreshes the `trip_id` denorm on their FinTxn legs.
    Accounting movement (amount, account, source identity, vehicle) is
    unchanged; only `trip_id` denorm rotates to "" — ZERO accounting delta.

    Set-safety: this function targets Set B (`source_trip_id != tid`).
    Set A (`source_trip_id == tid`, bridge-materialised, handled by B3)
    is disjoint by filter. A local per-call `set()` dedupe guards against
    accidental duplicate hook dispatch. No global cache / TTL / scheduler.
    """
    if not tid:
        return 0
    now_iso = now_utc().isoformat()
    b4_filter = {"user_id": uid, "company_id": cid,
                 "trip_id": tid, "source_trip_id": {"$ne": tid},
                 "is_deleted": {"$ne": True}}

    # 1. Pre-collect affected active Expense IDs (LOCAL, per-call dedupe).
    affected_rows = await db.expenses.find(
        b4_filter, {"_id": 0, "id": 1}
    ).to_list(10000)
    affected_ids: set[str] = {r["id"] for r in affected_rows if r.get("id")}

    # 2. Execute the existing update_many unchanged.
    r = await db.expenses.update_many(
        b4_filter,
        {"$set": {"trip_id": "", "modified_at": now_iso, "modified_by": uid}},
    )

    # 3. Fire hook after each authoritative denorm update; A-1 refreshes
    #    FinTxn.trip_id to "" — same amount / account / source identity.
    for eid in affected_ids:
        await hook_after_source_write(uid, cid, "expense", eid)

    return int(r.modified_count or 0)
